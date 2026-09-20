"""Configuration surface for doxtr-music.

This module is the **single** place every ``doxtr_music_*`` configuration value
is registered (see :func:`register_config`). It also provides the three-tier
(``core -> theme -> user``) merge helpers that later chunks import, and an
unknown-key validator that warns on typos without failing the build.

Design contracts honored here (see ``plan/chunks/CHUNK-0-3-config-surface.md``):

* All eight manifest values are registered here; later chunks add *behavior*,
  never *registration*. This keeps ``-W``/nitpicky builds green and lets any
  ``conf_override`` reference a documented key safely.
* ``on_config_inited`` runs at Sphinx's **default priority (~500)** and performs
  only validation and the ``chord_system`` fallback. It must **not** read
  theme-provided defaults: ``doxtr-pdf-theme-core`` resolves its own config on
  ``config-inited`` at priority 900, so theme-tier consumption is reserved for
  CHUNK-7-1 (priority > 900).
* ``doxtr-pdf-theme-core`` is a **soft** dependency: this module never imports
  it. The theme tier is read via a Sphinx config *attribute*
  (``doxtr_music_theme_defaults_resolved``) and degrades to ``{}`` when absent.
"""
import copy

from sphinx.util import logging

logger = logging.getLogger(__name__)

__all__ = [
    "CONFIG_MANIFEST",
    "MANIFEST_NAMES",
    "VALID_CHORD_SYSTEMS",
    "VALID_ROMAN_DISPLAYS",
    "DEFAULT_ROMAN_FORMAT",
    "DEFAULT_INDEX_PAGE_FORMAT",
    "validate_roman_format",
    "validate_index_page_format",
    "deep_update",
    "three_tier_merge",
    "validate_config_keys",
    "register_config",
    "on_config_inited",
]

# --- The manifest -----------------------------------------------------------
# Each row: name -> (default, rebuild_scope). This is the authoritative,
# complete eight-row contract mirroring README.md's "Configuration" table.
# Register ALL of them now (even those whose behavior lands in a later chunk)
# so conf_overrides can reference them safely.
CONFIG_MANIFEST = {
    "doxtr_music_chord_system": ("english", "env"),
    "doxtr_music_latex_package": ("songbook", "env"),
    "doxtr_music_typography": ({}, "env"),
    "doxtr_music_singer_colors": ({}, "env"),
    # Roman-numeral display mode + alongside format. ``roman_display`` is one of
    # ``off``/``replace``/``alongside`` (default ``off``): show the chord name,
    # the numeral instead of the chord, or both together. ``roman_format`` is
    # the ``alongside`` template with ``{chord}`` + ``{roman}`` placeholders
    # (default ``"{chord} ({roman})"``); a newline stacks chord over numeral.
    "doxtr_music_roman_display": ("off", "env"),
    "doxtr_music_roman_format": ("{chord} ({roman})", "env"),
    # The format string wrapping a song's page number in the alphabetical
    # ``.. song-index:: :style: index`` and anywhere else a song's page
    # reference is rendered (LaTeX/PDF only — HTML/EPUB have no pages). The
    # single ``{page}`` placeholder is replaced with the resolved page number;
    # default ``"{page}"`` shows the bare number, e.g. ``"page {page}"`` reads
    # ``page 12``. The whole formatted string hyperlinks to the song.
    "doxtr_music_index_page_format": ("{page}", "env"),
    "doxtr_music_theme_interop": (True, "env"),
    "doxtr_music_chord_preprocess": (None, "env"),
    "doxtr_music_node_parsed": (None, "env"),
    "doxtr_music_html_visit": (None, "html"),
    # CHUNK-7-1 amendment (cross-chunk with CHUNK-2-1): the LaTeX backend
    # override-dir key the 2-1 resolver already reads defensively. Registered
    # here so it is a documented config surface and the resolver's user-override
    # tier is first-class; a user override dir wins over the theme tier, which
    # wins over the packaged backends. Its addition takes the manifest from the
    # original 8-row 0-3 snapshot to 9 (recorded amendment, not silent creep).
    "doxtr_music_latex_backend_path": (None, "env"),
    # Auto-load doxtr-pdf-theme-core when it is importable (so a user need not
    # list it before doxtr_music in ``extensions``). Default True; set False to
    # opt out of the automatic load (the extension can still be listed manually,
    # and a build that must NOT pull in the theme's engine requirements — e.g. a
    # bare pdflatex compile — can disable it).
    "doxtr_music_autoload_theme": (True, "env"),
}

#: The set of registered manifest names — the authority the typo guard uses.
MANIFEST_NAMES = frozenset(CONFIG_MANIFEST)

