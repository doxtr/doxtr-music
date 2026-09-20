Typography
==========

Granular per-element typography. The global ``doxtr_music_typography`` (set in
this feature's conf override) colors every chord; the per-song directive
options below override only specific element/attr cells for this one song,
inheriting the global for the rest.

.. song::
   :lyrics-color: #0000cc
   :chord-font: monospace
   :title-color: #008000

   {title: Styled Song}
   {key: C}

   {start_of_verse}
   [C]Hello [Am]world
   [F]Line two [G]here
   {end_of_verse}
