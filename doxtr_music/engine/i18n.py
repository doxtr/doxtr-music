"""Chord-system localization + shared render-display helper (CHUNK-3-4).

Localize chord **letter names** into regional systems
(``german`` / ``italian`` Do-Re-Mi / ``hungarian``) and resolve the shared
render-time chord-display string. This module is pure: it consumes
:mod:`doxtr_music.engine.theory` (``parse_chord`` / ``ChordParts``) and
re-implements no chord parsing. It imports nothing from Sphinx / Docutils /
``doxtr_pdf_theme_core``.

Canonical chord-display resolution order (LOCKED, CHUNK-3-4 owns the statement)::

    stored English (1-1)
      -> parse-time transpose annotate (3-2)
      -> parse-time roman annotate if :roman-numerals: OR chord_system=="roman" (3-3)
      -> build
      -> render: resolve_chord_display(node, config)

``localize_chord`` handles ONLY the letter systems
(``english`` / ``german`` / ``italian`` / ``hungarian``). The ``roman`` system
is NOT a ``localize_chord`` case: it is resolved at *parse time*
(``ChordNode.roman`` is populated in ``_post_parse_transform``) and consumed by
:func:`resolve_chord_display`, so the render path never calls ``roman_for_chord``
and never needs an effective key.

Localization is the **last** render step, applied to the *effective*
(post-transpose) English chord per the CHUNK-3-2 contract. Only the root letter
+ accidental (and the slash-bass) are remapped; quality / extensions
(``m7``, ``sus4``, ``6/9``) are carried verbatim. Remapping is keyed on the
*parsed* :attr:`ChordParts.root` (spelled) — never a string prefix — so the
classic German bug (``Bbm7`` mis-mapped by prefix) cannot occur.
"""

from __future__ import annotations

import logging
import unicodedata

from .theory import parse_chord

__all__ = [
    "localize_chord",
    "resolve_chord_display",
    "resolve_chord_display_parts",
    "resolve_key_display",
    "has_strong_rtl",
    "LETTER_SYSTEMS",
]

_LOG = logging.getLogger(__name__)

#: The letter-name systems handled by :func:`localize_chord`. ``english`` is the
#: stored/identity system; ``roman`` is deliberately excluded (parse-time).
LETTER_SYSTEMS = frozenset({"english", "german", "italian", "hungarian"})


# ---------------------------------------------------------------------------
# Note maps (LOCKED, concrete — keyed on the parsed spelled root)
# ---------------------------------------------------------------------------
#
# Each map takes the English spelled note (letter + optional accidental, as
# emitted by parse_chord: E# / Cb / double-accidentals included) to the regional
# spelling. An unmapped note falls back to the English spelling + a debug log
# (a unit test asserts no fallback fires for the enumerated CHUNK-3-2 spellings).

# German (H/B system): B -> H, Bb -> B (the classic swap). Sharps append -is;
# flats append -es with the elisions Es (E flat) and As (A flat), else Des/Ges;
# double-accidentals documented (Heses = B double-flat).
_GERMAN: dict[str, str] = {
    # naturals
    "C": "C", "D": "D", "E": "E", "F": "F", "G": "G", "A": "A", "B": "H",
    # sharps (-is)
    "C#": "Cis", "D#": "Dis", "E#": "Eis", "F#": "Fis", "G#": "Gis",
    "A#": "Ais", "B#": "His",
    # flats (-es, with Es / As elisions)
    "Cb": "Ces", "Db": "Des", "Eb": "Es", "Fb": "Fes", "Gb": "Ges",
    "Ab": "As", "Bb": "B",
    # double sharps (-isis)
    "C##": "Cisis", "D##": "Disis", "E##": "Eisis", "F##": "Fisis",
    "G##": "Gisis", "A##": "Aisis", "B##": "Hisis",
    # double flats (-eses, with Ases / Eses elisions mirroring the singles)
    "Cbb": "Ceses", "Dbb": "Deses", "Ebb": "Eses", "Fbb": "Feses",
    "Gbb": "Geses", "Abb": "Ases", "Bbb": "Heses",
}

# Italian (Do-Re-Mi): C->Do D->Re E->Mi F->Fa G->Sol A->La B->Si. Accidentals
# LOCKED to ASCII # / b suffix (Do#, Sib) — trivial LaTeX-escaper boundary and
# identical across all three formats.
_ITALIAN_LETTER: dict[str, str] = {
    "C": "Do", "D": "Re", "E": "Mi", "F": "Fa", "G": "Sol", "A": "La", "B": "Si",
}

