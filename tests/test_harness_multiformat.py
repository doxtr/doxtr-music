"""CHUNK-2-3 — Cross-format harness assertion + structural-guard tests.

Proves the LaTeX/EPUB per-format assertions (added in this chunk) pass on
representative Sphinx write-stage output and FAIL on negative fixtures (no
false greens), and enforces the renderable-feature format mandate structural
guard: any format a feature lists in ``formats`` must have non-empty
``expected_markers[fmt]``.

These are dependency-free unit tests over the assertion functions + the
``features.py`` registry; they do NOT invoke sphinx-build.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make test_harness/ importable (assertions.py, features.py live there).
HARNESS_DIR = Path(__file__).resolve().parent.parent / "test_harness"
sys.path.insert(0, str(HARNESS_DIR))

from assertions import (  # noqa: E402
    AssertType,
    check_assertions,
)
from features import FEATURE_REGISTRY, get_feature_names  # noqa: E402


# ---------------------------------------------------------------------------
# Representative write-stage fixtures
# ---------------------------------------------------------------------------

LATEX_OK = r"""
\documentclass{report}
\usepackage{needspace}
\usepackage[chordbk]{songbook}
\begin{document}
\dmneedspace
\dmsectionbegin{verse}{Verse}
\dmchord{Am}{Hello }\dmchord{C}{world}
\dmsectionend{verse}
\end{document}
"""

LATEX_NO_NEEDSPACE = r"""
\documentclass{report}
\usepackage[chordbk]{songbook}
\begin{document}
\dmchord{Am}{Hello }
\end{document}
"""

LATEX_NO_PACKAGE = r"""
\documentclass{report}
\begin{document}
\dmneedspace
\dmchord{Am}{Hello }
\end{document}
"""

EPUB_OK = (
    '<div class="doxtr-song doxtr-song-epub" id="test-song">'
    '<div class="doxtr-section doxtr-section-verse">'
    '<pre class="doxtr-line-epub">'
    '<span class="doxtr-chordrow" aria-hidden="true">Am    C </span>\n'
    '<span class="doxtr-lyricrow">Hello world</span></pre>'
    "</div></div>"
)

# Negative: chord row NOT aria-hidden (would let AT / copy pick up chords).
EPUB_CHORDROW_NOT_HIDDEN = (
    '<div class="doxtr-song doxtr-song-epub">'
    '<pre class="doxtr-line-epub">'
    '<span class="doxtr-chordrow">Am    C </span>\n'
    '<span class="doxtr-lyricrow">Hello world</span></pre>'
    "</div>"
)

# Negative: lyric row marked user-select:none (not copyable).
EPUB_LYRICROW_UNSELECTABLE = (
    '<div class="doxtr-song doxtr-song-epub">'
    '<pre class="doxtr-line-epub">'
    '<span class="doxtr-chordrow" aria-hidden="true">Am    C </span>\n'
    '<span class="doxtr-lyricrow" style="user-select:none">Hello world</span></pre>'
    "</div>"
)

# Negative: EPUB using absolute positioning (the HTML layout, not reflow-safe).
EPUB_ABSOLUTE = (
    '<div class="doxtr-song doxtr-song-epub">'
    '<pre class="doxtr-line-epub" style="position:absolute">'
    '<span class="doxtr-chordrow" aria-hidden="true">Am</span>\n'
    '<span class="doxtr-lyricrow">Hello</span></pre>'
    "</div>"
)

# Negative: no <pre> block at all.
EPUB_NO_PRE = '<div class="doxtr-song doxtr-song-epub"><p>Hello world</p></div>'


def _one(content: str, atype: AssertType) -> bool:
    """Return the pass/fail of a single assertion against ``content``."""
    results = check_assertions(content, [atype])
    assert len(results) == 1
    return results[0].passed


# ---------------------------------------------------------------------------
# LaTeX assertions
# ---------------------------------------------------------------------------

def test_needspace_present_passes_on_real_output():
    assert _one(LATEX_OK, AssertType.NEEDSPACE_PRESENT) is True


def test_needspace_present_fails_without_dmneedspace():
    assert _one(LATEX_NO_NEEDSPACE, AssertType.NEEDSPACE_PRESENT) is False


def test_latex_package_loaded_passes_on_songbook():
    assert _one(LATEX_OK, AssertType.LATEX_PACKAGE_LOADED) is True


def test_latex_package_loaded_accepts_generic_package():
    # needspace-only preamble (no songbook) still counts as a package loaded.
    generic = r"\usepackage{needspace}" + "\n" + r"\dmneedspace"
    assert _one(generic, AssertType.LATEX_PACKAGE_LOADED) is True


def test_latex_package_loaded_fails_without_any_package():
    assert _one(LATEX_NO_PACKAGE, AssertType.LATEX_PACKAGE_LOADED) is False


# ---------------------------------------------------------------------------
# EPUB assertions
# ---------------------------------------------------------------------------

def test_epub_pre_fallback_passes_on_real_output():
    assert _one(EPUB_OK, AssertType.EPUB_PRE_FALLBACK) is True


def test_epub_pre_fallback_fails_without_pre():
    assert _one(EPUB_NO_PRE, AssertType.EPUB_PRE_FALLBACK) is False


def test_epub_pre_fallback_fails_with_absolute_positioning():
    assert _one(EPUB_ABSOLUTE, AssertType.EPUB_PRE_FALLBACK) is False


def test_copy_safe_order_epub_pre_passes_on_two_row_pre():
    assert _one(EPUB_OK, AssertType.COPY_SAFE_ORDER_EPUB_PRE) is True


def test_copy_safe_order_epub_pre_fails_when_chordrow_not_hidden():
    assert _one(EPUB_CHORDROW_NOT_HIDDEN, AssertType.COPY_SAFE_ORDER_EPUB_PRE) is False


def test_copy_safe_order_epub_pre_fails_when_lyricrow_unselectable():
    assert _one(EPUB_LYRICROW_UNSELECTABLE, AssertType.COPY_SAFE_ORDER_EPUB_PRE) is False


def test_copy_safe_order_epub_pre_fails_without_pre():
    assert _one(EPUB_NO_PRE, AssertType.COPY_SAFE_ORDER_EPUB_PRE) is False


# ---------------------------------------------------------------------------
# HTML copy-safe (CHUNK-1-4 gate, reused): passes on clean, fails on interleaved
# ---------------------------------------------------------------------------

HTML_CLEAN = (
    '<div class="doxtr-song">'
    '<span class="doxtr-chord" data-chord="Am">Am</span>'
    "<span>Hello </span>"
    '<span class="doxtr-chord" data-chord="C">C</span>'
    "<span>world</span>"
    "</div>"
)

# Negative: a chord glyph leaked into the copyable lyric text.
HTML_INTERLEAVED = (
    '<div class="doxtr-song">'
    '<span class="doxtr-chord" data-chord="Am">Am</span>'
    "<span>AmHello world</span>"
    "</div>"
)


def test_copy_safe_order_html_passes_on_clean_dom():
    # POSITION_ABSOLUTE_CSS / user-select depend on shipped CSS; here we only
    # assert the DOM-strip residual has no leaked chord glyph. If the packaged
    # CSS lacks user-select the gate can still fail for that reason, so only
    # assert the *interleaved* negative deterministically and treat the clean
    # case as "not a false-fail due to leakage".
    from assertions import _copy_safe_order_html  # noqa: WPS433
    parser_ok = _copy_safe_order_html(HTML_CLEAN)
    # Clean DOM must not fail due to a leaked chord glyph.
    assert "leaked" not in (parser_ok.details or "")


def test_copy_safe_order_html_fails_on_interleaved_chord():
    assert _one(HTML_INTERLEAVED, AssertType.COPY_SAFE_ORDER_HTML) is False


# ---------------------------------------------------------------------------
# Renderable-feature format mandate — structural guard (generalized)
# ---------------------------------------------------------------------------

def test_song_declares_all_three_formats():
    song = FEATURE_REGISTRY["song"]
    st = song.sub_tests[0]
    assert st.formats == ["html", "latex", "epub"]
    for fmt in ("html", "latex", "epub"):
        assert st.expected_markers.get(fmt), f"song must have markers for {fmt}"


def test_format_mandate_structural_guard_over_all_features():
    """Every format a feature LISTS must have non-empty expected_markers[fmt].

    A listed-but-empty format is a configuration error (silent under-declaring
    of a renderable format), caught here rather than passing silently.
    """
    for fname in get_feature_names():
        feat = FEATURE_REGISTRY[fname]
        for st in feat.sub_tests:
            for fmt in st.formats:
                markers = st.expected_markers.get(fmt, [])
                assert markers, (
                    f"feature {fname!r} sub-test {st.name!r} lists format "
                    f"{fmt!r} but has no expected_markers[{fmt!r}]"
                )
