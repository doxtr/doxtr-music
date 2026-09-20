"""Tests for CHUNK-2-2 — EPUB reflow-safe ``<pre>`` foundation.

Covers the exit criteria:

* A ``.. song::`` builds under ``-b epub`` (write-only) to EPUB XHTML with the
  ``<pre>`` chord-row/lyric-row model, not absolute-positioned chords.
* ``COPY_SAFE_ORDER_EPUB_PRE``: the lyric row is extractable and equals the
  logical lyric stream; the chord row is a separate run; the lyric row is not
  ``user-select:none``.
* Alignment: a multi-chord **Latin** line aligns chord cells over lyric cells
  (East-Asian-width cell mapping + shared-cursor overrun policy).
* No ``position:absolute`` in the EPUB **song XHTML markup**.
* Rendering wired via ``_VISITORS["epub"]`` (dict assignment); no ``nodes.py``
  edit, no ``add_node(override=True)``, no HTML branch.
* a11y wrapper hook present; ``svg`` reserved with a text-alternative note.
* No import of ``doxtr_pdf_theme_core``; reads no ``doxtr_music_*`` config.
"""

from __future__ import annotations

import glob
import re
import textwrap
from pathlib import Path

import pytest

from doxtr_music import nodes as _nodes
from doxtr_music.builders import epub as dm_epub

sphinx = pytest.importorskip("sphinx")
from sphinx.application import Sphinx  # noqa: E402


def _code_only(module):
    """Return module source with docstrings and comments removed.

    Static "no X in the code" assertions must inspect executable code, not the
    module/function docstrings (which legitimately *describe* the contracts by
    name) nor ``#`` comments.
    """
    import io
    import tokenize

    src = Path(module.__file__).read_text(encoding="utf-8")
    out = []
    prev_type = tokenize.NEWLINE
    tokens = tokenize.generate_tokens(io.StringIO(src).readline)
    for tok_type, tok_str, _start, _end, _line in tokens:
        if tok_type == tokenize.COMMENT:
            continue
        if tok_type == tokenize.STRING and prev_type in (
            tokenize.INDENT,
            tokenize.NEWLINE,
            tokenize.NL,
            tokenize.ENCODING,
        ):
            # A string statement in expression position = a docstring; skip.
            prev_type = tokenize.STRING
            continue
        out.append(tok_str)
        if tok_type not in (tokenize.NL,):
            prev_type = tok_type
    return " ".join(out)


# ---------------------------------------------------------------------------
# Display-cell math (East-Asian width)
# ---------------------------------------------------------------------------

def test_char_cells_latin_single_width():
    assert dm_epub._char_cells("a") == 1
    assert dm_epub._char_cells("#") == 1


def test_char_cells_wide_and_combining():
    # CJK ideograph is 2 cells; a combining acute accent is 0 cells.
    assert dm_epub._char_cells("\u4e2d") == 2  # 中
    assert dm_epub._char_cells("\u0301") == 0  # combining acute


def test_cell_offset_latin_is_identity():
    text = "Hello world"
    assert dm_epub._cell_offset(text, 0) == 0
    assert dm_epub._cell_offset(text, 6) == 6


def test_cell_offset_past_end_pads_by_codepoint():
    text = "abc"
    assert dm_epub._cell_offset(text, 5) == 5


def test_cell_offset_wide_prefix():
    # Two wide chars before column 2 → 4 cells.
    text = "\u4e2d\u6587xy"  # 中文xy
    assert dm_epub._cell_offset(text, 2) == 4


# ---------------------------------------------------------------------------
# Row layout helpers
# ---------------------------------------------------------------------------

def test_lyric_stream_is_logical_order_single_space():
    lyrics = [(0, "Hello", None), (6, "world", None), (12, "today", None)]
    assert dm_epub._lyric_stream(lyrics) == "Hello world today"


def test_reconstruct_lyric_row_pads_from_cell_gaps():
    lyrics = [(0, "Hello", None), (6, "world", None)]
    row, segments = dm_epub._reconstruct_lyric_row(lyrics)
    assert row == "Hello world"
    # No singer colors → no colored segments.
    assert segments == []


def test_layout_chord_row_aligns_over_cells():
    # Am at cell 0, C at cell 6 → chord row places C above "world".
    row, _segments = dm_epub._layout_chord_row([(0, "Am", None), (6, "C", None)])
    assert row.startswith("Am")
    assert row.index("C") == 6


