r"""WCAG 2.1 AA accessibility for doxtr-music HTML + EPUB output (CHUNK-4-3).

This module is the single authority for the extension's accessibility helpers:
ARIA name builders (chord / roman / song group), the visible non-color
multi-singer cue (WCAG 1.4.1), the EPUB visually-hidden chord↔word text
alternative, and the resolved-color contrast validation (WCAG 1.4.3). The HTML
and EPUB visitors call into here; LaTeX/PDF a11y is **out of scope for v1**
(PDF/UA tagged-PDF is a distinct domain, deliberately declined — see the module
note below), and LaTeX contrast is explicitly **not** validated (the background
is even less knowable there).

A11y invariant (LOCKED — CHUNK-4-3)
-----------------------------------

Every a11y addition (a) reads only **node-local plain attrs** (``chord`` /
``roman`` / ``assoc_word`` / ``singer`` / ``singer_color``) — never a cross-node
or ancestor lookup; and (b) is **copy-neutral**: added text lives inside a
wrapper that the copy gate removes (HTML: the ``.doxtr-chord`` / ``.doxtr-singer``
DOM-strip; EPUB: emitted **outside** the copyable ``<pre>`` lyric row), so the
copied / extracted lyric stream is unchanged. **No a11y addition uses**
``::before`` **/ generated content on a lyric-carrying element** (it pollutes the
copy buffer, is not DOM-strippable, and vanishes when CSS is stripped in EPUB).

Contrast background (LOCKED heuristic + CHUNK-7-1 forward-contract)
------------------------------------------------------------------

The effective page/reader background is theme- and reader-controlled (Sphinx
HTML theme, user CSS, EPUB night-mode) and **not knowable** at this layer, so the
contrast check uses a single documented heuristic default ``#ffffff``. The
**forward-contract to CHUNK-7-1** is that its theme pickup feeds a resolved
"effective background" into :func:`check_song_contrast` (the ``background`` arg);
until then it stays ``#ffffff``. Sub-AA → **warn** (element + ratio) and render
as-authored (warn-not-fail — correct given the background uncertainty; never
mutate the author's color or fail the build).

PDF/UA note
-----------

Producing a tagged (PDF/UA) accessible PDF from LaTeX is a distinct problem
domain (structure tagging via ``tagpdf``/``pdfx``, out of the visitor layer's
reach) and is **deliberately declined for v1**. The LaTeX harness lane carries
no a11y assertion by design (self-documenting, mirroring the CHUNK-2-2 per-format
copy-table exemption pattern).
"""

from __future__ import annotations

from sphinx.util import logging as _sphinx_logging

_LOG = _sphinx_logging.getLogger(__name__)

__all__ = [
    "chord_aria_label",
    "roman_aria_label",
    "epub_chord_word_alt",
    "singer_visible_cue",
    "singer_sr_label",
    "VISUALLY_HIDDEN_STYLE",
    "parse_hex_color",
    "relative_luminance",
    "wcag_contrast_ratio",
    "size_is_large",
    "AA_NORMAL",
    "AA_LARGE",
    "DEFAULT_BACKGROUND",
    "check_song_contrast",
]

#: WCAG 2.1 AA contrast thresholds.
AA_NORMAL = 4.5   #: normal text
AA_LARGE = 3.0    #: large text (>=18pt regular / >=14pt bold)

#: Documented heuristic background (LOCKED). CHUNK-7-1 feeds a resolved value.
DEFAULT_BACKGROUND = "#ffffff"

#: An EPUB-safe visually-hidden inline style. It deliberately AVOIDS
#: ``position:absolute`` (the ``EPUB_PRE_FALLBACK`` gate forbids absolute
#: positioning anywhere in the EPUB song markup) while still removing the text
#: from the visual flow for sighted users; screen readers still announce it.
#: ``clip-path: inset(50%)`` + a 1px box + ``overflow:hidden`` hides it without
#: absolute positioning. This rides an inline ``style`` on a strippable sibling
#: element, never on a lyric-carrying node.
VISUALLY_HIDDEN_STYLE = (
    "clip-path:inset(50%);width:1px;height:1px;overflow:hidden;"
    "white-space:nowrap;display:inline-block"
)


# ---------------------------------------------------------------------------
# ARIA accessible-name builders (node-local plain attrs only)
# ---------------------------------------------------------------------------

