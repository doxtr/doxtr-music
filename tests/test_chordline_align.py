"""Unit tests for the chord-line parser + shared song-directive base (CHUNK-3-1).

Covers: column alignment (incl. mid-word), classification precedence
(directive > section > chord > lyric), pairing rules (chord→lyric, chord-only
EOF, stacked chord→chord, two lyrics, blank stanza), tab expansion, ragged
recovery, wide/combining + strong-RTL warnings, structural token-stream
equivalence with the equivalent ChordPro block, shared-seam usage, and the
absence of Sphinx imports / ``chord_column_in_lyric``.
"""

from __future__ import annotations

import inspect

import pytest

from doxtr_music.parsers.chordline import (
    CHORD_RE,
    is_plausible_chord,
    parse_chord_line,
)
from doxtr_music.parsers.chordpro import parse_chordpro
from doxtr_music.tokens import (
    ChordToken,
    LineBreakToken,
    LyricToken,
    SectionToken,
    SingerToken,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _chords(tokens):
    return [t for t in tokens if isinstance(t, ChordToken)]


def _lyrics(tokens):
    return [t for t in tokens if isinstance(t, LyricToken)]


def _sections(tokens):
    return [t for t in tokens if isinstance(t, SectionToken)]


def _chord_at(tokens, text):
    for t in _chords(tokens):
        if t.text == text:
            return t
    raise AssertionError("chord %r not found in %r" % (text, _chords(tokens)))


# ---------------------------------------------------------------------------
# column alignment (exit #1)
# ---------------------------------------------------------------------------

def test_chord_column_basic_alignment():
    text = "Am      C\nHello world here"
    tokens, meta = parse_chord_line(text)
    am = _chord_at(tokens, "Am")
    c = _chord_at(tokens, "C")
    # "Am" is at column 0, "C" at column 8 in the chord row.
    assert am.column == 0
    assert c.column == 8
    # Lyric "world" starts where? "Hello " = 6 chars -> world at 6.
    lyr = {t.text: t.column for t in _lyrics(tokens)}
    assert lyr["Hello"] == 0
    assert lyr["world"] == 6


def test_chord_mid_word_alignment():
    # Chord over the middle of a word: 'C' at column 3 lands inside "Hello".
    text = "   C\nHello"
    tokens, _ = parse_chord_line(text)
    c = _chord_at(tokens, "C")
    hello = _lyrics(tokens)[0]
    assert c.column == 3
    assert hello.column == 0
    # chord.column - word.column recovers the intra-word offset (3).
    assert c.column - hello.column == 3


def test_chord_line_index_is_lyric_row():
    # The chord + lyric collapse to the lyric row's logical index.
    text = "Am\nHello"
    tokens, _ = parse_chord_line(text)
    am = _chord_at(tokens, "Am")
    hello = _lyrics(tokens)[0]
    assert am.line == hello.line == 1


# ---------------------------------------------------------------------------
# classification precedence (exit #4)
# ---------------------------------------------------------------------------

def test_directive_beats_section_and_chord():
    # {title} is a directive, not a lyric of chord-like words.
    text = "{title: My Song}\nAm\nHello"
    tokens, meta = parse_chord_line(text)
    assert meta.get("title") == "My Song"
    # No lyric token named "My" (the directive line was consumed).
    assert all(t.text != "My" for t in _lyrics(tokens))


def test_bracket_section_header():
    text = "[Chorus]\nAm\nHello"
    tokens, _ = parse_chord_line(text)
    secs = _sections(tokens)
    assert len(secs) == 1
    assert secs[0].label == "Chorus"
    assert secs[0].kind == "chorus"


def test_bracket_verse_number_maps_kind():
    text = "[Verse 1]\nHello"
    tokens, _ = parse_chord_line(text)
    sec = _sections(tokens)[0]
    assert sec.label == "Verse 1"
    assert sec.kind == "verse"


def test_bracketed_chord_is_not_a_section():
    # ``[Am]`` alone is a chord-only row, never a section.
    text = "[Am]"
    tokens, _ = parse_chord_line(text)
    assert _sections(tokens) == []
    assert _chord_at(tokens, "Am").column == 0


def test_soc_and_singer_directives_match_song():
    text = "{soc}\n{singer: A}\nAm\nHello\n{eoc}"
    tokens, _ = parse_chord_line(text)
    secs = _sections(tokens)
    kinds = [s.kind for s in secs]
    assert "chorus" in kinds
    assert "none" in kinds  # {eoc} close
    assert any(isinstance(t, SingerToken) and t.singer == "A" for t in tokens)


# ---------------------------------------------------------------------------
# pairing rules (exit #5)
# ---------------------------------------------------------------------------

def test_chord_only_at_eof():
    text = "Am C"
    tokens, _ = parse_chord_line(text)
    assert [t.text for t in _chords(tokens)] == ["Am", "C"]
    assert _lyrics(tokens) == []  # anchored to empty lyric


def test_stacked_chord_rows_first_is_chord_only():
    text = "Am\nC\nHello"
    tokens, _ = parse_chord_line(text)
    chords = _chords(tokens)
    # Am is chord-only (followed by another chord row); C pairs with "Hello".
    assert [c.text for c in chords] == ["Am", "C"]
    hello = _lyrics(tokens)[0]
    assert hello.text == "Hello"
    # C pairs with the lyric line.
    c = _chord_at(tokens, "C")
    assert c.line == hello.line


def test_two_lyric_lines():
    text = "Hello there\nSecond line"
    tokens, _ = parse_chord_line(text)
    assert _chords(tokens) == []
    lyric_texts = [t.text for t in _lyrics(tokens)]
    assert "Hello" in lyric_texts and "Second" in lyric_texts


def test_blank_line_stanza_break():
    text = "Am\nHello\n\nC\nWorld"
    tokens, _ = parse_chord_line(text)
    # A LineBreak boundary exists between the two stanzas.
    assert any(isinstance(t, LineBreakToken) for t in tokens)
    assert [c.text for c in _chords(tokens)] == ["Am", "C"]


def test_chord_row_before_directive_is_chord_only():
    text = "Am\n{soc}\nHello"
    tokens, _ = parse_chord_line(text)
    # Am is not paired with the {soc} directive; it is chord-only.
    am = _chord_at(tokens, "Am")
    assert am.line == 0
    assert _sections(tokens)[0].kind == "chorus"


# ---------------------------------------------------------------------------
# robustness: tabs / ragged / wide / rtl (exit #5)
# ---------------------------------------------------------------------------

def test_tab_expansion_both_rows_same_stops():
    # Tab expands to column 8 on BOTH rows; chord lands over the lyric char at 8.
    text = "\tC\n\tHello"
    tokens, _ = parse_chord_line(text)
    c = _chord_at(tokens, "C")
    hello = _lyrics(tokens)[0]
    assert c.column == 8
    assert hello.column == 8
    assert c.column - hello.column == 0


def test_ragged_column_recovers_with_warning():
    # Chord far past lyric end -> clamped, warned, no crash.
    text = "          C\nHi"
    tokens, meta = parse_chord_line(text)
    c = _chord_at(tokens, "C")
    assert c.column == len("Hi")  # clamped to lyric length
    assert any("past the end" in msg for _, msg in meta.get("_warnings", []))


def test_wide_char_lyric_warns():
    text = "C\n\u4f60\u597d world"  # CJK "nihao"
    tokens, meta = parse_chord_line(text)
    assert any("single-cell" in msg for _, msg in meta.get("_warnings", []))
    # still produces tokens, no crash
    assert _chords(tokens)


def test_rtl_lyric_warns():
    text = "C\n\u05e9\u05dc\u05d5\u05dd world"  # Hebrew "shalom"
    tokens, meta = parse_chord_line(text)
    assert any("right-to-left" in msg for _, msg in meta.get("_warnings", []))
    assert _chords(tokens)


def test_never_crashes_on_garbage():
    for bad in ["", "   ", "\n\n", "]]][[[", "{", "{unknown junk}", "\t\t"]:
        tokens, meta = parse_chord_line(bad)
        assert isinstance(tokens, list)
        assert isinstance(meta, dict)


# ---------------------------------------------------------------------------
# structural equivalence with ChordPro (exit #2)
# ---------------------------------------------------------------------------

def test_structural_equivalence_with_chordpro():
    # Well-formed chord-line block and its ChordPro equivalent produce the same
    # ChordToken (text, column) + LyricToken (text, column) streams.
    cl_text = "Am      C\nHello world here"
    # Equivalent ChordPro: chord anchored at the same lyric columns.
    #   "Hello world here" -> "Hello " is 6 chars, so C is at column 8? No:
    #   In chord-line, Am@0 over 'H', C@8 over the 3rd char of "world".
    #   ChordPro places [Am] at col0, [C] before the char at col 8.
    #   col 8 in "Hello world here" is the 'r' of "world" (H0 e1 l2 l3 o4 sp5 w6 o7 r8)
    cp_text = "[Am]Hello wo[C]rld here"
    cl_tokens, _ = parse_chord_line(cl_text)
    cp_tokens, _ = parse_chordpro(cp_text)

    cl_chords = [(t.text, t.column) for t in _chords(cl_tokens)]
    cp_chords = [(t.text, t.column) for t in _chords(cp_tokens)]
    cl_lyrics = [(t.text, t.column) for t in _lyrics(cl_tokens)]
    cp_lyrics = [(t.text, t.column) for t in _lyrics(cp_tokens)]

    assert cl_chords == cp_chords
    assert cl_lyrics == cp_lyrics


# ---------------------------------------------------------------------------
# shared-seam usage + no Sphinx import (exit #3, #7)
# ---------------------------------------------------------------------------

def test_uses_shared_seams_not_chord_column_in_lyric():
    import doxtr_music.parsers.chordline as mod

    src = inspect.getsource(mod)
    assert "scan_chord_row" in src
    assert "tokenize_lyric_line" in src
    assert "parse_directive_line" in src
    # chord_column_in_lyric must be neither imported nor called (bracket-only).
    assert "chord_column_in_lyric" not in getattr(mod, "__dict__", {})
    import ast

    tree = ast.parse(src)
    imported = set()
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)
    assert "chord_column_in_lyric" not in imported
    assert "chord_column_in_lyric" not in called
    # positively confirm the three shared seams are imported.
    assert {"scan_chord_row", "tokenize_lyric_line", "parse_directive_line"} <= imported


def test_parser_has_no_sphinx_import():
    import ast

    import doxtr_music.parsers.chordline as mod

    tree = ast.parse(inspect.getsource(mod))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    assert not any(m == "sphinx" or m.startswith("sphinx.") for m in modules)
    assert not any(m == "docutils" or m.startswith("docutils.") for m in modules)


def test_return_contract_shape():
    tokens, meta = parse_chord_line("Am\nHello")
    assert isinstance(tokens, list)
    assert isinstance(meta, dict)


# ---------------------------------------------------------------------------
# chord-recognition regex
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "chord",
    ["A", "Am", "G7", "C#", "Bb", "F#m7", "Csus4", "Dadd9", "C/E", "G/B", "A#dim"],
)
def test_regex_accepts_plausible_chords(chord):
    assert is_plausible_chord(chord)
    assert CHORD_RE.match(chord)


@pytest.mark.parametrize("word", ["Hello", "world", "Chorus", "Verse", "the", "Am7and"])
def test_regex_rejects_non_chords(word):
    assert not is_plausible_chord(word)
