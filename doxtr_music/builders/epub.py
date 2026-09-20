"""EPUB visitors for the doxtr-music node tree (CHUNK-2-2).

Fills ``_VISITORS["epub"]`` (the CHUNK-1-2 seam) so the single SongNode tree
renders to **reflow-safe** EPUB, and ships EPUB's own minimal ``<pre>``
stylesheet. This module fills the ``"epub"`` bucket **only** — it never touches
``_VISITORS["html"]`` / ``["latex"]`` (owned by CHUNK-1-4/2-1). Registration
stays in :mod:`doxtr_music.nodes`; here we just assign function bodies into the
existing registry, and format resolution is by *builder name* (``epub*`` →
``"epub"``) — EPUB inherits ``format == "html"`` so name is the discriminator.

Reflow-safe render model (LOCKED — spec §4.3, ``pre`` strategy only)
--------------------------------------------------------------------

The HTML path positions chords absolutely above each lyric line; that is
reflow-fragile once an e-reader resizes fonts. EPUB instead renders each line as
a fixed-width ``<pre>`` with a **chord row above a lyric row**, aligned by
monospace character cells. Because both rows are monospace text, alignment
survives font resizing.

* **Cell vs codepoint (LOCKED caveat).** ``ChordNode.column`` / ``LyricNode``
  ``column`` are **codepoint** offsets; monospace alignment is by **display
  cell**. For single-width Latin, 1 codepoint = 1 cell. CJK/full-width count as
  2 cells, combining marks 0. We map codepoint → cell via East-Asian width
  (:func:`_cell_offset`) before emitting chord-row padding. Reliable non-Latin /
  complex-script alignment (and RTL) is the **future ``svg`` path's** job; the
  ``pre`` alignment test is scoped to single-width Latin.
* **Chord overrun policy (LOCKED).** A chord label is variable width
  (``F#m7b5``). We reserve ``max(1, len(chord)+1)`` cells and advance a **shared
  cursor** for both rows so chord and lyric rows stay column-locked when a label
  is wider than the gap to the next chord.
* **Lyric row = clean lyric stream.** The lyric row contains only lyric text (no
  chord glyphs), reconstructing inter-word spacing from column gaps (same
  authority as CHUNK-1-3). This is the copy contract below.

Per-format copy/selection contract (LOCKED — EPUB ``pre`` gate)
---------------------------------------------------------------

``COPY_SAFE_ORDER_EPUB_PRE``: the **lyric row** is extractable and equals the
logical lyric stream (space-joined words in logical order); the chord row is a
**separate run** (its own ``<span>``); the lyric row is **not**
``user-select:none``. The canonical per-format table lives in
``plan/chunks/CHUNK-2-2-epub-foundation.md``; CHUNK-3-4/4-1/4-2/4-3 MUST NOT
weaken it.

Accessibility seam (reserved for CHUNK-4-3)
-------------------------------------------

Each song ``<pre>`` block lives inside a wrapper element carrying
``class="doxtr-song"`` (shared marker with HTML) that CHUNK-4-3 can label (e.g.
``role="group"`` + a visually-hidden text alternative giving the chord↔word
reading, derived from ``assoc_word``). Any future ``svg`` output MUST carry a
text alternative (``<title>``/``<desc>`` or adjacent visually-hidden text) —
reserved now so ``svg`` is not a silent WCAG 1.1.1 trap. **CHUNK-4-3 owns EPUB
a11y; this chunk provides the wrapper hook.**

Soft dependency: this module never imports ``doxtr_pdf_theme_core`` and reads no
``doxtr_music_*`` config value (keeps the CHUNK-0-3 centralized-registration
invariant; a future ``doxtr_music_epub_strategy`` would be added to the 0-3
manifest when the ``svg`` strategy lands).
"""

from __future__ import annotations

import unicodedata

from docutils.nodes import SkipNode

from sphinx.util import logging as _sphinx_logging

from doxtr_music import nodes as _nodes

_LOG = _sphinx_logging.getLogger(__name__)

