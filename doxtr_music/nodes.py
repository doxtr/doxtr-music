"""Docutils node model for doxtr-music — the single AST all builders consume.

This module defines the custom Docutils node classes that the token→node
builder (:func:`build_nodes`) produces and that every format translator
(HTML/LaTeX/EPUB) visits. It is the linchpin that guarantees cross-format
parity: **one** node tree, **three** visitor sets.

Pipeline position::

    raw strings  ->  [Token]  ->  build_nodes  ->  SongNode tree
                                                        |
                              +-------------+-----------+-----------+
                              v             v                       v
                         HTML visitors  LaTeX visitors        EPUB visitors
                         (_VISITORS      (_VISITORS            (_VISITORS
                          ["html"])       ["latex"])            ["epub"])

Locked invariants (see ``plan/chunks/CHUNK-1-2-node-model.md``):

* **Format-neutral tree.** No node carries HTML/LaTeX/EPUB markup. All format
  rendering lives in visitors. A static test enforces that this source file
  contains no format-markup literals.
* **Picklable plain-data attrs.** Node attributes hold only plain picklable
  values (str/int/tuple/dict/None) — never callables, compiled regexes, or
  unpicklable option objects. This preserves ``parallel_read_safe`` /
  ``parallel_write_safe`` (CHUNK-0-1).
* **Single visitor-registration seam.** ``register_nodes`` registers a thin
  dispatcher once per visible node; the dispatcher resolves the active format
  bucket by *builder name* and looks up the real function in the module-level
  :data:`_VISITORS` registry. CHUNK-2-1/2-2 fill the ``latex``/``epub`` buckets
  by plain dict assignment — never ``add_node(override=True)`` and never editing
  this file.
* **Single assembly point.** :func:`build_nodes` is the only place that turns a
  token stream into a node tree; parsers never build nodes directly.
"""

from __future__ import annotations

from docutils import nodes

__all__ = [
    # Node classes
    "SongNode",
    "SectionNode",
    "LineNode",
    "ChordNode",
    "LyricNode",
    "RomanNode",
    "SingerSpanNode",
    "KeyNode",
    "ChordProgressionNode",
    "ProgressionRowNode",
    "ProgressionCellNode",
    "SongListNode",
    "SongIndexNode",
    # Assembly + registration
    "build_nodes",
    "register_nodes",
    # Visitor seam
    "_VISITORS",
]


# ---------------------------------------------------------------------------
# Node classes
# ---------------------------------------------------------------------------
#
# Data is stored ONLY as plain picklable values (str/int/tuple/dict/None) in the
# node attribute dict — never live objects. ``options`` on SongNode is reduced
# to plain data by build_nodes before being stored.


class SongNode(nodes.General, nodes.Element):
    """Per-song container.

    Carries ``song_meta`` (plain dict, render-time source of truth for this
    song's own output) and resolved ``options`` reduced to plain data
    (bools/strings, never a hook callable). Owns a stable ``ids``/``names``
    entry and a ``title_id`` attr so CHUNK-4-3 ``role="group"
    aria-labelledby`` and cross-refs (CHUNK-5-3) can target it.
    """


class SectionNode(nodes.General, nodes.Element):
    """A labeled song section (verse/chorus/bridge/…).

    Attrs: ``label`` (str) + ``kind`` (str; ``"verse"``/``"chorus"``/… — the
    reserved ``"none"`` boundary never yields a SectionNode).
    """


class LineNode(nodes.General, nodes.Element):
    """One chord+lyric line; children are in logical (reading) order."""


