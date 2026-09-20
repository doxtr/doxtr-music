"""Input parsers for doxtr-music.

Each parser is a **pure function** that turns raw text into the locked
``(tokens, song_meta)`` contract from :mod:`doxtr_music.tokens`:

    raw strings  ->  [Token]  ->  Docutils nodes  ->  HTML / LaTeX / EPUB

The ChordPro parser (:mod:`doxtr_music.parsers.chordpro`) is the primary input
path and the single tokenization authority. Its hardest, drift-prone logic —
lyric word-splitting, per-word lyric-relative columns, bracketed-chord column
math, and single-line ``{...}`` directive handling — is factored into
:mod:`doxtr_music.parsers._lyrics` so that chord-line (CHUNK-3-1) and the
importers (CHUNK-6-1/6-2) reuse the **same** authority instead of forking a
second implementation. Song-include (CHUNK-3-5) calls :func:`parse_chordpro`
directly.

This package imports nothing from Sphinx, Docutils, or ``doxtr_pdf_theme_core``
so the pure parsing layer (and the CLI in CHUNK-6-3) stay importable standalone.
"""

from __future__ import annotations

from doxtr_music.parsers.chordpro import parse_chordpro

__all__ = ["parse_chordpro"]
