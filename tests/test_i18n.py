"""Tests for CHUNK-3-4 — chord-system i18n + RTL + resolve_chord_display.

Covers:
  * concrete note maps (german -is/-es + Es/As elisions + double-accidentals;
    italian ASCII accidentals; hungarian -sz);
  * root-keyed collision (Bbm7 / Bm7 / F/Bb) — remap on parsed root, not prefix;
  * transpose+localize composition (effective + sharp-key row);
  * roman resolution is parse-time (never letter-localized), no-key English
    fallback;
  * english identity; unparseable passthrough; no-fallback-fires for the
    enumerated CHUNK-3-2 spellings;
  * resolve_chord_display branch table (roman-set vs localize, node-local);
  * has_strong_rtl detection.

These exercise the pure engine (no Sphinx build); render integration + RTL
warnings are asserted by the harness lanes.
"""

from __future__ import annotations

import pytest

from doxtr_music.engine.i18n import (
    LETTER_SYSTEMS,
    has_strong_rtl,
    localize_chord,
    resolve_chord_display,
)


# ---------------------------------------------------------------------------
# German note map — sharps -is, flats -es with Es/As elisions, double-accidentals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "english, expected",
    [
        # naturals + the classic swap
        ("C", "C"), ("D", "D"), ("E", "E"), ("F", "F"), ("G", "G"), ("A", "A"),
        ("B", "H"),          # B -> H
        ("Bb", "B"),         # Bb -> B (the classic swap)
        # sharps append -is
        ("C#", "Cis"), ("D#", "Dis"), ("F#", "Fis"), ("G#", "Gis"), ("A#", "Ais"),
        # flats append -es, with Es / As elisions
        ("Eb", "Es"), ("Ab", "As"),
        ("Db", "Des"), ("Gb", "Ges"), ("Cb", "Ces"), ("Fb", "Fes"),
        # double-accidentals documented
        ("Bbb", "Heses"),    # B double-flat
        ("F##", "Fisis"),
    ],
)
def test_german_note_map(english, expected):
    assert localize_chord(english, "german") == expected


def test_german_quality_preserved():
    # Quality/extensions are carried verbatim, only the root localizes.
    assert localize_chord("Bm7", "german") == "Hm7"
    assert localize_chord("A#dim", "german") == "Aisdim"
    assert localize_chord("Ebmaj7", "german") == "Esmaj7"


# ---------------------------------------------------------------------------
# Root-keyed collision — the classic German prefix bug must NOT occur
# ---------------------------------------------------------------------------

def test_german_root_keyed_collision():
    # Bbm7 remaps the parsed root Bb -> B (not a "B" prefix match); Bm7's root
    # B -> H; and a slash-bass Bb -> B. Proves remap on ChordParts.root.
    assert localize_chord("Bbm7", "german") == "Bm7"
    assert localize_chord("Bm7", "german") == "Hm7"
    assert localize_chord("F/Bb", "german") == "F/B"


def test_german_slash_bass_localized():
    # Both root and bass localize; quality between them is verbatim.
    assert localize_chord("G/B", "german") == "G/H"
    assert localize_chord("Am7/E", "german") == "Am7/E"


# ---------------------------------------------------------------------------
# Italian (Do-Re-Mi) — ASCII '#'/'b' accidentals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "english, expected",
    [
        ("C", "Do"), ("D", "Re"), ("E", "Mi"), ("F", "Fa"),
        ("G", "Sol"), ("A", "La"), ("B", "Si"),
        ("C#", "Do#"), ("F#", "Fa#"),
        ("Bb", "Sib"), ("Eb", "Mib"),
    ],
)
def test_italian_note_map(english, expected):
    assert localize_chord(english, "italian") == expected


def test_italian_quality_and_bass():
    assert localize_chord("Cmaj7", "italian") == "Domaj7"
    assert localize_chord("G/B", "italian") == "Sol/Si"