class ChordNode(nodes.Inline, nodes.Element):
    """One chord.

    Attrs:

    * ``chord`` (str, English notation) — accessible-name source for CHUNK-4-3.
    * ``column`` (Optional[int]) — lyric-relative logical offset, or ``None``
      when the chord has no lyric context (``:chord:`` role / progression cell).
    * ``roman`` (reserved, str) — set when this chord is *displayed with* its
      roman numeral annotation (CHUNK-3-3). Distinct from :class:`RomanNode`.
    * ``transposed`` (reserved, str) — transposed form (CHUNK-3-2).
    * ``duration`` (reserved) — timed-notation metadata (CHUNK-6-1/6-2).
    * ``assoc_word`` (optional, str) — the lyric word this chord sits over,
      populated by :func:`build_nodes` when derivable; CHUNK-4-3 ARIA reads it
      as a plain attr (no cross-node lookup).
    * ``typography`` (reserved, dict) — resolved per-song typography stamp
      (CHUNK-4-1); ``singer_color`` (reserved, str) resolved singer color
      (CHUNK-4-2).
    """


class LyricNode(nodes.Inline, nodes.TextElement):
    """One lyric fragment (visible text in DOM/logical order for copy-safety).

    Carries ``column`` (int) — the word's lyric-relative logical start offset
    (from ``LyricToken.column``) so LaTeX/EPUB visitors can recover a chord's
    intra-word split via ``chord.column - word.column``. May carry the reserved
    ``typography``/``singer_color`` stamps.
    """


class RomanNode(nodes.Inline, nodes.Element):
    """A **standalone** roman numeral (``:roman:`` role, or a progression cell
    rendered as roman); ``roman`` attr.

    Distinct from ``ChordNode.roman`` (which annotates a chord *displayed with*
    its roman). One definition, stated to prevent CHUNK-3-3/4-4 conflation.
    """


class SingerSpanNode(nodes.Inline, nodes.Element):
    """Intra-line inline wrapper around a run attributed to a singer.

    Attrs: ``singer`` (str) + reserved ``singer_color`` (str) stamp
    (CHUNK-4-2). A span is closed and reopened at every :class:`LineNode` and
    :class:`SectionNode` boundary, so **no span ever crosses a line or
    section** (Docutils cannot have a node whose children span two parents).
    """


class KeyNode(nodes.Inline, nodes.Element):
    """Reserved for the ``:key:`` role (CHUNK-3-5); ``key`` attr."""


class ChordProgressionNode(nodes.General, nodes.Element):
    """Reserved grid container for CHUNK-4-4 (chords/roman, no lyrics).

    Attr ``columns`` (int) — max cells-per-row, set by the directive; drives the
    LaTeX column spec + ragged-row padding.
    """


class ProgressionRowNode(nodes.General, nodes.Element):
    """Reserved: one row of a :class:`ChordProgressionNode` (CHUNK-4-4)."""


class ProgressionCellNode(nodes.General, nodes.Element):
    """Reserved: one cell of a progression row (CHUNK-4-4).

    Attr ``cell_kind`` (str, plain data) — ``"chord"``/``"roman"``/``"empty"``;
    holds a :class:`ChordNode`/:class:`RomanNode` child (or nothing for
    ``"empty"``).
    """


class SongListNode(nodes.General, nodes.Element):
    """Reserved resolve-phase query placeholder for CHUNK-5-3 ``.. song-list::``.

    Carries the raw ``:filter:`` / ``:group-by:`` strings as plain attrs.
    Emitted during read, replaced in ``doctree-resolved`` (CHUNK-5-3). Not a
    :class:`SongNode`.
    """


class SongIndexNode(nodes.General, nodes.Element):
    """Reserved resolve-phase query placeholder for CHUNK-5-3 ``.. song-index::``.

    Carries the raw ``:filter:`` / ``:group-by:`` strings as plain attrs.
    Emitted during read, replaced in ``doctree-resolved`` (CHUNK-5-3). Not a
    :class:`SongNode`.
    """


# ---------------------------------------------------------------------------
# Visitor registration seam (LOCKED)
# ---------------------------------------------------------------------------
#
# {format: {NodeClass: (visit_fn, depart_fn)}}. CHUNK-1-4 fills the "html"
# bucket with real functions; CHUNK-2-1/2-2 fill "latex"/"epub" by plain dict
# assignment (never add_node(override=True), never editing this file).
_VISITORS = {"html": {}, "latex": {}, "epub": {}}


