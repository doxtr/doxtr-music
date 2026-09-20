"""LaTeX/PDF visitors + preamble-injection seam for doxtr-music (CHUNK-2-1).

Fills ``_VISITORS["latex"]`` (the CHUNK-1-2 seam) so the single SongNode tree
renders to LaTeX, and owns the **preamble-injection seam** every later chunk
(4-1 typography, 4-2 singer color, 7-1 theme interop) extends. This module fills
the ``"latex"`` bucket **only** — it never touches ``_VISITORS["html"]`` /
``["epub"]``.

Backend exchangeability (LOCKED — the ``\\dm…`` macro contract)
--------------------------------------------------------------

Visitors emit **backend-neutral** ``\\dm…`` macros (``\\dmchord``,
``\\dmsectionbegin``/``\\dmsectionend``, ``\\dmsinger``, ``\\dmroman``,
``\\dmneedspace``, …). Each ``latex_backends/<name>.tex_t`` maps those macros
onto its package's primitives, so the backend is genuinely swappable — a visitor
never emits ``\\beginverse`` or any package-native command directly.

Preamble seam (LOCKED — mirrors ``_VISITORS``)
----------------------------------------------

``latex_elements['preamble']`` is one shared string many parties append to. We
never do ad-hoc ``+=``. Instead an ordered registry
:data:`_LATEX_PREAMBLE_CONTRIBUTORS` (``(priority, fn(config) -> str)``) is
assembled by :func:`assemble_latex_preamble` and injected **once** at a
dedicated ``config-inited`` handler (priority ~700, after 0-3 validation @~500,
before 7-1 interop @>900). Injection is sentinel-guarded (``% doxtr-music
preamble v1``) so autobuild reruns don't double-inject. CHUNK-4-1/4-2/7-1
register contributors here; none mutate ``latex_elements`` directly.

Soft dependency: this module never imports ``doxtr_pdf_theme_core`` (interop is
deferred to CHUNK-7-1). Escaping uses the own :mod:`doxtr_music.latex_escape`.
"""

from __future__ import annotations

import os

from sphinx.util import logging

from doxtr_music import nodes as _nodes
from doxtr_music.latex_escape import esc_latex

logger = logging.getLogger(__name__)

__all__ = [
    "register_latex_visitors",
    "register_latex_preamble_seam",
    "register_preamble_contributor",
    "assemble_latex_preamble",
    "resolve_backend_template",
    "render_backend_fragment",
    "PREAMBLE_SENTINEL",
    "PREAMBLE_INIT_PRIORITY",
    "DEFAULT_BACKEND",
    "KNOWN_BACKENDS",
]

#: Sentinel marking an already-injected preamble (idempotency guard). Kept in
#: lockstep with the leading comment of ``preamble.tex_t``.
PREAMBLE_SENTINEL = "% doxtr-music preamble v1"

#: ``config-inited`` priority for the preamble injection handler. It runs
#: AFTER doxtr-pdf-theme-core resolves dark mode (its ``config-inited`` @900)
#: and AFTER doxtr-music's late global-typography re-resolution
#: (:data:`doxtr_music.typography.TYPOGRAPHY_LATE_INIT_PRIORITY`, 910), so the
#: global typography contributor bakes DARK-correct colors into the preamble;
#: it runs BEFORE the 7-1 theme-interop patch (950), which appends to the
#: assembled preamble.
PREAMBLE_INIT_PRIORITY = 920

#: The backend used when the configured one is unknown/missing.
DEFAULT_BACKEND = "songbook"

#: Backends this chunk ships a ``.tex_t`` for. Unknown → warn + fall back.
KNOWN_BACKENDS = ("songbook", "songs")

_BACKENDS_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "latex_backends")


# ---------------------------------------------------------------------------
# Backend template resolution + rendering
# ---------------------------------------------------------------------------

def _override_dirs(config):
    """User-supplied backend override directories (hierarchical tier 1).

    Read defensively from ``doxtr_music_latex_backend_path`` (str or list of
    str). This config key is **not** registered by CHUNK-2-1 (the CHUNK-0-3
    manifest is a locked 8-row contract); it is read via ``getattr`` so the
    resolver already supports the user-override tier the moment CHUNK-7-1
    registers the key while wiring the theme tier into this same resolver. When
    unregistered/unset the attr is absent and this returns ``[]`` (resolver
    falls through to theme/package tiers).
    """
    raw = getattr(config, "doxtr_music_latex_backend_path", None)
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    try:
        return [str(p) for p in raw]
    except TypeError:
        return []