def chord_aria_label(chord_display: str) -> str:
    """Return the ``aria-label`` for a positioned chord: ``"Chord: <display>"``.

    HTML relies on DOM proximity to the following lyric word, so the label does
    **not** append ``, word: <assoc_word>`` (that would duplicate the adjacent
    lyric read). The EPUB two-row ``<pre>`` has no positional DOM order, so it
    uses :func:`epub_chord_word_alt` instead.
    """
    return "Chord: %s" % (chord_display or "")


def roman_aria_label(numeral: str) -> str:
    """Return the ``aria-label`` for a roman numeral: ``"Roman numeral: <n>"``."""
    return "Roman numeral: %s" % (numeral or "")


def epub_chord_word_alt(chord_display: str, assoc_word: str) -> str:
    """Return the EPUB hidden chord↔word alternative text.

    The two-row ``<pre>`` model has no positional DOM order between a chord and
    its word, so the linear reading is spelled out: ``"Chord: G, word: Amazing"``
    (or just ``"Chord: G"`` when no associated word is known). This text is
    emitted **outside** the copyable ``<pre>`` lyric row (a sibling container),
    so it never pollutes the extracted lyric stream.
    """
    if assoc_word:
        return "Chord: %s, word: %s" % (chord_display or "", assoc_word)
    return "Chord: %s" % (chord_display or "")


# ---------------------------------------------------------------------------
# WCAG 1.4.1 visible non-color multi-singer cue (LOCKED)
# ---------------------------------------------------------------------------

def singer_visible_cue(singer_id: str) -> str:
    """Return the **visible** non-color cue text for a singer run (WCAG 1.4.1).

    A visible label/badge derived from the singer id (e.g. ``"A:"``) so
    sighted color-blind users can distinguish singer runs without relying on
    color. Rendered inside the strippable ``.doxtr-singer`` wrapper (HTML) / the
    singer segment (EPUB) so it is copy-neutral. An SR-only label does NOT
    satisfy 1.4.1 (it targets *sighted* users), so this is a real visible glyph.
    """
    sid = (singer_id or "").strip()
    if not sid:
        return ""
    return "%s:" % sid


def singer_sr_label(singer_id: str) -> str:
    """Return the SR-only label text for a singer run (WCAG 1.3.1 / 4.1.2).

    An *additional* screen-reader affordance ("Singer A") layered on top of the
    visible 1.4.1 cue — not the 1.4.1 mechanism itself. Emitted as visually
    hidden text inside the strippable wrapper.
    """
    sid = (singer_id or "").strip()
    if not sid:
        return ""
    return "Singer %s" % sid


# ---------------------------------------------------------------------------
# WCAG 2.1 contrast math (mirrors the core wcag_contrast shape)
# ---------------------------------------------------------------------------

def parse_hex_color(hex_color):
    """Parse a hex color string to an ``(R, G, B)`` int tuple, or ``None``.

    Supports ``#RGB`` / ``#RGBA`` / ``#RRGGBB`` / ``#RRGGBBAA`` (alpha
    discarded), with or without a leading ``#``. Non-hex color values (named
    CSS colors, ``rgb(...)`` functions) return ``None`` — the caller then skips
    the contrast check (background/foreground not both knowable as hex).
    """
    if not hex_color or not isinstance(hex_color, str):
        return None
    clean = hex_color.strip().lstrip("#")
    if len(clean) == 3:
        clean = "".join(c * 2 for c in clean)
    elif len(clean) == 4:
        clean = "".join(c * 2 for c in clean[:3])
    elif len(clean) == 8:
        clean = clean[:6]
    if len(clean) != 6 or not all(c in "0123456789abcdefABCDEF" for c in clean):
        return None
    return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))