def _resolve_format(builder):
    """Resolve the active format bucket from the *builder name*.

    EPUB builders subclass the HTML builder and inherit ``format == "html"``,
    so they must be discriminated by **name**, not format. This central
    resolution is the single seam for all three formats.
    """
    name = getattr(builder, "name", "")
    if name.startswith("epub"):
        return "epub"
    if name == "latex":
        return "latex"
    return "html"  # html / singlehtml / dirhtml / anything else


def _dispatch_visit(node_class):
    """Build a thin visit dispatcher bound to ``node_class``.

    Resolves the format bucket from ``self.builder`` and calls the real
    registered ``visit`` function. Missing entries are treated as no-ops so a
    format that has not registered a visitor still completes the build (its
    matching ``depart`` is likewise a no-op) — never dropping container
    children.
    """

    def _visit(self, node):
        fmt = _resolve_format(self.builder)
        entry = _VISITORS[fmt].get(node_class)
        if entry is not None:
            entry[0](self, node)

    return _visit


def _dispatch_depart(node_class):
    """Build a thin depart dispatcher bound to ``node_class`` (see above)."""

    def _depart(self, node):
        fmt = _resolve_format(self.builder)
        entry = _VISITORS[fmt].get(node_class)
        if entry is not None:
            entry[1](self, node)

    return _depart


# Every visible node registered here gets its ``html``/``latex``/``epub``
# dispatchers wired once. Downstream chunks fill _VISITORS[fmt][NodeClass]
# without touching add_node.
_REGISTERED_NODES = (
    SongNode,
    SectionNode,
    LineNode,
    ChordNode,
    LyricNode,
    RomanNode,
    SingerSpanNode,
    KeyNode,
    ChordProgressionNode,
    ProgressionRowNode,
    ProgressionCellNode,
    SongListNode,
    SongIndexNode,
)


def register_nodes(app):
    """Register every node class with a per-format thin dispatcher.

    Called from :func:`doxtr_music.setup`. Registers each node once via
    ``app.add_node(NodeClass, html=(v,d), latex=(v,d), epub=(v,d))`` where each
    visitor is a dispatcher into :data:`_VISITORS`. This is the single seam:
    later chunks add real visitor bodies by assigning into ``_VISITORS[fmt]``,
    never by re-registering nodes or using ``override=True``.
    """
    for node_class in _REGISTERED_NODES:
        v = _dispatch_visit(node_class)
        d = _dispatch_depart(node_class)
        app.add_node(node_class, html=(v, d), latex=(v, d), epub=(v, d))


# ---------------------------------------------------------------------------
# Default (safe) HTML visitors — minimal container/inline wrappers
# ---------------------------------------------------------------------------
#
# CHUNK-1-4 supplies the real HTML visitor bodies. Here they are minimal
# no-crash wrappers so an HTML build of a song completes; content is
# placeholder until 1-4. LaTeX/EPUB entries are intentionally left empty (their
# dispatchers no-op), so a write-only -b latex/-b epub build completes without
# an unhandled-node exception until CHUNK-2-1/2-2 fill them.


def _html_visit_noop(self, node):
    """No-op HTML visit (placeholder until CHUNK-1-4)."""


def _html_depart_noop(self, node):
    """No-op HTML depart (placeholder until CHUNK-1-4)."""


# Minimal HTML entries so the html bucket is non-empty and children still
# render as text. These are safe no-ops (visit + matching depart), NOT
# SkipNode (which would drop the song subtree).
for _nc in _REGISTERED_NODES:
    _VISITORS["html"][_nc] = (_html_visit_noop, _html_depart_noop)


# ---------------------------------------------------------------------------
# Single assembly point: build_nodes
# ---------------------------------------------------------------------------

