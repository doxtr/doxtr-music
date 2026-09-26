"""Release-level packaging tests (CHUNK-7-2).

Enforces the soft-dependency discipline at the metadata level: the runtime
``dependencies`` must stay minimal (``sphinx``/``Jinja2`` only) and must NOT
contain the optional-feature or interop packages (``defusedxml``, ``pyperclip``,
``doxtr-pdf-theme-core``). Also checks the console-script entry point, the
optional extras, and that the single-source ``__version__`` matches the
CHANGELOG heading. Dependency-free (parses ``pyproject.toml`` + ``CHANGELOG.md``
statically) so it runs without a build.
"""
import re
from pathlib import Path

try:  # Python 3.11+ stdlib; fall back to tomli if ever needed.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - environment shim
    import tomli as tomllib

import doxtr_music

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _ROOT / "pyproject.toml"
_CHANGELOG = _ROOT / "CHANGELOG.md"


def _project():
    with _PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)["project"]


def test_runtime_dependencies_are_minimal():
    deps = _project()["dependencies"]
    names = {re.split(r"[<>=!~ ]", d, maxsplit=1)[0].lower() for d in deps}
    assert names == {"sphinx", "jinja2"}


def test_soft_dependencies_not_in_install_requires():
    deps = " ".join(_project()["dependencies"]).lower()
    for soft in ("defusedxml", "pyperclip", "doxtr-pdf-theme-core", "doxtr_pdf_theme_core"):
        assert soft not in deps, f"{soft} must stay a soft/optional dependency"


def test_optional_extras_declared_soft():
    extras = _project()["optional-dependencies"]
    assert any("defusedxml" in d for d in extras["musicxml"])
    assert any("pyperclip" in d for d in extras["clipboard"])
    # The convenience bundle exists and is still soft (extras, not runtime deps).
    assert "all" in extras


def test_console_script_entry_point():
    scripts = _project()["scripts"]
    assert scripts.get("doxtr-music-convert") == "doxtr_music.cli:main"


def test_version_is_single_source_and_release_literal():
    # A release literal (no ``.dev``/``-dev`` suffix), single source of truth.
    assert doxtr_music.__version__ == "0.1.1"
    assert "dev" not in doxtr_music.__version__


def test_changelog_heading_matches_version():
    text = _CHANGELOG.read_text(encoding="utf-8")
    # The newest (top) release section heading must carry the release version.
    m = re.search(r"^##\s+([0-9][^\s]*)\b", text, re.MULTILINE)
    assert m is not None, "no version heading found in CHANGELOG"
    assert m.group(1) == doxtr_music.__version__
    assert "unreleased" not in text.split("\n", 4)[2].lower()


def test_project_urls_complete():
    urls = _project()["urls"]
    assert "Homepage" in urls
    assert "Repository" in urls
    assert "Changelog" in urls
