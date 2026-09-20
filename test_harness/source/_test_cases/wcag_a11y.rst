WCAG Accessibility
==================

WCAG 2.1 AA accessibility for HTML + EPUB song output: the song is a named
``role="group"``, each chord announces atomically via ``role="img"`` +
``aria-label``, multi-singer runs carry a **visible** non-color cue (WCAG 1.4.1),
and the EPUB two-row ``<pre>`` gets a visually-hidden chord↔word alternative
emitted outside the copyable lyric row. Copy-safety (HTML DOM-strip / EPUB
row-extract) is preserved: the a11y additions live inside stripped wrappers or
sibling containers, so the copied lyric stream is unchanged.

.. song::
   :singer-colors: A: #1a53a1, B: #e07b00

   {title: Amazing Grace}

   {start_of_verse}
   {singer: A}
   [G]Amazing [C]grace how [G]sweet the sound
   {singer: B}
   [D]That saved a [G]wretch like me
   {end_of_verse}
