"""Resolve ``dd:`` color expressions via doxtr-pdf-theme-core.

doxtr-music typography ``color`` / ``background`` values may be **static**
(``#rrggbb`` / an xcolor name) or a **``dd:`` expression** that derives a color
from the active theme's semantic palette (e.g. ``dd:primary``,
``dd:secondary:darken:30``, ``dd:primary:contrast:fg:page``). Resolving a ``dd:``
expression requires ``doxtr-pdf-theme-core`` (it owns the palette + the
resolver). When the theme is **not installed** and a ``dd:`` value is present we
raise a clear, actionable error — there is deliberately no silent fallback.

This module performs a **lazy, function-local** import of doxtr-pdf-theme-core
(only when a ``dd:`` value is actually encountered). It is intentionally
separate from :mod:`doxtr_music.theme_interop`, which is contractually
import-free (it detects the theme via a config attribute, never an import). The
``dd:`` feature is a deeper, opt-in integration: using a ``dd:`` value is the
user's explicit request for theme-derived colors, so the theme dependency is
justified at that point.
"""

from __future__ import annotations

from sphinx.errors import ExtensionError
from sphinx.util import logging

from .typography import ATTRS

logger = logging.getLogger(__name__)

__all__ = [
    "DD_PREFIX",
    "has_dd_expression",
    "resolve_dd_value",
    "resolve_dd_color",
    "resolve_dd_in_typography",
    "fill_lyrics_body_color",
    "ensure_contrast",
    "contrast_fix_typography",
    "theme_body_text_color",
]

#: The color-expression prefix (doxtr-pdf-theme-core's ``dd:`` DSL).
DD_PREFIX = "dd:"

#: A short, correct example set for the error message.
_DD_ERROR_HINT = (
    "A 'dd:' color expression derives a color from the active "
    "doxtr-pdf-theme-core semantic palette. It requires the theme to be "
    "installed. Either:\n"
    "  1. install the theme:  pip install doxtr-pdf-theme-core\n"
    "  2. or use a static color value instead, e.g. a hex color '#1a3d7a' "
    "(or '#f0a860') or a known xcolor name like 'blue'."
)


def has_dd_expression(typography) -> bool:
    """True if any ``color``/``background`` cell in ``typography`` is a ``dd:`` expr."""
    if not isinstance(typography, dict):
        return False
    for cell in typography.values():
        if not isinstance(cell, dict):
            continue
        for attr in ("color", "background"):
            value = cell.get(attr)
            if isinstance(value, str) and value.strip().startswith(DD_PREFIX):
                return True
    return False


def _theme_resolver():
    """Return ``(resolve_color, palette)`` from theme-core, or ``None``.

    Lazy import (only reached when a ``dd:`` value is present). The palette is
    the theme-core semantic palette merged with the user's
    ``doxtr_theme_defaults['semantic_palette']`` overrides (mirroring how the
    theme itself resolves it). Returns ``None`` when the theme is not installed.
    """
    try:
        from doxtr_pdf_theme_core.core_config import DOXTR_SEMANTIC_PALETTE
        from doxtr_pdf_theme_core.utils import resolve_color
    except Exception:  # pragma: no cover - theme absent / import error
        return None
    base = dict(DOXTR_SEMANTIC_PALETTE) if isinstance(DOXTR_SEMANTIC_PALETTE, dict) else {}
    return resolve_color, base


def _dark_context(config):
    """Return theme-core's dark-mode context bundle, or ``None`` (theme absent).

    Lazy, defensive import. The bundle (``get_dark_mode_context``) tells us
    whether the build is genuinely dark, the resolved **dark palette**, the dark
    body ``text_color`` and an ``invert_color`` callable — the theme's own
    helpers, so doxtr-music colors transform for dark mode exactly like the rest
    of the document.
    """
    try:
        from doxtr_pdf_theme_core import get_dark_mode_context
    except Exception:  # pragma: no cover - theme absent
        return None
    try:
        return get_dark_mode_context(config)
    except Exception:  # pragma: no cover - defensive
        return None


def _merged_palette(base_palette, config):
    """Merge the user's ``doxtr_theme_defaults['semantic_palette']`` over ``base``."""
    palette = dict(base_palette)
    theme_defaults = getattr(config, "doxtr_theme_defaults", None)
    if isinstance(theme_defaults, dict):
        overrides = theme_defaults.get("semantic_palette")
        if isinstance(overrides, dict):
            palette.update({k: v for k, v in overrides.items() if isinstance(v, str)})
    return palette


