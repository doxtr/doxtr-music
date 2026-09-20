Chord Progression Grid
======================

The ``.. chord-progression::`` directive renders a tabular grid of chords and/or
Roman numerals **without lyrics** — a semantic ``<table>`` in HTML/EPUB and a
standard ``tabular`` in LaTeX.

A plain chord grid (localized per ``chord_system``):

.. chord-progression::

   | C | F | G | C |
   | Am | Dm | G | C |

An author-literal Roman-numeral row (never re-analyzed):

.. chord-progression::

   | I | IV | V | I |

Computed Roman numerals: with ``:key: C`` and ``:roman-numerals:`` each chord
cell also gets its harmonic numeral (``C`` → ``I``, ``F`` → ``IV``, ``G`` →
``V``). A ragged short row is padded, and an empty cell is a spacer:

.. chord-progression::
   :key: C
   :roman-numerals:

   | C | F | G |
   | Am |  | G7 |