__all__ = ["register_epub_visitors", "EPUB_CSS_FILENAME"]

#: EPUB ships its own minimal ``<pre>`` stylesheet (monospace, no absolute
#: positioning) — NOT the CHUNK-1-4 absolute-positioning HTML CSS. It rides the
#: existing ``static/*`` package-data glob (CHUNK-0-1), so no ``package-data``
#: change is needed for this chunk.
EPUB_CSS_FILENAME = "doxtr_music_epub.css"


# ---------------------------------------------------------------------------
# Display-cell math (East-Asian width)
# ---------------------------------------------------------------------------

def _char_cells(ch):
    """Return the monospace display-cell width of a single character.

    Combining marks occupy 0 cells; East-Asian *wide* / *fullwidth* characters
    occupy 2; everything else occupies 1. This is the single authority the
    ``pre`` renderer uses to convert a codepoint offset into a cell offset.
    """
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def _text_cells(text):
    """Total display-cell width of ``text`` (sum of per-char cell widths)."""
    return sum(_char_cells(ch) for ch in text)


def _cell_offset(text, codepoint_column):
    """Map a 0-based *codepoint* column into a 0-based *display-cell* column.

    ``text`` is the logical (reading-order) lyric text of the line;
    ``codepoint_column`` indexes into it. The cell offset is the display width
    of ``text[:codepoint_column]``. A column past the end of ``text`` extends by
    one cell per extra codepoint (chords may sit beyond the last lyric char).
    """
    if codepoint_column <= 0:
        return 0
    prefix = text[:codepoint_column]
    cells = _text_cells(prefix)
    # A column beyond the logical text length: pad one cell per extra codepoint.
    if codepoint_column > len(text):
        cells += codepoint_column - len(text)
    return cells


# ---------------------------------------------------------------------------
# Line collection: gather chords + lyrics, then emit two <pre> rows
# ---------------------------------------------------------------------------
#
# The dispatcher visits inline nodes one at a time, but the reflow-safe render
# needs the whole line at once (to lay out a chord row over a lyric row). So the
# LineNode visitor opens a per-line buffer on the translator, chord/lyric
# visitors append to it, and the LineNode departer lays the two rows out.


def _line_buffer(self):
    """Return (creating if needed) the current line's collection buffer."""
    buf = getattr(self, "_dm_epub_line", None)
    if buf is None:
        buf = {"lyrics": [], "chords": [], "alts": [], "singers": set()}
        self._dm_epub_line = buf
    # Record the currently-open singer id (if any) for the per-line 1.4.1 cue.
    singer = getattr(self, "_dm_epub_singer", None)
    if singer:
        buf["singers"].add(singer)
    return buf


def _reconstruct_lyric_row(lyrics):
    """Rebuild the clean lyric stream string from column-positioned words.

    ``lyrics`` is a list of ``(cell_column, text, singer_color)`` in logical
    order. Inter-word spacing is reconstructed from the **cell** gap between
    adjacent words (same authority as CHUNK-1-3: spacing derives from column
    gaps, never stored). The returned string is the copy-contract lyric stream:
    words in logical order, single/multi space per the gap. Returns
    ``(row_text, segments)`` where ``segments`` is a list of
    ``(char_start, char_end, singer_color)`` character-index sub-ranges into
    ``row_text`` for each word carrying a singer color (CHUNK-4-2). The
    character indices are into the emitted row string so the caller can wrap
    exactly the word's characters in a colored span.
    """
    row = ""
    cursor = 0  # current display-cell position in ``row``
    segments = []  # (char_start, char_end, singer_color) for colored words
    for cell_col, text, singer_color in lyrics:
        # Pad to the word's cell column (never backwards; clamp to cursor).
        if cell_col > cursor:
            row += " " * (cell_col - cursor)
            cursor = cell_col
        char_start = len(row)
        row += text
        char_end = len(row)
        cursor += _text_cells(text)
        if singer_color:
            segments.append((char_start, char_end, singer_color))
    return row, segments