# Annotation keys that build_nodes propagates from ChordToken.annotations into
# same-named ChordNode attrs.
_PROPAGATED_CHORD_ANNOTATIONS = ("roman", "transposed", "duration")


def _reduce_options(options):
    """Reduce a resolved-options mapping to plain picklable data.

    Keeps bools/ints/strings/None and simple containers thereof; drops anything
    else (e.g. a hook callable) so a pickle round-trip of the built SongNode
    succeeds. Returns a new plain dict.
    """
    if not options:
        return {}
    reduced = {}
    for key, value in dict(options).items():
        if isinstance(value, (bool, int, float, str, type(None))):
            reduced[str(key)] = value
        elif isinstance(value, (list, tuple)):
            items = [v for v in value if isinstance(v, (bool, int, float, str))]
            reduced[str(key)] = items
        elif isinstance(value, dict):
            reduced[str(key)] = _reduce_plain_dict(value)
        # else: drop non-plain values (callables, live objects, …)
    return reduced


def _reduce_plain_dict(value):
    """Reduce a nested dict to plain picklable data, one extra level deep.

    Keeps scalar values directly; keeps a nested dict of scalars (e.g. the
    CHUNK-4-1 ``typography`` option, ``{element: {attr: value}}``) so per-song
    typography survives the plain-data reduction and reaches the visitors /
    ``stamp_typography``. Deeper / non-plain values are dropped.
    """
    out = {}
    for k, v in value.items():
        if isinstance(v, (bool, int, float, str, type(None))):
            out[str(k)] = v
        elif isinstance(v, dict):
            out[str(k)] = {
                str(ik): iv
                for ik, iv in v.items()
                if isinstance(iv, (bool, int, float, str, type(None)))
            }
    return out


def _emit_warning(warn, message):
    """Emit ``message`` via the optional ``warn`` callable if provided."""
    if warn is not None:
        warn(message)


