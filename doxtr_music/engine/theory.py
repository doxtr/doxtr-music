"""Chord-parsing + pitch-class authority (the single engine truth).

This module is the **single authority** (LOCKED, CHUNK-3-2) for:

* note name ⇄ pitch-class conversion (``NOTE_TO_PC`` / spelling policy),
* chord parsing into :class:`ChordParts` (root / quality / optional bass),
* key parsing (:func:`parse_key`),
* diatonic scale-degree tables (consumed by CHUNK-3-3 roman analysis).

CHUNK-3-3 (roman), CHUNK-3-4 (i18n), and CHUNK-4-4 (progressions) MUST consume
this module and MUST NOT re-implement chord parsing, note tables, key parsing,
or degree tables. Centralizing avoids drift on the hard cases (``6/9`` vs
``/bass``, ``m7b5``, ``sus4``, double-accidentals, ``E#`` / ``Cb``).

Chords are stored English-only (CHUNK-1-1); nothing here localizes. This module
imports nothing from Sphinx / Docutils / ``doxtr_pdf_theme_core``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

__all__ = [
    "ChordParts",
    "NOTE_TO_PC",
    "SHARP_NAMES",
    "FLAT_NAMES",
    "parse_note",
    "parse_chord",
    "parse_key",
    "spell_pc",
    "MAJOR_SCALE_STEPS",
    "MINOR_SCALE_STEPS",
    "diatonic_pcs",
]

# ---------------------------------------------------------------------------
# Note tables
# ---------------------------------------------------------------------------

# Every accepted spelling → pitch class (0..11), C = 0. Includes the "white
# key" enharmonics E#/Fb/B#/Cb and the double-accidentals that can arise from
# key-signature spelling. Lookups are case-sensitive on the accidental
# (``#``/``b``); the letter is upper-cased by the parser.
NOTE_TO_PC = {
    "C": 0, "B#": 0, "Dbb": 0,
    "C#": 1, "Db": 1, "B##": 1,
    "D": 2, "C##": 2, "Ebb": 2,
    "D#": 3, "Eb": 3, "Fbb": 3,
    "E": 4, "Fb": 4, "D##": 4,
    "F": 5, "E#": 5, "Gbb": 5,
    "F#": 6, "Gb": 6, "E##": 6,
    "G": 7, "F##": 7, "Abb": 7,
    "G#": 8, "Ab": 8,
    "A": 9, "G##": 9, "Bbb": 9,
    "A#": 10, "Bb": 10, "Cbb": 10,
    "B": 11, "Cb": 11, "A##": 11,
}

# Preferred single-accidental spellings per pitch class. Used by the spelling
# policy to render a shifted pitch class on the sharp or flat "side".
SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

# Diatonic scale step patterns (semitone offsets from the tonic).
MAJOR_SCALE_STEPS = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE_STEPS = (0, 2, 3, 5, 7, 8, 10)  # natural minor

# Keys whose signatures use flats (major-key convention). A key on the flat
# side spells accidentals with ``b``; sharp-side keys use ``#``. C major / A
# minor default to flats (LOCKED). This drives the chromatic spelling policy.
_FLAT_MAJOR_TONICS = {5, 10, 3, 8, 1, 6}  # F, Bb, Eb, Ab, Db, Gb
# 0 (C) → flats by the locked default; everything else sharp.


# ---------------------------------------------------------------------------
# Note parsing + spelling
# ---------------------------------------------------------------------------

def parse_note(text):
    """Parse a note name (letter + optional accidentals) → pitch class.

    Accepts ``A``–``G`` (case-insensitive letter) followed by any run of
    ``#`` / ``b`` (also ``♯`` / ``♭`` for convenience). Returns the pitch class
    ``0..11`` or ``None`` if not a recognizable note.
    """
    if not text:
        return None
    s = text.strip().replace("\u266f", "#").replace("\u266d", "b")
    if not s:
        return None
    letter = s[0].upper()
    if letter not in "ABCDEFG":
        return None
    accidentals = s[1:]
    if accidentals and any(c not in "#b" for c in accidentals):
        return None
    key = letter + accidentals
    return NOTE_TO_PC.get(key)


def _note_length(text):
    """Return the character length of the leading note-name in ``text``.

    ``0`` if ``text`` does not start with a note letter. Used to split root
    from quality and to detect a note-name bass in the slash rule.
    """
    if not text:
        return 0
    s = text.replace("\u266f", "#").replace("\u266d", "b")
    if s[0].upper() not in "ABCDEFG":
        return 0
    i = 1
    while i < len(s) and s[i] in "#b":
        i += 1
    # Only a valid note if it actually maps to a pitch class.
    if parse_note(s[:i]) is None:
        return 0
    return i


def spell_pc(pc, key_tonic=None, key_mode="major", prefer=None):
    """Spell a pitch class as a note name under the enharmonic policy (LOCKED).

    * If ``key_tonic`` is given, **diatonic** pitch classes use the key's
      key-signature spelling; **chromatic** pitch classes use the key's
      sharp/flat *side* (sharp keys → ``#``, flat keys → ``b``; C/Am → flats).
    * If ``key_tonic`` is ``None``, prefer flats (locked default) unless
      ``prefer="sharp"`` is passed for a preserved explicit sharp input.

    Never returns a double-accidental: the ``SHARP_NAMES``/``FLAT_NAMES`` tables
    only carry single-accidental spellings, so a simpler enharmonic is always
    chosen.
    """
    pc %= 12
    if key_tonic is None:
        side = "flat" if prefer != "sharp" else "sharp"
        return (FLAT_NAMES if side == "flat" else SHARP_NAMES)[pc]

    tonic = key_tonic % 12
    steps = MAJOR_SCALE_STEPS if key_mode != "minor" else MINOR_SCALE_STEPS
    # Relative-major tonic determines the sharp/flat side for a minor key.
    side_tonic = tonic if key_mode != "minor" else (tonic + 3) % 12
    flat_side = side_tonic in _FLAT_MAJOR_TONICS or side_tonic == 0

    diatonic = {(tonic + s) % 12 for s in steps}
    if pc in diatonic:
        # Use the key-signature spelling for a diatonic pitch: pick the side
        # consistent with the key so e.g. F major spells pc10 as Bb, not A#.
        return (FLAT_NAMES if flat_side else SHARP_NAMES)[pc]
    # Chromatic pitch: use the key's side.
    return (FLAT_NAMES if flat_side else SHARP_NAMES)[pc]


# ---------------------------------------------------------------------------
# Chord parsing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChordParts:
    """Parsed chord: root + quality + optional slash bass.

    * ``root`` — the spelled root incl. accidental (e.g. ``"Bb"``).
    * ``root_pc`` — root pitch class ``0..11``.
    * ``quality`` — everything after the root that is not a slash-bass
      (verbatim, e.g. ``"m7b5"``, ``"sus4"``, ``"6/9"``). ``""`` for a bare
      major triad.
    * ``bass`` — the spelled slash-bass note (e.g. ``"E"``) or ``None``.
    * ``bass_pc`` — bass pitch class or ``None``.
    """

    root: str
    root_pc: int
    quality: str
    bass: Optional[str]
    bass_pc: Optional[int]


def parse_chord(text):
    """Parse a chord string → :class:`ChordParts`, or ``None`` if unrecognized.

    Splits the leading note-name as the root, the remainder as quality, with a
    trailing ``/X`` treated as a **bass iff** ``X`` parses as a note name
    (LOCKED ``6/9``-vs-slash rule)::

        "C/E"   → root C, quality "",   bass E
        "C6/9"  → root C, quality "6/9", bass None   (9 is not a note)
        "C6/E"  → root C, quality "6",   bass E

    Returns ``None`` for non-chord input (``"N.C."``, ``"%"``, garbage) so
    callers can pass such tokens through unchanged.
    """
    if not text:
        return None
    s = text.strip()
    if not s:
        return None

    root_len = _note_length(s)
    if root_len == 0:
        return None
    root_raw = s[:root_len]
    root_pc = parse_note(root_raw)
    if root_pc is None:
        return None
    root = root_raw[0].upper() + root_raw[1:].replace("\u266f", "#").replace(
        "\u266d", "b"
    )

    remainder = s[root_len:]

    bass = None
    bass_pc = None
    quality = remainder
    # A slash-bass is the LAST '/' whose following token parses as a note name.
    slash = remainder.rfind("/")
    if slash != -1:
        candidate = remainder[slash + 1:]
        if candidate and _note_length(candidate) == len(candidate):
            bass_pc = parse_note(candidate)
            if bass_pc is not None:
                bass = candidate[0].upper() + candidate[1:].replace(
                    "\u266f", "#"
                ).replace("\u266d", "b")
                quality = remainder[:slash]

    return ChordParts(
        root=root,
        root_pc=root_pc,
        quality=quality,
        bass=bass,
        bass_pc=bass_pc,
    )


# ---------------------------------------------------------------------------
# Key parsing + diatonic degrees
# ---------------------------------------------------------------------------

def parse_key(key):
    """Parse a key string → ``(tonic_pc, mode)`` or ``None`` if unparseable.

    ``mode`` is ``"major"`` (default) or ``"minor"`` when the key ends in a
    lone ``m`` (e.g. ``"Am"``, ``"F#m"``). A trailing ``"maj"``/``"major"`` or
    ``"min"``/``"minor"`` word is also honored. The note portion is parsed with
    :func:`parse_note`.
    """
    if not key:
        return None
    s = key.strip()
    if not s:
        return None
    lower = s.lower()
    mode = "major"
    note_part = s
    for suffix, m in (
        ("minor", "minor"), ("min", "minor"),
        ("major", "major"), ("maj", "major"),
    ):
        if lower.endswith(suffix):
            mode = m
            note_part = s[: len(s) - len(suffix)].strip()
            break
    else:
        # Bare trailing 'm' (not part of an accidental) → minor.
        if len(s) >= 2 and s[-1] == "m" and s[-2] in "ABCDEFG#b":
            mode = "minor"
            note_part = s[:-1]

    tonic = parse_note(note_part)
    if tonic is None:
        return None
    return (tonic, mode)


def diatonic_pcs(tonic_pc, mode="major"):
    """Return the tuple of 7 diatonic pitch classes for a key.

    Consumed by CHUNK-3-3 (roman analysis) so the degree math has one source.
    """
    steps = MAJOR_SCALE_STEPS if mode != "minor" else MINOR_SCALE_STEPS
    return tuple((tonic_pc + s) % 12 for s in steps)
