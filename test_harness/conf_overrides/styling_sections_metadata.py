# Config override for the ``typography_sections`` harness feature.
#
# Exercises the extended typography surface introduced for granular styling:
#   * background colors (title background),
#   * per-section-kind title styling (verse on a tinted background; chorus green),
#   * a section-body size,
#   * a song-metadata block with a generic ``metadata`` default plus a per-key
#     ``meta-tempo`` override (monospace + blue) and ``meta-key`` (green).
#
# All four styleable attributes (font/size/color/background) and the flexible
# ``section-<kind>-title/-body`` + ``meta-<key>`` element namespaces are covered.
#
# ``doxtr_music_autoload_theme = False`` isolates this case to the config under
# test: without it, an installed real ``doxtr-pdf-theme-core`` would be
# auto-loaded and its theme-tier palette would color the chords/lyrics, masking
# the config styling this case asserts.
doxtr_music_autoload_theme = False

doxtr_music_typography = {
    "title": {"color": "#1a3d7a", "background": "#eeeeff"},
    "section-verse-title": {"color": "#7a4a00", "background": "#ffeeee"},
    "section-chorus-title": {"color": "#00aa00"},
    "section-body": {"size": "0.98em"},
    "metadata": {"size": "0.9em"},
    "meta-tempo": {"color": "#0000aa", "font": "monospace"},
    "meta-key": {"color": "#00aa00"},
}
