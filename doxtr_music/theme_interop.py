"""Soft ``doxtr-pdf-theme-core`` interop (CHUNK-7-1).

When ``doxtr-pdf-theme-core`` is the active Sphinx theme, doxtr-music picks up
its font/palette so songs visually match the surrounding themed document. This
fills the previously-inert **``theme`` tier** of
:func:`doxtr_music.config.three_tier_merge`, contributes a LaTeX preamble block
(incl. RTL/bidi), and feeds the theme's resolved page/background color into the
CHUNK-4-3 contrast check.

Soft-dependency discipline (LOCKED — CHUNK-0-3 / CHUNK-7-1)
----------------------------------------------------------

* **Presence is a config-attribute read, never an import.** The >900 handler
  gates on ``getattr(config, "doxtr_theme_defaults", {})`` truthiness — the
  accessor CHUNK-0-3 locked. This correctly reflects "theme-core is the active
  theme for this build and has resolved its palette", unlike ``find_spec`` (which
  only detects *installed*). No top-level import of ``doxtr_pdf_theme_core``
  anywhere.
* **Off-switch:** when ``config.doxtr_music_theme_interop`` is falsy the handler
  early-returns, identical to the theme being absent.
* **Absent / interop off / empty →** the ``theme`` tier stays ``{}``, the
  contrast background stays ``#ffffff``, no preamble block, no bidi — output is
  byte-for-byte identical to pre-7-1.
* **Duck-typed, defensive pickup + warn-once.** The theme palette is read
  best-effort from ``doxtr_theme_defaults`` (whatever shape theme-core populates
  it with); a missing/renamed sub-key or version mismatch warns **once per
  process** (module sentinel) and falls back to ``{}``. Never crash, never
  hard-pin a theme-core version.

Conservative theme→typography mapping (LOCKED)
----------------------------------------------

The theme provides a *small palette*, not per-element styling. Map only where the
intent is unambiguous and emit **only** those keys so unmapped elements fall
through to core defaults (never broadcast one palette color across all elements):

* theme font family → the **lyric** element font (a song's body text);
* theme base text color → **lyric** color;
* theme accent/link color → **chord** color;
* section / roman / metadata elements: **unmapped** → core defaults show through.
"""

from __future__ import annotations

from sphinx.util import logging

logger = logging.getLogger(__name__)

__all__ = [
    "THEME_INTEROP_INIT_PRIORITY",
    "RESOLVED_THEME_ATTR",
    "on_config_inited_theme_interop",
    "map_theme_to_typography",
    "resolve_theme_background",
    "register_theme_interop",
]

#: ``config-inited`` priority for the theme-interop handler. Strictly greater
#: than theme-core's ~900 resolution so the theme palette is populated when we
#: read it (ascending priority = later).
THEME_INTEROP_INIT_PRIORITY = 950

#: Where the mapped theme styling dict is stored (reserved ``_resolved`` suffix
#: so it is excluded from the CHUNK-0-3 typo guard). CHUNK-4-1's merge reads it.
RESOLVED_THEME_ATTR = "doxtr_music_theme_defaults_resolved"

#: Where the resolved effective background color is stored for the CHUNK-4-3
#: contrast feed (HTML + EPUB). ``_resolved`` suffix → typo-guard-excluded.
RESOLVED_BACKGROUND_ATTR = "doxtr_music_theme_background_resolved"

#: Sentinel in the LaTeX preamble marking the theme block already patched in
#: (idempotency guard for autobuild reruns).
_LATEX_THEME_SENTINEL = "% doxtr-music theme interop v1"

#: Module-level warn-once sentinel (per process, not per doc).
_warned_once = False


def _warn_once(message: str) -> None:
    """Emit ``message`` as a warning at most once per process."""
    global _warned_once
    if _warned_once:
        return
    _warned_once = True
    logger.warning("[doxtr-music] %s", message)


