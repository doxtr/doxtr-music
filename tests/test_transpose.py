"""Unit tests for the transposition engine (CHUNK-3-2).

Covers the shared chord-parsing authority (``engine/theory.py``), the
quality-preserving enharmonic transposer (``engine/transpose.py``), and the
effective-shift resolution rules. No Sphinx build is required here; a rendered
``.. song::`` ``:transpose:`` variant lives in the harness (all three formats).
"""

from __future__ import annotations

import dataclasses

import pytest

from doxtr_music.engine.theory import (
    ChordParts,
    parse_chord,
    parse_key,
    parse_note,
    diatonic_pcs,
    spell_pc,
)
from doxtr_music.engine.transpose import (
    compute_effective_shift,
    transpose_chord,
    transpose_tokens,
)
from doxtr_music.tokens import (
    ChordToken,
    LyricToken,
    SectionToken,
    SingerToken,
    BarToken,
    LineBreakToken,
)


# ---------------------------------------------------------------------------
# theory.py — note + chord + key parsing
# ---------------------------------------------------------------------------

def test_parse_note_basic_and_enharmonic():
    assert parse_note("C") == 0
    assert parse_note("c") == 0
    assert parse_note("E#") == 5
    assert parse_note("Fb") == 4
    assert parse_note("B#") == 0
    assert parse_note("Cb") == 11
    assert parse_note("Bb") == 10
    assert parse_note("F##") == 7
    assert parse_note("H") is None
    assert parse_note("") is None
    assert parse_note("X#") is None


def test_parse_chord_root_quality_bass():
    assert parse_chord("C") == ChordParts("C", 0, "", None, None)
    assert parse_chord("Am") == ChordParts("A", 9, "m", None, None)
    assert parse_chord("G7") == ChordParts("G", 7, "7", None, None)
    assert parse_chord("Cmaj7") == ChordParts("C", 0, "maj7", None, None)
    assert parse_chord("Bb") == ChordParts("Bb", 10, "", None, None)


def test_parse_chord_slash_rules_locked():
    # /X is a bass iff X parses as a note.
    assert parse_chord("C/E") == ChordParts("C", 0, "", "E", 4)
    # 6/9 is a quality (9 is not a note).
    assert parse_chord("C6/9") == ChordParts("C", 0, "6/9", None, None)
    # 6/E → quality "6", bass E.
    assert parse_chord("C6/E") == ChordParts("C", 0, "6", "E", 4)
    # slash-bass with accidental
    assert parse_chord("D/F#") == ChordParts("D", 2, "", "F#", 6)


def test_parse_chord_unrecognized_returns_none():
    assert parse_chord("N.C.") is None
    assert parse_chord("%") is None
    assert parse_chord("") is None
    assert parse_chord("   ") is None
    assert parse_chord("???") is None


def test_parse_key_major_minor():
    assert parse_key("C") == (0, "major")
    assert parse_key("Am") == (9, "minor")
    assert parse_key("F#m") == (6, "minor")
    assert parse_key("Bb") == (10, "major")
    assert parse_key("Bb major") == (10, "major")
    assert parse_key("A minor") == (9, "minor")
    assert parse_key("garbage") is None
    assert parse_key("") is None
    # A bare 'B' is B major, not "B minor"; the trailing-m rule needs a real 'm'.
    assert parse_key("B") == (11, "major")


def test_diatonic_pcs():
    assert diatonic_pcs(0, "major") == (0, 2, 4, 5, 7, 9, 11)  # C major
    assert diatonic_pcs(9, "minor") == (9, 11, 0, 2, 4, 5, 7)  # A minor


def test_spell_pc_never_double_accidental():
    # Every pitch class in every key spells with at most one accidental.
    for tonic in range(12):
        for mode in ("major", "minor"):
            for pc in range(12):
                name = spell_pc(pc, tonic, mode)
                assert name.count("#") + name.count("b") <= 1, (pc, tonic, mode, name)
    for pc in range(12):
        name = spell_pc(pc, None)
        assert name.count("#") + name.count("b") <= 1


