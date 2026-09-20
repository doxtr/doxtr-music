r"""Multi-singer ``{singer: X}`` color resolution for doxtr-music (CHUNK-4-2).

Renders ``{singer: X}`` vocal-part attribution with distinct colors per singer
id across HTML, LaTeX/PDF and EPUB. The parser already turns ``{singer: X}`` into
a ``SingerToken`` and :func:`doxtr_music.nodes.build_nodes` already wraps the
attributed run in a :class:`~doxtr_music.nodes.SingerSpanNode`; this module owns
**only** the color map: resolving it and stamping the winning color onto the run.

Color precedence resolved in Python, emitted once (LOCKED — the core invariant)
------------------------------------------------------------------------------

For every element that can receive both a typography color and a singer color,
the final color is **decided here at build time** (singer over the typography
*color*, per the CHUNK-4-1 lock) and stamped as a single ``singer_color`` plain
attr on the run's :class:`SingerSpanNode` and its chord/lyric child nodes. No
format relies on CSS cascade (HTML) or ``\color`` lexical proximity (LaTeX) to
pick the winner: the visitors read the stamped ``singer_color`` and emit exactly
one color per element. The collision is **color-only** — typography ``font`` /
``size`` always apply (singer never sets them).

Resolution (LOCKED)
-------------------

Effective map = ``three_tier_merge(core={}, theme={}, global) ⊕ per_song`` via
:mod:`doxtr_music.config` (``theme={}`` until CHUNK-7-1). Global =
``doxtr_music_singer_colors``; per-song = ``node['options']['singer_colors']``.
:func:`stamp_singer_colors` walks each :class:`SingerSpanNode`, resolves its
singer id against the effective map and stamps the winning color:

* **Unmapped singer id → stamp nothing (None)** → the element falls back to its
  typography color (never removes typography color); a debug log is emitted;
  never crash.
* **Invalid color string → warn + fall back to inherited** (Python resolution
  time, reusing CHUNK-4-1's validation helpers).

The merge itself is delegated to :mod:`doxtr_music.config`
(``three_tier_merge``) — this module never re-implements it.
"""

from __future__ import annotations

import re

from sphinx.util import logging

from .config import three_tier_merge

logger = logging.getLogger(__name__)

__all__ = [
    "CONFIG_ATTR",
    "resolve_singer_colors",
    "validate_singer_colors",
    "stamp_singer_colors",
    "resolve_latex_singer_color",
]

#: The user-facing global config key (registered in CHUNK-0-3's manifest).
CONFIG_ATTR = "doxtr_music_singer_colors"

#: A conservative CSS color sanitizer — a singer color rides an inline
#: ``style="color:<value>"`` (HTML/EPUB), so reject anything carrying a
#: declaration-breaking char. Mirrors the CHUNK-4-1 typography sanitizer so the
#: two style layers validate identically.
_CSS_UNSAFE_RE = re.compile(r"[;{}<>\n\r]")


def _is_css_safe(value) -> bool:
    """True if ``value`` is a string with no CSS-declaration-breaking chars."""
    return isinstance(value, str) and not _CSS_UNSAFE_RE.search(value)


def validate_singer_colors(raw, warn=None) -> dict:
    """Return a cleaned ``{singer_id: color}`` dict.

    * Non-dict input → warn (when truthy) + return ``{}``.
    * Non-string ids/colors, empty colors, or CSS-unsafe colors → warn + drop.

    ``warn`` is an optional ``(message: str) -> None`` sink (defaults to the
    module logger's ``warning``); passing an explicit sink keeps the helper
    unit-testable without Sphinx.
    """
    emit = warn if warn is not None else logger.warning
    cleaned: dict = {}
    if not isinstance(raw, dict):
        if raw:
            emit(
                "[doxtr-music] doxtr_music_singer_colors must be a dict of "
                "{singer: color}; ignoring %r." % (raw,)
            )
        return cleaned
    for singer, color in raw.items():
        if not isinstance(singer, str) or not singer.strip():
            emit(
                "[doxtr-music] Ignoring non-string singer id %r in singer "
                "colors." % (singer,)
            )
            continue
        if color is None or (isinstance(color, str) and not color.strip()):
            continue
        if not _is_css_safe(color):
            emit(
                "[doxtr-music] Singer color for %r is not a safe style string; "
                "ignoring %r." % (singer, color)
            )
            continue
        cleaned[singer.strip()] = color.strip()
    return cleaned


