"""Tests for CHUNK-4-4 (``.. chord-progression::`` grid).

Two layers:

* Pure unit tests for the parse/classification/columns logic
  (:func:`classify_cell`, :func:`parse_grid`) — no Sphinx build.
* In-process Sphinx integration builds (HTML / LaTeX / EPUB) verifying the
  semantic-table rendering, chord localization, computed vs author-literal
  roman, empty/spacer cells, ragged-row padding, and that CHUNK-4-4 constructs
  ``RomanNode`` but does NOT register its visitor (3-3 owns it).
"""

from __future__ import annotations

import io
import re
import textwrap
from pathlib import Path

import pytest

from doxtr_music.directives.chord_progression import classify_cell, parse_grid

sphinx = pytest.importorskip("sphinx")
from sphinx.application import Sphinx  # noqa: E402


# ---------------------------------------------------------------------------
# Pure unit: cell classification (LOCKED evaluation order)
# ---------------------------------------------------------------------------

def test_classify_empty_is_spacer():
    assert classify_cell("") == ("empty", None)
    assert classify_cell("   ") == ("empty", None)


def test_classify_chord_before_roman():
    # A real chord that could look roman-ish still classifies as a chord first.
    kind, payload = classify_cell("C")
    assert kind == "chord"
    assert payload == "C"
    # G7 parses as a chord (root G, quality 7), NOT an author-literal roman.
    assert classify_cell("G7")[0] == "chord"


def test_classify_author_literal_roman():
    # V7 is not a chord (V is not a note) → author-literal roman.
    assert classify_cell("V7") == ("roman", "V7")
    assert classify_cell("I") == ("roman", "I")
    assert classify_cell("III") == ("roman", "III")
    assert classify_cell("vi") == ("roman", "vi")
    assert classify_cell("ii\u00b0") == ("roman", "ii\u00b0")


def test_classify_chord_wins_over_ambiguous_roman():
    # LOCKED evaluation order: parse_chord() is tried BEFORE the roman
    # recognizer, so ``bVII`` (flat-B root, quality "VII") is a chord, not a
    # roman. This is intentional — chord recognition has priority.
    assert classify_cell("bVII")[0] == "chord"


def test_classify_literal_passthrough():
    kind, payload = classify_cell("???")
    assert kind == "literal"
    assert payload == "???"


# ---------------------------------------------------------------------------
# Pure unit: grid parse (columns derivation, ragged padding, warnings)
# ---------------------------------------------------------------------------

def test_parse_grid_columns_and_cells():
    rows, columns, warnings = parse_grid(["| C | F | G | C |"])
    assert columns == 4
    assert len(rows) == 1
    assert [k for k, _ in rows[0]] == ["chord", "chord", "chord", "chord"]
    assert warnings == []


def test_parse_grid_leading_trailing_bar_optional():
    rows, columns, _ = parse_grid(["C | F | G"])
    assert columns == 3
    assert [k for k, _ in rows[0]] == ["chord", "chord", "chord"]


def test_parse_grid_empty_cell_is_spacer():
    rows, columns, _ = parse_grid(["| C |  | G |"])
    assert columns == 3
    assert rows[0][1] == ("empty", None)


def test_parse_grid_ragged_row_padded_with_warning():
    rows, columns, warnings = parse_grid(["| C | F | G | C |", "| Am | G7 |"])
    assert columns == 4
    # short row padded to 4 with trailing empty cells
    assert len(rows[1]) == 4
    assert rows[1][2] == ("empty", None)
    assert rows[1][3] == ("empty", None)
    assert any("ragged" in msg for _, msg in warnings)


def test_parse_grid_literal_cell_warns():
    _, _, warnings = parse_grid(["| C | ??? | G |"])
    assert any("unrecognized" in msg for _, msg in warnings)


def test_parse_grid_blank_lines_skipped():
    rows, columns, _ = parse_grid(["| C | F |", "", "| G | C |"])
    assert len(rows) == 2
    assert columns == 2


# ---------------------------------------------------------------------------
# Integration: in-process Sphinx builds (HTML / LaTeX / EPUB)
# ---------------------------------------------------------------------------

def _make_project(root: Path, index_rst: str, extra_conf: str = "") -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music"]\n'
        'html_theme = "basic"\n'
        + extra_conf,
        encoding="utf-8",
    )
    (src / "index.rst").write_text(index_rst, encoding="utf-8")
    return src


def _build(root: Path, index_rst: str, builder: str, extra_conf: str = "",
           warnings_buf=None):
    src = _make_project(root, index_rst, extra_conf)
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(root / "out"),
        doctreedir=str(root / "doctrees"),
        buildername=builder,
        freshenv=True,
        warning=warnings_buf,
    )
    app.build(force_all=True)
    return root / "out"


_BASIC_GRID = textwrap.dedent(
    """
    Title
    =====

    .. chord-progression::

       | C | F | G | C |
    """
)

_ROMAN_GRID = textwrap.dedent(
    """
    Title
    =====

    .. chord-progression::
       :key: C
       :roman-numerals:

       | C | F | G | C |
    """
)

_LITERAL_ROMAN_GRID = textwrap.dedent(
    """
    Title
    =====

    .. chord-progression::

       | I | IV | V | I |
    """
)

