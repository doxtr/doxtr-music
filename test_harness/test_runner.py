"""
doxtr-music — Test Harness Test Runner

Builds each feature independently with its own merged ``conf.py``, then for
each output format the sub-test declares (``subtest.formats``) resolves that
builder's output via ``BUILDER_MAP`` and validates the format-keyed
``expected_markers`` + ``assertions`` from ``features.py``.

Usage:
    python test_runner.py                          # Run all features
    python test_runner.py --feature smoke          # Run a specific feature
    python test_runner.py --clean                  # Clean build dir first
    python test_runner.py --report-only            # Report without building
    python test_runner.py --fail-on-pending        # Exit 1 if any pending tests
    python test_runner.py --verbose                # Detailed output
    python test_runner.py --assertions-only        # Only run assertions

Exit codes:
    0  All tests passed (and no pending when --fail-on-pending)
    1  One or more tests failed (or pending when --fail-on-pending)
    2  Invalid arguments
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

# Add test_harness to path so we can import features.py / assertions.py.
sys.path.insert(0, str(Path(__file__).parent))
from features import (  # noqa: E402
    FEATURE_REGISTRY,
    count_by_status,
    get_feature_names,
    get_pending_features,
    print_summary,
)
from assertions import (  # noqa: E402
    AssertType,
    check_assertions,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HARNESS_DIR = Path(__file__).parent.resolve()
SOURCE_DIR = HARNESS_DIR / "source"
BUILD_ROOT = HARNESS_DIR / "build"
OVERRIDES_DIR = HARNESS_DIR / "conf_overrides"
REPORT_DIR = BUILD_ROOT / "reports"


# ---------------------------------------------------------------------------
# Builder resolver map (LOCKED contract — CHUNK-0-2)
# ---------------------------------------------------------------------------
#
# builder -> (sphinx_target, resolver(build_dir, feature_name) -> str)
#
# The per-format loop reads output ONLY via BUILDER_MAP[fmt][1](...). It never
# hardcodes index.html. HTML is implemented; latex/epub resolvers are present
# but raise NotImplementedError("CHUNK-2-3") so the contract is visible and
# CHUNK-2-3 fills only the resolver bodies (no loop/dataclass edits).


def _resolve_html_output(build_dir: Path, feature_name: str) -> str:
    """Return the built HTML text for the page containing the feature.

    The harness builds a single-page toctree per feature; the feature's RST
    fixture lives in ``source/_test_cases/`` and is rendered into
    ``_test_cases/<feature>.html``. Prefer that dedicated per-feature page, then
    a root ``<feature>.html``, and finally fall back to ``index.html``.
    """
    candidates = [
        build_dir / "_test_cases" / f"{feature_name}.html",
        build_dir / f"{feature_name}.html",
        build_dir / "index.html",
    ]
    for page in candidates:
        if page.exists():
            return page.read_text(encoding="utf-8")
    return ""


def _resolve_latex_output(build_dir: Path, feature_name: str) -> str:
    """Return the built LaTeX (``.tex``) text for the feature.

    READ-only: the runner loop already ran ``sphinx -b latex`` into
    ``build_dir``; this resolver only reads the written output. Sphinx writes a
    single top-level ``*.tex`` (the whole doc, incl. preamble) per project, so
    glob it and return its text. Never invokes sphinx-build or ``pdflatex`` —
    the LaTeX lane asserts on write-stage emission, not a compiled PDF.
    """
    tex_files = sorted(build_dir.glob("*.tex"))
    if not tex_files:
        return ""
    return "\n".join(p.read_text(encoding="utf-8") for p in tex_files)


def _resolve_epub_output(build_dir: Path, feature_name: str) -> str:
    """Return the built EPUB song XHTML for the feature.

    READ-only: the runner loop already ran ``sphinx -b epub`` into
    ``build_dir``. Sphinx's ``-b epub`` writes the content documents as loose
    ``*.xhtml`` directly into the outdir (flat layout, **no** ``OEBPS/``
    prefix), mirroring the HTML layout: the feature fixture lands in
    ``_test_cases/<feature>.xhtml``. Prefer that dedicated page, then a root
    ``<feature>.xhtml``, then ``index.xhtml``.

    Only if the loose XHTML is absent (e.g. a build that emitted just the
    packaged ``.epub`` zip) do we fall back to unzipping the archive and
    resolving the content path via the OPF spine — never a hardcoded
    ``OEBPS/`` prefix. Never invokes sphinx-build or ``epubcheck``.
    """
    candidates = [
        build_dir / "_test_cases" / f"{feature_name}.xhtml",
        build_dir / f"{feature_name}.xhtml",
        build_dir / "index.xhtml",
    ]
    parts = [p.read_text(encoding="utf-8") for p in candidates if p.exists()]
    if parts:
        return "\n".join(parts)
    return _resolve_epub_from_zip(build_dir, feature_name)


def _resolve_epub_from_zip(build_dir: Path, feature_name: str) -> str:
    """Fallback: read song XHTML from a packaged ``*.epub`` via its OPF spine.

    Resolves the content-document path from ``META-INF/container.xml`` → OPF
    rather than assuming an ``OEBPS/`` prefix (EPUB packagers differ). Returns
    the concatenation of any content document whose name matches the feature,
    else all content documents.
    """
    import xml.etree.ElementTree as ET
    import zipfile

    epubs = sorted(build_dir.glob("*.epub"))
    if not epubs:
        return ""
    try:
        with zipfile.ZipFile(epubs[0]) as zf:
            container = zf.read("META-INF/container.xml").decode("utf-8")
            cm = re.search(r'full-path="([^"]+)"', container)
            if not cm:
                return ""
            opf_path = cm.group(1)
            opf_dir = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""
            opf_text = zf.read(opf_path).decode("utf-8")
            # Strip XML namespaces for a simple href scan.
            hrefs = re.findall(r'href="([^"]+\.x?html)"', opf_text)
            docs = [f"{opf_dir}/{h}" if opf_dir else h for h in hrefs]
            wanted = [d for d in docs if feature_name in d] or docs
            out: list[str] = []
            for name in wanted:
                try:
                    out.append(zf.read(name).decode("utf-8"))
                except KeyError:
                    continue
            return "\n".join(out)
    except (KeyError, zipfile.BadZipFile):
        return ""


BUILDER_MAP: dict[str, tuple[str, Callable[[Path, str], str]]] = {
    "html": ("html", _resolve_html_output),
    "latex": ("latex", _resolve_latex_output),
    "epub": ("epub", _resolve_epub_output),
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class TestResult(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class SubTestResult:
    name: str
    description: str
    fmt: str
    rst_file: Optional[str]
    conf_override: Optional[str]
    expected_markers: list[str]
    status: TestResult
    found_markers: list[str] = field(default_factory=list)
    missing_markers: list[str] = field(default_factory=list)
    assertion_results: list = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class FeatureResult:
    name: str
    description: str
    sub_results: list[SubTestResult]
    status: TestResult

    @property
    def all_passed(self) -> bool:
        return all(sr.status == TestResult.PASSED for sr in self.sub_results)

    @property
    def has_any_test(self) -> bool:
        return len(self.sub_results) > 0


# ---------------------------------------------------------------------------
# conf.py override loader
# ---------------------------------------------------------------------------

def load_conf_override(filename: str) -> Optional[str]:
    """Load a conf.py override file and return its content, or None."""
    override_path = OVERRIDES_DIR / filename
    if not override_path.exists():
        return None
    return override_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Sphinx builder (per feature, per format)
# ---------------------------------------------------------------------------

def _merged_conf(feature_name: str) -> str:
    """Compose the base conf.py + this feature's unique overrides."""
    feat = FEATURE_REGISTRY[feature_name]
    base_conf = (HARNESS_DIR / "conf.py").read_text(encoding="utf-8")

    seen_files: set[str] = set()
    feature_overrides: list[str] = []
    for st in feat.sub_tests:
        if st.conf_override and st.conf_override not in seen_files:
            seen_files.add(st.conf_override)
            content = load_conf_override(st.conf_override)
            if content:
                feature_overrides.append(content)

    merged = base_conf
    for override in feature_overrides:
        merged += "\n\n# === Merged conf.py override ===\n" + override
    return merged


