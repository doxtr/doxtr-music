# Config override for the ``plugin_hooks`` harness feature (CHUNK-5-4).
#
# Registers the ``html_visit`` plugin hook via a DOTTED-STRING config value
# (importlib resolution, never eval). The fixture module lives on the harness
# ``_extensions`` path (dm_hook_fixture.py). The hook appends a sentinel span,
# which doxtr-music injects inside a copy-neutral ``.doxtr-hook`` wrapper so it
# never pollutes the copy-safe lyric stream.
doxtr_music_html_visit = "dm_hook_fixture.inject_hook"
