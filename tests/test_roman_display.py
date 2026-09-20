"""Roman-numeral display modes: off / replace / alongside (+ formattable).

The ``roman_display`` mode selects whether a chord shows its name, the numeral
instead, or both; the ``alongside`` template (``roman_format``) is a
``{chord}``/``{roman}`` string the user controls.
"""
from __future__ import annotations

import pytest

from doxtr_music import config as cfg
from doxtr_music.engine.i18n import (
    resolve_chord_display,
    resolve_chord_display_parts,
)
from doxtr_music.engine.roman import roman_tokens
from doxtr_music.nodes import ChordNode, build_nodes
from doxtr_music.parsers.chordpro import parse_chordpro


class _Cfg:
    doxtr_music_chord_system = "english"


def _analyzed_chords(src="[G]Amazing [C]grace [D]now", key="G"):
    tokens, meta = parse_chordpro(src)
    tokens = roman_tokens(tokens, key)
    song = build_nodes(tokens, meta)
    return list(song.findall(ChordNode))


def _set(chords, mode, fmt=None):
    for c in chords:
        c["roman_display"] = mode
        if fmt is not None:
            c["roman_format"] = fmt


# --- config validation ------------------------------------------------------

def test_validate_roman_format_requires_both_placeholders():
    assert cfg.validate_roman_format("{chord} ({roman})") == "{chord} ({roman})"
    warns = []
    # missing {roman} -> default
    assert cfg.validate_roman_format("{chord}", warn=warns.append) == cfg.DEFAULT_ROMAN_FORMAT
    # unknown placeholder -> default
    assert cfg.validate_roman_format("{chord} {bogus}", warn=warns.append) == cfg.DEFAULT_ROMAN_FORMAT
    # empty -> default
    assert cfg.validate_roman_format("", warn=warns.append) == cfg.DEFAULT_ROMAN_FORMAT
    assert len(warns) == 2  # the two invalid non-empty templates warned


def test_default_roman_format_is_parenthesized():
    assert cfg.DEFAULT_ROMAN_FORMAT == "{chord} ({roman})"


def test_valid_roman_displays():
    assert cfg.VALID_ROMAN_DISPLAYS == frozenset({"off", "replace", "alongside"})


# --- display resolution -----------------------------------------------------

def test_display_off_is_chord_name():
    chords = _analyzed_chords()
    _set(chords, "off")
    assert [resolve_chord_display(c, _Cfg()) for c in chords] == ["G", "C", "D"]


def test_display_replace_is_numeral():
    chords = _analyzed_chords()
    _set(chords, "replace")
    assert [resolve_chord_display(c, _Cfg()) for c in chords] == ["I", "IV", "V"]


def test_display_alongside_default_format():
    chords = _analyzed_chords()
    _set(chords, "alongside", "{chord} ({roman})")
    assert [resolve_chord_display(c, _Cfg()) for c in chords] == [
        "G (I)", "C (IV)", "D (V)"
    ]


def test_display_alongside_custom_format():
    chords = _analyzed_chords()
    _set(chords, "alongside", "{roman}: {chord}")
    assert [resolve_chord_display(c, _Cfg()) for c in chords] == [
        "I: G", "IV: C", "V: D"
    ]


def test_display_alongside_stacked_newline():
    chords = _analyzed_chords()
    _set(chords, "alongside", "{chord}\n{roman}")
    assert resolve_chord_display(chords[0], _Cfg()) == "G\nI"


def test_alongside_degrades_without_numeral():
    # A chord with no roman (e.g. no key) in alongside mode -> chord name only.
    tokens, meta = parse_chordpro("[G]Hi")
    song = build_nodes(tokens, meta)  # no roman annotation
    chord = list(song.findall(ChordNode))[0]
    chord["roman_display"] = "alongside"
    chord["roman_format"] = "{chord} ({roman})"
    assert resolve_chord_display(chord, _Cfg()) == "G"


# --- parts (independent numeral styling) ------------------------------------

def test_parts_alongside_splits_chord_and_roman():
    chords = _analyzed_chords()
    _set(chords, "alongside", "{chord} ({roman})")
    parts = resolve_chord_display_parts(chords[0], _Cfg())
    assert parts == [
        ("chord", "G"), ("literal", " ("), ("roman", "I"), ("literal", ")")
    ]


def test_parts_replace_is_single_roman():
    chords = _analyzed_chords()
    _set(chords, "replace")
    assert resolve_chord_display_parts(chords[0], _Cfg()) == [("roman", "I")]


def test_parts_off_is_single_chord():
    chords = _analyzed_chords()
    _set(chords, "off")
    assert resolve_chord_display_parts(chords[0], _Cfg()) == [("chord", "G")]


# --- option parsing ---------------------------------------------------------

def test_normalize_options_roman_display_and_format():
    from doxtr_music.directives._options import normalize_options

    n = normalize_options({"roman-display": "alongside", "roman-format": "{chord} ({roman})"})
    assert n["roman_display"] == "alongside"
    assert n["roman_format"] == "{chord} ({roman})"


def test_legacy_roman_numerals_flag_maps_to_replace():
    from doxtr_music.directives._options import normalize_options

    n = normalize_options({"roman-numerals": None})  # flag present
    assert n["roman_numerals"] is True
    assert n["roman_display"] == "replace"


def test_roman_display_wins_over_legacy_flag():
    from doxtr_music.directives._options import normalize_options

    n = normalize_options({"roman-numerals": None, "roman-display": "alongside"})
    assert n["roman_display"] == "alongside"


def test_no_roman_option_leaves_display_none():
    from doxtr_music.directives._options import normalize_options

    n = normalize_options({})
    assert n["roman_display"] is None


# --- integration across the three builders ----------------------------------

_RST = (
    "S\n=\n\n"
    ".. song::\n"
    "   :roman-display: alongside\n"
    "   :roman-format: {chord} ({roman})\n\n"
    "   {key: G}\n"
    "   [G]Amazing [C]grace [D]now\n"
)


def _build(tmp_path, builder):
    from sphinx.application import Sphinx

    src = tmp_path / "src"
    src.mkdir()
    conf = (
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music"]\n'
        "doxtr_music_autoload_theme = False\n"
    )
    if builder == "latex":
        conf += 'latex_documents = [("index", "s.tex", "S", "A", "manual")]\n'
    (src / "conf.py").write_text(conf, encoding="utf-8")
    (src / "index.rst").write_text(_RST, encoding="utf-8")
    out = tmp_path / builder
    app = Sphinx(
        srcdir=str(src), confdir=str(src), outdir=str(out),
        doctreedir=str(tmp_path / "dt" / builder), buildername=builder,
        status=None, warning=None, freshenv=True,
    )
    app.build(force_all=True)
    return out


def test_html_alongside_renders_chord_and_styled_roman(tmp_path):
    html = (_build(tmp_path, "html") / "index.html").read_text(encoding="utf-8")
    assert "G (" in html and "IV" in html
    # the numeral part is a styled inner span
    assert "doxtr-roman-inline" in html


def test_latex_alongside_wraps_numeral_in_dmroman(tmp_path):
    tex = next((_build(tmp_path, "latex")).glob("*.tex")).read_text(encoding="utf-8")
    assert "\\dmchord{G (\\dmroman{I})}" in tex


@pytest.mark.integration
def test_epub_alongside_scalar(tmp_path):
    out = _build(tmp_path, "epub")
    xhtmls = list(out.rglob("index.xhtml")) + list(out.rglob("index.html"))
    assert xhtmls
    content = xhtmls[0].read_text(encoding="utf-8")
    assert "G (I)" in content