def _write_single_feature_toctree(feature_name: str) -> None:
    """Overwrite the generated toctree so only this feature builds."""
    toctree_path = SOURCE_DIR / "_generated_toctree.rst"
    lines = [
        ".. toctree::\n",
        "   :maxdepth: 1\n",
        "   :caption: Test Cases\n",
        "   :hidden:\n",
        "\n",
        f"   _test_cases/{feature_name}\n",
    ]
    toctree_path.write_text("".join(lines), encoding="utf-8")


def build_feature(feature_name: str, sphinx_target: str, clean: bool = False) -> tuple[Path, str]:
    """Build ``feature_name`` with the given Sphinx builder.

    Returns (build_dir, build_output). The build_dir is where resolvers read
    the rendered output from.
    """
    build_dir = BUILD_ROOT / sphinx_target

    if clean and build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    # Always wipe the doctrees cache between feature builds: each feature uses a
    # different conf.py and Sphinx's incremental build would otherwise reuse
    # stale cached AST nodes from a prior feature.
    doctrees_dir = build_dir / ".doctrees"
    if doctrees_dir.exists():
        shutil.rmtree(doctrees_dir)

    # Write merged conf + single-feature toctree.
    (SOURCE_DIR / "conf.py").write_text(_merged_conf(feature_name), encoding="utf-8")
    _write_single_feature_toctree(feature_name)

    cmd = [
        sys.executable, "-m", "sphinx",
        "-b", sphinx_target,
        "-c", str(SOURCE_DIR),
        "-d", str(build_dir / ".doctrees"),
        str(SOURCE_DIR),
        str(build_dir),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(HARNESS_DIR),
        )
        return build_dir, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return build_dir, "ERROR: Build timed out after 180 seconds"
    except Exception as exc:  # pragma: no cover - defensive
        return build_dir, f"ERROR: {exc}"


