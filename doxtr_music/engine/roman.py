"""Roman-numeral harmonic analysis — the single roman authority (LOCKED).

CHUNK-3-3. :func:`roman_for_chord` is the **one** function that maps a chord +
key to its harmonic Roman numeral; CHUNK-4-4 (progression roman cells) and the
``chord_system="roman"`` render path (CHUNK-3-4) reuse it — there is never a
second implementation. The ``:roman:`` role (CHUNK-3-5) is author-literal and
does NOT call this.

This module consumes :mod:`doxtr_music.engine.theory` (``parse_chord`` /
``ChordParts`` / ``parse_key`` / diatonic degree tables) and re-implements
nothing. It imports nothing from Sphinx / Docutils / ``doxtr_pdf_theme_core``.

Analysis rules (LOCKED — quality-driven, deterministic):

* **Degree number** = the diatonic step of the chord root's *letter name* above
  the tonic *letter* (1..7 as the numeral). Uses ``ChordParts.root`` (spelled),
  so ``Bb`` in C is letter B = degree 7.
* **Accidental prefix** = ``root_pc − diatonic_pc_of_that_letter``, spelled with
  ASCII ``b`` / ``#``. This deterministically disambiguates e.g. ``bIII`` vs
  ``#II``.
* **Case + symbol** are driven by the chord's *actual* ``ChordParts.quality``,
  not by a key template: uppercase for major/augmented, lowercase for
  minor/diminished; ``°`` appended for diminished, ``+`` for augmented; the
  seventh/extension suffix is carried verbatim. This makes minor-key V-vs-v
  automatic (``E`` in Am → ``V``, ``Em`` in Am → ``v``) with no natural-minor
  mode assumption.
* **Unclassifiable quality** (``sus``, power ``5``, add-only, unknown third) →
  uppercase root-position numeral + the raw quality suffix verbatim
  (``Csus4`` → ``Isus4``, ``C5`` → ``I5``).
* An unparseable chord (``N.C.``, garbage) → ``None`` at step 1; an absent or
  unparseable key → ``None``.
"""

from __future__ import annotations

import dataclasses

from .theory import diatonic_pcs, parse_chord, parse_key

__all__ = ["roman_for_chord", "roman_tokens"]


# ---------------------------------------------------------------------------
# Degree math
# ---------------------------------------------------------------------------

# Diatonic (natural, no-accidental) pitch class of each letter, C = 0. Used to
# compute the accidental prefix = root_pc − diatonic_pc_of_letter.
_LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_LETTER_ORDER = ("C", "D", "E", "F", "G", "A", "B")
_ROMAN_NUMERALS = ("I", "II", "III", "IV", "V", "VI", "VII")


def _accidental_prefix(delta: int) -> str:
    """Spell a semitone ``delta`` (root_pc − diatonic_pc_of_letter) as b/# runs.

    ``delta`` is normalized into ``-6..+6`` so the shorter enharmonic accidental
    run is chosen (e.g. a raw +11 becomes -1 → one flat, not eleven sharps).
    """
    delta = ((delta + 6) % 12) - 6
    if delta > 0:
        return "#" * delta
    if delta < 0:
        return "b" * (-delta)
    return ""


# ---------------------------------------------------------------------------
# Quality classification (case + °/+ symbol) — quality-driven, not templated
# ---------------------------------------------------------------------------

