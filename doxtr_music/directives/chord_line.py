"""The ``.. chord-line::`` directive — legacy chords-over-lyrics → song node tree.

Parses monospaced "chord row above lyric row" text (Ultimate Guitar style) into
the **same** :class:`~doxtr_music.nodes.SongNode` tree as ``.. song::`` by
reusing the shared :class:`~doxtr_music.directives._base.SongDirectiveBase`
pipeline with :func:`~doxtr_music.parsers.chordline.parse_chord_line` as the
parser. Because it converges on the single token vocabulary + ``build_nodes``
path, transpose/roman/typography/singer all apply identically and every output
format (HTML/LaTeX/EPUB) renders it the same as an inline ChordPro song.
"""

from __future__ import annotations

from doxtr_music.directives._base import SongDirectiveBase
from doxtr_music.parsers.chordline import parse_chord_line

__all__ = ["ChordLineDirective"]


class ChordLineDirective(SongDirectiveBase):
    """``.. chord-line::`` — render legacy chords-over-lyrics text."""

    parser_fn = staticmethod(parse_chord_line)
