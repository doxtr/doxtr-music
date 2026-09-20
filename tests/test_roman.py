"""Unit tests for CHUNK-3-3 roman-numeral analysis (``engine/roman.py``).

Covers the LOCKED rules: quality-driven case (V-vs-v automatic), letter-degree
+ pc-delta accidental (deterministic chromatic mapping), unclassifiable-quality
uppercase default, effective-(transposed)-pitch analysis, no-key → all ``None``,
``roman_tokens`` immutability/idempotency/hashability, and that roman consumes
``theory.py`` (not a re-implemented parser/tables).
"""

import dataclasses

import pytest

from doxtr_music.engine.roman import roman_for_chord, roman_tokens
from doxtr_music.engine import theory
from doxtr_music.tokens import ChordToken, LyricToken


# ---------------------------------------------------------------------------
# Exit #1 — major + minor tables (quality-driven)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "chord,expected",
    [
        ("C", "I"), ("Dm", "ii"), ("Em", "iii"), ("F", "IV"),
        ("G", "V"), ("G7", "V7"), ("Am", "vi"), ("Bdim", "vii°"),
    ],
)
def test_c_major_table(chord, expected):
    assert roman_for_chord(chord, "C") == expected


@pytest.mark.parametrize(
    "chord,expected",
    [
        ("Am", "i"), ("Dm", "iv"), ("Em", "v"),
        ("E", "V"),      # major dominant reflects the chord as written
        ("C", "III"), ("F", "VI"), ("G", "VII"),
    ],
)
def test_a_minor_table_quality_driven(chord, expected):
    """A minor: V-vs-v is automatic from the chord's actual quality."""
    assert roman_for_chord(chord, "Am") == expected


def test_v_vs_v_automatic():
    """The whole point of quality-driven case: E→V, Em→v in the same key."""
    assert roman_for_chord("E", "Am") == "V"
    assert roman_for_chord("Em", "Am") == "v"


def test_sharp_key_major_table():
    """A sharp key (D major): D→I, G→IV, A→V, Bm→vi."""
    assert roman_for_chord("D", "D") == "I"
    assert roman_for_chord("G", "D") == "IV"
    assert roman_for_chord("A", "D") == "V"
    assert roman_for_chord("Bm", "D") == "vi"


def test_flat_key_major_table():
    """A flat key (F major): F→I, Bb→IV, C→V, Dm→vi."""
    assert roman_for_chord("F", "F") == "I"
    assert roman_for_chord("Bb", "F") == "IV"
    assert roman_for_chord("C", "F") == "V"
    assert roman_for_chord("Dm", "F") == "vi"


# ---------------------------------------------------------------------------
# Exit #2 — chromatic mapping: letter-degree + pc-delta accidental
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "chord,expected",
    [
        ("Bb", "bVII"),   # letter B = degree 7, one flat
        ("D", "II"),      # letter D = degree 2, pc matches
        ("D#", "#II"),    # letter D = degree 2, one sharp
        ("Eb", "bIII"),   # letter E = degree 3, one flat
    ],
)
def test_chromatic_in_c(chord, expected):
    assert roman_for_chord(chord, "C") == expected


def test_sharp_vs_flat_disambiguation():
    """bIII and #II are the same pitch but spelled per the root letter."""
    assert roman_for_chord("Eb", "C") == "bIII"  # letter E
    assert roman_for_chord("D#", "C") == "#II"    # letter D


def test_chromatic_minor_quality_keeps_case():
    """A raised-fourth minor chord in C: #iv (quality-driven lowercase)."""
    assert roman_for_chord("F#m", "C") == "#iv"


# ---------------------------------------------------------------------------
# Exit #3 — unclassifiable quality + unparseable
# ---------------------------------------------------------------------------

def test_unclassifiable_quality_uppercase_plus_suffix():
    assert roman_for_chord("Csus4", "C") == "Isus4"
    assert roman_for_chord("C5", "C") == "I5"


def test_sus_and_power_on_other_degrees():
    assert roman_for_chord("Gsus4", "C") == "Vsus4"
    assert roman_for_chord("G5", "C") == "V5"


def test_unparseable_chord_returns_none():
    assert roman_for_chord("N.C.", "C") is None
    assert roman_for_chord("%", "C") is None
    assert roman_for_chord("123", "C") is None
    assert roman_for_chord("", "C") is None


def test_never_raises_on_odd_input():
    # A grab-bag of weird-but-nonfatal inputs; must never raise.
    for text in ("H", "9", "///", "N.C.", "  ", "Cmaj7#11", "F#m7b5"):
        roman_for_chord(text, "C")  # no assertion — just must not raise


