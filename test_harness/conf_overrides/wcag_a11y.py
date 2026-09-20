# Config override for the ``wcag_a11y`` harness feature (CHUNK-4-3).
#
# Provides a global singer-color map so the multi-singer runs in the fixture
# resolve a color (proving color + the VISIBLE non-color cue coexist). The
# fixture's per-song ``:singer-colors:`` overrides these per-id. The visible
# 1.4.1 cue is independent of color (it satisfies Use-of-Color for sighted
# color-blind users), so it renders regardless of this map.
doxtr_music_singer_colors = {
    "A": "#1a53a1",
    "B": "#e07b00",
}