# Hungarian: German-style H/B swap, but with Hungarian -sz sharp spellings
# (Fisz / Cisz / Disz) and -sz flat spellings (esz / asz / desz). Pinned so it
# is NOT silently German-identical.
_HUNGARIAN: dict[str, str] = {
    # naturals
    "C": "C", "D": "D", "E": "E", "F": "F", "G": "G", "A": "A", "B": "H",
    # sharps (-isz)
    "C#": "Cisz", "D#": "Disz", "E#": "Eisz", "F#": "Fisz", "G#": "Gisz",
    "A#": "Aisz", "B#": "Hisz",
    # flats (-esz, with esz / asz elisions)
    "Cb": "Cesz", "Db": "Desz", "Eb": "esz", "Fb": "Fesz", "Gb": "Gesz",
    "Ab": "asz", "Bb": "B",
    # double sharps (-iszisz)
    "C##": "Ciszisz", "D##": "Diszisz", "E##": "Eiszisz", "F##": "Fiszisz",
    "G##": "Giszisz", "A##": "Aiszisz", "B##": "Hiszisz",
    # double flats (-eszesz)
    "Cbb": "Ceszesz", "Dbb": "Deszesz", "Ebb": "eszesz", "Fbb": "Feszesz",
    "Gbb": "Geszesz", "Abb": "aszesz", "Bbb": "Heszesz",
}


def _italian_note(note: str) -> str:
    """Map an English spelled note to Italian (ASCII # / b accidental suffix)."""
    if not note:
        return note
    letter = note[0]
    accidentals = note[1:]  # already ASCII '#'/'b' as emitted by parse_chord
    base = _ITALIAN_LETTER.get(letter)
    if base is None:
        return note
    return base + accidentals


def _localize_note(note: str, system: str) -> str:
    """Localize a single spelled note; English/unknown-system → identity.

    Returns ``None``-free: an unmapped note under a known system falls back to
    the English spelling and logs at DEBUG.
    """
    if system == "english":
        return note
    if system == "italian":
        return _italian_note(note)
    table = {"german": _GERMAN, "hungarian": _HUNGARIAN}.get(system)
    if table is None:
        return note
    mapped = table.get(note)
    if mapped is None:
        _LOG.debug("i18n: no %s mapping for note %r; using English spelling", system, note)
        return note
    return mapped


def localize_chord(effective_chord: str, system: str) -> str:
    """Localize a chord's letter names into ``system``.

    ``english`` (and any non-letter system, e.g. ``roman``) → identity. Otherwise
    parse the effective chord, remap the **root** (letter + accidental) and the
    optional **slash-bass**, and reassemble
    ``localized_root + quality + ("/" + localized_bass)``. Quality/extensions are
    carried verbatim (never localized). An unparseable chord is returned
    unchanged (graceful passthrough).

    Remapping is keyed on the parsed :attr:`ChordParts.root`, so ``Bbm7`` → ``Bm7``
    (german) while ``Bm7`` → ``Hm7`` — no string-prefix collision.
    """
    if not effective_chord:
        return effective_chord
    if system == "english" or system not in LETTER_SYSTEMS:
        return effective_chord
    parts = parse_chord(effective_chord)
    if parts is None:
        return effective_chord  # unparseable → graceful passthrough
    root = _localize_note(parts.root, system)
    result = root + parts.quality
    if parts.bass is not None:
        result += "/" + _localize_note(parts.bass, system)
    return result


def resolve_chord_display(chord_node, config) -> str:
    """The single shared render-display helper for all three visitors.

    **Node-local** (LOCKED): reads only ``chord_node`` attributes
    (``transposed`` / ``chord`` / ``roman`` / ``roman_display`` /
    ``roman_format``) and ``config`` — never an ancestor node or an effective
    key — so it works on any ``ChordNode`` including a standalone role chord with
    no ``SongNode`` ancestor.

    Resolution:

    * ``effective = chord_node["transposed"] or chord_node["chord"]``;
      ``chord_label = localize_chord(effective, chord_system)``.
    * ``roman = chord_node["roman"]`` (parse-time numeral, may be absent).
    * Roman-display mode (``chord_node["roman_display"]``, default the legacy
      ``replace`` when a numeral is present and no mode is stamped):

      - ``off`` or no numeral → the localized chord label;
      - ``replace`` → the roman numeral verbatim (numerals are NEVER localized);
      - ``alongside`` → the ``roman_format`` template filled with ``chord`` +
        ``roman`` (e.g. ``"G (I)"``). With no numeral it degrades to the chord
        label alone.

    Returns the **unescaped** display string; the LaTeX visitor escapes at its
    own boundary. The other formats emit text nodes / attribute-escaped output.

    NOTE: ``alongside`` mixes the ``chord`` and ``roman`` typography elements in
    one string; the visitors that want independently-styled parts use
    :func:`resolve_chord_display_parts` instead. This scalar helper is the
    plain-text form (used where a single run/label is expected).
    """
    effective = chord_node.get("transposed") or chord_node.get("chord", "")
    roman = chord_node.get("roman")
    system = getattr(config, "doxtr_music_chord_system", "english")
    chord_label = localize_chord(effective, system)

    mode = chord_node.get("roman_display")
    if mode is None:
        # Back-compat: a stamped numeral with no explicit mode = replace.
        mode = "replace" if roman else "off"

    if not roman or mode == "off":
        return chord_label
    if mode == "replace":
        return roman
    # alongside
    fmt = chord_node.get("roman_format") or "{chord} ({roman})"
    return _apply_roman_format(fmt, chord_label, roman)


