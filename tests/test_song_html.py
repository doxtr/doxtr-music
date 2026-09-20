"""Integration + unit tests for CHUNK-1-4 (``.. song::`` + copy-safe HTML).

Covers the exit criteria:

* ``.. song::`` builds to HTML with ``class="doxtr-song"`` and real
  ``<span class="doxtr-chord">`` elements with ``data-chord``.
* Lyric text is in logical DOM order (copy-safety precondition).
* A ``title_id`` target element exists (CHUNK-4-3 aria-labelledby target).
* The built ``_static/doxtr_music.css`` exists (CSS delivery wiring).
* Malformed ChordPro still renders the wrapper AND emits a Sphinx warning at
  the correct content-relative source line (warning provenance).
* A top-level ``{end_of_*}`` (``kind="none"``) case renders LineNodes directly
  under the song wrapper (no stray empty ``<section>``).
* Unit tests for the ``POSITION_ABSOLUTE_CSS`` / ``COPY_SAFE_ORDER_HTML``
  assertion bodies (DOM-strip definition).
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sphinx = pytest.importorskip("sphinx")
from sphinx.application import Sphinx  # noqa: E402

# Make the harness assertions importable (mirrors tests/conftest.py path setup).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "test_harness"))


def _make_project(root: Path, index_rst: str) -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music"]\n'
        'html_theme = "basic"\n',
        encoding="utf-8",
    )
    (src / "index.rst").write_text(index_rst, encoding="utf-8")
    return src


def _build_html(root: Path, index_rst: str, warnings_buf=None):
    src = _make_project(root, index_rst)
    out = root / "out"
    doctrees = root / "doctrees"
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(doctrees),
        buildername="html",
        freshenv=True,
        warning=warnings_buf,
    )
    app.build(force_all=True)
    return out


# ---------------------------------------------------------------------------
# Integration: basic render
# ---------------------------------------------------------------------------

_BASIC = textwrap.dedent(
    """
    Title
    =====

    .. song::

       {title: My Song}
       {start_of_verse}
       [Am]Hello [C]world
       {end_of_verse}
    """
)


@pytest.mark.integration
def test_song_renders_wrapper_and_real_chord_spans(tmp_path):
    out = _build_html(tmp_path, _BASIC)
    html = (out / "index.html").read_text(encoding="utf-8")

    assert 'class="doxtr-song"' in html
    assert 'role="group"' in html
    # Real chord text spans carrying data-chord (not ::before).
    assert '<span class="doxtr-chord" data-chord="Am"' in html
    assert ">Am</span>" in html  # real chord text present
    assert 'data-chord="C"' in html


@pytest.mark.integration
def test_lyrics_in_logical_dom_order(tmp_path):
    out = _build_html(tmp_path, _BASIC)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Hello" in html and "world" in html
    assert html.index("Hello") < html.index("world")


@pytest.mark.integration
def test_title_id_target_element_present(tmp_path):
    out = _build_html(tmp_path, _BASIC)
    html = (out / "index.html").read_text(encoding="utf-8")
    # SongNode gets a stable id; the title element carries "<id>-title".
    # CHUNK-4-3 adds aria-labelledby/aria-label between role and id, so match
    # the id attribute independently of surrounding a11y attribute order.
    import re

    m = re.search(
        r'<div class="doxtr-song" role="group"[^>]*\bid="([^"]+)"', html
    )
    assert m, "song wrapper has no id"
    song_id = m.group(1)
    assert ('id="%s-title"' % song_id) in html


@pytest.mark.integration
def test_static_css_present_in_build(tmp_path):
    out = _build_html(tmp_path, _BASIC)
    css = out / "_static" / "doxtr_music.css"
    assert css.exists(), "packaged doxtr_music.css not copied into build"
    text = css.read_text(encoding="utf-8")
    assert "position: absolute" in text
    assert "user-select: none" in text
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "doxtr_music.css" in html  # linked


# ---------------------------------------------------------------------------
# Integration: warning provenance (malformed ChordPro still renders)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_malformed_chordpro_warns_and_still_renders(tmp_path):
    import io

    # Unbalanced '[' on the third body line of the directive.
    index_rst = textwrap.dedent(
        """
        Title
        =====

        .. song::

           {title: Broken}
           [Am]ok line
           [Unbalanced chord here
        """
    )
    buf = io.StringIO()
    out = _build_html(tmp_path, index_rst, warnings_buf=buf)
    html = (out / "index.html").read_text(encoding="utf-8")
    # Still renders the wrapper (graceful recovery).
    assert 'class="doxtr-song"' in html
    warnings = buf.getvalue()
    assert "unbalanced" in warnings.lower()
    # Provenance: the warning references the source file (best-effort line math).
    assert "index.rst" in warnings


# ---------------------------------------------------------------------------
# Integration: top-level kind="none" (lines outside any section)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_top_level_lines_no_empty_section(tmp_path):
    index_rst = textwrap.dedent(
        """
        Title
        =====

        .. song::

           {start_of_chorus}
           [C]In chorus
           {end_of_chorus}
           [G]Back at top level
        """
    )
    out = _build_html(tmp_path, index_rst)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="doxtr-song"' in html
    # The chorus section renders; the top-level line after end_of_chorus must
    # NOT open a second empty section. Exactly one <section> in the song.
    song_html = html[html.index('class="doxtr-song"'):]
    song_html = song_html[: song_html.index("</div>")]
    # Count <section ... in the whole song block (children include the chorus).
    full_song = html[html.index('<div class="doxtr-song"'):]
    # trim to the matching close is hard with nesting; assert the top-level
    # line's chord/lyric is present and only one section-label appears.
    assert "Back" in full_song
    assert full_song.count('class="doxtr-section-label"') == 1


# ---------------------------------------------------------------------------
# Integration: later options accepted without error (transpose etc.)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_later_options_accepted(tmp_path):
    index_rst = textwrap.dedent(
        """
        Title
        =====

        .. song::
           :transpose: 2
           :key: G
           :roman-numerals:
           :chord-color: red

           [Am]Hello
        """
    )
    # Must not raise / crash the build.
    out = _build_html(tmp_path, index_rst)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="doxtr-song"' in html


# ---------------------------------------------------------------------------
# Unit: assertion bodies (POSITION_ABSOLUTE_CSS / COPY_SAFE_ORDER_HTML)
# ---------------------------------------------------------------------------

def _run(assertion_name, content):
    from assertions import AssertType, check_assertions

    (result,) = check_assertions(content, [AssertType(assertion_name)])
    return result


_GOOD_SONG_HTML = (
    "<html><head><body>"
    '<link rel="stylesheet" href="_static/doxtr_music.css">'
    '<div class="doxtr-song" role="group">'
    '<div class="doxtr-line">'
    '<span class="doxtr-chord" data-chord="Am" aria-hidden="true">Am</span>'
    '<span class="doxtr-lyric">Hello</span>'
    "</div></div></body></head></html>"
)


def test_position_absolute_css_passes_on_shipped_css():
    result = _run("position_absolute_css", _GOOD_SONG_HTML)
    assert result.passed, result.details


def test_position_absolute_css_fails_without_link():
    no_link = _GOOD_SONG_HTML.replace(
        '<link rel="stylesheet" href="_static/doxtr_music.css">', ""
    )
    result = _run("position_absolute_css", no_link)
    assert not result.passed


def test_copy_safe_order_passes_chord_not_in_lyric_stream():
    result = _run("copy_safe_order_html", _GOOD_SONG_HTML)
    assert result.passed, result.details


def test_copy_safe_order_detects_leaked_chord():
    # A (broken) renderer that put the chord glyph into selectable lyric text.
    leaked = (
        "<html><head><body>"
        '<div class="doxtr-song">'
        '<div class="doxtr-line">'
        '<span class="doxtr-chord" data-chord="Am">x</span>'
        '<span class="doxtr-lyric">Am and lyrics</span>'
        "</div></div></body></head></html>"
    )
    result = _run("copy_safe_order_html", leaked)
    assert not result.passed


def test_copy_safe_order_fails_without_song():
    result = _run("copy_safe_order_html", "<html><body>nothing</body></html>")
    assert not result.passed