def _classify_quality(quality: str):
    """Classify a chord's quality string → ``(is_minor, symbol, suffix)``.

    Returns:
        ``is_minor`` — ``True`` if the numeral should be lowercase (minor /
        diminished), ``False`` for uppercase (major / augmented / default).
        ``symbol`` — ``"°"`` (diminished), ``"+"`` (augmented), or ``""``.
        ``suffix`` — the verbatim extension carried onto the numeral (``"7"``,
        ``"sus4"``, ...); ``None`` means "unclassifiable third" (caller applies
        the uppercase-plus-raw-suffix default).

    Detection is intentionally simple and quality-driven: it inspects only the
    quality string produced by :func:`~doxtr_music.engine.theory.parse_chord`
    (the root has already been stripped).
    """
    q = quality or ""

    # Diminished: m7b5 / half-dim, dim, °, o. Check before the plain-minor test
    # (m7b5 starts with 'm' but is diminished-flavored).
    low = q.lower()
    for marker in ("m7b5", "m7-5"):
        if low.startswith(marker):
            return (True, "°", q[len(marker):])
    if q.startswith("°") or q.startswith("o") or low.startswith("dim") or \
            q.startswith("ø"):
        for marker in ("dim", "°", "ø", "o"):
            if q.startswith(marker):
                return (True, "°", q[len(marker):])
        return (True, "°", q)  # pragma: no cover - defensive

    # Augmented: aug / + / #5 flavor.
    if low.startswith("aug") or q.startswith("+"):
        marker = "aug" if low.startswith("aug") else "+"
        return (False, "+", q[len(marker):])

    # Minor: a leading 'm' or 'min' NOT followed by 'aj' (major). Excludes 'maj'.
    if low.startswith("min"):
        return (True, "", q[3:])
    if q.startswith("m") and not low.startswith("maj"):
        return (True, "", q[1:])

    # Major-with-explicit-third markers (maj7, M7, major triad, dominant 7,
    # extensions on a major triad): uppercase, no symbol, carry the suffix.
    # A bare "" (plain major triad) also lands here.
    _MAJOR_THIRD_MARKERS = ("maj", "M", "6", "7", "9", "11", "13", "add", "")
    if q == "" or q.startswith(("maj", "M", "6", "7", "9", "11", "13", "add")):
        return (False, "", q)

    # Unclassifiable third (sus, power 5, unknown): signal the default.
    return (False, "", None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def roman_for_chord(chord_text, key):
    """Return the harmonic Roman numeral for ``chord_text`` in ``key``.

    Returns ``None`` when the chord is unparseable (``N.C.``, garbage) or when
    ``key`` is absent / unparseable. Never raises. This is the single roman
    authority (LOCKED).
    """
    parts = parse_chord(chord_text)
    if parts is None:  # unparseable root (N.C., garbage) → not analyzable
        return None
    parsed_key = parse_key(key)
    if parsed_key is None:  # no key → cannot analyze
        return None
    tonic_pc, _mode = parsed_key

    # Degree = letter distance above the tonic letter (0-based step → 1..7
    # numeral). Uses the SPELLED root letter so Bb is letter B.
    root_letter = parts.root[0].upper()
    if root_letter not in _LETTER_ORDER:  # pragma: no cover - parse_chord guards
        return None
    tonic_letter = _spell_tonic_letter(tonic_pc)
    step = (_LETTER_ORDER.index(root_letter) - _LETTER_ORDER.index(tonic_letter)) % 7
    numeral = _ROMAN_NUMERALS[step]

    # Accidental prefix = root_pc − the pitch class of that scale degree in the
    # key's own diatonic scale (theory.py is the single degree-table authority).
    # This makes diatonic chords accidental-free even in accidental-bearing keys
    # (e.g. Bb is IV in F, not bIV), while chromatic roots get b/# spelled by the
    # pc delta against their letter's scale position.
    scale = diatonic_pcs(tonic_pc, _mode)
    diatonic_pc = scale[step]
    accidental = _accidental_prefix(parts.root_pc - diatonic_pc)

    is_minor, symbol, suffix = _classify_quality(parts.quality)
    if suffix is None:  # unclassifiable third → uppercase + raw quality verbatim
        return accidental + numeral + parts.quality

    if is_minor:
        numeral = numeral.lower()
    return accidental + numeral + symbol + suffix


def _spell_tonic_letter(tonic_pc):
    """Return the natural letter whose pitch class matches ``tonic_pc``.

    For a chromatic tonic pitch (e.g. F#/Gb) we pick the letter of the nearest
    natural at or below the pitch so degree counting stays letter-based. This is
    an internal helper for degree math; enharmonic tonic spelling for *display*
    is theory.py's concern, not roman's.
    """
    tonic_pc %= 12
    for letter in _LETTER_ORDER:
        if _LETTER_PC[letter] == tonic_pc:
            return letter
    # Chromatic tonic: choose the letter just below (so F# uses letter F).
    best = "C"
    best_pc = -1
    for letter in _LETTER_ORDER:
        pc = _LETTER_PC[letter]
        if pc <= tonic_pc and pc > best_pc:
            best, best_pc = letter, pc
    return best


def _effective_chord_text(tok):
    """Return the chord text roman should analyze: transposed if set, else text."""
    for k, v in tok.annotations:
        if k == "transposed":
            return v
    return tok.text


def roman_tokens(tokens, key):
    """Annotate every ``ChordToken`` with its roman numeral (LOCKED contract).

    Returns a NEW list. Each ``ChordToken`` is rebuilt via
    :func:`dataclasses.replace` with an added ``("roman", <numeral>)`` annotation
    when :func:`roman_for_chord` yields a numeral (skipped when ``None``); all
    other tokens pass by identity. Uses the *effective* chord
    (``annotations["transposed"]`` if present, else ``text``). Order preserved;
    idempotent; annotation values stay hashable.
    """
    from doxtr_music.tokens import ChordToken

    out = []
    for tok in tokens:
        if not isinstance(tok, ChordToken):
            out.append(tok)
            continue
        numeral = roman_for_chord(_effective_chord_text(tok), key)
        if numeral is None:
            out.append(tok)
            continue
        kept = tuple((k, v) for (k, v) in tok.annotations if k != "roman")
        out.append(dataclasses.replace(tok, annotations=kept + (("roman", numeral),)))
    return out
