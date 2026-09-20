Song List
=========

Three songs with queryable metadata, then a filtered ``.. song-list::`` and a
valid-but-empty list. The resolved list links back to the songs on this page,
so the cross-references target real in-document anchors in every format.

.. song::

   {title: Rocking Nineties}
   {artist: The Nines}
   {meta: tags rock, pop}
   {meta: year 1995}

   [C]Rocking in the [G]nineties

.. song::

   {title: Old Ballad}
   {artist: The Nines}
   {meta: tags ballad}
   {meta: year 1975}

   [Am]An older [F]tune

.. song::

   {title: Modern Rock}
   {artist: New Band}
   {meta: tags rock}
   {meta: year 2005}

   [D]Modern [A]rock song

Matching list (rock songs after 1990):

.. song-list::
   :filter: "rock" in tags and year > 1990

Empty list (no songs match this valid filter):

.. song-list::
   :filter: "jazz" in tags
