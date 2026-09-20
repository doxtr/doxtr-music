"""The ``.. song::`` directive — ChordPro body → copy-safe song node tree.

This is the primary user-facing feature: a directive whose body is inline
ChordPro (``[Am]Hello [C]world`` + ``{title: ...}`` metadata) that parses into
the locked token stream (CHUNK-1-3) and assembles the single Docutils node tree
(CHUNK-1-2). It is **format-neutral**: it only parses + builds. HTML rendering
lives in :mod:`doxtr_music.builders.html`; LaTeX/EPUB in CHUNK-2-1/2-2.

The full ``run`` sequence lives in
:class:`doxtr_music.directives._base.SongDirectiveBase`; this directive only
supplies the ChordPro parser. ``.. chord-line::`` and ``.. song-include::``
share the same base so behavior never drifts.
"""

from __future__ import annotations

from doxtr_music.directives._base import SongDirectiveBase
from doxtr_music.parsers.chordpro import parse_chordpro

__all__ = ["SongDirective"]


class SongDirective(SongDirectiveBase):
    """``.. song::`` — render chords + lyrics from an inline ChordPro body."""

    parser_fn = staticmethod(parse_chordpro)
