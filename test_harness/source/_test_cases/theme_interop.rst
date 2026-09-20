Theme Interop
=============

When ``doxtr-pdf-theme-core`` is the active theme, doxtr-music picks up its
font/palette so songs visually match the surrounding themed document. The theme
palette fills the ``theme`` tier of the three-tier typography merge (below
global config and per-song overrides), contributes a LaTeX preamble block using
the existing ``\dm`` indirection macros (plus ``polyglossia``/``bidi`` for RTL),
and feeds the theme's page/background color into the WCAG contrast check
(HTML/EPUB). ``doxtr-pdf-theme-core`` stays a soft dependency: presence is a
config-attribute read (``doxtr_theme_defaults``), never an import, and the whole
path degrades to defaults when the theme is absent or interop is switched off.

This fixture simulates the theme via a stub that registers
``doxtr_theme_defaults`` with a dark page background and an accent color, so the
song's lyric font/color come from the theme body text and the chord color comes
from the theme accent.

.. song::

   {title: Themed Song}

   [C]Picked [G]up the [Am]theme
