"""Round-trip tests for the ``tokens_to_chordpro`` serializer (CHUNK-6-3).

CLI-independent: assert that serializing chord-line-parsed tokens to ChordPro and
re-parsing with ``parse_chordpro`` preserves chord columns, sections, singer and
metadata (the correct equivalence contract — not byte-identical text). Covers the
right-to-left multi-chord insertion trap, mid-word chords, chord-only/instrumental
lines, section/singer round-trip, metadata, and literal ``[ ] { }`` handling.
"""

from __future__ import annotations

from doxtr_music.parsers.chordline import parse_chord_line
from doxtr_music.parsers.chordpro import parse_chordpro
from doxtr_music.parsers.chordpro_serialize import tokens_to_chordpro
from doxtr_music.tokens import (
    ChordToken,
    LyricToken,
    SectionToken,
    SingerToken,
)


def _chord_cols(tokens):
    """(text, column) for every ChordToken, in stream order."""
    return [(t.text, t.column) for t in tokens if isinstance(t, ChordToken)]


def _lyric_words(tokens):
    return [(t.text, t.column) for t in tokens if isinstance(t, LyricToken)]


def _sections(tokens):
    return [(t.kind, t.label) for t in tokens if isinstance(t, SectionToken)]


def _singers(tokens):
    return [t.singer for t in tokens if isinstance(t, SingerToken)]


def _roundtrip(chordline_text):
    """chord-line text → tokens → ChordPro → re-parsed tokens."""
    tokens, meta = parse_chord_line(chordline_text)
    chordpro = tokens_to_chordpro(tokens, meta)
    re_tokens, re_meta = parse_chordpro(chordpro)
    return tokens, meta, chordpro, re_tokens, re_meta


# ---------------------------------------------------------------------------
# Chord columns
# ---------------------------------------------------------------------------

def test_single_chord_roundtrip():
    src = "C\nHello"
    tokens, meta, cp, re_tokens, re_meta = _roundtrip(src)
    assert _chord_cols(tokens) == _chord_cols(re_tokens)


def test_multi_chord_line_right_to_left():
    # Multiple chords on one line: inserting brackets must not shift later cols.
    src = "C       G       Am\nHello there my friend"
    tokens, meta, cp, re_tokens, re_meta = _roundtrip(src)
    assert _chord_cols(tokens) == _chord_cols(re_tokens)
    # Sanity: three chords survived.
    assert len(_chord_cols(re_tokens)) == 3


def test_mid_word_chord_roundtrip():
    # A chord anchored inside a word must land at the same column after round-trip.
    src = "  C\nHello"  # chord at column 2 (inside "Hello")
    tokens, meta, cp, re_tokens, re_meta = _roundtrip(src)
    assert _chord_cols(tokens) == _chord_cols(re_tokens)
    # The emitted ChordPro should contain an in-word bracket like "He[C]llo".
    assert "[C]" in cp


def test_chord_only_line_roundtrip():
    src = "Am"  # chord-only / instrumental row
    tokens, meta, cp, re_tokens, re_meta = _roundtrip(src)
    assert _chord_cols(tokens) == _chord_cols(re_tokens)


def test_lyric_words_preserved():
    src = "C     G\nHello world"
    tokens, meta, cp, re_tokens, re_meta = _roundtrip(src)
    assert _lyric_words(tokens) == _lyric_words(re_tokens)


# ---------------------------------------------------------------------------
# Sections / singer
# ---------------------------------------------------------------------------

def test_section_verse_roundtrip():
    src = "{start_of_verse}\nC\nHello\n{end_of_verse}"
    tokens, meta, cp, re_tokens, re_meta = _roundtrip(src)
    assert _sections(tokens) == _sections(re_tokens)


def test_section_chorus_close_deterministic():
    src = "{soc}\nG\nSing\n{eoc}"
    tokens, meta, cp, re_tokens, re_meta = _roundtrip(src)
    kinds = [k for k, _ in _sections(re_tokens)]
    assert "chorus" in kinds
    assert "none" in kinds  # the close round-trips to a kind="none" boundary


def test_singer_roundtrip():
    src = "{singer: A}\nC\nHello"
    tokens, meta, cp, re_tokens, re_meta = _roundtrip(src)
    assert _singers(tokens) == _singers(re_tokens) == ["A"]


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def test_metadata_roundtrip():
    src = "{title: My Song}\n{key: G}\nC\nHello"
    tokens, meta, cp, re_tokens, re_meta = _roundtrip(src)
    assert re_meta.get("title") == "My Song"
    assert re_meta.get("key") == "G"


def test_internal_meta_keys_not_emitted():
    # _warnings must never leak into the emitted ChordPro.
    tokens, meta = parse_chord_line("C\nHello")
    meta.setdefault("_warnings", []).append((0, "test warning"))
    cp = tokens_to_chordpro(tokens, meta)
    assert "_warnings" not in cp
    assert "test warning" not in cp


# ---------------------------------------------------------------------------
# Literal bracket / brace handling (Option B: emit as-is + detection flag)
# ---------------------------------------------------------------------------

def test_literal_brackets_detected():
    # A lyric containing a literal [later] is emitted as-is (the forward parser
    # has no de-escape); the serializer flags it so the CLI can warn.
    from doxtr_music.parsers.chordpro_serialize import has_literal_brackets

    lyric = [LyricToken(text="see", column=0, line=0),
             LyricToken(text="[later]", column=4, line=0)]
    cp = tokens_to_chordpro(lyric, {})
    assert "[later]" in cp  # literal text preserved verbatim
    assert has_literal_brackets(lyric) is True


def test_literal_brace_detected():
    from doxtr_music.parsers.chordpro_serialize import has_literal_brackets

    lyric = [LyricToken(text="{notdirective}", column=0, line=0)]
    cp = tokens_to_chordpro(lyric, {})
    assert "{notdirective}" in cp
    assert has_literal_brackets(lyric) is True


def test_no_literal_brackets_not_flagged():
    from doxtr_music.parsers.chordpro_serialize import has_literal_brackets

    lyric = [LyricToken(text="clean", column=0, line=0)]
    assert has_literal_brackets(lyric) is False


# ---------------------------------------------------------------------------
# Empty / trivial
# ---------------------------------------------------------------------------

def test_empty_tokens():
    assert tokens_to_chordpro([], {}) == ""


def test_only_metadata():
    cp = tokens_to_chordpro([], {"title": "T"})
    assert cp.strip() == "{title: T}"