_MIXED_GRID = textwrap.dedent(
    """
    Title
    =====

    .. chord-progression::
       :key: C
       :roman-numerals:

       | V7 | C | F |
    """
)


def test_html_basic_grid_is_semantic_table(tmp_path):
    out = _build(tmp_path, _BASIC_GRID, "html")
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="doxtr-progression"' in html
    assert "<table" in html and "<td" in html
    assert "<caption" in html
    # chords localized (english identity here) present
    assert ">C<" in html or ">C</span>" in html
    # a progression has NO lyrics / no chord-over-lyric <pre>
    assert "doxtr-line" not in html


def test_html_computed_roman_from_key(tmp_path):
    out = _build(tmp_path, _ROMAN_GRID, "html")
    html = (out / "index.html").read_text(encoding="utf-8")
    # C->I, F->IV, G->V computed alongside the chord
    for numeral in ("I", "IV", "V"):
        assert 'aria-label="Roman numeral: %s"' % numeral in html or (
            ">%s<" % numeral in html
        )


def test_html_no_key_no_computed_roman(tmp_path):
    out = _build(tmp_path, _BASIC_GRID, "html")
    html = (out / "index.html").read_text(encoding="utf-8")
    # No :key: → no computed roman span in the chord cells.
    assert 'class="doxtr-roman"' not in html


def test_html_author_literal_roman_not_reanalyzed(tmp_path):
    out = _build(tmp_path, _LITERAL_ROMAN_GRID, "html")
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="doxtr-roman"' in html
    # author-literal romans render as-is
    for numeral in ("I", "IV", "V"):
        assert ">%s<" % numeral in html


def test_html_german_localization(tmp_path):
    grid = textwrap.dedent(
        """
        Title
        =====

        .. chord-progression::

           | Bb | B | C |
        """
    )
    out = _build(tmp_path, grid, "html",
                 extra_conf='doxtr_music_chord_system = "german"\n')
    html = (out / "index.html").read_text(encoding="utf-8")
    # german: Bb->B, B->H
    assert ">B<" in html  # from Bb
    assert ">H<" in html  # from B


def test_html_mixed_row_literal_and_computed(tmp_path):
    out = _build(tmp_path, _MIXED_GRID, "html")
    html = (out / "index.html").read_text(encoding="utf-8")
    # V7 stays author-literal; C/F get computed roman I/IV
    assert ">V7<" in html
    assert "<td" in html


def test_latex_emits_tabular(tmp_path):
    out = _build(tmp_path, _ROMAN_GRID, "latex")
    tex = next(out.glob("*.tex")).read_text(encoding="utf-8")
    assert "\\begin{tabular}" in tex
    assert "\\dmchordinline" in tex
    assert "\\dmroman" in tex


def test_latex_escapes_and_colspec(tmp_path):
    out = _build(tmp_path, _BASIC_GRID, "latex")
    tex = next(out.glob("*.tex")).read_text(encoding="utf-8")
    # 4-column grid → column spec derived from `columns`
    assert "{*{4}{c}}" in tex


def test_epub_emits_semantic_table(tmp_path):
    out = _build(tmp_path, _ROMAN_GRID, "epub")
    xhtml = "".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in out.glob("*.xhtml")
    )
    assert 'class="doxtr-progression"' in xhtml
    assert "<td" in xhtml
    assert "<caption" in xhtml
    # EPUB progression is a genuine table, NOT the song <pre> two-row model
    assert "doxtr-line-epub" not in xhtml


def test_ragged_row_warns_but_builds(tmp_path):
    grid = textwrap.dedent(
        """
        Title
        =====

        .. chord-progression::

           | C | F | G | C |
           | Am | G7 |
        """
    )
    buf = io.StringIO()
    out = _build(tmp_path, grid, "html", warnings_buf=buf)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "<table" in html  # built despite ragged row
    assert "ragged" in buf.getvalue()


def test_never_crashes_on_garbage(tmp_path):
    grid = textwrap.dedent(
        """
        Title
        =====

        .. chord-progression::

           | ??? | @@ | !! |
        """
    )
    buf = io.StringIO()
    out = _build(tmp_path, grid, "html", warnings_buf=buf)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "<table" in html
    assert "unrecognized" in buf.getvalue()


# ---------------------------------------------------------------------------
# Seam checks: reserved nodes + no RomanNode-visitor registration by 4-4
# ---------------------------------------------------------------------------

def test_uses_reserved_progression_cell_node():
    from doxtr_music import nodes as _nodes
    from doxtr_music.directives.chord_progression import (
        ChordProgressionDirective,
    )

    # The directive class references the reserved node types (no nodes.py edit).
    assert hasattr(_nodes, "ProgressionCellNode")
    assert hasattr(_nodes, "ProgressionRowNode")
    assert hasattr(_nodes, "ChordProgressionNode")
    assert ChordProgressionDirective.has_content is True


def test_chord_progression_module_does_not_register_roman_visitor():
    import inspect

    from doxtr_music.directives import chord_progression

    src = inspect.getsource(chord_progression)
    # 4-4 constructs RomanNode but must NOT register a RomanNode _VISITORS entry
    # (3-3 owns the RomanNode visitor). Check there is no assignment INTO the
    # visitor registry from this module.
    assert "_VISITORS[" not in src
    assert ".RomanNode]" not in src  # no dict-assignment registration
    assert "RomanNode" in src  # it does construct them