# ---------------------------------------------------------------------------
# Marker checking
# ---------------------------------------------------------------------------

def check_markers(content: str, markers: list[str]) -> tuple[list[str], list[str]]:
    """Return (found, missing) markers. Regex first, literal fallback."""
    found: list[str] = []
    missing: list[str] = []
    for marker in markers:
        try:
            matched = bool(re.search(marker, content))
        except re.error:
            matched = marker in content
        (found if matched else missing).append(marker)
    return found, missing


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

def generate_report(
    feature_results: list[FeatureResult],
    feature_name: Optional[str] = None,
) -> str:
    """Generate a text report of test results."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("           doxtr-music — Test Harness Report")
    lines.append("=" * 70)
    lines.append("")

    if feature_name:
        lines.append(f"Feature: {feature_name}")
        lines.append("-" * 70)
    else:
        counts = count_by_status()
        total_feats = len(FEATURE_REGISTRY)
        total_subs = sum(f.total_count for f in FEATURE_REGISTRY.values())
        lines.append(
            f"Features: {total_feats} total | "
            f"{counts['features']['complete']} complete | "
            f"{counts['features']['partial']} partial | "
            f"{counts['features']['pending']} pending"
        )
        lines.append(
            f"Sub-tests: {total_subs} total | "
            f"{counts['sub_tests']['complete']} complete | "
            f"{counts['sub_tests']['partial']} partial | "
            f"{counts['sub_tests']['pending']} pending"
        )
        lines.append("")
        lines.append("-" * 70)

    total_passed = total_failed = total_skipped = 0

    for fr in feature_results:
        passed = sum(1 for sr in fr.sub_results if sr.status == TestResult.PASSED)
        failed = sum(1 for sr in fr.sub_results if sr.status == TestResult.FAILED)
        skipped = sum(1 for sr in fr.sub_results if sr.status == TestResult.SKIPPED)
        total_passed += passed
        total_failed += failed
        total_skipped += skipped

        status_icon = "✓" if fr.all_passed else "✗"
        lines.append(f"\n[{status_icon}] {fr.name}: {passed}/{len(fr.sub_results)} passed")
        lines.append(f"    {fr.description}")

        for sr in fr.sub_results:
            label = f"{sr.name} [{sr.fmt}]"
            if sr.status == TestResult.PASSED:
                lines.append(f"    [✓] {label}: {sr.description}")
            elif sr.status == TestResult.FAILED:
                lines.append(f"    [✗] {label}: {sr.description}")
                if sr.missing_markers:
                    lines.append(f"        Missing markers: {sr.missing_markers}")
                for ar in sr.assertion_results:
                    if not ar.passed:
                        lines.append(f"        ✗ Assertion failed: {ar.description}")
                if sr.error:
                    lines.append(f"        Error: {sr.error}")
            else:
                lines.append(f"    [○] {label}: {sr.description} (skipped)")

    lines.append("\n" + "-" * 70)
    lines.append(f"\nSummary: {total_passed} passed, {total_failed} failed, {total_skipped} skipped")

    if total_failed > 0:
        lines.append("\n❌ SOME TESTS FAILED")
    elif total_skipped > 0 and total_failed == 0:
        lines.append("\n⚠ All tests passed (some skipped)")
    else:
        lines.append("\n✅ ALL TESTS PASSED")

    lines.append("\n" + "=" * 70)
    return "\n".join(lines)


def save_report(report_text: str, feature_name: Optional[str] = None) -> Path:
    """Save the report to the build/reports directory."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORT_DIR / (f"report_{feature_name}.txt" if feature_name else "report_all.txt")
    report_file.write_text(report_text, encoding="utf-8")
    return report_file


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def _evaluate_subtest(
    st,
    fmt: str,
    content: str,
    content_size: Optional[int],
    assertions_only: bool,
    build_css_path: Optional[str] = None,
) -> SubTestResult:
    """Validate one sub-test against one format's resolved output."""
    markers = st.expected_markers.get(fmt, [])
    assertion_strs = st.assertions.get(fmt, [])

    # Parse assertion strings into AssertType; tolerate unknown (parse & skip).
    assertion_types: list[AssertType] = []
    for name in assertion_strs:
        try:
            assertion_types.append(AssertType(name))
        except ValueError:
            continue

    # Nothing to validate for this format: skipped.
    if not markers and not assertion_types:
        return SubTestResult(
            name=st.name, description=st.description, fmt=fmt,
            rst_file=st.rst_file, conf_override=st.conf_override,
            expected_markers=[], status=TestResult.SKIPPED,
        )

    found, missing = ([], [])
    if markers and not assertions_only:
        found, missing = check_markers(content, markers)

    assertion_results = []
    if assertion_types:
        assertion_results = check_assertions(
            content, assertion_types, file_size=content_size,
            build_css_path=build_css_path,
        )

    # Status: markers must all match (unless assertions_only) AND all assertions pass.
    markers_ok = assertions_only or not missing
    assertions_ok = all(ar.passed for ar in assertion_results)
    status = TestResult.PASSED if (markers_ok and assertions_ok) else TestResult.FAILED

    return SubTestResult(
        name=st.name, description=st.description, fmt=fmt,
        rst_file=st.rst_file, conf_override=st.conf_override,
        expected_markers=markers, status=status,
        found_markers=found, missing_markers=missing,
        assertion_results=assertion_results,
    )


