Multi-Singer
============

Duet attribution with distinct per-singer colors (``{singer: A}`` /
``{singer: B}``). Colors merge a **global** ``doxtr_music_singer_colors`` (set in
this feature's conf override) with a **per-song** ``:singer-colors:`` option that
overrides singer ``A`` per-id and adds singer ``B``. A per-song ``:chord-color:``
+ ``:chord-font:`` proves the LOCKED collision rule: the singer color **wins**
over the typography chord color, while the typography **font** (monospace) still
applies — resolved in Python and emitted once per element in all three formats.

.. song::
   :chord-color: #cc0000
   :chord-font: monospace
   :singer-colors: A: #1a53a1, B: #e07b00

   {title: Duet}

   {start_of_verse}
   {singer: A}
   [C]Hello [Am]world
   {singer: B}
   [F]Goodbye [G]now
   {end_of_verse}
