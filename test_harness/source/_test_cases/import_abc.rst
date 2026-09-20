Import ABC
==========

The ``.. import-abc::`` directive converts an ABC notation tune into the locked
token vocabulary and renders it **exactly** like ``.. song::`` (same node tree,
same ``SongDirectiveBase`` pipeline), so all three formats render it
identically: real ``.doxtr-chord`` spans above lyrics (HTML), ``\dmchord`` +
``\dmneedspace`` under a loaded package (LaTeX), and a reflow-safe ``<pre>``
two-row layout (EPUB). Chord symbols come from quoted ``"Am"`` strings, lyrics
from ``w:`` lines (aligned over the note events they sit above via the
note-event → syllable → column algorithm), and the tune ``K:`` field feeds
roman analysis. The imported file path is confined to the source tree and
registered as a build dependency. Bar lines and note durations are
metadata-only in v1 (carried on the tokens, rendered by no builder).

.. import-abc:: ../_static/example.abc
