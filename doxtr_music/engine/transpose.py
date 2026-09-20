"""Quality-preserving, enharmonically correct chord transposition.

Transposition shifts a chord's root (and slash bass) by a number of semitones
and re-spells the result per the LOCKED enharmonic policy in
:mod:`doxtr_music.engine.theory`, preserving the chord quality verbatim. The
transposed display string is attached to each :class:`~doxtr_music.tokens.ChordToken`
via the reserved ``annotations["transposed"]`` key (CHUNK-1-1); nothing mutates
``ChordToken.text`` (English-only storage).

Render pipeline order (LOCKED, forward-contract to CHUNK-3-4)::

    parse → transpose (annotate English) → build → render: localize(effective)

where ``effective = node.transposed or node.chord`` (both English). This module
NEVER localizes; CHUNK-3-4 localizes the post-transpose ``effective`` string.

This module imports nothing from Sphinx / Docutils / ``doxtr_pdf_theme_core``.
"""

from __future__ import annotations

import dataclasses

from doxtr_music.engine.theory import parse_chord, parse_key, spell_pc
from doxtr_music.tokens import ChordToken

__all__ = [
    "transpose_chord",
    "transpose_tokens",
    "compute_effective_shift",
]


def _accidental_prefer(*note_names):
    """Infer a keyless enharmonic ``prefer`` from the input chord's spelling.

    Without a key context there is no key-signature to spell against, so we
    preserve the INPUT's accidental side: a ``b`` in any provided note name →
    prefer flats; a ``#`` → prefer sharps. A wholly natural input (e.g. ``Em``,
    ``C``) has no side to preserve, so we prefer **sharps** — the near-universal
    chord-chart convention that avoids theoretically-poor spellings like
    ``Gbm``/``Dbm``/``Abm`` (the standard names are ``F#m``/``C#m``/``G#m``).
    """
    joined = "".join(n or "" for n in note_names)
    if "b" in joined:
        return "flat"
    # A '#' present, OR a fully-natural input: prefer sharps.
    return "sharp"


def transpose_chord(text, semitones, key=None):
    """Transpose one chord string by ``semitones``, spelling per ``key``.

    ``key`` is the **target** key string (e.g. ``"D"``, ``"Bb"``, ``"Am"``)
    used to choose enharmonic spelling. When ``key`` is ``None`` there is no
    key-signature to spell against, so the enharmonic side is taken from the
    INPUT chord's own accidental (a ``b`` → flats, a ``#`` → sharps); a wholly
    natural input prefers **sharps** (the chord-chart convention, avoiding
    ``Gbm``-style spellings). Returns the complete render-ready English display
    string (``root + quality + /bass``). Unrecognized input is returned
    unchanged (graceful): ``"N.C."`` / ``"%"`` / garbage pass through verbatim.

    A zero shift with a recognizable chord still re-spells (idempotent, and lets
    a ``key`` override reflect its side); quality is preserved verbatim.
    """
    parts = parse_chord(text)
    if parts is None:
        return text

    semitones = int(semitones) % 12
    parsed_key = parse_key(key) if key else None
    if parsed_key is not None:
        key_tonic, key_mode = parsed_key
    else:
        key_tonic, key_mode = None, "major"

    # Keyless spelling side: preserve the input chord's own accidental (see
    # :func:`_accidental_prefer`). With a key, ``spell_pc`` ignores ``prefer``.
    prefer = _accidental_prefer(parts.root, parts.bass) if parsed_key is None else None

    new_root_pc = (parts.root_pc + semitones) % 12
    new_root = spell_pc(new_root_pc, key_tonic, key_mode, prefer=prefer)

    display = new_root + parts.quality
    if parts.bass_pc is not None:
        new_bass_pc = (parts.bass_pc + semitones) % 12
        new_bass = spell_pc(new_bass_pc, key_tonic, key_mode, prefer=prefer)
        display = display + "/" + new_bass
    return display


def _set_transposed(tok, value):
    """Return a copy of ``tok`` with ``annotations["transposed"] = value``.

    Idempotent: replaces an existing ``"transposed"`` pair rather than
    appending a second one, so re-transposing a stream is well-defined. Uses
    :func:`dataclasses.replace` (never in-place) so inputs stay immutable.
    """
    kept = tuple((k, v) for (k, v) in tok.annotations if k != "transposed")
    return dataclasses.replace(tok, annotations=kept + (("transposed", value),))


def transpose_tokens(tokens, semitones, key=None):
    """Return a NEW token list with each ``ChordToken`` annotated ``transposed``.

    Only :class:`~doxtr_music.tokens.ChordToken` instances are transformed; all
    other token types pass through **by identity, order preserved**. Inputs are
    never mutated (``replace``). Idempotent on re-transpose (see
    :func:`_set_transposed`). Silent on unrecognized chords (they annotate their
    own unchanged text, matching the single-drain contract in the directive).
    """
    out = []
    for tok in tokens:
        if isinstance(tok, ChordToken):
            out.append(_set_transposed(tok, transpose_chord(tok.text, semitones, key)))
        else:
            out.append(tok)
    return out


def compute_effective_shift(options, song_meta, warn=None):
    """Resolve the single effective shift + target key (LOCKED — never summed).

    ``:transpose:`` and target ``:key:`` are mutually exclusive intents:

    * ``:transpose: N`` given → shift = ``N``; the target key for spelling is
      ``source_key + N`` when the source key is known, else ``None`` (flats).
    * ``:key: TARGET`` given (no ``:transpose:``) → shift =
      ``interval(source_key → TARGET)``; spelling key is ``TARGET``.
    * **Both given** → ``:transpose:`` wins; ``warn`` is called noting ``:key:``
      is ignored.
    * Source ``{key}`` absent/unparseable while ``:key:`` given → no-op
      (shift 0) + ``warn``.

    ``options`` is the resolved directive-over-file options dict (CHUNK-1-4);
    ``song_meta`` supplies the source ``key``. Returns ``(shift, spell_key)``
    where ``spell_key`` is the target key string used for enharmonic spelling
    (may be ``None``). Capo is display-only and never contributes (LOCKED).
    """
    meta = song_meta or {}
    source_key = meta.get("key") if isinstance(meta.get("key"), str) else None
    transpose = options.get("transpose")
    target_key = options.get("key")

    def _warn(message):
        if warn is not None:
            try:
                warn(message)
            except Exception:  # pragma: no cover - warn must never be fatal
                pass

    if transpose is not None:
        if target_key:
            _warn(":key: ignored because :transpose: is set")
        shift = int(transpose) % 12
        spell_key = None
        if source_key:
            parsed = parse_key(source_key)
            if parsed is not None:
                tonic, mode = parsed
                new_tonic = (tonic + shift) % 12
                # Build a spelling key string from the shifted tonic (side by
                # the target pitch); minor keeps the ``m`` suffix.
                spell_key = spell_pc(new_tonic, tonic, mode) + (
                    "m" if mode == "minor" else ""
                )
        return (shift, spell_key)

    if target_key:
        parsed_target = parse_key(target_key)
        parsed_source = parse_key(source_key) if source_key else None
        if parsed_target is None:
            _warn(":key: %r is not a recognizable key" % target_key)
            return (0, None)
        if parsed_source is None:
            _warn(
                ":key: has no effect because the song's source {key} is "
                "missing or unrecognizable"
            )
            return (0, None)
        shift = (parsed_target[0] - parsed_source[0]) % 12
        return (shift, target_key)

    return (0, None)