def test_layout_chord_row_overrun_stays_column_locked():
    # F#m7b5 (6 cells) at cell 0, next chord requested at cell 5 → pushed past
    # the wide label so labels never collide.
    row, _segments = dm_epub._layout_chord_row([(0, "F#m7b5", None), (5, "C", None)])
    assert row.startswith("F#m7b5")
    # The C must appear AFTER the full F#m7b5 label (no overlap).
    assert row.index("C") >= len("F#m7b5")


# ---------------------------------------------------------------------------
# Seam: _VISITORS["epub"] filled by dict assignment; no HTML/latex touch
# ---------------------------------------------------------------------------

def test_epub_bucket_filled_by_assignment():
    dm_epub.register_epub_visitors()
    epub = _nodes._VISITORS["epub"]
    for nc in (
        _nodes.SongNode,
        _nodes.SectionNode,
        _nodes.LineNode,
        _nodes.ChordNode,
        _nodes.LyricNode,
        _nodes.SingerSpanNode,
    ):
        assert nc in epub
        assert callable(epub[nc][0]) and callable(epub[nc][1])


def test_epub_module_does_not_touch_other_buckets():
    src = _code_only(dm_epub)
    assert '_VISITORS["html"]' not in src
    assert '_VISITORS["latex"]' not in src
    assert "add_node" not in src  # no re-registration / override


def test_no_core_import():
    src = Path(dm_epub.__file__).read_text(encoding="utf-8")
    assert "import doxtr_pdf_theme_core" not in src
    assert "from doxtr_pdf_theme_core" not in src


def test_reads_no_config():
    """This chunk registers/reads no doxtr_music_* config value.

    Scoped to config *attribute access* (``config.doxtr_music_*`` /
    ``getattr(config, "doxtr_music_...")``) so the EPUB CSS *filename* literal
    (``doxtr_music_epub.css``) is not a false positive.
    """
    src = _code_only(dm_epub)
    assert "config.doxtr_music_" not in src
    assert '"doxtr_music_' not in src.replace('"doxtr_music_epub.css"', "")
    assert "'doxtr_music_" not in src
    assert "add_config_value" not in src


def test_svg_text_alternative_reserved_in_docs():
    """The svg future strategy's WCAG 1.1.1 text-alt requirement is documented."""
    src = Path(dm_epub.__file__).read_text(encoding="utf-8")
    assert "svg" in src.lower()
    assert "text alternative" in src.lower()


# ---------------------------------------------------------------------------
# Write-only -b epub integration build
# ---------------------------------------------------------------------------

_SONG_RST = textwrap.dedent(
    """
    Title
    =====

    .. song::

       {title: My Song}
       {start_of_verse}
       [Am]Hello [C]world today
       {end_of_verse}
       [F#m7b5]Weird[C]stuff
    """
)


def _build_epub(root: Path) -> str:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\nversion = "1"\n'
        'copyright = "s"\n'
        'extensions = ["doxtr_music"]\n',
        encoding="utf-8",
    )
    (src / "index.rst").write_text(_SONG_RST, encoding="utf-8")
    out = root / "out"
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(root / "dt"),
        buildername="epub",
        freshenv=True,
    )
    app.build(force_all=True)
    for f in sorted(glob.glob(str(out / "*.xhtml"))):
        txt = Path(f).read_text(encoding="utf-8")
        if "doxtr-song" in txt:
            return txt
    raise AssertionError("no EPUB xhtml with a song found")


def _extract_song_block(xhtml: str) -> str:
    start = xhtml.index('<div class="doxtr-song')
    # Balance divs from the song wrapper to its close.
    depth = 0
    i = start
    for m in re.finditer(r"</?div\b", xhtml[start:]):
        if xhtml[start + m.start() + 1] == "/":
            depth -= 1
        else:
            depth += 1
        if depth == 0:
            end = start + m.end()
            close = xhtml.index(">", end) + 1
            return xhtml[start:close]
    return xhtml[start:]


def _pre_blocks(song_block: str):
    return re.findall(r"<pre class=\"doxtr-line-epub\">(.*?)</pre>", song_block, re.S)


def _chordrow(pre: str) -> str:
    m = re.search(r'<span class="doxtr-chordrow"[^>]*>(.*?)</span>', pre, re.S)
    return m.group(1) if m else ""


