"""Directives package for doxtr-music.

Houses the user-facing reStructuredText directives (``.. song::`` and, in later
chunks, ``.. chord-line::`` / ``.. song-include::`` / ``.. chord-progression::``)
plus the shared option-normalization helpers in :mod:`doxtr_music.directives._options`.

Each directive is **format-neutral**: it parses its body into the locked token
stream (CHUNK-1-3) and assembles the single Docutils node tree via
:func:`doxtr_music.nodes.build_nodes` (CHUNK-1-2). No HTML/LaTeX/EPUB markup is
produced here — rendering lives entirely in the ``_VISITORS`` seam.
"""

from __future__ import annotations

__all__ = []
