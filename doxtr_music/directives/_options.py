"""Shared option converters + normalization for song-family directives.

This module is the **single parse point** (LOCKED, CHUNK-1-4) for every
``.. song::``-family option. The ``option_spec`` converters here are the only
place raw option strings are turned into the locked, plain-data
``node['options']`` shape. Later chunks (3-2 transpose, 3-4 i18n, 4-1
typography, 4-2 multi-singer) **consume** ``node['options'][...]`` and MUST NOT
add ``option_spec`` entries; a genuinely new option is a design escalation, not
a local edit (mirrors CHUNK-0-3 "register all now").

Normalized ``node['options']`` shape (LOCKED)::

    transpose:      int | None
    key:            str | None
    roman_numerals: bool                 # legacy :roman-numerals: flag
    roman_display:  str | None           # off|replace|alongside (None=inherit)
    roman_format:   str | None           # alongside {chord}/{roman} template
    format:         str | None
    singer_colors:  dict[str, str]   # parsed "A: darkblue, B: orange"
    typography:     dict[str, dict]  # parsed ":<element>-font/-size/-color:"

Typography elements the ``:<element>-...:`` mini-language recognizes are the
five granular targets CHUNK-4-1 owns; the converters accept them now so the
directive signature never changes downstream.
"""

from __future__ import annotations

from docutils.parsers.rst import directives

__all__ = [
    "TYPOGRAPHY_ELEMENTS",
    "TYPOGRAPHY_PROPS",
    "singer_colors_option",
    "song_option_spec",
    "normalize_options",
    "resolve_transpose_key",
]

#: The five granular typography targets (CHUNK-4-1 owns rendering). LOCKED by
#: CHUNK-4-1: title, metadata, roman, chord, lyrics. The option names are
#: ``:<element>-<prop>:`` (e.g. ``:lyrics-color:``, ``:metadata-size:``).
TYPOGRAPHY_ELEMENTS = ("title", "metadata", "roman", "chord", "lyrics")

#: The per-element typography properties (suffixes of ``:<element>-<prop>:``).
#: ``background`` was added alongside the original font/size/color so per-song
#: options mirror the ``doxtr_music_typography`` config surface
#: (e.g. ``:chord-background:``, ``:lyrics-background:``).
TYPOGRAPHY_PROPS = ("font", "size", "color", "background")


def singer_colors_option(argument):
    """Parse the ``A: darkblue, B: orange`` singer→color mini-language.

    Returns a plain ``dict[str, str]`` mapping singer id → color string. A
    missing/empty argument yields ``{}``. Malformed entries (no colon) are
    skipped silently here; the directive validates + warns at ``run`` time so
    the warning carries source-line provenance.
    """
    result: dict = {}
    if not argument:
        return result
    for part in argument.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        singer, _, color = part.partition(":")
        singer = singer.strip()
        color = color.strip()
        if singer and color:
            result[singer] = color
    return result


def _typography_option(argument):
    """Identity converter for a single ``:<element>-<prop>:`` value.

    The raw string value is stashed as-is; the directive folds each
    ``<element>-<prop>`` option into the nested ``typography`` dict at ``run``
    time. Kept permissive (never raises) so unknown-but-registered options
    never crash a build.
    """
    return (argument or "").strip()


def _build_typography_spec():
    """Build the ``:<element>-<prop>:`` entries for ``option_spec``."""
    spec = {}
    for element in TYPOGRAPHY_ELEMENTS:
        for prop in TYPOGRAPHY_PROPS:
            spec[f"{element}-{prop}"] = _typography_option
    return spec


def song_option_spec():
    """Return the full, locked ``option_spec`` for song-family directives.

    Registers every option consumed now or later (transpose/key/roman-numerals/
    format/singer-colors + the 5×3 typography grid) so later chunks add
    *behavior*, never *registration*. Unknown options still raise Docutils'
    standard error, but every documented option is accepted here.
    """
    spec = {
        "transpose": directives.unchanged,  # validated to int in normalize
        "key": directives.unchanged,
        "roman-numerals": directives.flag,
        "roman-display": directives.unchanged,   # off | replace | alongside
        "roman-format": directives.unchanged,    # {chord}/{roman} template
        "format": directives.unchanged,
        "singer-colors": singer_colors_option,
    }
    spec.update(_build_typography_spec())
    return spec


def _coerce_int(value):
    """Coerce ``value`` to ``int`` or ``None`` (never raises)."""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def normalize_options(raw_options):
    """Normalize a directive's ``self.options`` into the locked plain-data dict.

    ``raw_options`` is the Docutils-parsed options mapping (already run through
    the ``option_spec`` converters). Returns a new dict with exactly the locked
    keys/types. Transpose/key precedence against ``song_meta`` is applied
    separately by :func:`resolve_transpose_key` (the directive's single home for
    precedence).
    """
    raw = dict(raw_options or {})

    typography: dict = {}
    for element in TYPOGRAPHY_ELEMENTS:
        props: dict = {}
        for prop in TYPOGRAPHY_PROPS:
            opt_key = f"{element}-{prop}"
            if opt_key in raw and raw[opt_key]:
                props[prop] = raw[opt_key]
        if props:
            typography[element] = props

    singer_colors = raw.get("singer-colors") or {}
    if not isinstance(singer_colors, dict):
        singer_colors = {}

    # Roman display mode (off/replace/alongside) + alongside format template.
    # ``:roman-display:`` given wins; else the legacy ``:roman-numerals:`` flag
    # maps to ``replace``; else ``None`` (inherit the global config default).
    roman_display = None
    rd = raw.get("roman-display")
    if rd:
        roman_display = rd.strip().lower()
        if "roman-numerals" in raw:
            # Both given: :roman-display: wins (recorded so the directive can warn).
            roman_display = rd.strip().lower()
    elif "roman-numerals" in raw:
        roman_display = "replace"
    roman_format = raw["roman-format"].strip() if raw.get("roman-format") else None

    return {
        "transpose": _coerce_int(raw.get("transpose")),
        "key": (raw["key"].strip() if raw.get("key") else None),
        "roman_numerals": "roman-numerals" in raw,
        "roman_display": roman_display,
        "roman_format": roman_format,
        "format": (raw["format"].strip() if raw.get("format") else None),
        "singer_colors": dict(singer_colors),
        "typography": typography,
    }


def resolve_transpose_key(options, song_meta):
    """Apply transpose/key precedence into single resolved ``options`` fields.

    Directive-level ``:transpose:`` / ``:key:`` override the file-level
    ``song_meta["transpose"]`` / ``song_meta["key"]``. This is the **single
    home** for that precedence (LOCKED): CHUNK-3-2 consumes
    ``options['transpose']`` / ``options['key']`` and does NOT re-resolve;
    CHUNK-3-5 (song-include) delegates here. Capo is untouched (owned by 3-2).

    Mutates and returns ``options`` in place for convenience.
    """
    meta = song_meta or {}

    if options.get("transpose") is None:
        meta_transpose = _coerce_int(meta.get("transpose"))
        if meta_transpose is not None:
            options["transpose"] = meta_transpose

    if not options.get("key"):
        meta_key = meta.get("key")
        if isinstance(meta_key, str) and meta_key.strip():
            options["key"] = meta_key.strip()

    return options