def _lyricrow(pre: str) -> str:
    m = re.search(r'<span class="doxtr-lyricrow">(.*?)</span>', pre, re.S)
    return m.group(1) if m else ""


@pytest.mark.integration
def test_epub_build_has_pre_two_row_model(tmp_path):
    xhtml = _build_epub(tmp_path)
    block = _extract_song_block(xhtml)
    # Exit #1: <pre> chord-row/lyric-row model present.
    assert '<pre class="doxtr-line-epub">' in block
    assert 'class="doxtr-chordrow"' in block
    assert 'class="doxtr-lyricrow"' in block
    # Exit #6: a11y wrapper hook with the shared marker.
    assert 'class="doxtr-song doxtr-song-epub"' in block


@pytest.mark.integration
def test_epub_no_absolute_positioning_in_markup(tmp_path):
    xhtml = _build_epub(tmp_path)
    block = _extract_song_block(xhtml)
    # Exit #4: no absolute positioning nor absolute-positioned .doxtr-chord span
    # in the song XHTML markup (assertion scoped to markup, not the CSS file).
    assert "position:absolute" not in block.replace(" ", "")
    assert '<span class="doxtr-chord"' not in block  # HTML absolute chord span


@pytest.mark.integration
def test_epub_copy_safe_order_lyric_row_extract(tmp_path):
    xhtml = _build_epub(tmp_path)
    block = _extract_song_block(xhtml)
    pres = _pre_blocks(block)
    assert pres, "no <pre> line blocks"
    # First line: "Hello world today" — the lyric row equals the logical stream.
    lyric = _lyricrow(pres[0])
    assert lyric == "Hello world today"
    # Chord row is a SEPARATE run (its own span), not interleaved into lyrics.
    assert "doxtr-chordrow" in pres[0]
    chord = _chordrow(pres[0])
    assert "Hello" not in chord and "world" not in chord
    # Exit #2: the lyric row is NOT user-select:none (the CSS gates that; the
    # markup must not stamp an inline non-select on the lyric run).
    assert "user-select" not in _lyricrow(pres[0])


@pytest.mark.integration
def test_epub_latin_multichord_alignment(tmp_path):
    xhtml = _build_epub(tmp_path)
    block = _extract_song_block(xhtml)
    pres = _pre_blocks(block)
    # Line 1: Am over "Hello" (cell 0), C over "world" (cell 6).
    chord = _chordrow(pres[0])
    lyric = _lyricrow(pres[0])
    assert chord.startswith("Am")
    # C aligns over the start of "world".
    assert chord.index("C") == lyric.index("world")


@pytest.mark.integration
def test_epub_chord_overrun_stays_column_locked(tmp_path):
    xhtml = _build_epub(tmp_path)
    block = _extract_song_block(xhtml)
    pres = _pre_blocks(block)
    # Last line: [F#m7b5]Weird[C]stuff — F#m7b5 is wider than the gap to C.
    overrun = [p for p in pres if "F#m7b5" in _chordrow(p)][0]
    chord = _chordrow(overrun)
    # C must appear after the full F#m7b5 label (labels never collide).
    assert chord.index("C") >= chord.index("F#m7b5") + len("F#m7b5")


@pytest.mark.integration
def test_html_vs_epub_differ(tmp_path):
    """HTML uses absolute .doxtr-chord spans + line box, no <pre>; EPUB uses a
    <pre> chord row and no absolute chord span (concrete divergence check)."""
    # EPUB output.
    epub_xhtml = _build_epub(tmp_path / "e")
    epub_block = _extract_song_block(epub_xhtml)
    assert '<pre class="doxtr-line-epub">' in epub_block
    assert '<span class="doxtr-chord"' not in epub_block

    # HTML output.
    src = tmp_path / "h" / "src"
    src.mkdir(parents=True)
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music"]\nhtml_theme = "basic"\n',
        encoding="utf-8",
    )
    (src / "index.rst").write_text(_SONG_RST, encoding="utf-8")
    out = tmp_path / "h" / "out"
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(tmp_path / "h" / "dt"),
        buildername="html",
        freshenv=True,
    )
    app.build(force_all=True)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert '<span class="doxtr-chord"' in html  # real absolute-positioned span
    assert '<div class="doxtr-line">' in html  # position-context line box
    assert '<pre class="doxtr-line-epub">' not in html  # no EPUB pre in HTML