#: Allowed chord-notation systems. ``"roman"`` means "display chords as
#: functional Roman numerals" and consumes the single ``engine/roman.py``
#: engine (CHUNK-3-3); with no effective key it falls back gracefully.
VALID_CHORD_SYSTEMS = frozenset(
    {"english", "german", "italian", "hungarian", "roman"}
)

#: Allowed Roman-numeral display modes (``doxtr_music_roman_display``):
#: ``off`` (chord name only), ``replace`` (numeral instead of the chord name),
#: ``alongside`` (chord name AND numeral, combined via ``doxtr_music_roman_format``).
VALID_ROMAN_DISPLAYS = frozenset({"off", "replace", "alongside"})

#: The default ``alongside`` template. Placeholders ``{chord}`` and ``{roman}``
#: are both required; a newline stacks the chord over the numeral.
DEFAULT_ROMAN_FORMAT = "{chord} ({roman})"

#: The default page-number format for the alphabetical index / song page
#: reference. The single ``{page}`` placeholder is required; the default emits
#: the bare page number.
DEFAULT_INDEX_PAGE_FORMAT = "{page}"

#: Attributes matching this reserved suffix are derived/internal and are
#: excluded from the unknown-key typo check. CHUNK-7-1 adds
#: ``doxtr_music_theme_defaults_resolved`` and must not trip the guard.
_RESOLVED_SUFFIX = "_resolved"


# --- Merge helpers ----------------------------------------------------------
def deep_update(base, over):
    """Recursively merge ``over`` into a deep copy of ``base``.

    Nested dicts merge key-by-key; non-dict values in ``over`` replace those in
    ``base``. Neither input is mutated (both are deep-copied), so the result is
    safe to mutate freely.
    """
    result = copy.deepcopy(base)
    for key, over_val in over.items():
        base_val = result.get(key)
        if isinstance(base_val, dict) and isinstance(over_val, dict):
            result[key] = deep_update(base_val, over_val)
        else:
            result[key] = copy.deepcopy(over_val)
    return result


def three_tier_merge(core, theme, user):
    """Merge the three config tiers: ``user`` over ``theme`` over ``core``.

    Applies ``deep_update(deep_update(core, theme), user)`` with deep-copied
    inputs, so none of ``core``/``theme``/``user`` is mutated and the returned
    dict is independently mutable.

    The ``theme`` tier is inert until CHUNK-7-1 populates
    ``doxtr_music_theme_defaults_resolved``; callers pass
    ``getattr(config, "doxtr_music_theme_defaults_resolved", {})`` for it, which
    is ``{}`` today (a clean two-tier ``core -> user`` merge).
    """
    return deep_update(deep_update(core, theme), user)


# --- Validation -------------------------------------------------------------
def validate_config_keys(config, known_prefixes=("doxtr_music_",)):
    """Warn on any ``doxtr_music_*`` attribute not in the manifest set.

    Compares against :data:`MANIFEST_NAMES` so registered keys never self-warn.
    Attributes using the reserved ``_resolved`` suffix (derived/internal, e.g.
    CHUNK-7-1's ``doxtr_music_theme_defaults_resolved``) are excluded. This is a
    warn-not-fail typo guard; it never raises.

    The candidate key names come from the raw ``conf.py`` namespace
    (``config._raw_config``) when available — Sphinx does not surface
    *unregistered* values as attributes, so ``dir(config)`` alone would never
    see a typo like ``doxtr_music_bogus``. A ``dir(config)`` fallback keeps the
    helper usable with lightweight config stand-ins in unit tests.
    """
    raw = getattr(config, "_raw_config", None)
    if isinstance(raw, dict):
        candidates = set(raw)
    else:
        candidates = set(dir(config))

    unknown = set()
    for name in candidates:
        if not any(name.startswith(prefix) for prefix in known_prefixes):
            continue
        if name in MANIFEST_NAMES:
            continue
        if name.endswith(_RESOLVED_SUFFIX):
            continue
        unknown.add(name)
    if unknown:
        logger.warning(
            "[doxtr-music] Unknown configuration value(s): %s. "
            "These will be ignored. Did you mean one of: %s?",
            sorted(unknown),
            sorted(MANIFEST_NAMES),
        )


# --- Registration + config-inited hook --------------------------------------
def register_config(app):
    """Register every manifest value via ``app.add_config_value``.

    Called once from ``setup()``. This is the sole registration site for
    ``doxtr_music_*`` config values.
    """
    for name, (default, rebuild) in CONFIG_MANIFEST.items():
        app.add_config_value(name, default, rebuild)