def resolve_backend_template(name, config=None):
    """Resolve a backend ``<name>.tex_t`` path by hierarchical search.

    Order (core parity): user override dir(s) → theme dir (CHUNK-7-1, via the
    same key) → packaged ``latex_backends/<name>.tex_t``. Returns an absolute
    path to the first existing file, or ``None`` if none exists.
    """
    filename = "%s.tex_t" % name
    search = []
    if config is not None:
        search.extend(_override_dirs(config))
    search.append(_BACKENDS_DIR)
    for directory in search:
        candidate = os.path.abspath(os.path.join(directory, filename))
        if os.path.isfile(candidate):
            return candidate
    return None


def _select_backend(config):
    """Return the effective backend name, warning + falling back if unknown."""
    name = getattr(config, "doxtr_music_latex_package", DEFAULT_BACKEND)
    if name in KNOWN_BACKENDS and resolve_backend_template(name, config):
        return name
    # A user override dir may legitimately ship a non-builtin name; honor it if
    # a .tex_t actually resolves. Otherwise warn + fall back.
    if resolve_backend_template(name, config):
        return name
    logger.warning(
        "[doxtr-music] Unknown LaTeX backend %r; falling back to %r. "
        "Known backends: %s.",
        name,
        DEFAULT_BACKEND,
        list(KNOWN_BACKENDS),
    )
    return DEFAULT_BACKEND


def _render_tex_t(path, context):
    """Render a ``.tex_t`` file via Sphinx's LaTeXRenderer (``<%= %>``)."""
    from sphinx.util.template import LaTeXRenderer

    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    return LaTeXRenderer().render_string(source, context)


def render_backend_fragment(name, config):
    """Render the backend fragment ``<name>.tex_t`` (no preamble wrapper)."""
    path = resolve_backend_template(name, config)
    if path is None:  # pragma: no cover - _select_backend guarantees existence
        return ""
    return _render_tex_t(path, {})


# ---------------------------------------------------------------------------
# Preamble-injection seam
# ---------------------------------------------------------------------------

#: Ordered registry of ``(priority, fn(config) -> str)``. Lower priority is
#: assembled first. CHUNK-2-1 registers the backend contributor; 4-1/4-2/7-1
#: append their own without touching this module's structure.
_LATEX_PREAMBLE_CONTRIBUTORS: list = []


def register_preamble_contributor(priority, fn):
    """Register a preamble contributor ``fn(config) -> str`` at ``priority``.

    Contributors are assembled in ascending priority order. This is the single
    documented way to add to the LaTeX preamble; never mutate
    ``latex_elements['preamble']`` directly.
    """
    _LATEX_PREAMBLE_CONTRIBUTORS.append((priority, fn))


def _backend_preamble_contributor(config):
    """The CHUNK-2-1 contributor: renders ``preamble.tex_t`` for the backend."""
    backend = _select_backend(config)
    fragment = render_backend_fragment(backend, config)
    preamble_path = resolve_backend_template("preamble", config)
    if preamble_path is None:  # pragma: no cover - packaged file always present
        return ""
    return _render_tex_t(preamble_path, {"backend_fragment": fragment})


def assemble_latex_preamble(config):
    """Concatenate all registered contributors in ascending priority order."""
    parts = []
    for _priority, fn in sorted(
        _LATEX_PREAMBLE_CONTRIBUTORS, key=lambda item: item[0]
    ):
        text = fn(config)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _on_config_inited_preamble(app, config):
    """``config-inited`` handler (priority ~700): inject the preamble once.

    Idempotent: if the sentinel is already present in the shared preamble
    string we skip, so an autobuild rerun doesn't double-inject. Uses
    ``setdefault`` so an unset ``latex_elements['preamble']`` doesn't KeyError.
    """
    latex_elements = config.latex_elements
    existing = latex_elements.setdefault("preamble", "")
    if PREAMBLE_SENTINEL in existing:
        return
    assembled = assemble_latex_preamble(config)
    if assembled:
        latex_elements["preamble"] = existing + "\n" + assembled


def register_latex_preamble_seam(app):
    """Register the CHUNK-2-1 backend contributor + the injection handler.

    Called from :func:`doxtr_music.setup`. The backend contributor is registered
    at a low priority (200) so 4-1/4-2/7-1 (higher) can redefine the color/font
    macros it references; the injection handler runs at priority ~700.
    """
    # Guard against duplicate registration if setup() runs twice in one process
    # (e.g. across test builds sharing the module): keep exactly one backend
    # contributor entry.
    global _LATEX_PREAMBLE_CONTRIBUTORS
    _LATEX_PREAMBLE_CONTRIBUTORS = [
        entry
        for entry in _LATEX_PREAMBLE_CONTRIBUTORS
        if entry[1] is not _backend_preamble_contributor
    ]
    register_preamble_contributor(200, _backend_preamble_contributor)
    app.connect("config-inited", _on_config_inited_preamble, PREAMBLE_INIT_PRIORITY)


