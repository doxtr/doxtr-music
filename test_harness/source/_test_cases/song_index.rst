Song Index
==========

Songs grouped by a metadata key via ``.. song-index:: :group-by: artist``. One
song omits the artist key so it lands in the single ``Other`` group. The index
group entries link back to the songs on this page (real in-document anchors).

.. song::

   {title: First By Nines}
   {artist: The Nines}

   [C]First [G]song

.. song::

   {title: Second By Nines}
   {artist: The Nines}

   [Am]Second [F]song

.. song::

   {title: Anonymous Tune}

   [D]No artist [A]here

Grouped index:

.. song-index::
   :group-by: artist
