Typography — sections & metadata
=================================

This case exercises the extended styling surface: per-section-kind title/body
styling (verse/chorus), a background color on the title, and a visible
song-metadata block (Key / Tempo) with per-metadata-key styling. All driven by
``doxtr_music_typography`` in the merged ``conf.py`` for this case.

.. song::

   {title: Styled Reference}
   {key: G}
   {tempo: 120 BPM}
   {start_of_verse}
   [C]Hello [Am]world
   {end_of_verse}
   {start_of_chorus}
   [F]Sing [G]along
   {end_of_chorus}