# ---------------------------------------------------------------------------
# LaTeX visitors (_VISITORS["latex"])
# ---------------------------------------------------------------------------
#
# Content args are escaped at THIS boundary only (nodes store unescaped text).
# Control words (\dm...) are never escaped.


def _lyric_fragment_for_chord(chord_node):
    """Recover the lyric fragment a chord sits over via column arithmetic.

    A chord at ``chord.column`` sits over the lyric word whose
    ``[word.column, word.column + len(text))`` range contains it (CHUNK-1-3
    lyric-relative columns). We scan the chord's line siblings for the matching
    :class:`~doxtr_music.nodes.LyricNode` and return its (unescaped) text.
    ``column is None`` → inline chord, no positioning (empty fragment). Falls
    back to the plain ``assoc_word`` attr (chord-after-lyric case) when no
    column match is found.
    """
    column = chord_node.get("column")
    if column is None:
        return ""
    match = _matching_lyric(chord_node, column)
    if match is not None:
        return match
    return chord_node.get("assoc_word") or ""


def _matching_lyric(chord_node, column):
    """Return the sibling lyric word covering ``column``, or ``None``.

    Siblings are searched within the same parent (LineNode or SingerSpanNode).
    A word ``w`` covers ``column`` when ``w.column <= column < w.column +
    len(w.text)``; ties prefer the word starting exactly at ``column``.
    """
    parent = chord_node.parent
    if parent is None:
        return None
    best = None
    for sibling in parent.children:
        if not isinstance(sibling, _nodes.LyricNode):
            continue
        wcol = sibling.get("column")
        if wcol is None:
            continue
        text = sibling.astext()
        if wcol == column:
            return text
        if wcol <= column < wcol + max(len(text), 1):
            best = text
    return best


# ---- SongNode -------------------------------------------------------------

def _visit_song(self, node):
    from doxtr_music.typography import song_typography_latex_group

    self.body.append("\n\\dmneedspace\n")
    # Emit a LaTeX target label (\phantomsection\label{...}) for the song's id(s)
    # so cross-references and page references resolve: song-list / song-index
    # \hyperref[...] links and the alphabetical index's \autopageref* both
    # target ``<docname>:<id>``. Guarded for lightweight unit-test translators
    # that lack hypertarget_to.
    if node.get("ids") and hasattr(self, "hypertarget_to"):
        self.body.append(self.hypertarget_to(node, anchor=True))
    # Per-song typography (CHUNK-4-1) LaTeX mechanism #2: a scoped TeX group that
    # \def's ONLY the overridden attr-macros (inheriting global for the rest) --
    # the LaTeX analog of HTML inline style. Global typography is handled by the
    # preamble contributor (mechanism #1). The song's OWN override delta lives
    # in node['options']['typography'] (parsed by 1-4's _options.py).
    per_song = (node.get("options") or {}).get("typography")
    open_tex, close_tex = song_typography_latex_group(per_song)
    node["_dm_song_group_close"] = close_tex
    self.body.append(open_tex)
    self._dm_latex_rtl_warned = False
    meta = node.get("song_meta") or {}
    resolved_typo = node.get("typography") or {}
    title = meta.get("title")
    if isinstance(title, str) and title:
        # Title through \dmtitle (base font/bold), wrapped with the resolved
        # ``title`` cell so color/background/size/font overrides apply.
        self.body.append(_styled_block("\\dmtitle", title, resolved_typo.get("title"),
                                       define_name="dm@titlecell"))
    _emit_latex_song_meta(self, meta, resolved_typo)


def _styled_block(macro, text, cell, *, define_name):
    r"""Render ``macro{text}`` wrapped in the resolved ``cell`` inline styling.

    Used for block-level song elements (title, metadata rows, section labels)
    that are not backed by preamble indirection macros. The text is escaped and
    wrapped by :func:`latex_cell_wrap` (font/size/color/background); any
    ``\definecolor`` prefix is emitted before the macro call. Returns a TeX
    string ending in a newline.
    """
    from doxtr_music.typography import latex_cell_wrap

    prefix, wrapped = latex_cell_wrap(esc_latex(text), cell or {}, define_name=define_name)
    return "%s%s{%s}\n" % (prefix, macro, wrapped)


def _emit_latex_song_meta(self, meta, resolved_typo):
    r"""Render the visible song-metadata rows in LaTeX (per-key styled).

    Mirrors the HTML metadata block: one ``\dmmeta`` line per renderable
    metadata row (``Label: value``), each wrapped with its per-key cell
    (``meta-<key>`` over the generic ``metadata``). Emits nothing for a song
    with no renderable metadata.
    """
    from doxtr_music.builders.html import _iter_display_meta
    from doxtr_music.typography import meta_element_names, resolve_element_cell

    for key, label, value in _iter_display_meta(meta):
        cell = resolve_element_cell(resolved_typo, meta_element_names(key))
        text = "%s: %s" % (label, value)
        self.body.append(_styled_block("\\dmmeta", text, cell,
                                       define_name="dm@meta%scell" % _tex_safe(key)))