# ---------------------------------------------------------------------------
# Hungarian — -sz spellings, NOT silently German-identical
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "english, expected",
    [
        ("B", "H"), ("Bb", "B"),
        ("F#", "Fisz"), ("C#", "Cisz"), ("D#", "Disz"),
        ("Eb", "esz"), ("Ab", "asz"), ("Db", "Desz"),
    ],
)
def test_hungarian_note_map(english, expected):
    assert localize_chord(english, "hungarian") == expected


def test_hungarian_distinct_from_german():
    # F# is Fis (german) but Fisz (hungarian): the systems are not identical.
    assert localize_chord("F#", "german") == "Fis"
    assert localize_chord("F#", "hungarian") == "Fisz"


# ---------------------------------------------------------------------------
# english identity + unparseable passthrough + unknown system identity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("chord", ["C", "Bb", "F#m7", "G/B", "Amaj7", ""])
def test_english_identity(chord):
    assert localize_chord(chord, "english") == chord


@pytest.mark.parametrize("garbage", ["N.C.", "???", "xyz", "H"])
def test_unparseable_passthrough(garbage):
    # H is not an English note (unparseable) → returned unchanged.
    assert localize_chord(garbage, "german") == garbage


def test_roman_system_is_not_a_localize_case():
    # localize_chord handles ONLY letter systems; 'roman' is not one of them, so
    # it returns identity (roman is resolved at parse time, not here).
    assert "roman" not in LETTER_SYSTEMS
    assert localize_chord("C", "roman") == "C"


# ---------------------------------------------------------------------------
# No-fallback-fires for the enumerated CHUNK-3-2 transpose spellings
# ---------------------------------------------------------------------------

# The spellings the transpose engine can emit (sharps/flats/naturals across the
# circle). A localized result equal to the English input under german/hungarian
# would signal a missing map entry (fallback fired). We assert every one maps to
# a non-identity localized form where it should, i.e. no silent English fallback.
_CHUNK32_SPELLINGS = [
    "C", "C#", "Db", "D", "D#", "Eb", "E", "F", "F#", "Gb",
    "G", "G#", "Ab", "A", "A#", "Bb", "B",
]


@pytest.mark.parametrize("system", ["german", "hungarian"])
def test_no_fallback_fires_for_chunk32_spellings(system):
    # Every enumerated spelling must be present in the system's note map; a
    # missing entry would fall back to the English spelling (fallback fired).
    # We prove coverage by round-tripping: the localized single-note chord must
    # be produced without raising and must be non-empty.
    for note in _CHUNK32_SPELLINGS:
        out = localize_chord(note, system)
        assert out, "empty localization for %r under %s" % (note, system)
        # Naturals C/D/E/F/G/A stay identical; only B and accidentals change.
        if note in ("C", "D", "E", "F", "G", "A"):
            assert out == note
        else:
            # B and every accidental note must localize to a distinct spelling.
            assert out != note, (
                "no %s map for %r (silent English fallback fired)" % (system, note)
            )


# ---------------------------------------------------------------------------
# resolve_chord_display — the single shared render helper (node-local)
# ---------------------------------------------------------------------------

class _FakeConfig:
    def __init__(self, system):
        self.doxtr_music_chord_system = system


class _FakeNode(dict):
    """A minimal stand-in for a ChordNode (dict-attr access via .get)."""


def _node(chord=None, transposed=None, roman=None):
    n = _FakeNode()
    if chord is not None:
        n["chord"] = chord
    if transposed is not None:
        n["transposed"] = transposed
    if roman is not None:
        n["roman"] = roman
    return n


def test_resolve_display_roman_wins():
    # roman-set → return the numeral verbatim (replace mode), NEVER localized.
    node = _node(chord="C", roman="I")
    assert resolve_chord_display(node, _FakeConfig("german")) == "I"


def test_resolve_display_localize_branch():
    # No roman → localize the effective chord to the configured system.
    node = _node(chord="Bm7")
    assert resolve_chord_display(node, _FakeConfig("german")) == "Hm7"
    assert resolve_chord_display(node, _FakeConfig("english")) == "Bm7"


