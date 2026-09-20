Song Roman Numerals
===================

The same inline ChordPro song rendered with ``:roman-numerals:`` — every chord
is analyzed against the song key (C major) and its harmonic Roman numeral
**replaces** the chord label in the chord row across all three formats. The
chords ``[C] [Am] [F] [G]`` become ``I vi IV V``.

.. song::
   :roman-numerals:

   {title: Roman Song}
   {key: C}

   {start_of_verse}
   [C]Hello [Am]world
   [F]Line two [G]here
   {end_of_verse}
