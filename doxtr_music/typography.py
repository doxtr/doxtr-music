"""Granular typography resolution for doxtr-music (CHUNK-4-1).

Independent font/size/color styling for the five song **elements** —
``title``, ``metadata``, ``roman``, ``chord``, ``lyrics`` — globally via
``doxtr_music_typography`` and per-song via directive options, rendered
identically in intent across HTML, LaTeX/PDF and EPUB.

Text-vs-style invariant (LOCKED — stated once here)
---------------------------------------------------

:func:`doxtr_music.engine.i18n.resolve_chord_display` owns the chord **text**;
typography owns the element **style** (font/size/color). Neither reads the
other. Typography is **styling-only**: it never changes DOM order, element
class/identity, ``aria-hidden``, the display string, ``COPY_SAFE_ORDER`` or the
``resolve_chord_display`` order. CHUNK-4-2 singer color obeys the same
separation and contends only on *color* (singer wins), never font/size.

Resolution timing + data flow (LOCKED)
--------------------------------------

* **Core defaults** are a complete 5x3 dict (:data:`CORE_TYPOGRAPHY`).
* **Global** typography (``doxtr_music_typography``) is validated at
  ``config-inited`` and cached on the config as
  ``doxtr_music_typography_resolved`` (the reserved ``_resolved`` suffix keeps
  the 0-3 typo guard quiet).
* The **final per-element/per-attr merge happens per-song at build**, because
  the per-song tier lives on ``SongNode.options['typography']`` (only available
  after parse). Model::

      resolved = deep_update(
          three_tier_merge(core, theme, global), per_song
      )

  where ``three_tier_merge`` handles core/theme/global (``theme`` via the theme
  dict arg, ``{}`` until CHUNK-7-1) and ``deep_update`` layers per-song on top.
  Per-attr recursive merge means ``:chord-color:`` overrides only chord color.
* :func:`doxtr_music.nodes.build_nodes` stamps the resolved per-element
  typography onto the relevant child nodes (the reserved plain-data
  ``typography`` node attr), so render is node-local (no ancestor walk).

The merge itself is delegated to :mod:`doxtr_music.config`
(``three_tier_merge`` + ``deep_update``) — this module never re-implements it.
"""

from __future__ import annotations

import re

from sphinx.util import logging

from .config import deep_update, three_tier_merge

logger = logging.getLogger(__name__)

__all__ = [
    "ELEMENTS",
    "BASE_ELEMENTS",
    "ATTRS",
    "CORE_TYPOGRAPHY",
    "CONFIG_ATTR",
    "RESOLVED_CONFIG_ATTR",
    "is_valid_element",
    "section_element_names",
    "meta_element_names",
    "resolve_element_cell",
    "validate_typography",
    "resolve_global_typography",
    "resolve_song_typography",
    "stamp_typography",
    "css_declarations",
    "normalize_latex_color",
    "latex_font_switch",
    "latex_size_switch",
    "latex_cell_wrap",
    "global_typography_style_block",
    "latex_typography_contributor",
    "register_latex_typography_contributor",
    "song_typography_latex_group",
    "on_config_inited_typography",
    "on_config_inited_typography_late",
    "TYPOGRAPHY_LATE_INIT_PRIORITY",
    "add_global_typography_style",
    "TYPOGRAPHY_INIT_PRIORITY",
    "TYPOGRAPHY_PREAMBLE_PRIORITY",
]

#: The five *base* styleable song elements (LOCKED originals).
BASE_ELEMENTS = ("title", "metadata", "roman", "chord", "lyrics")

#: Backwards-compatible alias. Historically the only elements; kept so existing
#: callers/tests that iterate ``ELEMENTS`` still see the base grid. The
#: *resolution* machinery below is element-name-agnostic and also supports the
#: dynamic ``section[-<kind>]-title``/``-body`` and ``meta-<key>`` element
#: namespaces (see :data:`SECTION_ELEMENT_RE` / :data:`META_ELEMENT_RE`).
ELEMENTS = BASE_ELEMENTS

#: The styleable attributes per element (LOCKED). ``background`` was added to
#: the original ``font``/``size``/``color`` trio so any element can carry a
#: background color (rendered as ``background-color`` in HTML/EPUB and a
#: ``\colorbox``-style wrap in LaTeX).
ATTRS = ("font", "size", "color", "background")

#: Dynamic element-name namespaces (flexible, so a songwriter may introduce any
#: section kind or use any metadata key):
#:
#: * ``section-title`` / ``section-body`` — defaults for EVERY section.
#: * ``section-<kind>-title`` / ``section-<kind>-body`` — a specific section
#:   kind (``verse``/``chorus``/``bridge``/… or any custom kind), overriding the
#:   generic ``section-title``/``-body`` for that kind only.
#: * ``metadata`` — the default style for ALL rendered song-metadata rows.
#: * ``meta-<key>`` — a specific metadata key (``tempo``/``key``/… or any key an
#:   author uses), overriding ``metadata`` for that row only.
SECTION_ELEMENT_RE = re.compile(r"^section(?:-(?P<kind>[a-z0-9]+))?-(?P<part>title|body)$")
META_ELEMENT_RE = re.compile(r"^meta-(?P<key>[a-z0-9_]+)$")

#: A resolved-typography key is a *valid element name* if it is a base element,
#: a section element, or a meta element. Used by validation (accept dynamic
#: names) and by the resolvers (iterate whatever is present).
def is_valid_element(name) -> bool:
    """True if ``name`` is a base, ``section[-kind]-title/body`` or ``meta-<key>`` element."""
    if name in BASE_ELEMENTS:
        return True
    if SECTION_ELEMENT_RE.match(name or ""):
        return True
    if META_ELEMENT_RE.match(name or ""):
        return True
    return False


