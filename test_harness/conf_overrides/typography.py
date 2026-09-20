# Config override for the ``typography`` harness feature (CHUNK-4-1).
#
# Sets GLOBAL granular typography: chords are colored red (#cc0000) via the
# scoped element-class CSS (HTML/EPUB) / the LaTeX preamble indirection macro,
# without affecting lyrics/title. The RST fixture then overrides only specific
# per-song cells (lyrics color, chord font, title color) to prove per-attr
# merge and the two-mechanism LaTeX model.
doxtr_music_typography = {
    "chord": {"color": "#cc0000"},
}
