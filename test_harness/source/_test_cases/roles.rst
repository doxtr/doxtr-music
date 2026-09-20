Inline Roles
============

Inline roles integrate chords, keys and roman numerals into running prose. The
chord role :chord:`G7` renders through the shared display resolver using a
distinct ``.doxtr-chord-inline`` presentation (ordinary readable prose text, not
a positioned song chord). The key role :key:`Bb` renders as a note name, and the
roman role :roman:`IV` renders an author-literal numeral. A minor key such as
:key:`Bm` and an extended chord such as :chord:`Cmaj7` are also handled. Across
LaTeX these emit ``\dmchordinline`` / ``\dmkey`` / ``\dmroman``; across EPUB and
HTML they emit inline spans.
