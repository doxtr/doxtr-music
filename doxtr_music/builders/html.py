"""Copy-safe HTML visitors for the doxtr-music node tree (CHUNK-1-4).

Populates ``_VISITORS["html"]`` (the CHUNK-1-2 seam) with real visit/depart
bodies. This module fills the ``"html"`` bucket **only** — it never touches
``_VISITORS["latex"]`` / ``["epub"]`` (owned by CHUNK-2-1/2-2). Registration
stays in :mod:`doxtr_music.nodes`; here we just assign function bodies into the
existing registry, so later chunks add LaTeX/EPUB without editing this file.

Chord DOM contract (LOCKED — inherited by 3-4/4-2/4-3 and EPUB)
--------------------------------------------------------------

A chord is a **real inline element** carrying the chord as *text*, made
non-selectable::

    <span class="doxtr-chord" data-chord="Am" aria-hidden="true">Am</span>

with ``user-select: none`` and absolute positioning (see the CSS). Chords are
NOT rendered via ``::before { content: attr(data-chord) }`` — pseudo-element
content can neither carry the ``aria-label`` CHUNK-4-3 needs nor survive CSS
stripping (EPUB reflow), breaking accessibility + EPUB parity. The real chord
text lets CHUNK-4-3 swap ``aria-hidden`` for ``role="img"`` + ``aria-label`` and
lets CHUNK-3-4 localize the glyph — both without editing this file.
``data-chord`` remains as a redundant static hook (harness marker).

Copy-safety model (LOCKED PERMANENT GATE)
-----------------------------------------

Lyrics are the only *selectable* inline text, in logical DOM order; chord spans
are ``user-select: none`` and DOM-adjacent (never interleaved into lyric text).
``COPY_SAFE_ORDER_HTML``: after stripping every ``.doxtr-chord`` /
``.doxtr-singer`` wrapper from a ``.doxtr-song``, the residual text equals the
concatenated lyric tokens in logical order, and every chord span carries
``user-select:none``. CHUNK-3-4/4-1/4-2/4-3 MUST keep this unchanged.
"""

from __future__ import annotations

from docutils.nodes import SkipNode

from doxtr_music import nodes as _nodes