def _linearize(channel):
    """Convert one sRGB channel (0-255) to its linear value per WCAG 2.1."""
    srgb = channel / 255.0
    if srgb <= 0.03928:
        return srgb / 12.92
    return ((srgb + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color):
    """Return the WCAG 2.1 relative luminance of a hex color, or ``None``."""
    rgb = parse_hex_color(hex_color)
    if rgb is None:
        return None
    r, g, b = (_linearize(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def wcag_contrast_ratio(color1, color2):
    """Return the WCAG 2.1 contrast ratio between two hex colors, or ``None``.

    ``(L1 + 0.05) / (L2 + 0.05)`` with the lighter luminance on top; ranges from
    1.0 (identical) to 21.0 (black vs. white). ``None`` when either color is not
    parseable as hex.
    """
    l1 = relative_luminance(color1)
    l2 = relative_luminance(color2)
    if l1 is None or l2 is None:
        return None
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# Size-aware threshold (large text = >=18pt regular / >=14pt bold)
# ---------------------------------------------------------------------------

def _parse_pt(size):
    """Return the point value of a CSS size string, or ``None`` if not in pt.

    Only ``pt`` units contribute to the large-text decision; relative/px sizes
    (EPUB downgrades absolute → ``em``) fall through to the normal 4.5:1
    threshold, which is the conservative (stricter) choice.
    """
    if not size or not isinstance(size, str):
        return None
    import re

    m = re.match(r"^\s*([0-9.]+)\s*pt\s*$", size, re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:  # pragma: no cover - regex already constrains
        return None


def size_is_large(size, *, bold=False):
    """True when a resolved size qualifies as WCAG "large text".

    Large = >=18pt regular, or >=14pt when bold. Non-``pt`` sizes are treated as
    normal text (stricter 4.5:1). ``bold`` is reserved for a future weight input;
    v1 typography has no weight element, so it defaults False.
    """
    pt = _parse_pt(size)
    if pt is None:
        return False
    return pt >= 14.0 if bold else pt >= 18.0


def _threshold_for(size):
    """Return the AA contrast threshold for a resolved size (size-aware)."""
    return AA_LARGE if size_is_large(size) else AA_NORMAL


# ---------------------------------------------------------------------------
# Resolved-color contrast validation (warn-not-fail; HTML + EPUB)
# ---------------------------------------------------------------------------

def _resolved_element_colors(song_node):
    """Yield ``(element, color, size)`` for each song element with a set color.

    Reads the single **resolved emitted** color per element:

    * The song-level typography dict (``song_node['typography']``) supplies the
      title/metadata/roman/chord/lyrics colors + sizes (CHUNK-4-1).
    * Where a run's WINNING singer color (CHUNK-4-2) overrides an element color,
      the stamped ``singer_color`` is the emitted color for that run's chord /
      lyric nodes — so those are validated with the singer color, not the
      typography candidate (we validate the *single emitted* color, not both).

    Only elements with a non-None color are yielded (an unset color inherits the
    theme foreground, which is not knowable here → skipped).
    """
    from . import nodes as _nodes

    typo = song_node.get("typography") or {}
    # Song-level elements (title / metadata) — one resolved cell each.
    for element in ("title", "metadata", "roman", "chord", "lyrics"):
        cell = typo.get(element) or {}
        color = cell.get("color")
        if color:
            yield (element, color, cell.get("size"))

    # Per-run singer-color winners override the emitted chord/lyric color.
    seen = set()
    for span in song_node.findall(_nodes.SingerSpanNode):
        color = span.get("singer_color")
        if not color or color in seen:
            continue
        seen.add(color)
        # Use the chord/lyrics size for the threshold when available.
        size = (typo.get("chord") or {}).get("size")
        yield ("singer", color, size)


def check_song_contrast(song_node, warn=None, background=DEFAULT_BACKGROUND):
    """Warn (not fail) when a resolved emitted color is sub-AA vs ``background``.

    Validates the **single resolved emitted color** per element (post-singer
    precedence) against the ``background`` heuristic (default ``#ffffff``;
    CHUNK-7-1 feeds a resolved value), using the size-aware threshold
    (4.5:1 normal / 3:1 large). Renders as-authored regardless (warn-not-fail —
    correct given background uncertainty; never mutates a color or fails the
    build). When either color is not hex-parseable the check is **skipped** (no
    warning) — the ratio is genuinely unknown.

    ``warn`` is an optional ``(message) -> None`` sink (defaults to the module
    logger's ``warning``), keeping the helper unit-testable without a Sphinx app.
    Returns the list of ``(element, ratio)`` pairs that warned (for tests).
    """
    emit = warn if warn is not None else _LOG.warning
    bg_lum = relative_luminance(background)
    if bg_lum is None:
        # Background genuinely unknown / unparseable → skip silently.
        return []
    warned = []
    for element, color, size in _resolved_element_colors(song_node):
        ratio = wcag_contrast_ratio(color, background)
        if ratio is None:
            continue  # non-hex color → ratio unknown → skip (no warning)
        threshold = _threshold_for(size)
        if ratio < threshold:
            warned.append((element, ratio))
            emit(
                "[doxtr-music] Low contrast: %s color %s on background %s has "
                "ratio %.2f:1 (WCAG 2.1 AA needs %.1f:1); rendering as-authored. "
                "The assumed background is a %s heuristic (theme/reader may "
                "differ)." % (element, color, background, ratio, threshold,
                              DEFAULT_BACKGROUND)
            )
    return warned