def test_spell_pc_key_none_prefers_flats():
    # pc 10 → Bb (flat), not A#.
    assert spell_pc(10, None) == "Bb"
    assert spell_pc(3, None) == "Eb"
    assert spell_pc(6, None) == "Gb"


# ---------------------------------------------------------------------------
# transpose_chord — worked examples + enharmonic policy
# ---------------------------------------------------------------------------

def test_transpose_chord_worked_examples():
    assert transpose_chord("Am", 2, "B") == "Bm"
    assert transpose_chord("G7", 5, "C") == "C7"
    assert transpose_chord("C/E", 2, "D") == "D/F#"
    assert transpose_chord("A", 1, "Bb") == "Bb"


def test_transpose_chord_diatonic_uses_key_signature():
    # F major → Bb (not A#).
    assert transpose_chord("A", 1, "F") == "Bb"
    # G major → F# for the leading tone.
    assert transpose_chord("F", 1, "G") == "F#"


def test_transpose_chord_chromatic_target_row():
    # Chromatic target pitch class uses the key's side.
    # In A major (sharp side), a chromatic pitch spells sharp.
    result = transpose_chord("C", 3, "A")  # C(0)+3 = D#(3); D# chromatic in A
    assert result in ("D#", "Eb")
    # A is a sharp-side key → prefer sharp spelling.
    assert result == "D#"
    # In Eb major (flat side), a chromatic pitch spells flat.
    result_flat = transpose_chord("C", 3, "Eb")
    assert result_flat == "Eb"  # D#/Eb; Eb is diatonic in Eb major


def test_transpose_chord_key_none_prefers_input_side():
    # Without a key, the enharmonic side is taken from the INPUT chord's own
    # accidental; a wholly-natural input prefers SHARPS (chord-chart convention,
    # avoiding poor spellings like Bb-for-A# / Gbm-for-F#m).
    assert transpose_chord("A", 1, None) == "A#"
    assert transpose_chord("C", 1, None) == "C#"
    assert transpose_chord("Em", 2, None) == "F#m"
    # A flat input preserves flats; a sharp input preserves sharps.
    assert transpose_chord("Bb", 1, None) == "B"
    assert transpose_chord("Db", 1, None) == "D"
    assert transpose_chord("F#", 2, None) == "G#"


def test_transpose_chord_quality_preserved_matrix():
    qualities = ["m", "7", "maj7", "m7b5", "sus4", "add9", "dim", "aug", "6"]
    for q in qualities:
        result = transpose_chord("C" + q, 2, "D")
        assert result == "D" + q, (q, result)


def test_transpose_chord_slash_bass():
    assert transpose_chord("C/E", 5, "F") == "F/A"
    assert transpose_chord("G/B", 2, "A") == "A/C#"


def test_transpose_chord_full_display_string():
    # Reassembled root + quality + /bass, ready to render.
    assert transpose_chord("Am7/G", 2, "B") == "Bm7/A"


def test_transpose_chord_graceful_fallback():
    assert transpose_chord("N.C.", 3, "C") == "N.C."
    assert transpose_chord("%", 5, "G") == "%"
    assert transpose_chord("???", 1, None) == "???"


def test_transpose_chord_round_trip_by_pitch_class():
    # Spelling may change but pitch class must round-trip.
    for chord in ("C", "Am", "G7", "F#m7b5", "Bb", "C/E"):
        up = transpose_chord(chord, 7, None)
        back = transpose_chord(up, 5, None)
        assert parse_chord(back).root_pc == parse_chord(chord).root_pc, chord


# ---------------------------------------------------------------------------
# transpose_tokens — immutability, identity pass-through, idempotency
# ---------------------------------------------------------------------------

def test_transpose_tokens_new_list_inputs_unmutated():
    toks = [ChordToken("C", 0, 0), LyricToken("hi", 0, 0)]
    frozen_before = [dataclasses.astuple(t) for t in toks]
    out = transpose_tokens(toks, 2, "D")
    assert out is not toks
    # inputs unchanged
    assert [dataclasses.astuple(t) for t in toks] == frozen_before
    assert dict(out[0].annotations)["transposed"] == "D"