def _lyric_stream(lyrics):
    """The logical lyric stream: words space-joined in logical order.

    This is what ``COPY_SAFE_ORDER_EPUB_PRE`` extraction must equal. It is
    independent of alignment padding (single space between words).
    """
    return " ".join(text for _cell, text, _color in lyrics)


def _layout_chord_row(chords):
    """Lay out the chord row string over cell columns with the overrun policy.

    ``chords`` is a list of ``(cell_column, label, singer_color)`` in logical
    order. Each chord reserves ``max(1, len(label)+1)`` cells; a **shared
    cursor** prevents a wide label from colliding with the next chord (the next
    chord is pushed to at least ``cursor``), keeping both rows column-locked.
    Returns ``(row_text, segments)`` where ``segments`` is a list of
    ``(char_start, char_end, singer_color)`` character-index sub-ranges into
    ``row_text`` for each chord carrying a singer color (CHUNK-4-2), so the
    caller colors the correct cell sub-ranges on the chord row.
    """
    row = ""
    cursor = 0
    segments = []
    for cell_col, label, singer_color in chords:
        start = cell_col if cell_col > cursor else cursor
        if start > cursor:
            row += " " * (start - cursor)
            cursor = start
        char_start = len(row)
        row += label
        char_end = len(row)
        cursor += _text_cells(label)
        if singer_color:
            segments.append((char_start, char_end, singer_color))
        # Reserve a trailing separating cell so adjacent labels never touch.
        row += " "
        cursor += 1
    # rstrip trailing separators but keep segment indices valid (they only
    # index the labels, never the trailing spaces).
    return row.rstrip(), segments


# ---------------------------------------------------------------------------
# CHUNK-4-2: color sub-ranges of a rendered <pre> row (both rows)
# ---------------------------------------------------------------------------


def _color_segments(self, row, segments):
    """Return ``row`` HTML-escaped, with colored sub-ranges wrapped in spans.

    ``segments`` is a list of ``(char_start, char_end, color)`` character-index
    sub-ranges into ``row`` (from the layout helpers), one per chord/lyric that
    carries a WINNING singer color (CHUNK-4-2, resolved in Python). Each range
    is wrapped in ``<span style="color:<color>">...</span>`` so the run is
    colored on BOTH the chord row and the lyric row (the two-row model), while
    the uncolored gaps/words stay plain. Ranges are non-overlapping and in
    logical order; the surrounding text is escaped via the translator's own
    encoder (symmetric with the rest of this module). With no segments this is
    just ``self.encode(row)``.
    """
    if not segments:
        return self.encode(row)
    out = []
    cursor = 0
    for start, end, color in segments:
        if start > cursor:
            out.append(self.encode(row[cursor:start]))
        out.append(
            '<span style="color:%s">%s</span>'
            % (self.attval(color), self.encode(row[start:end]))
        )
        cursor = end
    if cursor < len(row):
        out.append(self.encode(row[cursor:]))
    return "".join(out)


# ---------------------------------------------------------------------------
# EPUB visitors
# ---------------------------------------------------------------------------
#
# All text is escaped at THIS boundary via the translator's own encoder (nodes
# store unescaped text), symmetric with the HTML/LaTeX visitors.


def _esc(self, text):
    return self.encode(text)


def _row_style(cell):
    """Return a per-song ``style="..."`` attr for an EPUB row span, or "".

    The EPUB two-row ``<pre>`` model renders one chord-row span and one
    lyric-row span per line, so per-song typography is applied to those row
    spans (not per glyph). ``cell`` is the resolved ``{attr: value}`` for the
    element; EPUB sizes are relative (reflow-safe). Returns ``""`` when unset.
    """
    from doxtr_music.typography import css_declarations

    if not cell:
        return ""
    decls = css_declarations(cell, relative_size=True)
    if not decls:
        return ""
    return ' style="%s"' % decls


def _song_typography(self):
    """Return the current song's resolved typography dict (set on visit_song)."""
    return getattr(self, "_dm_epub_typography", None) or {}


# ---- SongNode: a11y wrapper hook + shared marker --------------------------