def section_element_names(kind):
    """Return the (title, body) element-name pair for a section ``kind``.

    A section of kind ``verse`` reads its label style from ``section-verse-title``
    (falling back to the generic ``section-title``) and its body style from
    ``section-verse-body`` (falling back to ``section-body``). Returns the
    ordered fallback lists ``(["section-verse-title", "section-title"], [...])``.
    """
    k = (kind or "").strip().lower()
    title_chain = (["section-%s-title" % k, "section-title"] if k and k != "none"
                   else ["section-title"])
    body_chain = (["section-%s-body" % k, "section-body"] if k and k != "none"
                  else ["section-body"])
    return title_chain, body_chain


def meta_element_names(key):
    """Return the ordered fallback element-name list for a metadata ``key``.

    A metadata row for ``tempo`` reads ``meta-tempo`` then falls back to the
    generic ``metadata`` element. Keys are lower-cased/normalized for matching.
    """
    k = (key or "").strip().lower()
    return ["meta-%s" % k, "metadata"] if k else ["metadata"]

#: Complete core defaults for the base elements. ``None`` means "inherit the
#: surrounding document style" — the HTML/EPUB path emits no declaration and
#: LaTeX leaves the indirection macro at its ``\relax`` (or backend) default.
#: Keeping every base element/attr present makes the base merge total (no
#: ``KeyError`` on any cell). Dynamic ``section-*`` / ``meta-*`` elements have no
#: core default (they inherit ``section-title``/``metadata``/document style) and
#: are merged in lazily wherever the user/theme sets them.
CORE_TYPOGRAPHY: dict = {
    element: {attr: None for attr in ATTRS} for element in BASE_ELEMENTS
}

#: The user-facing config key (registered in CHUNK-0-3's manifest).
CONFIG_ATTR = "doxtr_music_typography"

#: Where the validated global merge is cached (reserved ``_resolved`` suffix so
#: the CHUNK-0-3 unknown-key guard ignores it).
RESOLVED_CONFIG_ATTR = "doxtr_music_typography_resolved"

#: ``config-inited`` priority: after 0-3 validation (~500), before the LaTeX
#: preamble injection (~700) so the resolved globals feed the preamble
#: contributor.
TYPOGRAPHY_INIT_PRIORITY = 600

#: LaTeX preamble-contributor priority. Higher than the CHUNK-2-1 backend
#: contributor (200) so the typography global macro redefinitions come *after*
#: the backend's ``\providecommand`` defaults and win. Lower than CHUNK-7-1
#: theme interop (which layers on top of these globals).
TYPOGRAPHY_PREAMBLE_PRIORITY = 400

#: A conservative CSS color/length/family sanitizer. Typography values are
#: emitted into inline ``style="..."`` / CSS rules, so we reject anything
#: carrying a ``;`` / ``{`` / ``}`` / newline that could break out of a single
#: declaration (defence-in-depth; values are author-controlled but still
#: validated). Empty after strip is treated as "unset".
_CSS_UNSAFE_RE = re.compile(r"[;{}<>\n\r]")

#: Hex color forms accepted for LaTeX ``\definecolor`` (``#rgb`` / ``#rrggbb``).
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

#: A small allow-list of xcolor built-in names usable directly as a LaTeX color
#: without ``\definecolor``. Unknown *names* (not hex) warn + fall back.
_LATEX_NAMED_COLORS = frozenset(
    {
        "black", "white", "red", "green", "blue", "cyan", "magenta", "yellow",
        "gray", "grey", "darkgray", "lightgray", "brown", "lime", "olive",
        "orange", "pink", "purple", "teal", "violet",
    }
)