def _depart_song(self, node):
    self.body.append(node.get("_dm_song_group_close") or "\\endgroup% doxtr-music song\n")


# ---- SectionNode ----------------------------------------------------------

def _visit_section(self, node):
    kind = node.get("kind") or "section"
    label = node.get("label") or ""
    self.body.append("\\dmneedspace\n")
    # The section label is styled by the resolved section-title cell (per-kind
    # over generic), passed through \dmsectionbegin so the backend still owns
    # the block boundary. When the cell styles the label we emit a pre-wrapped
    # label; otherwise the plain escaped label (backend \dmmeta styling).
    title_cell = node.get("typography_title")
    if title_cell:
        from doxtr_music.typography import latex_cell_wrap

        prefix, wrapped = latex_cell_wrap(
            esc_latex(label), title_cell, define_name="dm@sec%scell" % _tex_safe(kind)
        )
        self.body.append(prefix)
        self.body.append(
            "\\dmsectionbegin{%s}{%s}\n" % (esc_latex(kind), wrapped)
        )
    else:
        self.body.append(
            "\\dmsectionbegin{%s}{%s}\n" % (esc_latex(kind), esc_latex(label))
        )
    # Section-body styling (font/size/color) opens a scoped group that the
    # section's lines render inside; closed in _depart_section. Background on a
    # multi-line body is not wrapped (a \colorbox can't span page breaks); the
    # HTML/EPUB path carries body background via CSS.
    body_cell = node.get("typography_body") or {}
    open_grp = ""
    if body_cell:
        from doxtr_music.typography import latex_font_switch, latex_size_switch, normalize_latex_color

        switches = latex_font_switch(body_cell.get("font")) + latex_size_switch(body_cell.get("size"))
        color = body_cell.get("color")
        color_tex = ""
        if color:
            expr, defline = normalize_latex_color(color, define_name="dm@sec%sbodyfg" % _tex_safe(kind))
            if expr is not None:
                if defline:
                    open_grp += defline + "\n"
                color_tex = "\\color{%s}" % expr
        if switches or color_tex:
            open_grp += "\\begingroup " + switches + color_tex + "\n"
    node["_dm_section_body_close"] = "\\endgroup \n" if open_grp else ""
    self.body.append(open_grp)


def _depart_section(self, node):
    kind = node.get("kind") or "section"
    self.body.append(node.get("_dm_section_body_close") or "")
    self.body.append("\\dmsectionend{%s}\n" % esc_latex(kind))


def _tex_safe(name):
    """Return an alphanumeric-only token usable in an xcolor \\definecolor name."""
    return "".join(ch for ch in str(name) if ch.isalnum()) or "x"


# ---- LineNode + column-ordered line flow ----------------------------------
#
# A song line stores its chords and lyric words as SEPARATE column-ordered
# streams under a LineNode (or a nested SingerSpanNode): all ChordNodes first,
# then all LyricNodes (see ``build_nodes``). Emitting them in tree order would
# scramble the reading order AND drop inter-word spacing (words carry only a
# ``column``; spacing is reconstructed from column gaps, never stored — the
# CHUNK-1-3 authority). So the LaTeX visitor COLLECTS the line's chords/lyrics
# into a per-line buffer during child visits and RENDERS the whole line in
# ``_depart_line``: each lyric word, in column order, emitted as either
# ``\dmchord{<chord>}{<word>}`` (a chord stacks over it) or ``\dmlyric{<word>}``,
# separated by the reconstructed inter-word spacing. This mirrors the EPUB
# two-row reconstruction and keeps the backend-neutral ``\dm`` macro contract.
#
# A SectionToken(kind="none") yields top-level LineNodes directly under the
# SongNode (no SectionNode). Wrap each line in a \dmsectionbegin{none} boundary
# so the backend can treat unlabeled content uniformly, then a par break.


def _line_buffer(self):
    """Return (creating if needed) the current line's collection buffer.

    ``chords`` / ``lyrics`` are lists of ``(column, text, singer_color)`` in
    logical (tree) order; the renderer sorts/pairs by ``column``.
    """
    buf = getattr(self, "_dm_latex_line", None)
    if buf is None:
        buf = {"chords": [], "lyrics": []}
        self._dm_latex_line = buf
    return buf