def _visit_song(self, node):
    # The wrapper CHUNK-4-3 will label (role="group" + visually-hidden text
    # alternative). We provide it now with the shared ``doxtr-song`` marker so
    # the harness has a guaranteed hook and 4-3 need not reopen this chunk.
    # ``dir="auto"`` (CHUNK-3-4, documented+tested fallback): reflow-safe RTL
    # support at the wrapper level; true per-cell alignment for RTL/complex
    # scripts is the future ``svg`` path (CHUNK-2-2 lock). A best-effort
    # ``_warnings`` note fires from ``_depart_line`` when strong-RTL lyrics are
    # seen (once per song).
    song_id = node["ids"][0] if node.get("ids") else ""
    id_attr = ' id="%s"' % self.attval(song_id) if song_id else ""
    self._dm_epub_rtl_warned = False
    # Stash the song's resolved per-song typography (stamped by CHUNK-4-1's
    # stamp_typography onto SongNode['typography']) so the two-row <pre> spans
    # can style the chord/lyric rows without an ancestor walk.
    self._dm_epub_typography = node.get("typography") or {}
    # CHUNK-4-3 WCAG: name the song group (role="group" + aria-labelledby a real
    # title id, or aria-label="Song" fallback for a titleless song). The <pre>
    # rows have no positional DOM order, so a per-line hidden chord↔word
    # alternative is emitted as a SIBLING (outside the copyable <pre> lyric row)
    # by _depart_line — keeping the row-extract copy stream clean.
    meta = node.get("song_meta") or {}
    title = meta.get("title")
    has_title = isinstance(title, str) and bool(title)
    title_id = node.get("title_id", "")
    if has_title and title_id:
        group_name_attr = ' aria-labelledby="%s"' % self.attval(title_id)
    else:
        group_name_attr = ' aria-label="Song"'
    self.body.append(
        '<div class="doxtr-song doxtr-song-epub" role="group"%s dir="auto"%s>\n'
        % (group_name_attr, id_attr)
    )
    if has_title:
        title_style = _row_style((self._dm_epub_typography or {}).get("title"))
        title_id_attr = ' id="%s"' % self.attval(title_id) if title_id else ""
        self.body.append(
            '<p class="doxtr-song-title"%s%s>%s</p>\n'
            % (title_id_attr, title_style, _esc(self, title))
        )
    _emit_epub_song_meta(self, meta, self._dm_epub_typography or {})


def _emit_epub_song_meta(self, meta, resolved_typo):
    """Render the visible song-metadata block in EPUB (per-key styled).

    Mirrors the HTML metadata block (reusing the same row iterator + per-key
    fallback), emitting reflow-safe relative sizes. Copy-neutral: the block is
    outside the ``<pre>`` lyric rows, so the ``COPY_SAFE_ORDER_EPUB_PRE``
    row-extract stream is unaffected.
    """
    from doxtr_music.builders.html import _iter_display_meta
    from doxtr_music.typography import meta_element_names, resolve_element_cell

    rows = list(_iter_display_meta(meta))
    if not rows:
        return
    self.body.append('<dl class="doxtr-song-meta-list">\n')
    for key, label, value in rows:
        cell = resolve_element_cell(resolved_typo, meta_element_names(key))
        style = _row_style(cell)
        self.body.append(
            '<div class="doxtr-song-meta doxtr-song-meta-%s"%s>'
            '<dt class="doxtr-song-meta-label">%s</dt>'
            '<dd class="doxtr-song-meta-value">%s</dd></div>\n'
            % (self.attval(key), style, _esc(self, label), _esc(self, value))
        )
    self.body.append("</dl>\n")


def _depart_song(self, node):
    self._dm_epub_typography = None
    self.body.append("</div>\n")


# ---- SectionNode ----------------------------------------------------------