__all__ = ["register_html_visitors"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(translator, text):
    """HTML-escape ``text`` using the translator's own encoder."""
    return translator.encode(text)


def _kind_class(kind):
    """Return a safe CSS class fragment for a section kind."""
    if not kind:
        return ""
    safe = "".join(ch for ch in str(kind).lower() if ch.isalnum() or ch in "-_")
    return safe


def _style_attr(node, *, epub=False):
    """Return a per-song ``style="..."`` attr from the stamped typography, or "".

    Per-song typography is stamped onto the styleable child nodes (CHUNK-4-1's
    ``stamp_typography``) as a plain ``{attr: value}`` dict under the reserved
    ``typography`` node attr. Shared class CSS can't vary per song, so per-song
    styling rides an inline ``style`` (LOCKED). GLOBAL typography rides the
    injected ``<style>`` class rules instead. Returns ``""`` when nothing is
    stamped.

    Singer color (CHUNK-4-2) is folded in here as the **color winner**: when a
    ``singer_color`` is stamped on the node it overrides the typography *color*
    only (font/size stay), so the element emits a single resolved inline color
    (no CSS cascade contest). "Resolve in Python, emit once" -- the winner is
    decided at stamp time; this helper only reads the stamped plain attrs.
    """
    from doxtr_music.typography import css_declarations

    cell = node.get("typography")
    singer_color = node.get("singer_color")
    if singer_color:
        cell = dict(cell or {})
        cell["color"] = singer_color
    if not cell:
        return ""
    decls = css_declarations(cell, relative_size=epub)
    if not decls:
        return ""
    return ' style="%s"' % decls


def _style_attr_cell(cell, *, epub=False):
    """Return a ``style="..."`` attr from a resolved ``{attr: value}`` cell, or ""."""
    from doxtr_music.typography import css_declarations

    if not cell:
        return ""
    decls = css_declarations(cell, relative_size=epub)
    return ' style="%s"' % decls if decls else ""


#: Song-metadata keys rendered as a visible metadata block (in this order), plus
#: any other author-supplied keys. ``title`` is rendered separately (the song
#: title element); internal ``_``-prefixed keys and ``transpose`` are skipped.
_META_DISPLAY_LABELS = {
    "key": "Key",
    "tempo": "Tempo",
    "capo": "Capo",
    "artist": "Artist",
    "composer": "Composer",
    "album": "Album",
    "year": "Year",
    "time": "Time",
    "subtitle": "Subtitle",
}
_META_SKIP = frozenset({"title", "transpose"})


def _iter_display_meta(meta):
    """Yield ``(key, label, value)`` for each renderable metadata row.

    Skips the title (rendered as the song title), internal ``_``-prefixed keys,
    and control keys (``transpose``). Known keys use a friendly label; unknown
    author keys are title-cased. Preserves a stable, readable order (known keys
    first in ``_META_DISPLAY_LABELS`` order, then any extras alphabetically).
    """
    if not isinstance(meta, dict):
        return
    seen = set()
    for key in _META_DISPLAY_LABELS:
        if key in meta and key not in _META_SKIP:
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                seen.add(key)
                yield key, _META_DISPLAY_LABELS[key], value.strip()
    for key in sorted(meta):
        if key in seen or key in _META_SKIP or key.startswith("_"):
            continue
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            yield key, key.replace("_", " ").title(), value.strip()


# ---------------------------------------------------------------------------
# SongNode — <div class="doxtr-song" role="group"> + title element
# ---------------------------------------------------------------------------

def _visit_song(self, node):
    song_id = node["ids"][0] if node.get("ids") else ""
    title_id = node.get("title_id", "")
    meta = node.get("song_meta") or {}
    title = meta.get("title")

    id_attr = ' id="%s"' % self.attval(song_id) if song_id else ""
    dir_attr = ' dir="auto"'  # logical alignment; CHUNK-3-4 may switch to rtl
    # CHUNK-4-3 WCAG: name the group. When the song has a non-empty title we
    # point ``aria-labelledby`` at the title element's id; a titleless song
    # falls back to ``aria-label="Song"`` (never emit aria-labelledby pointing
    # at a missing/empty id). Only the song gets role="group" (singer runs do
    # NOT nest a group — avoids SR group-nesting noise).
    has_title = isinstance(title, str) and bool(title)
    if has_title and title_id:
        group_name_attr = ' aria-labelledby="%s"' % self.attval(title_id)
    else:
        group_name_attr = ' aria-label="Song"'
    self.body.append(
        '<div class="doxtr-song" role="group"%s%s%s>\n'
        % (group_name_attr, id_attr, dir_attr)
    )
    # A title element carrying id=title_id so aria-labelledby has a real target
    # even when the song has no {title} metadata (empty then). Title styling
    # (font/size/color/background) comes from the resolved ``title`` cell.
    resolved_typo = node.get("typography") or {}
    title_text = _esc(self, title) if has_title else ""
    title_id_attr = ' id="%s"' % self.attval(title_id) if title_id else ""
    title_style = _style_attr_cell(resolved_typo.get("title"))
    self.body.append(
        '<p class="doxtr-song-title"%s%s>%s</p>\n'
        % (title_id_attr, title_style, title_text)
    )
    # Song-metadata block: render each renderable metadata row (key/tempo/…)
    # styled by its per-key cell (``meta-<key>`` over the generic ``metadata``).
    _emit_song_meta(self, meta, resolved_typo)
    # CHUNK-5-4 html_visit plugin hook: HTML-only custom injection point. The
    # hook(s) append to ``translator.body`` INSIDE a ``.doxtr-hook`` wrapper,
    # which the COPY_SAFE_ORDER_HTML strip removes by construction — so injected
    # markup can never pollute the copyable lyric stream (the strip set includes
    # ``doxtr-hook``). Config-value hook first, then registered hooks; each
    # exception is warned + skipped (never crashes the build). Only emitted when
    # a hook exists, so the wrapper is absent for the common no-hook case.
    _emit_html_visit(self, node)


def _emit_html_visit(self, node):
    """Invoke the ``html_visit`` hooks inside a copy-neutral ``.doxtr-hook`` wrapper.

    HTML-only (this module fills only ``_VISITORS["html"]`` — LaTeX/EPUB never
    fire it). The wrapper is opened only when at least one hook exists so a
    hook-free build emits no extra markup. Copy-safety (LOCKED): the wrapper
    carries ``doxtr-hook``, which the COPY_SAFE_ORDER_HTML strip removes.
    """
    from doxtr_music.hooks import (
        _html_visit_hooks,
        run_html_visit,
    )

    config = getattr(self, "config", None)
    has_config_hook = False
    if config is not None:
        has_config_hook = (
            getattr(config, "doxtr_music_html_visit_resolved", None) is not None
        )
    if not has_config_hook and not _html_visit_hooks:
        return
    self.body.append('<span class="doxtr-hook" aria-hidden="true">')
    run_html_visit(node, self, config)
    self.body.append("</span>")


def _depart_song(self, node):
    self.body.append("</div>\n")


def _emit_song_meta(self, meta, resolved_typo):
    """Render the visible song-metadata block (key/tempo/…), per-key styled.

    Each row is ``<p class="doxtr-song-meta doxtr-song-meta-<key>">`` with a
    bold ``<span class="doxtr-song-meta-label">`` and the value. The per-key
    typography cell (``meta-<key>`` over the generic ``metadata``) is applied
    inline. No block is emitted when the song has no renderable metadata, so a
    bare song is unchanged. The metadata block is copy-neutral (outside any
    lyric line) and carries no song-chord classes.
    """
    from doxtr_music.typography import meta_element_names, resolve_element_cell

    rows = list(_iter_display_meta(meta))
    if not rows:
        return
    self.body.append('<dl class="doxtr-song-meta-list">\n')
    for key, label, value in rows:
        cell = resolve_element_cell(resolved_typo, meta_element_names(key))
        style = _style_attr_cell(cell)
        self.body.append(
            '<div class="doxtr-song-meta doxtr-song-meta-%s"%s>'
            '<dt class="doxtr-song-meta-label">%s</dt>'
            '<dd class="doxtr-song-meta-value">%s</dd></div>\n'
            % (self.attval(key), style, _esc(self, label), _esc(self, value))
        )
    self.body.append("</dl>\n")


# ---------------------------------------------------------------------------
# SectionNode — labeled <section>
# ---------------------------------------------------------------------------

def _visit_section(self, node):
    kind = _kind_class(node.get("kind"))
    label = node.get("label") or ""
    cls = "doxtr-section"
    if kind:
        cls += " doxtr-section-%s" % kind
    self.body.append('<section class="%s">\n' % cls)
    if label:
        title_style = _style_attr_cell(node.get("typography_title"))
        self.body.append(
            '<p class="doxtr-section-label"%s>%s</p>\n'
            % (title_style, _esc(self, label))
        )
    # A body wrapper carries the section-body styling (font/size/color/bg) so it
    # applies to the whole section's lines. Always emitted (even unstyled) so
    # the DOM shape is stable and the global ``section-body`` CSS has a target.
    body_style = _style_attr_cell(node.get("typography_body"))
    self.body.append('<div class="doxtr-section-body"%s>\n' % body_style)


def _depart_section(self, node):
    self.body.append("</div>\n")
    self.body.append("</section>\n")


# ---------------------------------------------------------------------------
# LineNode — position-context line box
# ---------------------------------------------------------------------------

def _visit_line(self, node):
    self.body.append('<div class="doxtr-line">')


def _depart_line(self, node):
    self.body.append("</div>\n")


# ---------------------------------------------------------------------------
# ChordNode — the real, non-selectable chord span (positioned above)
# ---------------------------------------------------------------------------

def _visit_chord(self, node):
    # Effective English chord kept for the ``data-chord`` source-recovery hook.
    # The VISIBLE display string is resolved by the single shared helper
    # (CHUNK-3-4): roman-if-set (replace mode) else localize to the configured
    # chord system. Localization is the last render step, applied to the
    # effective (post-transpose) chord (CHUNK-3-2 contract).
    from doxtr_music.engine.i18n import resolve_chord_display

    chord = node.get("chord", "")
    effective = node.get("transposed") or chord
    display = resolve_chord_display(node, self.config)
    # A ``:chord:`` role (CHUNK-3-5) is ordinary readable prose text, NOT a
    # positioned song chord. It uses the distinct ``.doxtr-chord-inline`` class
    # (no absolute positioning / no ``user-select:none`` / no ``aria-hidden``)
    # so the song-chord CSS never leaks onto prose chords and CHUNK-4-3 need not
    # touch role output.
    if node.get("inline_role"):
        self.body.append(
            '<span class="doxtr-chord-inline" data-chord="%s"%s>%s</span>'
            % (self.attval(effective), _style_attr(node), _esc(self, display))
        )
        return
    # The element stays a real, non-selectable .doxtr-chord span so the copy-safe
    # DOM order is unaffected. ``data-chord`` keeps the effective English chord
    # so tooling/tests can still recover the source chord behind a numeral or a
    # localized glyph. Per-song typography rides an inline ``style`` (CHUNK-4-1).
    #
    # CHUNK-4-3 WCAG: swap the CHUNK-1-4 interim ``aria-hidden="true"`` for
    # ``role="img"`` + ``aria-label`` (a bare generic span's aria-label is not
    # reliably announced by NVDA/Chrome; role="img" gives an atomic accessible
    # name and suppresses the redundant visible-text read). HTML relies on DOM
    # proximity to the following lyric word, so the label is ``Chord: <display>``
    # only (no ``, word: ...`` — that would duplicate the adjacent lyric read).
    from doxtr_music.a11y import chord_aria_label

    inner = _chord_inner_html(self, node, display)
    self.body.append(
        '<span class="doxtr-chord" data-chord="%s" role="img" aria-label="%s"%s>'
        '%s</span>'
        % (self.attval(effective), self.attval(chord_aria_label(display)),
           _style_attr(node), inner)
    )


def _chord_inner_html(self, node, display):
    """Return the chord span's inner HTML, styling an alongside numeral part.

    In ``alongside`` mode the numeral segment is wrapped in an inner
    ``<span class="doxtr-roman-inline">`` carrying the resolved ``roman``
    typography (font/size/color) so the numeral can look different from the
    chord.  Newline segments become ``<br>`` (a stacked ``{chord}\n{roman}``
    template).  For ``off``/``replace`` there is a single part, so this is just
    the escaped display text.
    """
    from doxtr_music.engine.i18n import resolve_chord_display_parts

    parts = resolve_chord_display_parts(node, self.config)
    if len(parts) == 1:
        return _esc(self, display)
    roman_style = _style_attr_cell(node.get("roman_typography"))
    out = []
    for kind, text in parts:
        if kind == "roman":
            out.append(
                '<span class="doxtr-roman-inline"%s>%s</span>'
                % (roman_style, _esc(self, text))
            )
        else:
            # chord / literal: escape; a newline becomes a <br> for stacking.
            out.append(_esc(self, text).replace("\n", "<br>"))
    return "".join(out)


def _depart_chord(self, node):
    pass  # self-contained inline element


# ---------------------------------------------------------------------------
# LyricNode — inline selectable text (the only copyable content)
# ---------------------------------------------------------------------------

def _visit_lyric(self, node):
    text = node.astext()
    self.body.append(
        '<span class="doxtr-lyric"%s>%s</span>'
        % (_style_attr(node), _esc(self, text))
    )
    raise SkipNode


def _depart_lyric(self, node):  # pragma: no cover - SkipNode short-circuits
    pass


# ---------------------------------------------------------------------------
# SingerSpanNode — transparent wrapper (color added in CHUNK-4-2)
# ---------------------------------------------------------------------------

def _visit_singer(self, node):
    from doxtr_music.a11y import (
        VISUALLY_HIDDEN_STYLE,
        singer_sr_label,
        singer_visible_cue,
    )

    singer = node.get("singer", "")
    self.body.append(
        '<span class="doxtr-singer" data-singer="%s">' % self.attval(singer)
    )
    # CHUNK-4-3 WCAG 1.4.1 (Use of Color): a VISIBLE non-color cue so sighted
    # color-blind users distinguish singer runs without relying on color. It is
    # a real DOM element INSIDE the .doxtr-singer wrapper, which the COPY_SAFE
    # strip removes — so the copied lyric stream excludes it (copy-neutral).
    # No ``::before`` on any lyric element (that pollutes the copy buffer).
    cue = singer_visible_cue(singer)
    if cue:
        self.body.append(
            '<span class="doxtr-singer-cue" aria-hidden="true">%s</span>'
            % _esc(self, cue)
        )
    # An ADDITIONAL SR-only label (WCAG 1.3.1 / 4.1.2), also inside the stripped
    # wrapper. Not the 1.4.1 mechanism (which must be visible) — a layered
    # affordance. Visually hidden without position:absolute (EPUB parity habit).
    sr = singer_sr_label(singer)
    if sr:
        self.body.append(
            '<span class="doxtr-sr-only" style="%s">%s</span>'
            % (VISUALLY_HIDDEN_STYLE, _esc(self, sr))
        )


def _depart_singer(self, node):
    self.body.append("</span>")


# ---------------------------------------------------------------------------
# RomanNode — a standalone roman numeral (:roman: role / progression cell)
# ---------------------------------------------------------------------------
#
# CHUNK-3-3 owns the RomanNode HTML visitor for all three formats. It renders a
# selectable ``.doxtr-roman`` span holding the numeral (standalone romans ARE
# meaningful text, unlike positioned chord labels). A chord *displayed with* its
# roman is handled by the chord visitor's replace-mode, not this node.


def _visit_roman(self, node):
    from doxtr_music.a11y import roman_aria_label

    numeral = node.get("roman", "")
    # An author-literal ``:roman:`` role is readable prose (a11y-exempt, like the
    # inline ``:chord:`` role): emit a plain selectable span. A musical roman
    # (analysis / progression cell) carries role="img" + aria-label so screen
    # readers announce "Roman numeral: IV" atomically rather than a bare glyph.
    if node.get("inline_role"):
        self.body.append(
            '<span class="doxtr-roman"%s>%s</span>'
            % (_style_attr(node), _esc(self, numeral))
        )
        return
    self.body.append(
        '<span class="doxtr-roman" role="img" aria-label="%s"%s>%s</span>'
        % (self.attval(roman_aria_label(numeral)), _style_attr(node),
           _esc(self, numeral))
    )


def _depart_roman(self, node):
    pass  # self-contained inline element


# ---------------------------------------------------------------------------
# KeyNode — a standalone key name (:key: role, CHUNK-3-5)
# ---------------------------------------------------------------------------
#
# A key is meaningful, selectable prose text rendered inline as a
# ``.doxtr-key`` span. It is localized as a NOTE NAME (root + optional ``m``
# minor-mode suffix) via ``localize_chord`` so minor keys localize (``Bm``→``Hm``
# in German); a free-text (non-note) key passes through unchanged. No
# ``aria-hidden`` (ordinary readable prose — CHUNK-4-3 exempt).


def _visit_key(self, node):
    from doxtr_music.engine.i18n import resolve_key_display

    key = node.get("key", "")
    display = resolve_key_display(key, self.config)
    self.body.append('<span class="doxtr-key">%s</span>' % _esc(self, display))


def _depart_key(self, node):
    pass  # self-contained inline element


# ---------------------------------------------------------------------------
# ChordProgressionNode grid (CHUNK-4-4) — a semantic <table>, no lyrics
# ---------------------------------------------------------------------------
#
# A progression is a genuine data grid (chords/roman, no chord-over-lyric
# alignment), so it renders as a self-contained semantic ``<table>`` with a
# ``<caption>`` (WCAG data-table semantics, sufficient for a static grid — NOT
# dependent on the song-scoped CHUNK-4-3). Chord cells localize via
# ``localize_chord`` directly (the separate-roman-cell model, distinct from a
# song ``ChordNode.roman`` annotation); a chord cell that also carries a computed
# ``roman`` (``:roman-numerals:`` + ``:key:``) renders the chord then the numeral.


def _visit_progression(self, node):
    self.body.append('<table class="doxtr-progression">')
    self.body.append(
        '<caption class="doxtr-sr-only">Chord progression</caption>'
    )
    self.body.append("<tbody>")


def _depart_progression(self, node):
    self.body.append("</tbody></table>\n")


def _visit_progression_row(self, node):
    self.body.append("<tr>")


def _depart_progression_row(self, node):
    self.body.append("</tr>")


def _visit_progression_cell(self, node):
    from doxtr_music.builders._progression import classify_progression_cell

    result = classify_progression_cell(node, self.config)
    kind = result[0]
    if kind == "chord":
        _, display, roman = result
        self.body.append(
            '<td class="doxtr-progression-cell"><span class="doxtr-chord">'
            '%s</span>' % _esc(self, display)
        )
        if roman:
            from doxtr_music.a11y import roman_aria_label
            self.body.append(
                ' <span class="doxtr-roman" role="img" aria-label="%s">'
                '%s</span>'
                % (self.attval(roman_aria_label(roman)), _esc(self, roman))
            )
        self.body.append("</td>")
        raise SkipNode
    if kind == "roman":
        from doxtr_music.a11y import roman_aria_label

        numeral = result[1]
        self.body.append(
            '<td class="doxtr-progression-cell"><span class="doxtr-roman" '
            'role="img" aria-label="%s">%s</span></td>'
            % (self.attval(roman_aria_label(numeral)), _esc(self, numeral))
        )
        raise SkipNode
    # empty / spacer (or literal passthrough Text): emit the cell + any text.
    text = result[1]
    self.body.append(
        '<td class="doxtr-progression-cell">%s</td>' % _esc(self, text)
    )
    raise SkipNode


def _depart_progression_cell(self, node):  # pragma: no cover - SkipNode
    pass


# ---------------------------------------------------------------------------
# Registration into the _VISITORS["html"] seam
# ---------------------------------------------------------------------------

def register_html_visitors():
    """Assign the real HTML visitor bodies into ``_VISITORS["html"]``.

    Called from :func:`doxtr_music.setup`. Overwrites the CHUNK-1-2 placeholder
    no-op HTML visitors with the real copy-safe renderers. Never touches the
    ``latex``/``epub`` buckets.
    """
    html = _nodes._VISITORS["html"]
    html[_nodes.SongNode] = (_visit_song, _depart_song)
    html[_nodes.SectionNode] = (_visit_section, _depart_section)
    html[_nodes.LineNode] = (_visit_line, _depart_line)
    html[_nodes.ChordNode] = (_visit_chord, _depart_chord)
    html[_nodes.LyricNode] = (_visit_lyric, _depart_lyric)
    html[_nodes.SingerSpanNode] = (_visit_singer, _depart_singer)
    html[_nodes.RomanNode] = (_visit_roman, _depart_roman)
    # CHUNK-3-5 adds ONLY the new KeyNode visitor by plain dict assignment
    # (RomanNode is owned by CHUNK-3-3 above; ChordNode reuses its existing
    # visitor with the inline_role branch). No add_node(override=True).
    html[_nodes.KeyNode] = (_visit_key, _depart_key)
    # CHUNK-4-4 adds the progression grid nodes by plain dict assignment.
    html[_nodes.ChordProgressionNode] = (_visit_progression, _depart_progression)
    html[_nodes.ProgressionRowNode] = (
        _visit_progression_row, _depart_progression_row)
    html[_nodes.ProgressionCellNode] = (
        _visit_progression_cell, _depart_progression_cell)