def _visit_line(self, node):
    # Fresh per-line collection buffer (chords + lyric words gathered from the
    # child ChordNode/LyricNode visits, rendered together in _depart_line).
    self._dm_latex_line = {"chords": [], "lyrics": []}
    if not isinstance(node.parent, _nodes.SectionNode):
        # Top-level line (kind="none" content): wrap in the "none" boundary.
        self.body.append("\\dmsectionbegin{none}{}%\n")
        node["_dm_none_wrapped"] = True


def _depart_line(self, node):
    buf = getattr(self, "_dm_latex_line", None)
    self._dm_latex_line = None
    if buf is not None:
        self.body.append(_render_line_flow(buf))
    if node.get("_dm_none_wrapped"):
        self.body.append("\\dmsectionend{none}%\n")
    self.body.append("\\par\n")


def _stamped_background(node):
    """Return the node's stamped typography ``background`` value, or ``None``."""
    cell = node.get("typography")
    if isinstance(cell, dict):
        return cell.get("background")
    return None


def _effective_word_color(self, node):
    r"""Return the per-word color for the line flow: singer wins, else typography.

    The line-flow renderer applies a per-word color by scoping ``\dmlyriccolor``
    / ``\dmchordcolor`` (see :func:`_wrap_singer_color`). The winning color is
    the singer color when present (CHUNK-4-2), otherwise the node's stamped
    typography ``color``. Using the stamped color per-word (not just the global
    ``\dm...color`` macro) is what carries a per-section / contrast-fixed lyric
    color — e.g. the dark text that must contrast against a highlight
    ``\colorbox`` background. ``None`` → the global indirection color stands.
    """
    singer = _current_singer_color(self)
    if singer:
        return singer
    cell = node.get("typography")
    if isinstance(cell, dict):
        return cell.get("color")
    return None


def _chord_at_column(chords, column):
    """Return the ``(label, color, background)`` of a chord covering ``column``.

    A chord at ``ccol`` covers the word starting at ``column`` when it starts
    exactly there. Returns ``(label, color, background)`` or ``None``.
    """
    for ccol, label, color, background in chords:
        if ccol == column:
            return (label, color, background)
    return None


def _render_line_flow(buf):
    r"""Render one song line's chords + lyrics in column order with spacing.

    Walks the line's lyric words in ascending ``column`` and emits, for each
    word, either ``\dmchord{<chord>}{<word>}`` (a chord starts at that column)
    or ``\dmlyric{<word>}``. Inter-word spacing is reconstructed from the gap
    between one word's end column and the next word's start column (never
    stored — the CHUNK-1-3 authority), emitted as ordinary interword space so
    the proportional-font line reads naturally ("Amazing grace how sweet…").
    A per-word WINNING singer color (CHUNK-4-2) scopes that word's indirection
    macros so \dmchord/\dmlyric pick it up. A per-word ``background`` wraps the
    word in a ``\colorbox`` (a highlight-marker effect). Chords with no covered
    word (rare) are dropped from the flow.
    """
    chords = buf.get("chords") or []
    lyrics = sorted(buf.get("lyrics") or [], key=lambda t: (t[0] if t[0] is not None else 0))
    out = []
    prev_end = None  # end column of the previous word
    for column, text, l_color, l_bg in lyrics:
        col = column if column is not None else (prev_end or 0)
        # Reconstruct inter-word spacing from the column gap (>=1 real space).
        # Prefix the space with an empty group ``{}`` so it is never swallowed
        # by a preceding control word: the previous piece may end in a control
        # sequence (e.g. a chord/singer color group's ``\endgroup``), and TeX
        # silently drops spaces that immediately follow a control word — which
        # would glue two words together ("Swing low" -> "Swinglow"). ``{}``
        # produces no output and breaks that adjacency; runs of spaces collapse
        # to one interword space in normal LaTeX text, so the gap still reads
        # as a single natural space.
        if prev_end is not None:
            gap = col - prev_end
            out.append("{}" + (" " if gap <= 0 else " " * gap))
        covering = _chord_at_column(chords, col)
        if covering is not None:
            label, c_color, c_bg = covering
            # ``label`` is already escaped TeX (may embed \dmroman{} for an
            # alongside numeral); only the lyric word needs escaping here.
            piece = "\\dmchord{%s}{%s}" % (label, esc_latex(text))
            # The chord glyph uses the CHORD color; the lyric fragment uses the
            # LYRIC color — they are independent (a colored chord over
            # body/contrast-fixed lyrics). Singer color, when present, already
            # won on both at stamp time (chord and lyric carry the same
            # singer_color), so this still yields one color in a singer run.
            piece = _wrap_word_colors(piece, c_color, l_color)
            background = c_bg or l_bg
            piece = _wrap_background(piece, background)
        else:
            piece = "\\dmlyric{%s}" % esc_latex(text)
            piece = _wrap_singer_color(piece, l_color)
            piece = _wrap_background(piece, l_bg)
        out.append(piece)
        prev_end = col + max(len(text), 1)
    return "".join(out)