def _visit_section(self, node):
    kind = node.get("kind") or ""
    label = node.get("label") or ""
    cls = "doxtr-section"
    safe_kind = "".join(
        ch for ch in str(kind).lower() if ch.isalnum() or ch in "-_"
    )
    if safe_kind:
        cls += " doxtr-section-%s" % safe_kind
    self.body.append('<div class="%s">\n' % cls)
    if label:
        title_style = _row_style(node.get("typography_title"))
        self.body.append(
            '<p class="doxtr-section-label"%s>%s</p>\n'
            % (title_style, _esc(self, label))
        )
    body_style = _row_style(node.get("typography_body"))
    self.body.append('<div class="doxtr-section-body"%s>\n' % body_style)


def _depart_section(self, node):
    self.body.append("</div>\n")
    self.body.append("</div>\n")


# ---- LineNode: open a per-line buffer, then lay out two rows ---------------

def _visit_line(self, node):
    # Start a fresh buffer for this line's chords + lyrics.
    self._dm_epub_line = {"lyrics": [], "chords": [], "alts": [], "singers": set()}


def _depart_line(self, node):
    buf = getattr(self, "_dm_epub_line", None)
    self._dm_epub_line = None
    if buf is None:
        return
    lyrics = buf["lyrics"]  # list of (cell_col, text)
    chords = buf["chords"]  # list of (cell_col, label)

    lyric_row, lyric_segments = _reconstruct_lyric_row(lyrics)
    chord_row, chord_segments = _layout_chord_row(chords)

    # RTL documented+tested fallback (CHUNK-3-4): the ``<pre>`` + ``dir="auto"``
    # wrapper reflows, but exact per-cell alignment for strong-RTL scripts is the
    # future ``svg`` path (CHUNK-2-2). Fire a best-effort note once per song and
    # never crash.
    if lyric_row and not getattr(self, "_dm_epub_rtl_warned", False):
        from doxtr_music.engine.i18n import has_strong_rtl

        if has_strong_rtl(lyric_row):
            self._dm_epub_rtl_warned = True
            _LOG.warning(
                "[doxtr-music] RTL lyrics in EPUB use a reflow-safe <pre> "
                "fallback; exact chord alignment for right-to-left scripts "
                "awaits the SVG render path"
            )

    # Two separate runs inside one <pre>: the chord row above the lyric row.
    # The chord row is its own span (a separate run per the copy contract); the
    # lyric row is a separate, selectable span (NOT user-select:none). Per-song
    # typography (CHUNK-4-1) styles the row spans (chord/lyrics elements).
    typo = _song_typography(self)
    chord_style = _row_style(typo.get("chord"))
    lyric_style = _row_style(typo.get("lyrics"))
    self.body.append('<pre class="doxtr-line-epub">')
    if chord_row.strip():
        self.body.append(
            '<span class="doxtr-chordrow" aria-hidden="true"%s>%s</span>\n'
            % (chord_style, _color_segments(self, chord_row, chord_segments))
        )
    self.body.append(
        '<span class="doxtr-lyricrow"%s>%s</span>'
        % (lyric_style, _color_segments(self, lyric_row, lyric_segments))
    )
    self.body.append("</pre>\n")
    # CHUNK-4-3 WCAG: a11y siblings emitted OUTSIDE the copyable <pre> lyric row
    # (a separate container, never a child text node of the <pre>) so the
    # COPY_SAFE_ORDER_EPUB_PRE row-extract stream excludes them.
    _emit_line_a11y(self, buf)