def _apply_roman_format(fmt, chord, roman) -> str:
    """Fill a validated ``{chord}``/``{roman}`` template; never raises."""
    try:
        return fmt.format(chord=chord, roman=roman)
    except Exception:  # pragma: no cover - fmt is validated upstream
        return "%s (%s)" % (chord, roman)


def resolve_chord_display_parts(chord_node, config):
    """Return the display as ordered parts for independent per-part styling.

    Returns a list of ``(kind, text)`` segments where ``kind`` is ``"chord"``,
    ``"roman"`` or ``"literal"`` (the fixed template text between placeholders,
    e.g. ``" ("`` / ``")"``). Visitors use this to style the chord part with the
    ``chord`` typography element and the numeral with the ``roman`` element:

    * ``off`` / no numeral → ``[("chord", <label>)]``.
    * ``replace`` → ``[("roman", <numeral>)]``.
    * ``alongside`` → the template split into chord/roman/literal segments,
      e.g. ``[("chord","G"),("literal"," ("),("roman","I"),("literal",")")]``.

    A newline in the template is preserved as literal text (stacking is a
    visitor concern).
    """
    effective = chord_node.get("transposed") or chord_node.get("chord", "")
    roman = chord_node.get("roman")
    system = getattr(config, "doxtr_music_chord_system", "english")
    chord_label = localize_chord(effective, system)

    mode = chord_node.get("roman_display")
    if mode is None:
        mode = "replace" if roman else "off"

    if not roman or mode == "off":
        return [("chord", chord_label)]
    if mode == "replace":
        return [("roman", roman)]
    fmt = chord_node.get("roman_format") or "{chord} ({roman})"
    return _split_roman_format(fmt, chord_label, roman)


def _split_roman_format(fmt, chord, roman):
    """Split a validated ``{chord}``/``{roman}`` template into typed segments."""
    import string

    parts = []
    try:
        pieces = list(string.Formatter().parse(fmt))
    except ValueError:  # pragma: no cover - fmt validated upstream
        return [("chord", chord), ("literal", " ("), ("roman", roman), ("literal", ")")]
    for literal_text, field, _spec, _conv in pieces:
        if literal_text:
            # Unescape doubled braces (str.format literal-brace convention).
            parts.append(("literal", literal_text.replace("{{", "{").replace("}}", "}")))
        if field == "chord":
            parts.append(("chord", chord))
        elif field == "roman":
            parts.append(("roman", roman))
    return parts


def resolve_key_display(key, config) -> str:
    """Render-display helper for a ``:key:`` role node (CHUNK-3-5).

    A key localizes as a **note name** (root + optional ``m`` minor-mode suffix)
    via :func:`localize_chord`, so minor keys localize (``Bm`` -> ``Hm`` in
    German) while a non-note/free-text key passes through unchanged. Reads only
    ``config`` (the configured chord system) — the ``doxtr_music_*`` attribute
    access lives here, not in each builder, mirroring
    :func:`resolve_chord_display` (keeps the per-format visitors free of direct
    config-key literals).
    """
    system = getattr(config, "doxtr_music_chord_system", "english")
    return localize_chord(key or "", system)


# ---------------------------------------------------------------------------
# RTL detection (pure) — the single authority reused by parsers + visitors
# ---------------------------------------------------------------------------

def has_strong_rtl(text: str) -> bool:
    """Return ``True`` if ``text`` contains a strong right-to-left codepoint.

    Strong-RTL = Unicode bidirectional class ``R`` (Hebrew) or ``AL`` (Arabic).
    Used at render time (LaTeX/EPUB) to fire the documented RTL fallback
    warning, and by the chord-line parser to warn on RTL input. Pure; no Sphinx.
    """
    for ch in text:
        if unicodedata.bidirectional(ch) in ("R", "AL"):
            return True
    return False