# ---------------------------------------------------------------------------
# Theme palette extraction (duck-typed, defensive)
# ---------------------------------------------------------------------------

def _theme_defaults(config) -> dict:
    """Return theme-core's raw ``doxtr_theme_defaults`` (config-attr read, never import)."""
    raw = getattr(config, "doxtr_theme_defaults", {})
    return raw if isinstance(raw, dict) else {}


def _semantic_palette(theme_defaults: dict) -> dict:
    """Best-effort extract the ``semantic_palette`` sub-dict (config-attr read).

    Read from ``doxtr_theme_defaults['semantic_palette']`` — the config attribute
    theme-core resolves its palette overrides into. Per the LOCKED soft-
    dependency contract this module NEVER imports doxtr-pdf-theme-core; it only
    reads the config attribute the theme populates. A build that wants the
    theme's semantic colors surfaced to songs sets them here (see the docs).
    """
    palette = theme_defaults.get("semantic_palette", {})
    return palette if isinstance(palette, dict) else {}


def _theme_font_family(theme_defaults: dict):
    """Best-effort theme font family (``globals.light.main_font`` / ``globals.main_font``)."""
    globals_ = theme_defaults.get("globals", {})
    if not isinstance(globals_, dict):
        return None
    light = globals_.get("light", {})
    if isinstance(light, dict) and light.get("main_font"):
        return light["main_font"]
    if globals_.get("main_font"):
        return globals_["main_font"]
    return None


def map_theme_to_typography(theme_defaults: dict) -> dict:
    """Map theme-core's semantic palette to a typography tier dict (conservative).

    Emits only unambiguously-intended keys so core defaults show through (never
    a broadcast). Supports both the doxtr-pdf-theme-core semantic keys
    (``primary``/``secondary``/``info``/``page``/…) and the generic
    ``accent``/``text``/``heading``/``panel`` names. Mapping:

    * **lyrics** color ← theme body/text color (generic ``text``/``body``);
      lyrics **font** ← theme body font;
    * **chord** color ← theme ``secondary``/``info``/``accent`` (a distinct
      accent color), else the theme ``primary`` brand color;
    * **title** color ← theme ``primary`` brand color (or a distinct generic
      ``heading``); only set when it differs from the chord color so a
      single-color theme does not broadcast to every element;
    * **section-title** background ← a distinct panel/surface color when the
      theme exposes one (never the page background).

    Returns ``{}`` when nothing maps. Defensive: any structural surprise → the
    key is simply omitted (with a warn-once note upstream).
    """
    palette = _semantic_palette(theme_defaults)
    result: dict = {}

    font = _theme_font_family(theme_defaults)
    text_color = palette.get("text") or palette.get("body") or palette.get("foreground")
    # Chord accent: a distinct accent (generic) or the theme's secondary/info.
    accent = (
        palette.get("accent") or palette.get("link")
        or palette.get("secondary") or palette.get("info")
    )
    # Title/brand: a distinct heading (generic) or the theme's primary brand.
    brand = palette.get("heading") or palette.get("title") or palette.get("primary")
    panel = palette.get("panel") or palette.get("surface") or palette.get("muted")

    lyric: dict = {}
    if isinstance(font, str) and font.strip():
        lyric["font"] = font.strip()
    if isinstance(text_color, str) and text_color.strip():
        lyric["color"] = text_color.strip()
    if lyric:
        result["lyrics"] = lyric

    chord_color = accent.strip() if isinstance(accent, str) and accent.strip() else None
    # Fall back to the brand color for chords only if there is no distinct accent.
    if chord_color is None and isinstance(brand, str) and brand.strip():
        chord_color = brand.strip()
    if chord_color:
        result["chord"] = {"color": chord_color}

    if isinstance(brand, str) and brand.strip():
        # Title uses the brand color; only set when it is distinct from the
        # chord color (so a single-color theme does not paint everything).
        if brand.strip() != chord_color:
            result["title"] = {"color": brand.strip()}

    if isinstance(panel, str) and panel.strip():
        result["section-title"] = {"background": panel.strip()}

    return result