def _emit_line_a11y(self, buf):
    """Emit the per-line a11y siblings after the <pre> (copy-neutral).

    * A **visible** non-color singer cue (WCAG 1.4.1) for each singer present on
      the line, so sighted color-blind users distinguish runs without color.
    * A visually-hidden chord↔word text alternative (WCAG 1.3.1) giving screen
      readers the linear chord↔word reading the two-row <pre> lacks.

    Both live in a ``.doxtr-line-a11y`` sibling of the <pre> — never inside the
    <pre> lyric row — so the row-extract copy stream stays clean. The hidden
    alternative uses the EPUB-safe visually-hidden style (no position:absolute,
    which the EPUB_PRE_FALLBACK gate forbids).
    """
    from doxtr_music.a11y import (
        VISUALLY_HIDDEN_STYLE,
        singer_sr_label,
        singer_visible_cue,
    )

    cues = []
    for sid in sorted(buf.get("singers") or ()):
        cue = singer_visible_cue(sid)
        if cue:
            cues.append(
                '<span class="doxtr-singer-cue">%s</span>' % _esc(self, cue)
            )
    alts = [a for a in (buf.get("alts") or ()) if a]
    if not cues and not alts:
        return
    self.body.append('<div class="doxtr-line-a11y">')
    for cue in cues:
        self.body.append(cue)
    for sid in sorted(buf.get("singers") or ()):
        sr = singer_sr_label(sid)
        if sr:
            self.body.append(
                '<span class="doxtr-sr-only" style="%s">%s</span>'
                % (VISUALLY_HIDDEN_STYLE, _esc(self, sr))
            )
    for alt in alts:
        self.body.append(
            '<span class="doxtr-sr-only" style="%s">%s</span>'
            % (VISUALLY_HIDDEN_STYLE, _esc(self, alt))
        )
    self.body.append("</div>\n")


# ---- ChordNode: collect into the line buffer (no direct emit) --------------

def _visit_chord(self, node):
    from doxtr_music.engine.i18n import resolve_chord_display

    # Shared display resolution (CHUNK-3-4): roman-if-set (replace mode) else
    # localize the effective (post-transpose) chord to the configured system.
    label = resolve_chord_display(node, self.config)
    # A ``:chord:`` role (CHUNK-3-5) is inline prose, NOT part of the song
    # two-row <pre> layout: emit an inline ``.doxtr-chord-inline`` span directly
    # (like HTML), never buffering into a line. No ``aria-hidden`` (readable
    # prose — CHUNK-4-3 exempt).
    if node.get("inline_role"):
        self.body.append(
            '<span class="doxtr-chord-inline"%s>%s</span>'
            % (_row_style(node.get("typography")), _esc(self, label))
        )
        raise SkipNode
    buf = _line_buffer(self)
    column = node.get("column")
    lyric_text = _line_lyric_text(node)
    if column is None:
        cell = 0
    else:
        cell = _cell_offset(lyric_text, column)
    # CHUNK-4-2: carry the run's WINNING singer color (stamped in Python) so the
    # chord-row layout can color this label's cell sub-range on the chord row.
    buf["chords"].append((cell, label, node.get("singer_color")))
    # CHUNK-4-3 WCAG: collect the linear chord↔word reading for the hidden
    # alternative emitted OUTSIDE the <pre> (the two-row <pre> has no positional
    # DOM order, so the alternative gives screen readers the chord↔word link).
    from doxtr_music.a11y import epub_chord_word_alt

    buf.setdefault("alts", []).append(
        epub_chord_word_alt(label, node.get("assoc_word") or "")
    )
    raise SkipNode


def _depart_chord(self, node):  # pragma: no cover - SkipNode short-circuits
    pass


# ---- LyricNode: collect into the line buffer (no direct emit) --------------

def _visit_lyric(self, node):
    buf = _line_buffer(self)
    text = node.astext()
    column = node.get("column")
    lyric_text = _line_lyric_text(node)
    if column is None:
        cell = _current_lyric_cursor(buf)
    else:
        cell = _cell_offset(lyric_text, column)
    # CHUNK-4-2: carry the run's WINNING singer color so the lyric-row layout
    # can color this word's cell sub-range on the lyric row (both rows colored).
    buf["lyrics"].append((cell, text, node.get("singer_color")))
    raise SkipNode


def _depart_lyric(self, node):  # pragma: no cover - SkipNode short-circuits
    pass


def _current_lyric_cursor(buf):
    """Fallback cell column for a column-less lyric word: after the last one."""
    if not buf["lyrics"]:
        return 0
    last_cell, last_text, _color = buf["lyrics"][-1]
    return last_cell + _text_cells(last_text) + 1