def build_nodes(tokens, song_meta, options=None, warn=None):
    """Assemble a token stream into a single :class:`SongNode` tree.

    This is the **only** structural assembly logic; parsers never build nodes
    directly. Behaviour (LOCKED):

    * Opens a :class:`SectionNode` on a ``SectionToken`` and closes the current
      section at the next ``SectionToken`` or song end (open-only model). A
      ``SectionToken(kind="none")`` closes the current section and returns to
      top-level (unlabeled) content **without** opening a new SectionNode — its
      following children attach directly under the SongNode.
    * Groups Chord/Lyric tokens into a :class:`LineNode` between
      ``LineBreakToken`` boundaries.
    * Applies current-singer state (``SingerToken``) as intra-line
      :class:`SingerSpanNode` wrappers, closed/reopened at every line & section
      boundary so no span crosses a line/section.
    * Ignores ``BarToken`` (untimed songs).
    * Propagates ``ChordToken.annotations`` keys ``"roman"``/``"transposed"``/
      ``"duration"`` into same-named :class:`ChordNode` attrs; unknown
      annotation keys are dropped with a Sphinx warning (via ``warn``).

    ``warn`` is an optional callable ``(message: str) -> None`` (e.g. a Sphinx
    logger's ``warning``); when ``None`` warnings are silently dropped (keeps
    the function usable in pure unit tests).
    """
    from .tokens import (  # local import: keeps tokens.py Sphinx-free path clean
        BarToken,
        ChordToken,
        LineBreakToken,
        LyricToken,
        SectionToken,
        SingerToken,
    )

    song = SongNode()
    song["song_meta"] = dict(song_meta) if song_meta else {}
    song["options"] = _reduce_options(options)

    # Container the current line's inline runs attach to: either the active
    # SectionNode or the SongNode itself (top-level / unlabeled content).
    current_section = None

    # Per-line state.
    current_line = None
    current_singer = None  # str singer id in effect (persists across lines)
    current_span = None  # active SingerSpanNode within the current line
    last_lyric_word = None  # (column, text) of the most recent lyric in line
    pending_chords = []  # chords on this line awaiting assoc_word resolution
    line_lyrics = []  # (column, text) of every lyric word seen on this line

    def _section_container():
        return current_section if current_section is not None else song

    def _resolve_pending_assoc():
        """Bind each pending chord to the lyric word it sits over (by column).

        The parser emits a line's chords and lyrics as two separate column-
        ordered streams (all chords, then all lyrics), so association is done
        positionally at line flush: a chord binds to the word whose span covers
        its column, else the nearest FOLLOWING word (the ``[G]Amazing`` layout),
        else — no word after it — the nearest PRECEDING word. A chord on a
        chord-only line stays unbound (assoc_word absent).
        """
        if not pending_chords or not line_lyrics:
            pending_chords.clear()
            return
        words = sorted(line_lyrics, key=lambda w: w[0])
        for chord in pending_chords:
            col = chord.get("column")
            if col is None:
                continue
            covering = following = preceding = None
            for wcol, wtext in words:
                if wcol <= col < wcol + len(wtext):
                    covering = wtext
                    break
                if wcol >= col and following is None:
                    following = wtext
                if wcol <= col:
                    preceding = wtext
            assoc = covering or following or preceding
            if assoc is not None:
                chord["assoc_word"] = assoc
        pending_chords.clear()

    def _open_line():
        nonlocal current_line, current_span, last_lyric_word
        current_line = LineNode()
        current_span = None
        last_lyric_word = None

    def _flush_line():
        nonlocal current_line, current_span, last_lyric_word
        _resolve_pending_assoc()
        if current_line is not None:
            _section_container().append(current_line)
        current_line = None
        current_span = None
        last_lyric_word = None
        line_lyrics.clear()

    def _inline_target():
        """Where an inline (chord/lyric) attaches: singer span or the line."""
        nonlocal current_span
        if current_line is None:
            _open_line()
        if current_singer is not None:
            if current_span is None:
                current_span = SingerSpanNode()
                current_span["singer"] = current_singer
                current_line.append(current_span)
            return current_span
        return current_line

    for tok in tokens:
        if isinstance(tok, SectionToken):
            _flush_line()
            if tok.kind == "none":
                current_section = None  # return to top-level content
            else:
                current_section = SectionNode()
                current_section["label"] = tok.label
                current_section["kind"] = tok.kind
                song.append(current_section)
            # A section boundary also ends any singer span (spans never cross).
            current_span = None

        elif isinstance(tok, LineBreakToken):
            _flush_line()

        elif isinstance(tok, SingerToken):
            # Positional context change: close the active span; the next inline
            # opens a fresh span for the new singer within the current line.
            current_singer = tok.singer or None
            current_span = None

        elif isinstance(tok, BarToken):
            continue  # ignored for untimed songs

        elif isinstance(tok, ChordToken):
            chord = ChordNode()
            chord["chord"] = tok.text
            chord["column"] = tok.column
            # Annotation → attr propagation.
            for key, value in tok.annotations:
                if key in _PROPAGATED_CHORD_ANNOTATIONS:
                    chord[key] = value
                else:
                    _emit_warning(
                        warn,
                        "doxtr-music: dropping unknown chord annotation "
                        "%r on chord %r" % (key, tok.text),
                    )
            # assoc_word (the lyric word this chord "sits over") is resolved
            # positionally at line flush (:func:`_resolve_pending_assoc`),
            # because the parser emits a line's chords and lyrics as two
            # separate column-ordered streams (all chords, then all lyrics).
            # Every chord is held pending until then.
            _inline_target().append(chord)
            pending_chords.append(chord)

        elif isinstance(tok, LyricToken):
            lyric = LyricNode(tok.text, tok.text)
            lyric["column"] = tok.column
            last_lyric_word = (tok.column, tok.text)
            line_lyrics.append((tok.column, tok.text))
            _inline_target().append(lyric)

        else:
            _emit_warning(
                warn, "doxtr-music: ignoring unknown token %r" % (tok,)
            )

    _flush_line()
    return song