def resolve_theme_background(theme_defaults: dict):
    """Return the theme's page/background color, or ``None`` when unset.

    Reads ``semantic_palette['page']`` (theme-core's page color) with a fallback
    to the legacy top-level ``page_background`` key. ``None`` → the CHUNK-4-3
    contrast default (``#ffffff``) stands.
    """
    palette = _semantic_palette(theme_defaults)
    page = palette.get("page") or theme_defaults.get("page_background")
    if isinstance(page, str) and page.strip():
        return page.strip()
    return None


# ---------------------------------------------------------------------------
# config-inited handler (>900) — theme tier + background + LaTeX patch
# ---------------------------------------------------------------------------

def on_config_inited_theme_interop(app, config):
    """``config-inited`` handler (priority >900): resolve + wire the theme tier.

    Idempotent (recompute + overwrite on autobuild reruns). Early-returns to the
    "inactive" state — resolved theme ``{}``, background ``None`` — when the
    theme is absent (empty ``doxtr_theme_defaults``) or the
    ``doxtr_music_theme_interop`` off-switch is falsy. Never imports theme-core.
    """
    # Off-switch (CHUNK-0-3-owned toggle) → identical to inactive.
    if not getattr(config, "doxtr_music_theme_interop", True):
        setattr(config, RESOLVED_THEME_ATTR, {})
        setattr(config, RESOLVED_BACKGROUND_ATTR, None)
        return

    theme_defaults = _theme_defaults(config)
    if not theme_defaults:
        # Theme inactive → inert tier, default background (byte-identical output).
        setattr(config, RESOLVED_THEME_ATTR, {})
        setattr(config, RESOLVED_BACKGROUND_ATTR, None)
        return

    try:
        mapped = map_theme_to_typography(theme_defaults)
        background = resolve_theme_background(theme_defaults)
    except Exception as exc:  # noqa: BLE001 - defensive: any shape surprise
        _warn_once(
            "could not read doxtr-pdf-theme-core palette (%s); song styling "
            "falls back to defaults" % exc
        )
        setattr(config, RESOLVED_THEME_ATTR, {})
        setattr(config, RESOLVED_BACKGROUND_ATTR, None)
        return

    setattr(config, RESOLVED_THEME_ATTR, {"typography": mapped} if mapped else {})
    setattr(config, RESOLVED_BACKGROUND_ATTR, background)

    # HTML/EPUB timing reconciliation (LOCKED, mirrors the LaTeX >900 patch):
    # CHUNK-4-1 caches the resolved GLOBAL typography at ~600 (before the theme
    # tier resolves here at >900), and the HTML/EPUB ``<style>`` injection reads
    # that cache. So the theme tier would never reach HTML/EPUB unless we
    # recompute the cache now that ``doxtr_music_theme_defaults_resolved`` is
    # populated. ``resolve_global_typography`` (typography.py stays the
    # resolution authority) folds the theme tier in via ``three_tier_merge``;
    # this is idempotent (recompute + overwrite on autobuild reruns) and, when
    # the theme tier is ``{}`` (inactive/off), yields a value byte-identical to
    # the ~600 cache (byte-identical-when-inactive contract preserved).
    _refresh_global_typography_cache(config)

    # LaTeX: patch the theme block into the already-assembled (~700) preamble.
    _patch_latex_preamble(config, mapped, background)


def _refresh_global_typography_cache(config) -> None:
    """Recompute the CHUNK-4-1 global-typography cache after theme resolution.

    The cache attr (``doxtr_music_typography_resolved``) is computed at ~600,
    before this >900 handler resolves the theme tier; the HTML/EPUB style-block
    injection reads it. Recompute it here so the theme tier reaches HTML/EPUB.
    Uses the typography module as the single resolution authority.
    """
    from doxtr_music.typography import (
        RESOLVED_CONFIG_ATTR,
        resolve_global_typography,
    )

    setattr(config, RESOLVED_CONFIG_ATTR, resolve_global_typography(config))


