Plugin Hooks
============

The ``html_visit`` plugin hook injects custom HTML during translation. The
harness registers it as a dotted-string config value; doxtr-music invokes it
inside a copy-neutral ``.doxtr-hook`` wrapper so the injected markup never
pollutes the copyable lyric stream.

.. song::

   {title: Hooked Song}
   {key: C}

   {start_of_verse}
   [Am]Hello [C]world
   [G]Line two [F]here
   {end_of_verse}