def _wrap_background(piece, background):
    r"""Wrap ``piece`` in a ``\colorbox`` when a background color is set.

    A per-word highlight (e.g. a yellow marker on a lyric). ``\colorbox`` needs
    xcolor (loaded by the preamble). Invalid colors are skipped (warn upstream).
    """
    if not background:
        return piece
    from doxtr_music.typography import normalize_latex_color

    expr, defline = normalize_latex_color(background, define_name="dm@wordbg")
    if expr is None:
        return piece
    prefix = (defline + " ") if defline else ""
    return "%s\\colorbox{%s}{%s}" % (prefix, expr, piece)


def _wrap_singer_color(piece, color):
    r"""Scope a rendered word's chord+lyric indirection color to a single color.

    Convenience wrapper around :func:`_wrap_word_colors` for the common case
    where the chord glyph and the lyric fragment share one color (a singer run,
    or a bare lyric). ``None`` → the typography color (global + per-song) stands.
    """
    return _wrap_word_colors(piece, color, color)


def _wrap_word_colors(piece, chord_color, lyric_color):
    r"""Scope a word's ``\dmchordcolor`` / ``\dmlyriccolor`` independently.

    A song chord renders as ``\ooalign`` of the chord glyph (``\dmchordcolor``)
    over the lyric fragment (``\dmlyric`` -> ``\dmlyriccolor``); the two must be
    able to use DIFFERENT colors (e.g. a colored chord over body-colored lyrics,
    or contrast-fixed-per-role text on a highlight background). We ``\def`` each
    indirection macro to its own color inside a ``\begingroup`` group so
    ``\dmchord`` / ``\dmlyric`` pick up their own. A ``None`` for either leaves
    that macro at the inherited (global/per-song) value.

    NOTE: emitted inline (words separated by spaces), so it must NOT use
    end-of-line ``%`` comments — a trailing ``%`` would comment out the next
    word's ``\begingroup`` (an "Extra \endgroup" imbalance).
    """
    if not chord_color and not lyric_color:
        return piece
    from doxtr_music.singer import resolve_latex_singer_color

    defs = ""
    prefix = ""
    if chord_color:
        expr, defline = resolve_latex_singer_color(
            chord_color, define_name="dm@wordchordcolor"
        )
        if expr is not None:
            if defline:
                prefix += defline + " "
            defs += "\\def\\dmchordcolor{\\color{%s}}" % expr
    if lyric_color:
        expr, defline = resolve_latex_singer_color(
            lyric_color, define_name="dm@wordlyriccolor"
        )
        if expr is not None:
            if defline:
                prefix += defline + " "
            defs += "\\def\\dmlyriccolor{\\color{%s}}" % expr
    if not defs:
        return piece
    return "\\begingroup " + prefix + defs + piece + "\\endgroup "


# ---- ChordNode ------------------------------------------------------------

def _visit_chord(self, node):
    from docutils.nodes import SkipNode

    from doxtr_music.engine.i18n import resolve_chord_display

    # Shared display resolution (CHUNK-3-4): off -> localized chord, replace ->
    # numeral, alongside -> chord+numeral per the format. For alongside the
    # numeral part is wrapped in \dmroman{} so it uses the roman font/size.
    if node.get("inline_role"):
        # A ``:chord:`` role (CHUNK-3-5) is inline prose (no roman combining).
        label = resolve_chord_display(node, self.config)
        self.body.append("\\dmchordinline{%s}" % esc_latex(label))
        return
    label = _latex_chord_label(node, self.config)
    # A song chord: COLLECT it into the current line buffer (rendered in column
    # order, paired with its lyric word, in _depart_line). Skip children.
    buf = getattr(self, "_dm_latex_line", None)
    if buf is not None:
        buf["chords"].append(
            (node.get("column"), label, _effective_word_color(self, node),
             _stamped_background(node))
        )
        raise SkipNode
    # Defensive: a song chord outside a LineNode (should not happen) — fall back
    # to the previous positioned-fragment behavior so nothing is lost.
    fragment = _lyric_fragment_for_chord(node)
    self.body.append(
        "\\dmchord{%s}{%s}" % (label, esc_latex(fragment))
    )