def test_half_diminished_is_diminished_case():
    assert roman_for_chord("Bm7b5", "C") == "vii°"


# ---------------------------------------------------------------------------
# Exit #5 — no-key case
# ---------------------------------------------------------------------------

def test_no_key_returns_none():
    assert roman_for_chord("C", None) is None
    assert roman_for_chord("C", "") is None
    assert roman_for_chord("C", "not-a-key") is None


# ---------------------------------------------------------------------------
# Exit #4 — roman from the effective (transposed) pitch
# ---------------------------------------------------------------------------

def test_roman_tokens_uses_transposed_pitch():
    """A C chord transposed to D, analyzed in D, is I (key-consistent)."""
    toks = [ChordToken(text="C", column=0, annotations=(("transposed", "D"),))]
    out = roman_tokens(toks, "D")
    roman = dict(out[0].annotations)["roman"]
    assert roman == "I"


def test_roman_tokens_falls_back_to_text_when_not_transposed():
    toks = [ChordToken(text="G", column=0)]
    out = roman_tokens(toks, "C")
    assert dict(out[0].annotations)["roman"] == "V"


# ---------------------------------------------------------------------------
# Exit #6 — roman_tokens immutability / identity / idempotency / hashable
# ---------------------------------------------------------------------------

def test_roman_tokens_returns_new_list_immutable_inputs():
    toks = [ChordToken(text="C", column=0), LyricToken(text="hi", column=0)]
    out = roman_tokens(toks, "C")
    assert out is not toks
    # Original untouched (frozen dataclass; new instances produced).
    assert toks[0].annotations == ()
    assert out[0] is not toks[0]


def test_roman_tokens_only_chordtokens_others_identity():
    lyric = LyricToken(text="hi", column=0)
    toks = [ChordToken(text="C", column=0), lyric]
    out = roman_tokens(toks, "C")
    assert out[1] is lyric  # non-ChordToken passes by identity
    assert "roman" in dict(out[0].annotations)


def test_roman_tokens_idempotent():
    toks = [ChordToken(text="G", column=0)]
    once = roman_tokens(toks, "C")
    twice = roman_tokens(once, "C")
    assert dict(twice[0].annotations)["roman"] == "V"
    # No duplicate roman keys accumulated.
    keys = [k for k, _ in twice[0].annotations]
    assert keys.count("roman") == 1


def test_roman_tokens_skips_none():
    """N.C. token gets no roman annotation (skipped, not None-valued)."""
    toks = [ChordToken(text="N.C.", column=0)]
    out = roman_tokens(toks, "C")
    assert "roman" not in dict(out[0].annotations)


def test_roman_tokens_no_key_all_none():
    toks = [ChordToken(text="C", column=0), ChordToken(text="G", column=0)]
    out = roman_tokens(toks, None)
    for t in out:
        assert "roman" not in dict(t.annotations)


def test_roman_annotation_hashable():
    toks = [ChordToken(text="G", column=0)]
    out = roman_tokens(toks, "C")
    # A frozen dataclass with hashable annotations must itself be hashable.
    hash(out[0])
    for k, v in out[0].annotations:
        hash((k, v))


# ---------------------------------------------------------------------------
# Exit #8 — consumes theory.py (single authority; no re-implemented tables)
# ---------------------------------------------------------------------------

def test_consumes_theory_parse_chord(monkeypatch):
    """roman_for_chord must go through theory.parse_chord (single authority)."""
    calls = []
    real = theory.parse_chord

    def spy(text):
        calls.append(text)
        return real(text)

    import doxtr_music.engine.roman as roman_mod
    monkeypatch.setattr(roman_mod, "parse_chord", spy)
    roman_for_chord("G", "C")
    assert "G" in calls


def test_consumes_theory_parse_key(monkeypatch):
    calls = []
    real = theory.parse_key

    def spy(key):
        calls.append(key)
        return real(key)

    import doxtr_music.engine.roman as roman_mod
    monkeypatch.setattr(roman_mod, "parse_key", spy)
    roman_for_chord("G", "C")
    assert "C" in calls


def test_no_sphinx_import_in_engine():
    """The engine module must be importable without Sphinx (soft-dep contract)."""
    import sys
    import importlib

    # roman.py + theory.py must not have pulled in sphinx at import time via
    # anything in engine/. (We can't un-import sphinx if the harness loaded it,
    # so assert the module's own source has no top-level sphinx import.)
    import doxtr_music.engine.roman as roman_mod
    src = importlib.util.find_spec("doxtr_music.engine.roman").origin
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    assert "import sphinx" not in text
    assert "from sphinx" not in text
    assert "import docutils" not in text