def _patch_latex_preamble(config, mapped: dict, background) -> None:
    """Insert the theme ``\\dm`` value block into the assembled LaTeX preamble.

    Reconciles the ~700-assembly vs >900-resolution timing (LOCKED): the preamble
    is assembled at ~700 before the theme resolves, so this >900 handler patches
    the theme block in afterwards. The theme block is emitted **before** CHUNK-4-1's
    global-typography block (theme is the weaker source: last ``\\def`` wins in
    LaTeX, so an earlier theme block is overridden by a later global block —
    matching the Python merge's theme-below-global precedence). Sentinel-guarded
    for idempotency; also loads the bidi package (closes the CHUNK-3-4 RTL handoff).
    """
    latex_elements = getattr(config, "latex_elements", None)
    if not isinstance(latex_elements, dict):
        return
    existing = latex_elements.get("preamble", "")
    if _LATEX_THEME_SENTINEL in existing:
        return  # already patched (rerun)

    block = _theme_latex_block(mapped, background)
    if not block:
        return

    # Insert the theme block BEFORE CHUNK-4-1's global-typography block if
    # present, so the global block (later) overrides the theme block.
    marker = "% doxtr-music global typography"
    if marker in existing:
        idx = existing.index(marker)
        latex_elements["preamble"] = existing[:idx] + block + "\n" + existing[idx:]
    else:
        latex_elements["preamble"] = existing + "\n" + block


def _theme_latex_block(mapped: dict, background) -> str:
    r"""Build the theme LaTeX block: ``\dm`` value redefs (via 4-1) + RTL setup.

    Uses only the **existing** CHUNK-4-1 ``\dm`` indirection macros (no new
    macros): the theme-mapped colors/fonts become ``\renewcommand`` lines via
    the 4-1 helper. Also enables bidirectional (RTL) text support so RTL lyrics
    render directionally in PDF, closing the CHUNK-3-4 handoff — in an
    **engine-safe** way:

    * under LuaTeX (the theme's engine), ``polyglossia`` provides bidi natively;
      the ``bidi`` package is NOT loaded (it aborts under LuaTeX). ``polyglossia``
      is loaded only if not already present (Sphinx usually loads it).
    * under XeTeX/pdfTeX, the ``bidi`` package is loaded (guarded).
    """
    from doxtr_music.typography import _latex_typography_lines

    lines = _latex_typography_lines(mapped, scope="global")
    parts = [_LATEX_THEME_SENTINEL]
    # Engine-safe RTL/bidi setup (CHUNK-3-4 handoff). LuaTeX -> polyglossia's
    # native bidi (never the bidi package, which fatally aborts under LuaTeX);
    # other engines -> the bidi package. All guarded so a double-load or a
    # wrong-engine load never breaks the build.
    parts.append("\\makeatletter")
    parts.append("\\@ifpackageloaded{polyglossia}{}{\\usepackage{polyglossia}}")
    parts.append("\\ifdefined\\directlua\\else")
    parts.append("  \\@ifpackageloaded{bidi}{}{\\usepackage{bidi}}%")
    parts.append("\\fi")
    parts.append("\\makeatother")
    if lines:
        parts.append("% doxtr-music theme typography")
        parts.extend(lines)
    return "\n".join(parts)


def register_theme_interop(app):
    """Register the >900 theme-interop ``config-inited`` handler.

    Called from :func:`doxtr_music.setup`. No top-level theme-core import; the
    handler gates on the resolved config attribute only.
    """
    app.connect(
        "config-inited",
        on_config_inited_theme_interop,
        THEME_INTEROP_INIT_PRIORITY,
    )