def _latex_chord_label(node, config):
    r"""Return the escaped TeX chord label, styling an alongside numeral.

    ``off``/``replace`` → the escaped display text. ``alongside`` → the format
    template split into segments: chord/literal parts are escaped plain, the
    numeral part is wrapped in ``\dmroman{...}`` so it renders in the roman
    font/size/color (e.g. Solitreo) distinct from the chord. A newline in the
    template becomes ``\\`` (a line break, stacking chord over numeral).
    """
    from doxtr_music.engine.i18n import (
        resolve_chord_display,
        resolve_chord_display_parts,
    )

    parts = resolve_chord_display_parts(node, config)
    if len(parts) == 1:
        return esc_latex(resolve_chord_display(node, config))
    out = []
    for kind, text in parts:
        if kind == "roman":
            out.append("\\dmroman{%s}" % esc_latex(text))
        else:
            out.append(esc_latex(text).replace("\n", "\\\\"))
    return "".join(out)


def _depart_chord(self, node):
    pass


# ---- RomanNode: a standalone roman numeral (:roman: role / progression cell) --
#
# CHUNK-3-3 owns the RomanNode LaTeX visitor for all three formats. LaTeX emits
# the standalone \dmroman{<numeral>} macro (defined in the preamble); the numeral
# is unescaped content and routes through esc_latex (it can contain ``#``).


def _visit_roman(self, node):
    numeral = node.get("roman", "")
    self.body.append("\\dmroman{%s}" % esc_latex(numeral))


def _depart_roman(self, node):
    pass


# ---- ChordProgressionNode grid (CHUNK-4-4): a standard ``tabular`` ----------
#
# A progression grid is generic LaTeX (a table), NOT a backend-specific song
# construct, so the visitor emits a standard ``tabular`` directly: the column
# spec is driven by ``columns`` (e.g. ``{*{4}{c}}``), cells via the existing
# ``\dmchordinline`` / ``\dmroman`` macros (already in the 2-1 contract), ``&``
# between cells and ``\\`` between rows. Cell content is escaped at the SAME
# esc_latex boundary. No whole-grid ``\dm`` macro (a table is not
# backend-specific); the standard ``tabular`` needs no extra package.


def _visit_progression(self, node):
    from docutils.nodes import SkipNode

    from doxtr_music.builders._progression import classify_progression_cell

    columns = int(node.get("columns", 0) or 0)
    colspec = "{*{%d}{c}}" % columns if columns else "{c}"
    self.body.append("\n\\begin{tabular}%s\n" % colspec)

    rows = [c for c in node.children if isinstance(c, _nodes.ProgressionRowNode)]
    for row in rows:
        cell_out = []
        for cell in row.children:
            if not isinstance(cell, _nodes.ProgressionCellNode):
                continue
            result = classify_progression_cell(cell, self.config)
            kind = result[0]
            if kind == "chord":
                _, display, roman = result
                piece = "\\dmchordinline{%s}" % esc_latex(display)
                if roman:
                    piece += " \\dmroman{%s}" % esc_latex(roman)
                cell_out.append(piece)
            elif kind == "roman":
                cell_out.append("\\dmroman{%s}" % esc_latex(result[1]))
            else:  # empty / spacer / literal passthrough
                cell_out.append(esc_latex(result[1]))
        self.body.append(" & ".join(cell_out) + " \\\\\n")

    self.body.append("\\end{tabular}\n")
    raise SkipNode


def _depart_progression(self, node):  # pragma: no cover - SkipNode short-circuits
    pass


# ---- KeyNode: a standalone key name (:key: role, CHUNK-3-5) ----------------
#
# LaTeX emits the backend-neutral \dmkey{<key>} macro (defined by both backends
# per the CHUNK-2-1 macro-contract extension). The key is localized as a note
# name (root + optional ``m`` minor mode) via localize_chord, then routed
# through the esc_latex boundary (it can contain ``#``).


def _visit_key(self, node):
    from doxtr_music.engine.i18n import resolve_key_display

    key = node.get("key", "")
    display = resolve_key_display(key, self.config)
    self.body.append("\\dmkey{%s}" % esc_latex(display))


def _depart_key(self, node):
    pass


# ---- LyricNode ------------------------------------------------------------
#
# A chord already renders its associated lyric fragment via \dmchord's second
# argument. To avoid double-printing the word, a LyricNode only emits its text
# when it is NOT covered by an immediately following chord over the same word.
# For v1 fidelity we emit every lyric fragment wrapped in \dmlyric; chords stack
# above via \ooalign (the fragment they carry aligns the chord, the standalone
# lyric provides the flowing text). To prevent duplication we suppress the lyric
# text on a word that a sibling chord positions over.


def _bidi_setup_active(translator) -> bool:
    """True when CHUNK-7-1 theme interop has loaded a bidi-capable setup.

    Closes the CHUNK-3-4 RTL handoff: when the theme is active (7-1 resolved a
    non-empty theme tier and patched ``polyglossia``/``bidi`` into the
    preamble), RTL lyrics render directionally, so the 3-4 verbatim-fallback
    warning is suppressed. Reads the resolved config attribute only (no import);
    defensive when there is no config (unit-test translators).
    """
    config = getattr(getattr(translator, "builder", None), "config", None)
    if config is None:
        config = getattr(translator, "config", None)
    if config is None:
        return False
    if not getattr(config, "doxtr_music_theme_interop", True):
        return False
    resolved = getattr(config, "doxtr_music_theme_defaults_resolved", None)
    return bool(resolved)