def resolve_singer_colors(config, per_song=None, warn=None) -> dict:
    """Resolve the effective ``{singer_id: color}`` map for a song.

    ``three_tier_merge(core={}, theme={}, global) ⊕ per_song`` — global from
    ``doxtr_music_singer_colors`` (validated), theme ``{}`` until CHUNK-7-1,
    per-song from the directive's parsed ``singer_colors`` option (validated).
    Returns a plain ``{singer: color}`` dict.
    """
    raw_global = getattr(config, CONFIG_ATTR, {}) if config is not None else {}
    global_clean = validate_singer_colors(raw_global or {}, warn=warn)
    theme_defaults = (
        getattr(config, "doxtr_music_theme_defaults_resolved", {}) or {}
        if config is not None
        else {}
    )
    theme_map = {}
    if isinstance(theme_defaults, dict):
        theme_map = theme_defaults.get("singer_colors", {}) or {}
    if not isinstance(theme_map, dict):
        theme_map = {}
    theme_clean = validate_singer_colors(theme_map, warn=warn)
    merged = three_tier_merge({}, theme_clean, global_clean)
    per_song_clean = validate_singer_colors(per_song or {}, warn=warn)
    merged.update(per_song_clean)
    return merged


def stamp_singer_colors(song_node, config, warn=None) -> dict:
    """Resolve + stamp the winning singer color onto each singer run.

    Walks every :class:`~doxtr_music.nodes.SingerSpanNode` under ``song_node``,
    resolves its ``singer`` id against the effective map, and stamps the winning
    color as the plain-data ``singer_color`` attr on the span **and** on the
    run's chord/lyric child nodes (the reserved CHUNK-1-2 slots) so each visitor
    is node-local. Applies the singer-over-typography-color precedence in Python
    so the stamped color is already the winner (font/size stay on the typography
    stamp). An unmapped id stamps nothing (``None``) → typography color survives;
    a debug log is emitted. Returns the effective map (also stored on
    ``song_node['singer_colors']`` as plain data for introspection/tests).
    """
    from . import nodes as _nodes

    per_song = (song_node.get("options") or {}).get("singer_colors") or {}
    effective = resolve_singer_colors(config, per_song=per_song, warn=warn)
    # Transform each singer color for the active build: resolve ``dd:``
    # expressions against the theme palette and soft-invert static hex colors in
    # dark mode — so singer colors adapt exactly like every other doxtr-music
    # color (and like the rest of the themed document). A ``dd:`` value without
    # the theme installed raises an actionable error (via resolve_dd_color).
    if effective and config is not None:
        from .dd_resolve import resolve_dd_color

        effective = {
            singer: resolve_dd_color(
                color, config, context_label="doxtr_music_singer_colors"
            )
            for singer, color in effective.items()
        }
    song_node["singer_colors"] = dict(effective)

    for span in song_node.findall(_nodes.SingerSpanNode):
        singer = span.get("singer") or ""
        color = effective.get(singer)
        if not color:
            # Unmapped singer id → stamp nothing; typography color survives.
            logger.debug(
                "[doxtr-music] singer id %r has no mapped color; falling back "
                "to typography/inherited color.", singer
            )
            continue
        span["singer_color"] = color
        for child in span.findall(_nodes.ChordNode):
            child["singer_color"] = color
        for child in span.findall(_nodes.LyricNode):
            child["singer_color"] = color
    return effective


def resolve_latex_singer_color(color, *, define_name, warn=None):
    """Normalize a singer color for LaTeX use (reuses CHUNK-4-1's normalizer).

    Returns ``(color_expr, definecolor_line)`` — see
    :func:`doxtr_music.typography.normalize_latex_color`. An invalid color warns
    and returns ``(None, "")`` so the LaTeX visitor falls back to the inherited
    (typography) color rather than emitting a broken ``\\definecolor``.
    """
    from .typography import normalize_latex_color

    return normalize_latex_color(color, define_name=define_name, warn=warn)
