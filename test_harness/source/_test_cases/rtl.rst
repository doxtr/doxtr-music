Song RTL — Right-to-Left Lyrics
===============================

A ``.. song::`` with Hebrew (right-to-left) lyrics. HTML is first-class: the
song wrapper carries ``dir="auto"`` and chord alignment uses CSS **logical**
properties only (``inset-inline-start`` / ``text-align: start``), so the layout
flips correctly under RTL without physical ``left``/``right``.

LaTeX and EPUB use a **documented, tested fallback**: LaTeX emits the lyrics
verbatim (no bidi package by default; a warning notes that RTL PDF needs a
bidi-capable setup — deferred to the theme/backend in CHUNK-7-1) and EPUB uses a
reflow-safe ``<pre>`` + ``dir="auto"`` (exact per-cell RTL alignment awaits the
future SVG path). Neither format crashes.

.. song::

   {title: RTL Song}

   {start_of_verse}
   [C]שלום [G]עולם
   {end_of_verse}