def validate_roman_format(value, warn=None):
    r"""Return a safe ``alongside`` roman-format template, or the default.

    A valid template is a string that (a) contains BOTH ``{chord}`` and
    ``{roman}`` placeholders and (b) contains no OTHER ``{...}`` field (so it is
    a fixed two-placeholder template, never an arbitrary/injecting format
    string). Invalid → warn + fall back to :data:`DEFAULT_ROMAN_FORMAT`. A
    literal brace can be escaped as ``{{`` / ``}}`` (standard ``str.format``).
    """
    emit = warn if warn is not None else logger.warning
    if not isinstance(value, str) or not value.strip():
        return DEFAULT_ROMAN_FORMAT
    # Extract the field names str.format would see (after removing escaped {{ }}).
    import string

    stripped = value.replace("{{", "").replace("}}", "")
    try:
        fields = [
            name for _text, name, _spec, _conv in string.Formatter().parse(stripped)
            if name is not None
        ]
    except ValueError:
        emit(
            "[doxtr-music] doxtr_music_roman_format %r is not a valid template; "
            "falling back to %r." % (value, DEFAULT_ROMAN_FORMAT)
        )
        return DEFAULT_ROMAN_FORMAT
    allowed = {"chord", "roman"}
    unknown = [f for f in fields if f not in allowed]
    if unknown or "chord" not in fields or "roman" not in fields:
        emit(
            "[doxtr-music] doxtr_music_roman_format %r must contain both "
            "{chord} and {roman} and no other placeholder; falling back to %r."
            % (value, DEFAULT_ROMAN_FORMAT)
        )
        return DEFAULT_ROMAN_FORMAT
    return value


def validate_index_page_format(value, warn=None):
    r"""Return a safe page-number format template, or the default.

    A valid template is a string that contains exactly ONE ``{page}``
    placeholder and no OTHER ``{...}`` field, so it is a fixed single-placeholder
    template (never an arbitrary/injecting format string). Invalid → warn + fall
    back to :data:`DEFAULT_INDEX_PAGE_FORMAT`. A literal brace can be escaped as
    ``{{`` / ``}}`` (standard ``str.format``).
    """
    emit = warn if warn is not None else logger.warning
    if not isinstance(value, str) or not value.strip():
        return DEFAULT_INDEX_PAGE_FORMAT
    import string

    stripped = value.replace("{{", "").replace("}}", "")
    try:
        fields = [
            name for _text, name, _spec, _conv in string.Formatter().parse(stripped)
            if name is not None
        ]
    except ValueError:
        emit(
            "[doxtr-music] doxtr_music_index_page_format %r is not a valid "
            "template; falling back to %r." % (value, DEFAULT_INDEX_PAGE_FORMAT)
        )
        return DEFAULT_INDEX_PAGE_FORMAT
    if fields.count("page") != 1 or any(f != "page" for f in fields):
        emit(
            "[doxtr-music] doxtr_music_index_page_format %r must contain exactly "
            "one {page} placeholder and no other placeholder; falling back to %r."
            % (value, DEFAULT_INDEX_PAGE_FORMAT)
        )
        return DEFAULT_INDEX_PAGE_FORMAT
    return value


def on_config_inited(app, config):
    """Validation-only ``config-inited`` handler (default priority ~500).

    Performs the unknown-key typo check and the ``chord_system`` /
    ``roman_display`` / ``roman_format`` fallbacks. It must NOT read
    theme-provided defaults — theme-tier consumption is owned by CHUNK-7-1 at
    priority > 900.
    """
    validate_config_keys(config)

    chord_system = config.doxtr_music_chord_system
    if chord_system not in VALID_CHORD_SYSTEMS:
        logger.warning(
            "[doxtr-music] Invalid doxtr_music_chord_system %r; "
            "falling back to 'english'. Valid systems: %s.",
            chord_system,
            sorted(VALID_CHORD_SYSTEMS),
        )
        config.doxtr_music_chord_system = "english"

    roman_display = getattr(config, "doxtr_music_roman_display", "off")
    if roman_display not in VALID_ROMAN_DISPLAYS:
        logger.warning(
            "[doxtr-music] Invalid doxtr_music_roman_display %r; falling back "
            "to 'off'. Valid modes: %s.",
            roman_display,
            sorted(VALID_ROMAN_DISPLAYS),
        )
        config.doxtr_music_roman_display = "off"

    config.doxtr_music_roman_format = validate_roman_format(
        getattr(config, "doxtr_music_roman_format", DEFAULT_ROMAN_FORMAT)
    )

    config.doxtr_music_index_page_format = validate_index_page_format(
        getattr(config, "doxtr_music_index_page_format", DEFAULT_INDEX_PAGE_FORMAT)
    )