def _line_lyric_text(node):
    """Reconstruct the covering line's logical lyric text for cell mapping.

    ``ChordNode.column`` / ``LyricNode.column`` are offsets into the *line's*
    de-bracketed lyric text (CHUNK-1-3). We recover that text by concatenating
    the line's lyric words at their columns so the East-Asian-width cell mapping
    sees the same string the parser measured. Reads sibling nodes' plain attrs
    only (no cross-node objects, parallel-safe).
    """
    line = node
    while line is not None and not isinstance(line, _nodes.LineNode):
        line = line.parent
    if line is None:
        return node.astext() if isinstance(node, _nodes.LyricNode) else ""
    words = []
    for lyr in line.findall(_nodes.LyricNode):
        col = lyr.get("column")
        if col is None:
            continue
        words.append((col, lyr.astext()))
    if not words:
        return ""
    words.sort(key=lambda item: item[0])
    text = ""
    for col, word in words:
        if col > len(text):
            text += " " * (col - len(text))
        # Overlapping columns should not happen; append defensively.
        text = text[:col] + word + text[col + len(word):]
    return text


# ---- SingerSpanNode: transparent (children collect into the buffer) --------
#
# Color/visible-cue handling for singers in EPUB is CHUNK-4-2/4-3's job via the
# reserved stamps; here the span is transparent so its chord/lyric children
# still collect into the current line buffer.

def _visit_singer(self, node):
    # Track the current singer id so per-line a11y (the visible 1.4.1 cue) can
    # be emitted as a sibling of the <pre> (copy-neutral). The span itself stays
    # transparent so its chord/lyric children still collect into the line buffer.
    self._dm_epub_singer = node.get("singer") or ""


def _depart_singer(self, node):
    self._dm_epub_singer = None


# ---- RomanNode: a standalone roman numeral (:roman: role / progression cell) --
#
# CHUNK-3-3 owns the RomanNode EPUB visitor for all three formats. A standalone
# roman is meaningful selectable text rendered inline (a ``.doxtr-roman`` span),
# NOT part of the song two-row <pre> layout — it appears in normal flow (role /
# progression cell), so it emits directly rather than buffering into a line.


def _visit_roman(self, node):
    from docutils.nodes import SkipNode

    from doxtr_music.a11y import roman_aria_label

    numeral = node.get("roman", "")
    # Author-literal ``:roman:`` role = readable prose (a11y-exempt); a musical
    # roman (analysis / progression) gets the atomic role="img" label.
    if node.get("inline_role"):
        self.body.append(
            '<span class="doxtr-roman"%s>%s</span>'
            % (_row_style(node.get("typography")), _esc(self, numeral))
        )
        raise SkipNode
    self.body.append(
        '<span class="doxtr-roman" role="img" aria-label="%s"%s>%s</span>'
        % (self.attval(roman_aria_label(numeral)),
           _row_style(node.get("typography")), _esc(self, numeral))
    )
    raise SkipNode


def _depart_roman(self, node):  # pragma: no cover - SkipNode short-circuits
    pass


# ---- KeyNode: a standalone key name (:key: role, CHUNK-3-5) ----------------
#
# A key is meaningful selectable prose text rendered inline as a ``.doxtr-key``
# span (NOT part of the song two-row <pre> layout). It is localized as a note
# name (root + optional ``m`` minor mode) via localize_chord; free-text keys
# pass through unchanged. No ``aria-hidden`` (readable prose).


def _visit_key(self, node):
    from docutils.nodes import SkipNode

    from doxtr_music.engine.i18n import resolve_key_display

    key = node.get("key", "")
    display = resolve_key_display(key, self.config)
    self.body.append('<span class="doxtr-key">%s</span>' % _esc(self, display))
    raise SkipNode


def _depart_key(self, node):  # pragma: no cover - SkipNode short-circuits
    pass


