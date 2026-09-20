# Config override for the ``theme_interop`` harness feature (CHUNK-7-1).
#
# Simulates ``doxtr-pdf-theme-core`` being the ACTIVE theme WITHOUT installing
# it: a ``setup(app)`` registers the ``doxtr_theme_defaults`` config value (the
# attribute theme-core populates) with a stub palette. doxtr-music's soft
# interop reads this via a config-attribute (never an import) and picks up the
# palette into the ``theme`` tier + the LaTeX preamble + the contrast feed.
#
# The stub uses a DARK page background so the CHUNK-4-3 contrast baseline flips
# (a dark background makes a dark chord color low-contrast), and an accent color
# that becomes the chord color and a body font/text color that become the lyric
# styling (the conservative mapping).
#
# ``doxtr_music_autoload_theme = False`` keeps the harness isolated to the STUB:
# without it, an installed real ``doxtr-pdf-theme-core`` would be auto-loaded and
# its own ``config-inited`` (priority 900) would overwrite the stub
# ``doxtr_theme_defaults`` with the real palette, breaking this simulation.
doxtr_music_autoload_theme = False


def setup(app):
    app.add_config_value(
        "doxtr_theme_defaults",
        {
            "globals": {"light": {"main_font": "serif"}},
            "semantic_palette": {
                "page": "#1a1a1a",      # dark page background (flips contrast)
                "text": "#e0e0e0",      # -> lyric color
                "accent": "#3aa0ff",    # -> chord color
            },
        },
        "env",
    )
