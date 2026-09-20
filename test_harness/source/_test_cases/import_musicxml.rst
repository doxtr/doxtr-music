Import MusicXML
===============

The ``.. import-musicxml::`` directive converts an uncompressed MusicXML score
into the locked token vocabulary and renders it **exactly** like ``.. song::``
(same node tree, same ``SongDirectiveBase`` pipeline), so all three formats
render it identically: real ``.doxtr-chord`` spans above lyrics (HTML),
``\dmchord`` + ``\dmneedspace`` under a loaded package (LaTeX), and a
reflow-safe ``<pre>`` two-row layout (EPUB). Chord symbols come from
``<harmony>``, lyrics from ``<lyric>`` (anchored over the note events they sit
above), and the score ``<key>`` feeds roman analysis. The imported file path is
confined to the source tree and registered as a build dependency; the XML is
parsed with ``defusedxml`` (XXE / entity-bomb safe). Bar boundaries and note
durations are metadata-only in v1 (carried on the tokens, rendered by no
builder).

.. import-musicxml:: ../_static/example.musicxml