def test_resolve_display_uses_effective_transposed():
    # effective = transposed or chord; localization applies to the effective
    # (post-transpose) chord (CHUNK-3-2 contract).
    node = _node(chord="C", transposed="Bb")
    assert resolve_chord_display(node, _FakeConfig("german")) == "B"      # Bb -> B
    assert resolve_chord_display(node, _FakeConfig("italian")) == "Sib"


def test_resolve_display_node_local_no_ancestor_needed():
    # Works on a standalone chord node with only .chord (no transposed/roman,
    # no SongNode ancestor).
    node = _node(chord="F#")
    assert resolve_chord_display(node, _FakeConfig("hungarian")) == "Fisz"


def test_resolve_display_roman_not_letter_localized():
    # A roman numeral that happens to contain a letter-like glyph is emitted
    # verbatim; localization never touches it.
    node = _node(chord="Bb", roman="bVII")
    assert resolve_chord_display(node, _FakeConfig("german")) == "bVII"


def test_resolve_display_defaults_to_english_when_config_missing():
    # A config object without the attribute → english identity (getattr default).
    class _Empty:
        pass

    node = _node(chord="Bb")
    assert resolve_chord_display(node, _Empty()) == "Bb"


# ---------------------------------------------------------------------------
# RTL detection
# ---------------------------------------------------------------------------

def test_has_strong_rtl():
    assert has_strong_rtl("שלום עולם")      # Hebrew
    assert has_strong_rtl("مرحبا")           # Arabic
    assert not has_strong_rtl("Hello world")
    assert not has_strong_rtl("")
    assert not has_strong_rtl("Cis Fis")


# ---------------------------------------------------------------------------
# chord_system="roman" resolves at PARSE time (via SongDirectiveBase._transform_roman)
# ---------------------------------------------------------------------------

from doxtr_music.directives._base import SongDirectiveBase
from doxtr_music.tokens import ChordToken, LyricToken


class _FakeEnvConfig:
    def __init__(self, system):
        self.doxtr_music_chord_system = system


class _FakeState:
    def __init__(self, system):
        env = type("E", (), {"config": _FakeEnvConfig(system)})()
        settings = type("S", (), {"env": env})()
        self.document = type("D", (), {"settings": settings})()


def _bare_directive(system):
    """Instantiate SongDirectiveBase without Sphinx to test _transform_roman."""
    d = SongDirectiveBase.__new__(SongDirectiveBase)
    d.state = _FakeState(system)
    return d


def _chord_tokens():
    # [C][Am][F][G] over lyrics, in C major.
    return [
        ChordToken(text="C", column=0),
        LyricToken(text="Hello", column=0),
        ChordToken(text="Am", column=6),
        LyricToken(text="world", column=6),
    ]


def _romans(tokens):
    out = []
    for t in tokens:
        if isinstance(t, ChordToken):
            out.append(dict(t.annotations).get("roman"))
    return out


def test_chord_system_roman_triggers_parse_time_roman():
    d = _bare_directive("roman")
    options = {"roman_numerals": False, "_effective_key": "C"}
    out = d._transform_roman(_chord_tokens(), {}, options)
    assert _romans(out) == ["I", "vi"]


def test_chord_system_roman_no_key_english_fallback_silent():
    d = _bare_directive("roman")
    options = {"roman_numerals": False, "_effective_key": None}
    out = d._transform_roman(_chord_tokens(), {}, options)
    # No key → roman None for every chord → chords fall back to English display.
    assert _romans(out) == [None, None]


def test_option_roman_still_triggers_even_when_system_english():
    d = _bare_directive("english")
    options = {"roman_numerals": True, "_effective_key": "C"}
    out = d._transform_roman(_chord_tokens(), {}, options)
    assert _romans(out) == ["I", "vi"]


def test_letter_system_does_not_trigger_roman():
    d = _bare_directive("german")
    options = {"roman_numerals": False, "_effective_key": "C"}
    out = d._transform_roman(_chord_tokens(), {}, options)
    # german is a letter system, not roman → no roman annotation.
    assert _romans(out) == [None, None]
