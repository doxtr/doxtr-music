"""Inline roles for natural prose integration (CHUNK-3-5).

Three Docutils roles let authors drop chords / keys / roman numerals into
running prose:

* ``:chord:`G7``` → a standalone :class:`~doxtr_music.nodes.ChordNode`
  (``column=None``, no ``transposed``/``roman``), rendered through the LOCKED
  single display call site
  :func:`~doxtr_music.engine.i18n.resolve_chord_display` (so it localizes per
  ``doxtr_music_chord_system`` but is never transposed). It uses a **distinct**
  ``.doxtr-chord-inline`` class (HTML/EPUB) so the positioned song-chord CSS
  (``user-select:none`` / absolute positioning / ``aria-hidden``) never leaks
  onto ordinary prose chords — role spans are readable prose text and get NO
  ``aria-hidden`` (CHUNK-4-3 need not touch role output).
* ``:key:`Bb``` → a :class:`~doxtr_music.nodes.KeyNode`, localized as a note
  name (root + optional ``m`` minor-mode suffix) so ``Bm`` → ``Hm`` under the
  German system; a non-note/free-text key passes through unchanged.
* ``:roman:`IV``` → an **author-literal** :class:`~doxtr_music.nodes.RomanNode`
  (``roman="IV"``); it is NEVER analyzed via ``roman_for_chord`` and is never
  letter-localized.

Author-literal construction invariant (LOCKED, CHUNK-3-5): roles are the ONLY
place ``KeyNode`` and author-literal ``RomanNode`` are constructed. Role chords
always carry ``column=None`` and no key-dependent analysis.

Roles are format-neutral: they build nodes only; HTML/LaTeX/EPUB rendering lives
in the existing per-format visitors (``ChordNode`` reused with an
``inline_role`` branch; ``RomanNode`` owned by CHUNK-3-3; ``KeyNode`` added by
CHUNK-3-5).
"""

from __future__ import annotations

from doxtr_music import nodes as _nodes

__all__ = [
    "chord_role",
    "key_role",
    "roman_role",
    "register_roles",
]


def chord_role(name, rawtext, text, lineno, inliner, options=None, content=None):
    """``:chord:`G7``` → an inline (prose) :class:`ChordNode`.

    The chord is validated with :func:`doxtr_music.engine.theory.parse_chord`;
    an unparseable value still renders (graceful — the literal text is shown),
    matching the parser's passthrough behaviour. The node carries
    ``column=None`` and ``inline_role=True`` so the shared ChordNode visitors
    emit the distinct ``.doxtr-chord-inline`` presentation (no ``aria-hidden``,
    no positioned song-chord CSS) and never attempt lyric-column arithmetic.
    """
    chord = _nodes.ChordNode()
    chord["chord"] = (text or "").strip()
    chord["column"] = None  # standalone role chord: no lyric context
    chord["inline_role"] = True  # distinct .doxtr-chord-inline render path
    return [chord], []


def key_role(name, rawtext, text, lineno, inliner, options=None, content=None):
    """``:key:`Bb``` → an inline :class:`KeyNode` (localized as a note name)."""
    key = _nodes.KeyNode()
    key["key"] = (text or "").strip()
    return [key], []


def roman_role(name, rawtext, text, lineno, inliner, options=None, content=None):
    """``:roman:`IV``` → an **author-literal** :class:`RomanNode`.

    The numeral is stored verbatim; it is never passed through
    ``roman_for_chord`` (author-literal construction) and never letter-localized.
    """
    roman = _nodes.RomanNode()
    roman["roman"] = (text or "").strip()
    # An author-literal ``:roman:`` role is ordinary readable prose (like the
    # ``:chord:`` inline role), so it is a11y-exempt: mark it ``inline_role`` so
    # the RomanNode visitors emit a plain selectable span (no role="img"/
    # aria-label). A musical roman from analysis/progression (no inline_role)
    # gets the atomic screen-reader label instead.
    roman["inline_role"] = True
    return [roman], []


def register_roles(app):
    """Register ``:chord:`` / ``:key:`` / ``:roman:`` with Sphinx.

    Called from :func:`doxtr_music.setup`. Docutils roles return ``([node], [])``
    and are format-neutral; per-format rendering lives in the ``_VISITORS`` seam.
    """
    app.add_role("chord", chord_role)
    app.add_role("key", key_role)
    app.add_role("roman", roman_role)
