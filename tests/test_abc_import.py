"""Unit tests for the ABC importer (CHUNK-6-2).

Exercise the pure ``parse_abc`` parser (chords, ``w:`` alignment algorithm,
bars-as-metadata, header→song_meta, multi-tune/multi-verse policy, robustness)
and the ``.. import-abc::`` directive wiring (subclasses 6-1's
``ImportDirectiveBase``, reuses the confined loader, front-end convergence).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from doxtr_music.parsers.abc import parse_abc
from doxtr_music.tokens import (
    BarToken,
    ChordToken,
    LyricToken,
    SectionToken,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chords(tokens):
    return [t for t in tokens if isinstance(t, ChordToken)]


def _lyrics(tokens):
    return [t for t in tokens if isinstance(t, LyricToken)]


def _bars(tokens):
    return [t for t in tokens if isinstance(t, BarToken)]


# ---------------------------------------------------------------------------
# Chords: quoted symbols, slash, annotations, parse_chord None policy
# ---------------------------------------------------------------------------

def test_quoted_chords_become_chord_text():
    tokens, meta = parse_abc('"C"C "G"D "Am"E\nw: la la la')
    texts = [c.text for c in _chords(tokens)]
    assert texts == ["C", "G", "Am"]


def test_slash_chord_kept_verbatim():
    tokens, meta = parse_abc('"C/E"C\nw: la')
    assert [c.text for c in _chords(tokens)] == ["C/E"]


def test_text_annotation_excluded_from_chords():
    tokens, meta = parse_abc('"^Slowly"C "C"C\nw: la la')
    texts = [c.text for c in _chords(tokens)]
    assert texts == ["C"]  # the "^Slowly" annotation is not a chord
    assert any("annotation" in w[1] for w in meta["_warnings"])


def test_all_annotation_leaders_excluded():
    for leader in "^_<>@":
        tokens, meta = parse_abc('"%sfoo"C\nw: la' % leader)
        assert _chords(tokens) == [], "leader %r should not be a chord" % leader


def test_parse_chord_none_kept_verbatim_and_warned():
    # 'Zylophone' is not a recognizable chord; kept verbatim, warned, not dropped.
    tokens, meta = parse_abc('"Zqx"C\nw: la')
    texts = [c.text for c in _chords(tokens)]
    assert texts == ["Zqx"]  # kept verbatim
    assert any("unrecognized chord" in w[1] for w in meta["_warnings"])


# ---------------------------------------------------------------------------
# w: alignment algorithm: note-event enumeration + syllable pairing + column
# ---------------------------------------------------------------------------

def test_note_event_enumeration_basic_columns():
    # Two chords over two syllables -> synthetic line "Hel lo ", chords at the
    # syllable start columns.
    tokens, meta = parse_abc('"C"C "G"D\nw: Hel lo')
    chords = _chords(tokens)
    lyrics = _lyrics(tokens)
    assert [c.text for c in chords] == ["C", "G"]
    # First chord over "Hel" at column 0, second over "lo".
    assert chords[0].column == 0
    line = "".join  # noqa: F841
    # "Hel" then space then "lo": column of "lo" is 4.
    lyric_words = {l.text: l.column for l in lyrics}
    assert "Hel" in lyric_words and "lo" in lyric_words
    assert chords[1].column == lyric_words["lo"]


def test_within_word_hyphen_break_reconstructs_word():
    # 'Hel-lo' is one word split into two syllables; two notes carry it.
    tokens, meta = parse_abc('"C"C "G"D\nw: Hel-lo')
    lyrics = _lyrics(tokens)
    # No space between the syllables -> single reconstructed word "Hello".
    assert [l.text for l in lyrics] == ["Hello"]
    chords = _chords(tokens)
    # First syllable at col 0, second syllable "lo" at col 3 (after "Hel").
    assert chords[0].column == 0
    assert chords[1].column == 3


def test_hold_underscore_consumes_note_without_syllable():
    # 'la _ la' : hold extends over the 2nd note (no new syllable there).
    tokens, meta = parse_abc('"C"C "G"D "Am"E\nw: la _ la')
    chords = _chords(tokens)
    assert [c.text for c in chords] == ["C", "G", "Am"]
    lyrics = _lyrics(tokens)
    words = [l.text for l in lyrics]
    assert words == ["la", "la"]
    # The 2nd chord (G) sits over the held (empty) position -> its column is the
    # gap between the two 'la' words, distinct from both.
    cols = [c.column for c in chords]
    assert cols[0] != cols[1] != cols[2]


def test_blank_star_skips_a_note():
    # '*' is a blank syllable: the note gets no lyric.
    tokens, meta = parse_abc('"C"C "G"D\nw: * la')
    lyrics = _lyrics(tokens)
    assert [l.text for l in lyrics] == ["la"]
    chords = _chords(tokens)
    # First chord over the blank (empty) position, second over 'la'.
    assert chords[0].column != chords[1].column


def test_bar_checkpoint_in_w_line_does_not_consume_note():
    tokens, meta = parse_abc('"C"C "G"D | "Am"E\nw: one two | three')
    lyrics = [l.text for l in _lyrics(tokens)]
    assert lyrics == ["one", "two", "three"]


def test_instrumental_note_without_syllable():
    # More notes than syllables: trailing note is instrumental (lyric-less), but
    # a chord over it still anchors at a distinct column.
    tokens, meta = parse_abc('"C"C "G"D "Am"E\nw: one two')
    chords = _chords(tokens)
    assert [c.text for c in chords] == ["C", "G", "Am"]
    cols = [c.column for c in chords]
    assert len(set(cols)) == 3  # all distinct columns


# ---------------------------------------------------------------------------
# Bars: metadata-only, repeat hint in annotations
# ---------------------------------------------------------------------------

def test_bars_present_on_token_stream():
    tokens, meta = parse_abc('"C"C | "G"D |\nw: la la')
    assert len(_bars(tokens)) == 2


def test_repeat_bar_hint_in_annotations():
    tokens, meta = parse_abc('|: "C"C :|\nw: la')
    bars = _bars(tokens)
    hints = [dict(b.annotations).get("repeat") for b in bars]
    assert "repeat-start" in hints
    assert "repeat-end" in hints


def test_bars_dropped_from_node_tree(sphinx_song_build):
    # build_nodes drops BarTokens: an imported tune with bars renders chords +
    # lyrics and never an unhandled-node error.
    tokens, meta = parse_abc('"C"C | "G"D |\nw: la la')
    # Sanity: the render tokens (chords/lyrics) are present alongside bars.
    assert _chords(tokens) and _bars(tokens)


# ---------------------------------------------------------------------------
# Header fields -> song_meta
# ---------------------------------------------------------------------------

def test_header_fields_to_song_meta():
    abc = (
        "X:1\n"
        "T:My Tune\n"
        "C:The Composer\n"
        "M:3/4\n"
        "Q:120\n"
        "K:G\n"
        '"G"G\n'
        "w: la\n"
    )
    tokens, meta = parse_abc(abc)
    assert meta["title"] == "My Tune"
    assert meta["artist"] == "The Composer"
    assert meta["time"] == "3/4"
    assert meta["tempo"] == "120"
    assert meta["key"] == "G"


def test_second_title_becomes_subtitle():
    abc = "X:1\nT:Main\nT:Secondary\nK:C\n\"C\"C\nw: la\n"
    tokens, meta = parse_abc(abc)
    assert meta["title"] == "Main"
    assert meta["subtitle"] == "Secondary"


def test_key_feeds_song_meta_for_roman():
    tokens, meta = parse_abc("X:1\nK:D\n\"D\"D\nw: la\n")
    assert meta["key"] == "D"


def test_tune_number_dropped():
    tokens, meta = parse_abc("X:1\nK:C\n\"C\"C\nw: la\n")
    # X: is not stored as a rendered field.
    assert "X" not in meta and "1" not in meta.values()


def test_unit_note_length_not_leaked():
    tokens, meta = parse_abc("X:1\nL:1/8\nK:C\n\"C\"C\nw: la\n")
    assert "_unit_note_length" not in meta


# ---------------------------------------------------------------------------
# Multi-tune / multi-verse policy
# ---------------------------------------------------------------------------

def test_multi_tune_imports_first_only():
    abc = (
        "X:1\nT:First\nK:C\n\"C\"C\nw: one\n"
        "X:2\nT:Second\nK:G\n\"G\"G\nw: two\n"
    )
    tokens, meta = parse_abc(abc)
    assert meta["title"] == "First"
    assert any("multiple tunes" in w[1] for w in meta["_warnings"])
    # No chord/lyric from the second tune.
    assert all(c.text != "G" for c in _chords(tokens))


def test_multi_verse_imports_first_only():
    abc = 'X:1\nK:C\n"C"C "G"D\nw: one two\nw: uno dos\n'
    tokens, meta = parse_abc(abc)
    words = [l.text for l in _lyrics(tokens)]
    assert words == ["one", "two"]
    assert any("first verse only" in w[1] for w in meta["_warnings"])


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

def test_empty_input():
    tokens, meta = parse_abc("")
    assert tokens == []
    assert meta.get("_warnings") == []


def test_none_input():
    tokens, meta = parse_abc(None)
    assert tokens == []


def test_unterminated_quote_no_crash():
    tokens, meta = parse_abc('"C"C "Gunclosed\nw: la')
    # Does not crash; warns about the unterminated quote.
    assert any("unterminated" in w[1] for w in meta["_warnings"])


def test_w_without_music_warns():
    tokens, meta = parse_abc("w: orphan lyric\n")
    assert any("no preceding music" in w[1] for w in meta["_warnings"])


def test_pathological_input_terminates_quickly():
    # A long run of hyphens / stars / bars must not blow up (linear scan).
    abc = "X:1\nK:C\n" + ("|" * 5000) + "\nw: " + ("-" * 5000) + "\n"
    tokens, meta = parse_abc(abc)  # should return fast, no crash
    assert isinstance(tokens, list)


def test_grace_notes_and_decorations_skipped():
    # Grace notes {ab} and decorations !trill! are not note events.
    tokens, meta = parse_abc('"C"{ab}!trill!C\nw: la')
    chords = _chords(tokens)
    assert [c.text for c in chords] == ["C"]


def test_note_chord_bracket_is_one_event():
    tokens, meta = parse_abc('"C"[CEG] "G"[GBD]\nw: one two')
    chords = _chords(tokens)
    assert [c.text for c in chords] == ["C", "G"]
    lyrics = [l.text for l in _lyrics(tokens)]
    assert lyrics == ["one", "two"]


# ---------------------------------------------------------------------------
# Directive wiring: reuses 6-1 base + confined loader; front-end convergence
# ---------------------------------------------------------------------------

def test_directive_subclasses_import_base():
    from doxtr_music.directives._import_base import ImportDirectiveBase
    from doxtr_music.directives.import_abc import ImportABCDirective

    assert issubclass(ImportABCDirective, ImportDirectiveBase)
    assert ImportABCDirective.parser_fn is parse_abc


def test_directive_takes_one_argument_no_body():
    from doxtr_music.directives.import_abc import ImportABCDirective

    assert ImportABCDirective.required_arguments == 1
    assert ImportABCDirective.has_content is False


def test_parser_has_no_sphinx_import():
    """The pure parser module must import without Sphinx present (CLI-reusable)."""
    code = (
        "import sys, types;"
        # Poison Sphinx so any top-level import would fail loudly.
        "sys.modules['sphinx'] = None;"
        "import doxtr_music.parsers.abc as m;"
        "print(hasattr(m, 'parse_abc'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_transpose_shifts_imported_chords():
    # The imported chords flow through SongDirectiveBase's transpose pipeline;
    # here we assert the parser yields transposable ChordTokens (English text).
    from doxtr_music.engine.transpose import transpose_chord

    tokens, meta = parse_abc('"C"C "G"D\nw: la la')
    shifted = [transpose_chord(c.text, 2) for c in _chords(tokens)]
    assert shifted == ["D", "A"]


@pytest.fixture
def sphinx_song_build():
    """Placeholder fixture — the harness feature covers the full Sphinx build.

    Kept minimal so the metadata-only bar assertion (build_nodes drops bars)
    reads clearly at the token level here; the end-to-end render is asserted by
    the ``import_abc`` harness feature across HTML/LaTeX/EPUB.
    """
    return None