def _visit_lyric(self, node):
    from docutils.nodes import SkipNode

    text = node.astext()
    # RTL documented+tested fallback (CHUNK-3-4, LOCKED): the backend loads NO
    # bidi package by default, so strong-RTL lyrics are emitted verbatim (never
    # a crash) and a best-effort warning fires once per song. Actual
    # polyglossia/bidi wiring is deferred to CHUNK-7-1 (theme/backend), which
    # suppresses this warning when a bidi-capable setup is active.
    if text and not getattr(self, "_dm_latex_rtl_warned", False):
        from doxtr_music.engine.i18n import has_strong_rtl

        if has_strong_rtl(text) and not _bidi_setup_active(self):
            self._dm_latex_rtl_warned = True
            logger.warning(
                "[doxtr-music] RTL lyrics in PDF require a bidi-capable setup "
                "(e.g. polyglossia/bidi via a theme or backend); rendering "
                "verbatim without bidi reordering"
            )
    # COLLECT the lyric word into the current line buffer (rendered in column
    # order, paired with its chord + reconstructed spacing, in _depart_line).
    buf = getattr(self, "_dm_latex_line", None)
    if buf is not None:
        buf["lyrics"].append(
            (node.get("column"), text, _effective_word_color(self, node),
             _stamped_background(node))
        )
        raise SkipNode
    # Defensive: a lyric outside a LineNode (should not happen) — emit directly.
    self.body.append("\\dmlyric{%s}" % esc_latex(text))
    raise SkipNode


def _depart_lyric(self, node):  # pragma: no cover - SkipNode short-circuits
    pass


# ---- SingerSpanNode -------------------------------------------------------
#
# CHUNK-4-2: the run's WINNING singer color (resolved in Python, stamped on
# SingerSpanNode['singer_color']) is applied per-word by the line renderer
# (:func:`_wrap_singer_color`), which scopes \dmchordcolor / \dmlyriccolor so
# \dmchord / \dmlyric pick up the winner from their own indirection. Because
# chords/lyrics are COLLECTED and rendered in _depart_line (not emitted inline),
# the singer visitor only tracks the CURRENT color on a small stack so the
# collector can stamp each word; it emits no inline text of its own.


def _current_singer_color(self):
    """The innermost open singer color (or ``None``)."""
    stack = getattr(self, "_dm_latex_singer_colors", None)
    return stack[-1] if stack else None


def _visit_singer(self, node):
    stack = getattr(self, "_dm_latex_singer_colors", None)
    if stack is None:
        stack = self._dm_latex_singer_colors = []
    stack.append(node.get("singer_color") or None)


def _depart_singer(self, node):
    stack = getattr(self, "_dm_latex_singer_colors", None)
    if stack:
        stack.pop()


# ---------------------------------------------------------------------------
# Registration into the _VISITORS["latex"] seam
# ---------------------------------------------------------------------------

def register_latex_visitors():
    r"""Assign the LaTeX visitor bodies into ``_VISITORS["latex"]``.

    Called from :func:`doxtr_music.setup`. Fills the ``latex`` bucket by plain
    dict assignment (never ``add_node(override=True)``, never editing
    ``nodes.py``). CHUNK-3-3 fills the ``RomanNode`` LaTeX visitor here
    (standalone ``\dmroman``), so its dispatcher renders rather than no-ops.
    """
    latex = _nodes._VISITORS["latex"]
    latex[_nodes.SongNode] = (_visit_song, _depart_song)
    latex[_nodes.SectionNode] = (_visit_section, _depart_section)
    latex[_nodes.LineNode] = (_visit_line, _depart_line)
    latex[_nodes.ChordNode] = (_visit_chord, _depart_chord)
    latex[_nodes.LyricNode] = (_visit_lyric, _depart_lyric)
    latex[_nodes.SingerSpanNode] = (_visit_singer, _depart_singer)
    latex[_nodes.RomanNode] = (_visit_roman, _depart_roman)
    # CHUNK-3-5 adds ONLY the new KeyNode visitor by plain dict assignment.
    latex[_nodes.KeyNode] = (_visit_key, _depart_key)
    # CHUNK-4-4 adds the progression grid: the container visitor emits a full
    # ``tabular`` and SkipNodes, so Row/Cell need no separate visitors.
    latex[_nodes.ChordProgressionNode] = (_visit_progression, _depart_progression)