def test_transpose_tokens_only_chords_transformed():
    toks = [
        ChordToken("C", 0, 0),
        LyricToken("hi", 0, 0),
        SectionToken("Verse", "verse"),
        SingerToken("A"),
        BarToken(),
        LineBreakToken(),
    ]
    out = transpose_tokens(toks, 2, "D")
    # ChordToken transformed
    assert dict(out[0].annotations)["transposed"] == "D"
    # everything else identical object (identity pass-through)
    for i in range(1, len(toks)):
        assert out[i] is toks[i]
    # order preserved
    assert [type(t).__name__ for t in out] == [type(t).__name__ for t in toks]


def test_transpose_tokens_annotations_hashable():
    out = transpose_tokens([ChordToken("C", 0, 0)], 2, "D")
    # frozen dataclass must stay hashable
    assert hash(out[0]) is not None


def test_transpose_tokens_idempotent_re_transpose():
    once = transpose_tokens([ChordToken("C", 0, 0)], 2, "D")
    twice = transpose_tokens(once, 2, "D")
    # exactly one "transposed" pair (no accumulation)
    keys = [k for (k, _) in twice[0].annotations if k == "transposed"]
    assert keys == ["transposed"]
    assert dict(twice[0].annotations)["transposed"] == "D"


def test_transpose_tokens_preserves_existing_annotations():
    tok = ChordToken("C", 0, 0, annotations=(("roman", "I"),))
    out = transpose_tokens([tok], 2, "D")
    ann = dict(out[0].annotations)
    assert ann["roman"] == "I"
    assert ann["transposed"] == "D"


# ---------------------------------------------------------------------------
# compute_effective_shift — the single formula (never summed)
# ---------------------------------------------------------------------------

def test_effective_shift_transpose_only():
    shift, key = compute_effective_shift({"transpose": 2, "key": None}, {"key": "C"})
    assert shift == 2
    assert parse_key(key)[0] == 2  # C + 2 → D


def test_effective_shift_key_only_derives_interval():
    shift, key = compute_effective_shift(
        {"transpose": None, "key": "D"}, {"key": "C"}
    )
    assert shift == 2
    assert key == "D"


def test_effective_shift_both_given_transpose_wins_and_warns():
    warnings = []
    shift, key = compute_effective_shift(
        {"transpose": 3, "key": "G"}, {"key": "C"}, warn=warnings.append
    )
    assert shift == 3  # transpose wins, not summed
    assert any("ignored" in w for w in warnings)


def test_effective_shift_missing_source_key_noop_and_warns():
    warnings = []
    shift, key = compute_effective_shift(
        {"transpose": None, "key": "D"}, {}, warn=warnings.append
    )
    assert shift == 0
    assert key is None
    assert warnings


def test_effective_shift_unparseable_target_key_noop_and_warns():
    warnings = []
    shift, key = compute_effective_shift(
        {"transpose": None, "key": "garbage"}, {"key": "C"}, warn=warnings.append
    )
    assert shift == 0
    assert warnings


def test_effective_shift_never_summed():
    # transpose 5 + key that would be interval 7 must NOT become 12/0.
    shift, _ = compute_effective_shift(
        {"transpose": 5, "key": "G"}, {"key": "C"}
    )
    assert shift == 5


def test_effective_shift_nothing_given_is_noop():
    shift, key = compute_effective_shift({"transpose": None, "key": None}, {"key": "C"})
    assert shift == 0
    assert key is None


# ---------------------------------------------------------------------------
# Capo is display-only — never shifts (LOCKED)
# ---------------------------------------------------------------------------

def test_capo_display_only_does_not_shift():
    # A capo in song_meta must not enter the shift; only transpose/key do.
    shift, key = compute_effective_shift(
        {"transpose": None, "key": None}, {"key": "C", "capo": "3"}
    )
    assert shift == 0
    assert key is None