#: EPUB font-size must be **relative** (``em``/``rem``/``%``) so the reflow
#: resize model holds. An absolute unit is downgraded to ``em`` (best effort)
#: with a warning at resolution time.
_RELATIVE_SIZE_RE = re.compile(r"^\s*[0-9.]+\s*(?:em|rem|%)\s*$", re.IGNORECASE)
_ABSOLUTE_SIZE_RE = re.compile(
    r"^\s*([0-9.]+)\s*(pt|px|cm|mm|in|pc)\s*$", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _is_css_safe(value) -> bool:
    """True if ``value`` is a string with no CSS-declaration-breaking chars."""
    return isinstance(value, str) and not _CSS_UNSAFE_RE.search(value)


def validate_typography(raw, warn=None) -> dict:
    """Return a cleaned ``{element: {attr: value}}`` dict.

    * Unknown element or attr keys → warn + drop (never crash).
    * Non-string / CSS-unsafe values → warn + drop.
    * Empty strings → dropped (treated as unset).

    ``warn`` is an optional ``(message: str) -> None`` callable (defaults to the
    module logger's ``warning`` when ``None``); passing an explicit sink keeps
    the helper unit-testable without Sphinx.
    """
    emit = warn if warn is not None else logger.warning
    cleaned: dict = {}
    if not isinstance(raw, dict):
        if raw:
            emit(
                "[doxtr-music] doxtr_music_typography must be a dict of "
                "{element: {attr: value}}; ignoring %r." % (raw,)
            )
        return cleaned
    for element, attrs in raw.items():
        if not is_valid_element(element):
            emit(
                "[doxtr-music] Unknown typography element %r; ignoring. Valid "
                "elements: the base %s, any ``section[-<kind>]-title`` / "
                "``section[-<kind>]-body``, or any ``meta-<key>``."
                % (element, list(BASE_ELEMENTS))
            )
            continue
        if not isinstance(attrs, dict):
            emit(
                "[doxtr-music] Typography element %r must map to a dict of "
                "attrs; ignoring %r." % (element, attrs)
            )
            continue
        for attr, value in attrs.items():
            if attr not in ATTRS:
                emit(
                    "[doxtr-music] Unknown typography attr %r on element %r; "
                    "ignoring. Valid attrs: %s." % (attr, element, list(ATTRS))
                )
                continue
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if not _is_css_safe(value):
                emit(
                    "[doxtr-music] Typography value for %s-%s is not a safe "
                    "style string; ignoring %r." % (element, attr, value)
                )
                continue
            cleaned.setdefault(element, {})[attr] = value.strip()
    return cleaned


# ---------------------------------------------------------------------------
# Global resolution (config-inited) + per-song resolution (build)
# ---------------------------------------------------------------------------

def resolve_global_typography(config, warn=None) -> dict:
    """Validate + merge core/theme/global into a complete resolved dict.

    Reads the raw ``doxtr_music_typography`` and the theme tier
    (``doxtr_music_theme_defaults_resolved['typography']``, ``{}`` until
    CHUNK-7-1) and returns ``three_tier_merge(core, theme, global)`` — a
    complete ``{element: {attr: value|None}}`` mapping.
    """
    raw_global = getattr(config, CONFIG_ATTR, {}) or {}
    global_clean = validate_typography(raw_global, warn=warn)
    theme_defaults = getattr(config, "doxtr_music_theme_defaults_resolved", {}) or {}
    theme_typo = {}
    if isinstance(theme_defaults, dict):
        theme_typo = theme_defaults.get("typography", {}) or {}
    if not isinstance(theme_typo, dict):
        theme_typo = {}
    return three_tier_merge(CORE_TYPOGRAPHY, theme_typo, global_clean)


def resolve_song_typography(resolved_global, per_song, warn=None) -> dict:
    """Layer a per-song override dict on top of the resolved global typography.

    ``per_song`` is the ``node['options']['typography']`` mapping parsed by
    CHUNK-1-4's ``_options.py`` (``{element: {attr: value}}``); it is
    re-validated here (defence-in-depth) then ``deep_update``-merged so a single
    ``:chord-color:`` overrides only that cell and every other cell inherits the
    global. Returns a complete resolved dict.
    """
    base = resolved_global if isinstance(resolved_global, dict) else CORE_TYPOGRAPHY
    per_song_clean = validate_typography(per_song or {}, warn=warn)
    return deep_update(base, per_song_clean)


def resolve_element_cell(resolved, element_chain):
    """Resolve one element's effective ``{attr: value}`` cell along a fallback chain.

    ``element_chain`` is an ordered list of element names from most-specific to
    least (e.g. ``["section-verse-title", "section-title"]`` or
    ``["meta-tempo", "metadata"]``). Attributes are filled most-specific-first;
    a less-specific element only supplies attrs the more-specific one left
    unset. Returns a plain ``{attr: value}`` dict of only the SET (non-``None``)
    attrs — ready to stamp on a node or render. Absent elements contribute
    nothing (dynamic ``section-*`` / ``meta-*`` keys need no core default).
    """
    if not isinstance(resolved, dict):
        return {}
    out: dict = {}
    for element in element_chain:
        cell = resolved.get(element)
        if not isinstance(cell, dict):
            continue
        for attr in ATTRS:
            if attr in out:
                continue
            value = cell.get(attr)
            if value is not None and value != "":
                out[attr] = value
    return out


def stamp_typography(song_node, resolved_global, warn=None, config=None) -> dict:
    """Compute + stamp per-element typography onto a SongNode's child nodes.

    Resolves the per-song typography (global + this song's ``options``), then
    walks the tree stamping the reserved plain-data ``typography`` attr onto the
    styleable child nodes so each visitor is node-local (no ancestor walk):

    * :class:`ChordNode` (non-inline) → ``chord`` element cell.
    * :class:`ChordNode` (``inline_role``) → ``chord`` (prose chord reuses chord
      typography).
    * :class:`LyricNode` → ``lyrics`` element cell.
    * :class:`RomanNode` → ``roman`` element cell.
    * :class:`KeyNode` → ``title`` cell (keys reuse the title styling target,
      matching the LaTeX ``\\dmkey`` mapping).

    ``config`` (when given) enables ``dd:`` color-expression resolution against
    the active doxtr-pdf-theme-core palette: any ``color``/``background`` value
    like ``dd:primary`` is resolved to a hex color; if a ``dd:`` value is used
    without the theme installed, an actionable error is raised.

    Title + metadata are song-level (rendered by the SongNode/section visitors)
    and read the resolved dict off the SongNode's stamped ``typography`` attr.
    Returns the resolved dict (also stored on ``song_node['typography']``).
    """
    from . import nodes as _nodes

    # The per-song delta still carries raw ``dd:``/hex values; resolve those
    # (``dd:`` + dark-mode transform) on the DELTA only, then merge onto the
    # already-resolved global. Re-transforming the whole merged dict would
    # double-invert the global's already-dark-resolved static colors, so we
    # transform the delta and the global separately (each exactly once).
    per_song = (song_node.get("options", {}) or {}).get("typography") or {}
    if config is not None and per_song:
        from .dd_resolve import resolve_dd_in_typography

        per_song = resolve_dd_in_typography(dict(per_song), config)
    resolved = resolve_song_typography(resolved_global, per_song, warn=warn)
    # The lyrics body-text default (dark mode) is a whole-song concern, not part
    # of the global cache or the per-song delta; apply it here once.
    if config is not None:
        from .dd_resolve import contrast_fix_typography, fill_lyrics_body_color

        resolved = fill_lyrics_body_color(resolved, config)
        # Make each element's color readable on its OWN background (e.g. a
        # section-title color on a section-title background), independent of the
        # page — using the theme's contrast helper.
        resolved = contrast_fix_typography(resolved, config)
    song_node["typography"] = resolved

    def _stamp(node, element):
        cell = resolved.get(element)
        if cell:
            # Store only set (non-None) attrs as plain data.
            plain = {k: v for k, v in cell.items() if v is not None}
            if plain:
                node["typography"] = plain

    for node in song_node.findall(_nodes.ChordNode):
        _stamp(node, "chord")
    for node in song_node.findall(_nodes.LyricNode):
        _stamp(node, "lyrics")
    for node in song_node.findall(_nodes.RomanNode):
        _stamp(node, "roman")
    for node in song_node.findall(_nodes.KeyNode):
        _stamp(node, "title")
    # Section-kind styling: each SectionNode carries the resolved title/body
    # cells (per-kind element over the generic ``section-title``/``-body``), so
    # the section visitors are node-local. Stored as plain-data attrs.
    from .dd_resolve import ensure_contrast

    for node in song_node.findall(_nodes.SectionNode):
        title_chain, body_chain = section_element_names(node.get("kind"))
        title_cell = _contrast_fix_cell(
            resolve_element_cell(resolved, title_chain), config
        )
        body_cell = _contrast_fix_cell(
            resolve_element_cell(resolved, body_chain), config
        )
        if title_cell:
            node["typography_title"] = title_cell
        if body_cell:
            node["typography_body"] = body_cell
            # Cascade the section-body cell onto the CHORD + LYRIC words in this
            # section so a section-body ``background`` acts as a per-section
            # highlight (a marker effect) in all three formats. The node's own
            # stamped typography wins per-attr; the section body only FILLS
            # attrs it did not set. Then make each word's color readable on the
            # highlight background (dark text on a light marker, or vice versa).
            body_bg = body_cell.get("background")
            for word in list(node.findall(_nodes.LyricNode)) + list(
                node.findall(_nodes.ChordNode)
            ):
                existing = dict(word.get("typography") or {})
                for attr, value in body_cell.items():
                    existing.setdefault(attr, value)
                bg = existing.get("background") or body_bg
                if bg and existing.get("color"):
                    existing["color"] = ensure_contrast(
                        existing["color"], bg, config
                    )
                if existing:
                    word["typography"] = existing
    return resolved


def _contrast_fix_cell(cell, config):
    """Return ``cell`` with its ``color`` made readable on its own ``background``."""
    if not cell or not (cell.get("color") and cell.get("background")):
        return cell
    from .dd_resolve import ensure_contrast

    fixed = ensure_contrast(cell["color"], cell["background"], config)
    if fixed == cell["color"]:
        return cell
    out = dict(cell)
    out["color"] = fixed
    return out


# ---------------------------------------------------------------------------
# HTML / EPUB emission helpers
# ---------------------------------------------------------------------------

def css_declarations(cell, *, relative_size=False, warn=None) -> str:
    """Render an element's resolved ``{attr: value}`` cell to a CSS style string.

    ``cell`` maps ``font``/``size``/``color`` → value (any subset). Produces an
    inline-``style`` fragment like ``font-family:serif;color:#c00``. When
    ``relative_size`` is True (EPUB), an absolute ``size`` unit is downgraded to
    a relative ``em`` (best effort) + a warning so the reflow model holds.
    Returns ``""`` when nothing is set.
    """
    if not cell:
        return ""
    emit = warn if warn is not None else logger.warning
    decls = []
    font = cell.get("font")
    if font:
        decls.append("font-family:%s" % font)
    size = cell.get("size")
    if size:
        decls.append("font-size:%s" % _css_size(size, relative_size, emit))
    color = cell.get("color")
    if color:
        decls.append("color:%s" % color)
    background = cell.get("background")
    if background:
        decls.append("background-color:%s" % background)
    return ";".join(decls)


def _css_size(size, relative_size, emit) -> str:
    """Return a CSS font-size, downgrading absolute→em for EPUB when needed."""
    if not relative_size:
        return size
    if _RELATIVE_SIZE_RE.match(size):
        return size
    m = _ABSOLUTE_SIZE_RE.match(size)
    if m:
        # Best-effort downgrade: treat pt roughly against a 12pt base.
        try:
            value = float(m.group(1))
        except ValueError:  # pragma: no cover - regex guarantees a number
            value = 12.0
        unit = m.group(2).lower()
        base = {"pt": 12.0, "px": 16.0, "cm": 1.06, "mm": 10.6,
                "in": 0.166, "pc": 1.0}.get(unit, 12.0)
        em = round(value / base, 3) if base else 1.0
        emit(
            "[doxtr-music] EPUB font-size %r is absolute; downgraded to %sem "
            "for reflow-safety." % (size, em)
        )
        return "%sem" % em
    # Unknown/odd form: pass through (validate_typography already sanitized it).
    return size


# ---------------------------------------------------------------------------
# LaTeX color normalization
# ---------------------------------------------------------------------------

def normalize_latex_color(value, *, define_name, warn=None):
    """Normalize a color value for LaTeX use.

    Returns ``(color_expr, definecolor_line)`` where ``color_expr`` is what to
    pass to ``\\color{...}`` and ``definecolor_line`` is a ``\\definecolor``
    line to emit (or ``""`` when a named color is used directly).

    * ``#rgb`` / ``#rrggbb`` → ``\\definecolor{<define_name>}{HTML}{RRGGBB}`` and
      ``color_expr = define_name``.
    * A known xcolor name → used directly (no ``\\definecolor``).
    * Anything else → warn + return ``(None, "")`` so the caller falls back to
      the inherited color (the write-only build cannot catch a bad
      ``\\definecolor`` at Python time, so we validate here).
    """
    emit = warn if warn is not None else logger.warning
    if not isinstance(value, str) or not value.strip():
        return None, ""
    value = value.strip()
    if _HEX_COLOR_RE.match(value):
        hexpart = value[1:]
        if len(hexpart) == 3:
            hexpart = "".join(ch * 2 for ch in hexpart)
        return define_name, "\\definecolor{%s}{HTML}{%s}" % (
            define_name, hexpart.upper()
        )
    if value.lower() in _LATEX_NAMED_COLORS:
        return value.lower(), ""
    emit(
        "[doxtr-music] LaTeX typography color %r is neither a #hex nor a known "
        "xcolor name; falling back to the inherited color." % value
    )
    return None, ""


# ---------------------------------------------------------------------------
# Global HTML/EPUB style block (scoped to element classes)
# ---------------------------------------------------------------------------

#: Maps each styleable element to the CSS selector its GLOBAL rule targets.
#: Per-song overrides ride inline ``style`` (emitted by the visitors); GLOBAL
#: typography rides these class rules so shared styling costs one injected
#: ``<style>`` block per page.
_HTML_ELEMENT_SELECTORS = {
    "title": ".doxtr-song-title",
    "metadata": ".doxtr-section-label",
    "roman": ".doxtr-roman",
    "chord": ".doxtr-chord, .doxtr-chord-inline",
    "lyrics": ".doxtr-lyric",
}

#: EPUB uses the two-row ``<pre>`` model: lyrics live in ``.doxtr-lyricrow``,
#: chords in ``.doxtr-chordrow``; title/metadata/roman reuse the shared classes.
_EPUB_ELEMENT_SELECTORS = {
    "title": ".doxtr-song-epub .doxtr-song-title",
    "metadata": ".doxtr-song-epub .doxtr-section-label",
    "roman": ".doxtr-roman",
    "chord": ".doxtr-line-epub .doxtr-chordrow, .doxtr-chord-inline",
    "lyrics": ".doxtr-line-epub .doxtr-lyricrow",
}


def _dynamic_selectors(resolved, *, epub):
    """Build CSS selectors for globally-set ``section-*`` / ``meta-*`` elements.

    Returns ``{element_name: selector}`` for every dynamic element present in
    ``resolved`` (section title/body per kind, metadata per key), so the global
    ``<style>`` block can target them. The base elements are handled by the
    static selector maps. Section/metadata classes are emitted by the visitors
    (``.doxtr-section-<kind> > .doxtr-section-label`` etc.).
    """
    prefix = ".doxtr-song-epub " if epub else ""
    sel = {}
    for name in resolved:
        m = SECTION_ELEMENT_RE.match(name)
        if m:
            kind = m.group("kind")
            part = m.group("part")
            base = prefix + (".doxtr-section-%s" % kind if kind else ".doxtr-section")
            if part == "title":
                sel[name] = "%s > .doxtr-section-label" % base
            else:  # body
                sel[name] = "%s > .doxtr-section-body" % base
            continue
        m = META_ELEMENT_RE.match(name)
        if m:
            key = m.group("key")
            sel[name] = "%s.doxtr-song-meta-%s" % (prefix, key)
    return sel


def global_typography_style_block(resolved_global, *, epub=False, warn=None) -> str:
    """Render the GLOBAL typography as a ``<style>`` block, or ``""``.

    Only elements with at least one non-``None`` global attr emit a rule.
    Covers the base elements plus any globally-set dynamic ``section-*`` /
    ``meta-*`` elements (and the generic ``metadata`` default, which targets
    every ``.doxtr-song-meta`` row). ``epub=True`` selects the EPUB selectors +
    relative-size downgrade. Returns ``""`` when nothing is globally set.
    """
    if not resolved_global:
        return ""
    base_selectors = _EPUB_ELEMENT_SELECTORS if epub else _HTML_ELEMENT_SELECTORS
    prefix = ".doxtr-song-epub " if epub else ""
    # The generic ``metadata`` element styles every metadata row + the default.
    selectors = dict(base_selectors)
    selectors["metadata"] = "%s.doxtr-song-meta" % prefix
    selectors.update(_dynamic_selectors(resolved_global, epub=epub))
    # Also style the generic section title/body when set globally.
    selectors.setdefault("section-title", "%s.doxtr-section > .doxtr-section-label" % prefix)
    selectors.setdefault("section-body", "%s.doxtr-section > .doxtr-section-body" % prefix)
    rules = []
    for element, cell in resolved_global.items():
        cell = cell or {}
        decls = css_declarations(cell, relative_size=epub, warn=warn)
        if not decls:
            continue
        selector = selectors.get(element)
        if not selector:
            continue
        rules.append("%s { %s; }" % (selector, decls))
    if not rules:
        return ""
    return (
        '<style class="doxtr-music-typography">\n'
        + "\n".join(rules)
        + "\n</style>\n"
    )


def add_global_typography_style(app, pagename, templatename, context, doctree):
    """``html-page-context`` handler: inject the GLOBAL typography style block.

    Works for HTML and EPUB (EPUB subclasses the HTML builder). The builder is
    discriminated by *name* (``epub*`` -> EPUB selectors + relative sizes),
    matching the CHUNK-1-2 ``_resolve_format`` seam. The block is appended to
    ``context['metatags']`` (a string) so it lands in every page ``<head>``
    without needing a static asset (dynamic content can't be a shipped file).
    """
    config = getattr(app, "config", None)
    if config is None:
        return
    resolved_global = getattr(config, RESOLVED_CONFIG_ATTR, None)
    if resolved_global is None:
        resolved_global = resolve_global_typography(config)
    is_epub = getattr(app.builder, "name", "").startswith("epub")
    block = global_typography_style_block(resolved_global, epub=is_epub)
    if block:
        context["metatags"] = context.get("metatags", "") + block


# ---------------------------------------------------------------------------
# LaTeX global typography: a preamble contributor setting indirection macros
# ---------------------------------------------------------------------------

#: Maps a typography element to its LaTeX indirection-macro *stem* (the preamble
#: defines ``\dm<stem>color`` / ``\dm<stem>font`` / ``\dm<stem>size``).
_LATEX_ELEMENT_STEMS = {
    "title": "title",
    "metadata": "meta",
    "roman": "roman",
    "chord": "chord",
    "lyrics": "lyric",
}

#: Generic CSS font-family -> LaTeX font-switch mapping. A value NOT in this map
#: (and not a bare generic) is treated as a NAMED font family (e.g. ``Lato``,
#: ``Anton``): under a fontspec engine (lualatex/xelatex — what the theme uses)
#: it is loaded with ``\newfontfamily`` and switched to; under pdflatex fontspec
#: is absent, so the switch degrades to a no-op (the hook is still emitted).
_LATEX_FONT_SWITCH = {
    "serif": "\\rmfamily",
    "sans-serif": "\\sffamily",
    "sans": "\\sffamily",
    "monospace": "\\ttfamily",
    "mono": "\\ttfamily",
}

#: A CSS generic family name (never treated as a named font face).
_CSS_GENERIC_FAMILIES = frozenset(_LATEX_FONT_SWITCH) | {"cursive", "fantasy", "system-ui"}


def _is_named_font(font) -> bool:
    """True when ``font`` is a specific font family (not a CSS generic)."""
    if not isinstance(font, str):
        return False
    f = font.strip()
    if not f:
        return False
    return f.lower() not in _CSS_GENERIC_FAMILIES


def _font_face_command(font) -> str:
    r"""Return the ``\dmfontface<Token>`` control-sequence name for a named font.

    The token is the font name reduced to letters so it is a valid LaTeX control
    sequence (``Sirin Stencil`` -> ``\dmfontfaceSirinStencil``). One face macro
    per distinct font name is declared once in the preamble.
    """
    token = "".join(ch for ch in str(font) if ch.isalpha()) or "X"
    return "\\dmfontface" + token


def collect_named_fonts(resolved) -> list:
    """Return the sorted unique NAMED font families used anywhere in ``resolved``.

    Scans every element cell's ``font`` attr (base + dynamic section/meta
    elements) and returns the named (non-generic) families, so the preamble can
    declare a ``\newfontfamily`` face for each.
    """
    names = set()
    if isinstance(resolved, dict):
        for cell in resolved.values():
            if isinstance(cell, dict):
                font = cell.get("font")
                if _is_named_font(font):
                    names.add(font.strip())
    return sorted(names)

#: Best-effort relative-size -> LaTeX size-switch mapping.
_LATEX_SIZE_SWITCH = {
    "0.75em": "\\footnotesize",
    "0.8em": "\\small",
    "0.85em": "\\small",
    "0.9em": "\\small",
    "1em": "\\normalsize",
    "1.1em": "\\large",
    "1.2em": "\\large",
    "1.5em": "\\Large",
    "2em": "\\huge",
}


def _latex_size_switch(size):
    r"""Best-effort LaTeX size switch for a CSS-ish size value.

    We cannot faithfully map arbitrary CSS sizes to LaTeX size commands, so we
    map a few relative hints; otherwise emit ``\relax`` (hook present, no-op).
    """
    return _LATEX_SIZE_SWITCH.get((size or "").strip().lower(), "\\relax")


def _redef(scope, macro, body):
    r"""Render a redefinition line for the arity-0 indirection ``macro``.

    ``scope="global"`` -> ``\renewcommand{\dmXcolor}{...}`` (preamble, once);
    ``scope="song"`` -> ``\def\dmXcolor{...}`` (per-song scoped ``\begingroup``
    group, only overridden attrs). Never changes any ``\dm...`` macro arity.
    """
    if scope == "global":
        return "\\renewcommand{%s}{%s}" % (macro, body)
    return "\\def%s{%s}" % (macro, body)


def _latex_typography_lines(resolved, *, scope):
    r"""Return redefinition lines for the set attrs in ``resolved``.

    Only non-``None`` attrs emit a line, so a per-song group ``\def``s ONLY the
    overridden macros and inherits the global for the rest. Colors are
    normalized/validated at Python time; an invalid color warns + is skipped.
    """
    lines = []
    for element in ELEMENTS:
        stem = _LATEX_ELEMENT_STEMS[element]
        cell = (resolved or {}).get(element) or {}
        # NOTE: ``background`` on a base inline element (chord/lyric) is not
        # emitted here — the flowing ``\ooalign`` chord/lyric model makes a
        # per-glyph ``\colorbox`` fragile across line breaks. Base-element
        # backgrounds render in HTML/EPUB (CSS ``background-color``); LaTeX
        # backgrounds apply to the BLOCK elements (title/metadata/section-title)
        # via :func:`latex_cell_wrap` in the visitors. Font/size/color below.
        color = cell.get("color")
        if color:
            expr, defline = normalize_latex_color(
                color, define_name="dm@%scolor" % stem
            )
            if expr is not None:
                if defline:
                    lines.append(defline)
                lines.append(
                    _redef(scope, "\\dm%scolor" % stem, "\\color{%s}" % expr)
                )
        font = cell.get("font")
        if font:
            switch = _latex_font_body(font)
            lines.append(_redef(scope, "\\dm%sfont" % stem, switch))
        size = cell.get("size")
        if size:
            lines.append(
                _redef(scope, "\\dm%ssize" % stem, _latex_size_switch(size))
            )
    return lines


# ---------------------------------------------------------------------------
# Inline LaTeX cell styling (for section labels/bodies + metadata rows)
# ---------------------------------------------------------------------------
#
# The dynamic ``section-*`` / ``meta-*`` elements are NOT backed by preamble
# indirection macros (there is an open-ended set of section kinds / metadata
# keys). Instead the section/metadata LaTeX visitors wrap their text in an
# inline styling group built from the resolved cell. This keeps the base-5
# macro-indirection contract intact while supporting arbitrary section kinds
# and metadata keys.


def latex_font_switch(font):
    r"""LaTeX font switch for a CSS-ish font-family (or ``""`` when unset).

    Generic families map to ``\rmfamily``/``\sffamily``/``\ttfamily``; a named
    family maps to its ``\dmfontface<Token>`` face command (declared in the
    preamble, a no-op under pdflatex). Returns ``""`` for an empty value.
    """
    if not isinstance(font, str) or not font.strip():
        return ""
    body = _latex_font_body(font)
    return "" if body == "\\relax" else body


def _latex_font_body(font):
    r"""Return the switch body for a font: a generic switch or a named face.

    A generic family -> its ``\rmfamily``-style switch; a named family -> its
    ``\dmfontface<Token>`` command. Never ``\relax`` for a named font (the face
    command is a no-op itself under pdflatex, so the hook stays present).
    """
    f = (font or "").strip()
    generic = _LATEX_FONT_SWITCH.get(f.lower())
    if generic:
        return generic
    if _is_named_font(f):
        return _font_face_command(f)
    return "\\relax"


def latex_size_switch(size):
    r"""Best-effort LaTeX size switch for a CSS-ish size (or ``""`` when unmapped)."""
    switch = _latex_size_switch(size)
    return "" if switch == "\\relax" else switch


def latex_cell_wrap(text, cell, *, define_name, warn=None):
    r"""Wrap ``text`` in inline TeX applying the resolved ``cell`` style.

    ``cell`` maps ``font``/``size``/``color``/``background`` -> value (any
    subset). Font/size become inline switches; color becomes ``\textcolor`` (or
    a ``\definecolor`` + ``\textcolor`` for a hex value); background becomes a
    ``\colorbox``. Returns ``(prefix, wrapped_text)`` where ``prefix`` is any
    ``\definecolor`` lines that must precede the text (emit once, before the
    wrapped text) and ``wrapped_text`` is the fully-wrapped, already-escaped
    ``text``. When the cell is empty the text is returned unchanged with an
    empty prefix. ``text`` MUST already be esc_latex-escaped by the caller.
    """
    if not cell:
        return "", text
    prefix_lines = []
    inner = text
    # Background as an outermost \colorbox (so it spans the whole run).
    background = cell.get("background")
    # Foreground color.
    color = cell.get("color")
    # Font + size switches go innermost (inside the color/box).
    switches = ""
    fs = latex_font_switch(cell.get("font"))
    if fs:
        switches += fs
    ss = latex_size_switch(cell.get("size"))
    if ss:
        switches += ss
    if switches:
        inner = "{%s %s}" % (switches, inner)
    if color:
        expr, defline = normalize_latex_color(
            color, define_name="%sfg" % define_name, warn=warn
        )
        if expr is not None:
            if defline:
                prefix_lines.append(defline)
            inner = "\\textcolor{%s}{%s}" % (expr, inner)
    if background:
        expr, defline = normalize_latex_color(
            background, define_name="%sbg" % define_name, warn=warn
        )
        if expr is not None:
            if defline:
                prefix_lines.append(defline)
            inner = "\\colorbox{%s}{%s}" % (expr, inner)
    prefix = ("\n".join(prefix_lines) + "\n") if prefix_lines else ""
    return prefix, inner


def _fontface_declarations(resolved) -> str:
    r"""Return ``\newfontfamily`` declarations for every named font in ``resolved``.

    One ``\newfontfamily\dmfontface<Token>{<FontName>}`` per distinct named
    font. Guarded by ``\@ifpackageloaded{fontspec}`` so it is a no-op under
    pdflatex (no fontspec); under the theme's lualatex/xelatex engine the fonts
    load by family name from the system (fontconfig). Also ``\providecommand``
    each face as ``\relax`` OUTSIDE the guard so the ``\dm<stem>font`` switch
    referencing it never errors when fontspec is absent.
    """
    fonts = collect_named_fonts(resolved)
    if not fonts:
        return ""
    lines = ["% doxtr-music named font faces (fontspec engine only)"]
    lines.append("\\makeatletter")
    lines.append("\\@ifpackageloaded{fontspec}{%")
    for font in fonts:
        face = _font_face_command(font)
        # fontspec present (lualatex/xelatex): load the real face by family name.
        lines.append("  \\newfontfamily%s{%s}%%" % (face, font))
    lines.append("}{%")
    for font in fonts:
        face = _font_face_command(font)
        # No fontspec (pdflatex): define the face as a no-op so the switch works.
        lines.append("  \\providecommand{%s}{\\relax}%%" % face)
    lines.append("}%")
    lines.append("\\makeatother")
    return "\n".join(lines)


def latex_typography_contributor(config):
    r"""Preamble contributor: font faces + GLOBAL typography indirection macros.

    Declares a ``\newfontfamily`` face for every named font used (guarded by
    fontspec presence), then for each globally-set element attr
    ``\renewcommand``s the matching indirection macro (``\dm<stem>color`` /
    ``\dm<stem>font`` / ``\dm<stem>size``). Emits nothing when no global
    typography is set. Registered at :data:`TYPOGRAPHY_PREAMBLE_PRIORITY` so it
    lands after the backend defaults and wins.
    """
    resolved_global = getattr(config, RESOLVED_CONFIG_ATTR, None)
    if resolved_global is None:
        resolved_global = resolve_global_typography(config)
    faces = _fontface_declarations(resolved_global)
    lines = _latex_typography_lines(resolved_global, scope="global")
    if not faces and not lines:
        return ""
    parts = []
    if faces:
        parts.append(faces)
    if lines:
        parts.append("% doxtr-music global typography\n" + "\n".join(lines))
    return "\n".join(parts)


def song_typography_latex_group(per_song_override, warn=None):
    r"""Return ``(open, close)`` TeX for a per-song scoped typography group.

    ``open`` = ``\begingroup`` + ``\def``s of ONLY the per-song-overridden
    attr-macros (inheriting global for the rest); ``close`` = ``\endgroup``.
    When a song sets no typography, ``open`` is just ``\begingroup`` (still
    balanced). The SongNode LaTeX visitor wraps the song body in this group --
    the LaTeX analog of HTML inline style -- without changing ``\dm...`` arity.

    ``per_song_override`` is the song's OWN override delta (its
    ``options['typography']``), re-validated here, so only what the song changed
    is re-``\def``'d.
    """
    clean = validate_typography(per_song_override or {}, warn=warn)
    lines = _latex_typography_lines(clean, scope="song")
    open_tex = "\\begingroup% doxtr-music song typography\n"
    if lines:
        open_tex += "\n".join(lines) + "\n"
    return open_tex, "\\endgroup% doxtr-music song typography\n"


def register_latex_typography_contributor():
    """Register the global typography preamble contributor (idempotent).

    Called from :func:`doxtr_music.setup`. Uses the CHUNK-2-1 seam
    (:func:`doxtr_music.builders.latex.register_preamble_contributor`) at
    :data:`TYPOGRAPHY_PREAMBLE_PRIORITY`; never mutates ``latex_elements``
    directly. Idempotent across repeated ``setup()`` calls in one process.
    """
    from .builders import latex as _latex

    _latex._LATEX_PREAMBLE_CONTRIBUTORS[:] = [
        entry
        for entry in _latex._LATEX_PREAMBLE_CONTRIBUTORS
        if entry[1] is not latex_typography_contributor
    ]
    _latex.register_preamble_contributor(
        TYPOGRAPHY_PREAMBLE_PRIORITY, latex_typography_contributor
    )


# ---------------------------------------------------------------------------
# config-inited handler
# ---------------------------------------------------------------------------

def on_config_inited_typography(app, config):
    """Validate + cache the global typography at ``config-inited`` (~600).

    Runs after 0-3 validation (~500), before the LaTeX preamble injection
    (~700), so the LaTeX preamble contributor and the HTML/EPUB global-CSS
    injection read a single resolved global dict. ``dd:``/dark-mode color
    transforms are (re)applied here and AGAIN at >900
    (:func:`on_config_inited_typography_late`) once the theme has resolved dark
    mode — this early pass keeps a valid cache for any consumer that runs before
    900, the late pass makes it dark-correct.
    """
    resolved = resolve_global_typography(config)
    from .dd_resolve import contrast_fix_typography, resolve_dd_in_typography

    resolved = resolve_dd_in_typography(resolved, config)
    resolved = contrast_fix_typography(resolved, config)
    setattr(config, RESOLVED_CONFIG_ATTR, resolved)


#: Priority for the LATE (>900) global-typography re-resolution, so it runs
#: after doxtr-pdf-theme-core resolves dark mode (its config-inited @900) and
#: BEFORE the LaTeX preamble injection (920), so the LaTeX global preamble bakes
#: dark-correct ``dd:``/inverted colors and the HTML/EPUB global ``<style>`` is
#: dark-correct too.
TYPOGRAPHY_LATE_INIT_PRIORITY = 910


def on_config_inited_typography_late(app, config):
    """Re-resolve the global typography cache at >900 (dark-mode correct).

    Recomputes the resolved global from scratch and re-applies the ``dd:`` +
    dark-mode color transform now that the theme has resolved dark mode, so the
    cached dict (read by the HTML/EPUB global ``<style>`` injector) uses the
    dark palette + dark body-text color in a dark build.
    """
    resolved = resolve_global_typography(config)
    from .dd_resolve import (
        contrast_fix_typography,
        fill_lyrics_body_color,
        resolve_dd_in_typography,
    )

    resolved = resolve_dd_in_typography(resolved, config)
    resolved = fill_lyrics_body_color(resolved, config)
    resolved = contrast_fix_typography(resolved, config)
    setattr(config, RESOLVED_CONFIG_ATTR, resolved)
