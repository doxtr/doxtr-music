"""Pure music-theory engine for doxtr-music.

This subpackage is the **single authority** for chord parsing, pitch-class
math, key parsing, and diatonic scale-degree tables. It imports nothing from
Sphinx, Docutils, or ``doxtr_pdf_theme_core`` and is safe to import from the
standalone CLI (CHUNK-6-3).

Modules:

* :mod:`doxtr_music.engine.theory` — ``parse_chord``, ``ChordParts``,
  ``parse_key``, note/pitch-class tables, diatonic degree tables. The shared
  chord-parsing authority consumed by transpose (this phase), roman analysis
  (CHUNK-3-3), i18n (CHUNK-3-4), and progressions (CHUNK-4-4).
* :mod:`doxtr_music.engine.transpose` — quality-preserving, enharmonically
  correct transposition over the token stream.
"""

from __future__ import annotations

__all__ = []