def resolve_dd_value(value, palette, resolve_color):
    """Resolve one ``dd:`` (or static) color ``value`` to a hex string.

    Static values (no ``dd:`` prefix) pass through unchanged. A ``dd:`` value is
    resolved via theme-core's :func:`resolve_color` against ``palette``.
    """
    if not isinstance(value, str) or not value.strip().startswith(DD_PREFIX):
        return value
    page_bg = palette.get("page", "#FFFFFF")
    # section/dict/config args are only needed for cross-section ``dd:this:``
    # references, which doxtr-music values never use — pass empty contexts.
    return resolve_color(
        value.strip(), palette, page_bg, "doxtr_music", {}, {}, {}, {}
    )


def _build_color_transformer(config, *, context_label):
    r"""Return a ``transform(value) -> value`` for one color, or ``None`` (no-op).

    The returned callable resolves a ``dd:`` expression against the theme's
    semantic palette (the **dark** palette in a genuinely dark build) and
    soft-inverts a static hex color for dark mode via the theme's own
    ``invert_color`` helper — so every doxtr-music color transforms exactly like
    the rest of the themed document. Returns ``None`` when there is nothing to do
    (light build with no ``dd:`` values and no dark transform), so the caller can
    keep values untouched.

    ``needs_dd`` is decided by the caller; if a ``dd:`` value is present but the
    theme is not installed, an actionable :class:`ExtensionError` is raised.
    ``context_label`` names where the ``dd:`` value came from, for the error.
    """
    dark = _dark_context(config)
    dark_active = bool(dark and dark.get("active"))
    invert = dark.get("invert_color") if dark_active else None
    # The palette + resolver are built lazily on first dd: value.
    state = {"palette": None, "resolve_color": None, "ready": False}

    def _ensure_resolver():
        if state["ready"]:
            return
        state["ready"] = True
        resolver = _theme_resolver()
        if resolver is None:
            raise ExtensionError(
                "[doxtr-music] A 'dd:' color expression was used in %s but "
                "doxtr-pdf-theme-core is not installed.\n%s"
                % (context_label, _DD_ERROR_HINT)
            )
        resolve_color, base_palette = resolver
        palette = _merged_palette(base_palette, config)
        if dark_active and isinstance(dark.get("palette"), dict):
            palette = dict(palette)
            palette.update(dark["palette"])
            if dark.get("page_color"):
                palette["page"] = dark["page_color"]
        state["palette"] = palette
        state["resolve_color"] = resolve_color

    def _transform(value):
        if not isinstance(value, str) or not value.strip():
            return value
        v = value.strip()
        if v.startswith(DD_PREFIX):
            _ensure_resolver()
            return resolve_dd_value(v, state["palette"], state["resolve_color"])
        # Static color: soft-invert a hex value for dark mode; leave names alone.
        if dark_active and invert is not None and v.startswith("#"):
            return invert(v) or v
        return value

    return _transform, dark_active


def resolve_dd_color(value, config, *, context_label="a doxtr-music color"):
    """Resolve/transform ONE color value (``dd:`` or static) for the active build.

    Used for colors that are not part of the typography dict — e.g. multi-singer
    colors. A ``dd:`` expression resolves against the theme palette (dark in a
    dark build); a static hex color is soft-inverted in dark mode; xcolor names
    pass through. A ``dd:`` value without the theme raises an actionable error.
    """
    if not isinstance(value, str) or not value.strip():
        return value
    transform, _ = _build_color_transformer(config, context_label=context_label)
    return transform(value)


