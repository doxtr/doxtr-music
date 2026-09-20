Song Include
============

The ``.. song-include::`` directive pulls a raw external ChordPro ``.cho`` file
and renders it **exactly** like ``.. song::`` (same parser, same
``SongDirectiveBase`` pipeline, same node tree), so all three formats render it
identically: real ``.doxtr-chord`` spans above lyrics (HTML), ``\dmchord`` +
``\dmneedspace`` under a loaded package (LaTeX), and a reflow-safe ``<pre>``
two-row layout (EPUB). The included file path is confined to the source tree and
registered as a build dependency so editing the ``.cho`` triggers a rebuild.

.. song-include:: ../_static/example.cho