# ---------------------------------------------------------------------------
# ChordProgressionNode grid (CHUNK-4-4) — a genuine XHTML <table>, no lyrics
# ---------------------------------------------------------------------------
#
# A progression is a genuine data grid (chords/roman, no chord-over-lyric
# alignment), so it renders as an XHTML ``<table>`` — NOT the ``<pre>`` two-row
# model (that is for chord-over-lyric songs). The table sets no fixed pixel
# width and allows wrap/scroll so a wide grid (8+ cols) degrades acceptably on
# narrow viewports. Self-contained a11y: a ``<caption>`` names the progression.
# Chord cells localize via ``localize_chord`` directly (separate-roman-cell
# model). The whole table is emitted in the container visit + SkipNode so it
# never enters the song ``<pre>`` line-buffer machinery.


def _visit_progression(self, node):
    from docutils.nodes import SkipNode

    from doxtr_music.a11y import roman_aria_label
    from doxtr_music.builders._progression import classify_progression_cell

    out = ['<table class="doxtr-progression">']
    out.append('<caption class="doxtr-sr-only">Chord progression</caption>')
    out.append("<tbody>")
    rows = [c for c in node.children if isinstance(c, _nodes.ProgressionRowNode)]
    for row in rows:
        out.append("<tr>")
        for cell in row.children:
            if not isinstance(cell, _nodes.ProgressionCellNode):
                continue
            result = classify_progression_cell(cell, self.config)
            kind = result[0]
            if kind == "chord":
                _, display, roman = result
                piece = (
                    '<td class="doxtr-progression-cell">'
                    '<span class="doxtr-chord">%s</span>' % _esc(self, display)
                )
                if roman:
                    piece += (
                        ' <span class="doxtr-roman" role="img" aria-label="%s">'
                        '%s</span>'
                        % (self.attval(roman_aria_label(roman)),
                           _esc(self, roman))
                    )
                out.append(piece + "</td>")
            elif kind == "roman":
                numeral = result[1]
                out.append(
                    '<td class="doxtr-progression-cell">'
                    '<span class="doxtr-roman" role="img" aria-label="%s">'
                    '%s</span></td>'
                    % (self.attval(roman_aria_label(numeral)),
                       _esc(self, numeral))
                )
            else:  # empty / spacer / literal passthrough
                out.append(
                    '<td class="doxtr-progression-cell">%s</td>'
                    % _esc(self, result[1])
                )
        out.append("</tr>")
    out.append("</tbody></table>\n")
    self.body.append("".join(out))
    raise SkipNode


def _depart_progression(self, node):  # pragma: no cover - SkipNode short-circuits
    pass


# ---------------------------------------------------------------------------
# Registration into the _VISITORS["epub"] seam
# ---------------------------------------------------------------------------

def register_epub_visitors():
    """Assign the EPUB visitor bodies into ``_VISITORS["epub"]``.

    Called from :func:`doxtr_music.setup`. Fills the ``epub`` bucket by plain
    dict assignment (never ``add_node(override=True)``, never editing
    ``nodes.py``), **replacing the CHUNK-1-2 epub no-op stubs** so a write-only
    ``-b epub`` build exercises real renderers. Symmetric with 2-1's
    ``register_latex_visitors``. CHUNK-3-3 fills the ``RomanNode`` EPUB visitor
    here (inline ``.doxtr-roman`` span), so its dispatcher renders rather than
    no-ops.
    """
    epub = _nodes._VISITORS["epub"]
    epub[_nodes.SongNode] = (_visit_song, _depart_song)
    epub[_nodes.SectionNode] = (_visit_section, _depart_section)
    epub[_nodes.LineNode] = (_visit_line, _depart_line)
    epub[_nodes.ChordNode] = (_visit_chord, _depart_chord)
    epub[_nodes.LyricNode] = (_visit_lyric, _depart_lyric)
    epub[_nodes.SingerSpanNode] = (_visit_singer, _depart_singer)
    epub[_nodes.RomanNode] = (_visit_roman, _depart_roman)
    # CHUNK-3-5 adds ONLY the new KeyNode visitor by plain dict assignment.
    epub[_nodes.KeyNode] = (_visit_key, _depart_key)
    # CHUNK-4-4 adds the progression grid: the container visitor emits the whole
    # XHTML table and SkipNodes, so Row/Cell need no separate visitors.
    epub[_nodes.ChordProgressionNode] = (_visit_progression, _depart_progression)