def resolve_dd_in_typography(typography, config):
    """Return ``typography`` with ``dd:`` resolved + dark-mode color transform.

    Three things happen to ``color``/``background`` values:

    * A ``dd:`` expression is resolved against the theme's semantic palette —
      the **dark** palette when the build is genuinely dark, so a ``dd:primary``
      chord uses the dark-adjusted brand color (exactly like the rest of the
      themed document). ``dd:`` used without the theme installed → an actionable
      error (no silent fallback).
    * A **static hex** color is soft-inverted for dark mode via the theme's own
      ``invert_color`` helper, so hardcoded colors adapt like body text/links.
      (xcolor names / non-hex values are left unchanged — they cannot be
      inverted reliably.)
    * In light mode with no theme and no ``dd:`` values, this is a no-op.

    A shallow copy is returned; the input is never mutated.
    """
    dark = _dark_context(config)
    dark_active = bool(dark and dark.get("active"))
    needs_dd = has_dd_expression(typography)

    # Fast path: no dd: expressions and not a dark build -> nothing to transform
    # (in a light build lyrics inherit the default black body color already, so
    # there is no body-color fill to apply). Returns the input unchanged.
    if not needs_dd and not dark_active:
        return typography

    transform, _ = _build_color_transformer(
        config, context_label="doxtr_music_typography (or a per-song option)"
    )

    resolved: dict = {}
    for element, cell in typography.items():
        if not isinstance(cell, dict):
            resolved[element] = cell
            continue
        new_cell = dict(cell)
        for attr in ("color", "background"):
            if attr in new_cell:
                new_cell[attr] = transform(new_cell[attr])
        resolved[element] = new_cell
    return resolved


def fill_lyrics_body_color(typography, config):
    """Fill an unset lyrics color with the theme's dark body-text color (dark only).

    When the theme is active AND the build is genuinely dark (so the document
    body text is no longer the default black), an unset lyrics color is filled
    with the document's dark body-text color so lyrics match the surrounding
    body text in HTML/EPUB as well as PDF. In a light build the body text is the
    default black, which lyrics already inherit, so nothing is stamped. Returns
    a shallow copy only when it changes something; otherwise the input.
    """
    dark = _dark_context(config)
    if not (dark and dark.get("active")):
        return typography
    body_color = theme_body_text_color(config)
    if not body_color:
        return typography
    lyric_cell = dict(typography.get("lyrics") or {})
    if lyric_cell.get("color"):
        return typography
    lyric_cell["color"] = body_color
    out = dict(typography)
    out["lyrics"] = lyric_cell
    return out


def theme_body_text_color(config):
    """Return the document's body text color from the active theme, or ``None``.

    Mirrors how doxtr-pdf-theme-core colors body text: ``#000000`` in light
    mode, ``config.doxtr_dark_text_color`` (e.g. ``#DBDBDB``) in a genuinely
    dark build. Returns ``None`` when the theme is not installed/active, so the
    caller leaves lyrics to inherit the document color.
    """
    dark = _dark_context(config)
    if dark is None:
        return None
    if dark.get("active"):
        return dark.get("text_color") or "#DBDBDB"
    # Theme installed but light build: the theme's body text is black.
    return "#000000"


def ensure_contrast(foreground, background, config):
    """Adjust ``foreground`` to meet WCAG AA contrast against ``background``.

    Uses doxtr-pdf-theme-core's own ``get_highest_contrast_color`` helper (the
    same one the theme uses for its admonition/table text), so a colored label
    on a colored background stays readable — e.g. a light section-title color on
    a light section-title background is darkened until it contrasts. Both must
    be resolvable hex colors; a non-hex value (xcolor name), a missing input, or
    the theme being unavailable → ``foreground`` unchanged. Never raises.
    """
    if not (isinstance(foreground, str) and foreground.strip().startswith("#")):
        return foreground
    if not (isinstance(background, str) and background.strip().startswith("#")):
        return foreground
    try:
        from doxtr_pdf_theme_core.utils import get_highest_contrast_color
    except Exception:  # pragma: no cover - theme absent
        return foreground
    try:
        fixed = get_highest_contrast_color(
            foreground.strip(), background.strip(), target="foreground"
        )
    except Exception:  # pragma: no cover - defensive
        return foreground
    return fixed or foreground


def contrast_fix_typography(typography, config):
    """Return ``typography`` with each cell's ``color`` made readable on its ``background``.

    For every element that sets BOTH a ``color`` and a ``background``, adjust the
    color (via :func:`ensure_contrast`) so the text is legible on its own
    background — independent of the page. A no-op when nothing pairs color with
    background, or the theme is unavailable. Shallow-copies only changed cells.
    """
    if not isinstance(typography, dict):
        return typography
    changed = None
    for element, cell in typography.items():
        if not isinstance(cell, dict):
            continue
        color = cell.get("color")
        background = cell.get("background")
        if not (color and background):
            continue
        fixed = ensure_contrast(color, background, config)
        if fixed != color:
            if changed is None:
                changed = dict(typography)
            new_cell = dict(cell)
            new_cell["color"] = fixed
            changed[element] = new_cell
    return changed if changed is not None else typography