def run_tests(
    feature_name: Optional[str] = None,
    clean: bool = False,
    verbose: bool = False,
    assertions_only: bool = False,
) -> tuple[list[FeatureResult], bool]:
    """Run tests for one feature (or all). Returns (results, all_passed)."""
    feature_names = [feature_name] if feature_name else get_feature_names()
    feature_results: list[FeatureResult] = []

    for fname in feature_names:
        feat = FEATURE_REGISTRY[fname]

        # Collect the set of formats this feature needs across its sub-tests.
        needed_formats: list[str] = []
        for st in feat.sub_tests:
            for fmt in st.formats:
                if fmt not in needed_formats:
                    needed_formats.append(fmt)

        # Build each needed format once, resolve its output.
        resolved: dict[str, str] = {}
        build_dirs: dict[str, Path] = {}
        for fmt in needed_formats:
            if fmt not in BUILDER_MAP:
                continue
            sphinx_target, resolver = BUILDER_MAP[fmt]
            build_dir, _output = build_feature(fname, sphinx_target, clean)
            build_dirs[fmt] = build_dir
            clean = False  # only clean before the very first build
            try:
                resolved[fmt] = resolver(build_dir, fname)
            except NotImplementedError:
                resolved[fmt] = ""  # lane not wired yet (CHUNK-2-3)

        sub_results: list[SubTestResult] = []
        for st in feat.sub_tests:
            for fmt in st.formats:
                content = resolved.get(fmt, "")
                content_size = len(content.encode("utf-8")) if content else None
                # For HTML, point POSITION_ABSOLUTE_CSS at the CSS the build
                # actually delivered into _static/ (not just the package copy).
                build_css_path = None
                if fmt == "html" and fmt in build_dirs:
                    css = build_dirs[fmt] / "_static" / "doxtr_music.css"
                    if css.exists():
                        build_css_path = str(css)
                sr = _evaluate_subtest(
                    st, fmt, content, content_size, assertions_only,
                    build_css_path,
                )
                sub_results.append(sr)
                if verbose:
                    icon = "✓" if sr.status == TestResult.PASSED else (
                        "○" if sr.status == TestResult.SKIPPED else "✗")
                    print(f"  {icon} {st.name} [{fmt}]: {st.description}")
                    if sr.missing_markers:
                        print(f"      Missing: {sr.missing_markers}")
                    for ar in sr.assertion_results:
                        print(f"      [{'✓' if ar.passed else '✗'}] {ar.description}")

        feature_results.append(FeatureResult(
            name=feat.name,
            description=feat.description,
            sub_results=sub_results,
            status=(
                TestResult.PASSED
                if all(sr.status == TestResult.PASSED for sr in sub_results)
                else TestResult.FAILED
            ),
        ))

    return feature_results, all(fr.all_passed for fr in feature_results)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="doxtr-music — Test Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_runner.py                     Run all features
  python test_runner.py --feature smoke     Run a specific feature
  python test_runner.py --clean             Clean build directory first
  python test_runner.py --report-only       Generate report without building
  python test_runner.py --fail-on-pending   Exit non-zero if any pending tests
  python test_runner.py --verbose           Show detailed output
        """,
    )
    parser.add_argument("--feature", "-f", type=str, default=None,
                        help="Run tests for a specific feature (e.g., smoke)")
    parser.add_argument("--clean", "-c", action="store_true",
                        help="Clean the build directory before building")
    parser.add_argument("--report-only", "-r", action="store_true",
                        help="Generate report from features.py without building")
    parser.add_argument("--fail-on-pending", action="store_true",
                        help="Exit with code 1 if any tests are still pending")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed output during testing")
    parser.add_argument("--assertions-only", action="store_true",
                        help="Only check assertions (no marker validation)")

    args = parser.parse_args()

    print_summary()
    print()

    if args.report_only:
        report = generate_report([], feature_name=args.feature)
        report_file = save_report(report, args.feature)
        print(report)
        print(f"\nReport saved to: {report_file}")
        sys.exit(0)

    feature_results, all_passed = run_tests(
        feature_name=args.feature,
        clean=args.clean,
        verbose=args.verbose,
        assertions_only=args.assertions_only,
    )

    report = generate_report(feature_results, args.feature)
    report_file = save_report(report, args.feature)
    print(report)
    print(f"\nReport saved to: {report_file}")

    pending = get_pending_features()
    if pending:
        print(f"\n⚠ {len(pending)} feature(s) still have pending tests: {pending}")

    if args.fail_on_pending and pending:
        sys.exit(1)
    elif not all_passed:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
