"""doxtr-music — sheet music (chords + lyrics) for Sphinx documents.

This Sphinx extension renders chords and lyrics to HTML, LaTeX/PDF and EPUB as
first-class output formats. It installs under the distribution name
``doxtr-music`` (hyphen) and is imported / registered under the package name
``doxtr_music`` (underscore); ``conf.py`` should use
``extensions = ["doxtr_music"]``.

Sphinx imports are deferred into :func:`setup` (never at module top level) so
the pure parser layer and the ``doxtr-music-convert`` CLI remain importable
without pulling in Sphinx.
"""

__version__ = "0.1.1"

__all__ = [
    "setup",
    "__version__",
    "register_chord_preprocess",
    "register_node_parsed",
    "register_html_visit",
    # Public child-theme rendering seams (FINDING F): a downstream theme should
    # import these stable names instead of reaching into underscored internals.
    "get_visitor_registry",
    "register_html_visitors",
    "register_latex_visitors",
    "register_epub_visitors",
    "register_preamble_contributor",
    "assemble_latex_preamble",
]


def register_chord_preprocess(fn):
    """Register a ``chord_preprocess(chord, song_meta) -> str`` plugin hook.

    Public re-export of :func:`doxtr_music.hooks.register_chord_preprocess`
    (parity with the core theme's module-level ``register_*`` API). Call during
    ``setup``/``conf.py`` import (before parallel workers spawn); late
    registration warns + is ignored.
    """
    from .hooks import register_chord_preprocess as _impl

    _impl(fn)


def register_node_parsed(fn):
    """Register a ``node_parsed(song) -> None`` plugin hook (see :mod:`.hooks`)."""
    from .hooks import register_node_parsed as _impl

    _impl(fn)


def register_html_visit(fn):
    """Register an ``html_visit(node, translator) -> None`` plugin hook."""
    from .hooks import register_html_visit as _impl

    _impl(fn)


# ---------------------------------------------------------------------------
# Public child-theme rendering seams (FINDING F)
#
# These are stable public re-exports of the rendering seams a downstream theme
# needs to swap in its own visitors/renderers WITHOUT forking core or reaching
# into underscored submodule internals:
#
#   - get_visitor_registry() -> the per-format visitor dict (``_VISITORS``);
#     assign into ``registry[fmt][NodeClass] = (visit, depart)`` to override a
#     format's rendering (never ``add_node(override=True)``). A child theme's
#     ``setup()`` must run AFTER ``doxtr_music.setup()`` for overrides to win.
#   - register_html_visitors / register_latex_visitors / register_epub_visitors
#     re-install the built-in bodies for a format bucket (call, then override).
#   - register_preamble_contributor(priority, fn) / assemble_latex_preamble(cfg)
#     the ordered LaTeX preamble contributor registry seam.
#
# All use function-local imports to preserve the deferred-Sphinx-import
# guarantee (the pure parser layer + CLI import standalone).
# ---------------------------------------------------------------------------


def get_visitor_registry():
    """Return the per-format visitor registry (the ``_VISITORS`` seam).

    A downstream theme overrides a format's rendering by assigning into
    ``get_visitor_registry()[fmt][NodeClass] = (visit_fn, depart_fn)`` (buckets
    ``"html"``/``"latex"``/``"epub"``), from its own ``setup()`` running after
    ``doxtr_music.setup()``. Never use ``add_node(override=True)``.
    """
    from .nodes import _VISITORS

    return _VISITORS


def register_html_visitors():
    """Install the built-in HTML visitor bodies into the ``html`` bucket."""
    from .builders.html import register_html_visitors as _impl

    _impl()


def register_latex_visitors():
    """Install the built-in LaTeX visitor bodies into the ``latex`` bucket."""
    from .builders.latex import register_latex_visitors as _impl

    _impl()


def register_epub_visitors():
    """Install the built-in EPUB visitor bodies into the ``epub`` bucket."""
    from .builders.epub import register_epub_visitors as _impl

    _impl()


def register_preamble_contributor(priority, fn):
    """Register an ordered LaTeX preamble contributor ``(priority, fn(config))``.

    Public re-export of the ``_LATEX_PREAMBLE_CONTRIBUTORS`` seam: a theme adds
    its own preamble block by registering a ``fn(config) -> str`` at a chosen
    priority; contributors are emitted in ascending priority order.
    """
    from .builders.latex import register_preamble_contributor as _impl

    _impl(priority, fn)


def assemble_latex_preamble(config):
    """Return the assembled LaTeX preamble from all registered contributors."""
    from .builders.latex import assemble_latex_preamble as _impl

    return _impl(config)


def _add_provenance_meta(app, pagename, templatename, context, doctree):
    """Inject the provenance ``<meta>`` tag into every HTML page head.

    ``context['metatags']`` is a *string* (not a list); concatenate onto it
    rather than calling ``.append()``. There is no ``app.add_html_meta`` API.
    """
    tag = f'<meta name="doxtr-music" content="{__version__}"/>\n'
    context["metatags"] = context.get("metatags", "") + tag


def _register_static_assets(app):
    """Make the packaged ``static/`` stylesheets available to the build.

    ``app.add_css_file`` only injects the ``<link>``; it does not copy the
    package file into the build. On ``builder-inited`` we append the package
    ``static/`` dir to ``config.html_static_path`` (available to the EPUB
    builder too, which subclasses the HTML builder) and then register the CSS
    link(s). LOCKED wiring (CHUNK-1-4): append static dir THEN ``add_css_file``.

    The HTML absolute-positioning CSS is registered for the HTML family; the
    EPUB builder (discriminated by builder *name*, since it inherits the HTML
    format) instead gets its own reflow-safe ``<pre>`` stylesheet (CHUNK-2-2).
    """
    import os

    from .builders.epub import EPUB_CSS_FILENAME

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    static_path = app.config.html_static_path
    if static_dir not in static_path:
        static_path.append(static_dir)
    if getattr(app.builder, "name", "").startswith("epub"):
        app.add_css_file(EPUB_CSS_FILENAME)
    else:
        app.add_css_file("doxtr_music.css")


def _maybe_autoload_theme_core(app):
    """Auto-load ``doxtr_pdf_theme_core`` as a Sphinx extension when installed.

    doxtr-music is a *soft* consumer of doxtr-pdf-theme-core: when the theme is
    the active theme, doxtr-music picks up its font/palette (CHUNK-7-1). This
    helper removes the requirement that a user list the theme *before*
    doxtr_music in ``extensions``: if the package is importable, we load it via
    :meth:`Sphinx.setup_extension` (idempotent — a no-op when the user already
    listed it, and it records the correct load order for config-inited
    priorities). Detection is import-availability only (``find_spec``), never a
    hard dependency; any error is swallowed so an absent or broken theme never
    breaks a doxtr_music build.
    """
    import importlib.util

    # Honor an opt-out from conf.py. This runs during setup() before our config
    # values are registered, so read the raw conf.py namespace directly
    # (default True when unset). Defensive: a lightweight app double may lack a
    # ``config``/``setup_extension`` — then auto-load is simply skipped.
    config = getattr(app, "config", None)
    raw = getattr(config, "_raw_config", None)
    if isinstance(raw, dict) and raw.get("doxtr_music_autoload_theme") is False:
        return
    if not hasattr(app, "setup_extension"):
        return

    try:
        spec = importlib.util.find_spec("doxtr_pdf_theme_core")
    except (ImportError, ValueError):  # pragma: no cover - defensive
        spec = None
    if spec is None:
        return
    try:
        app.setup_extension("doxtr_pdf_theme_core")
    except Exception:  # pragma: no cover - a broken theme must never break us
        logger = __import__("sphinx.util", fromlist=["logging"]).logging.getLogger(
            __name__
        )
        logger.warning(
            "[doxtr-music] doxtr_pdf_theme_core is installed but could not be "
            "auto-loaded; list it explicitly in conf.py 'extensions' if you "
            "want theme integration."
        )


def setup(app):
    """Register the extension with Sphinx.

    Sphinx-coupled imports (directives, builders, config) belong inside this
    function or lazy function-local imports — never at module top level. The
    config manifest is registered here via :mod:`doxtr_music.config` (CHUNK-0-3,
    the sole registration site); the ``html-page-context`` connection and the
    returned metadata dict are stable anchors that later chunks extend.
    """
    from . import config as _config
    from . import hooks as _hooks
    from . import nodes as _nodes
    from . import registry as _registry
    from . import theme_interop as _theme_interop
    from . import typography as _typography
    from .builders.epub import register_epub_visitors
    from .builders.html import register_html_visitors
    from .builders.latex import (
        register_latex_preamble_seam,
        register_latex_visitors,
    )
    from .directives.chord_line import ChordLineDirective
    from .directives.chord_progression import ChordProgressionDirective
    from .directives.import_musicxml import ImportMusicXMLDirective
    from .directives.import_abc import ImportABCDirective
    from .directives.song import SongDirective
    from .directives.song_include import SongIncludeDirective
    from .directives.song_list import SongIndexDirective, SongListDirective
    from .resolve import connect_resolve_handlers
    from .roles import register_roles

    app.require_sphinx("5.0")
    # Auto-load doxtr-pdf-theme-core when it is installed, so a user does NOT
    # have to list it before doxtr_music in ``extensions`` for the theme
    # font/palette pickup (CHUNK-7-1) to work. Soft + defensive: only when the
    # package is importable, and ``setup_extension`` is idempotent (a no-op if
    # the user already listed it). Never a hard dependency; any failure is
    # swallowed so a broken/absent theme never breaks a doxtr_music build.
    _maybe_autoload_theme_core(app)
    _config.register_config(app)
    app.connect("config-inited", _config.on_config_inited)
    # CHUNK-5-4: a SEPARATE config-inited handler (~500) resolves the three
    # plugin-hook config values (dotted-string -> importlib, callable -> module
    # registry) picklable-safely. builder-inited closes registration (workers
    # spawn after), the parallel-safety guarantee.
    app.connect(
        "config-inited",
        _hooks.on_config_inited_hooks,
        _hooks.HOOK_INIT_PRIORITY,
    )
    app.connect("builder-inited", _hooks.on_builder_inited_hooks)
    app.connect(
        "config-inited",
        _typography.on_config_inited_typography,
        _typography.TYPOGRAPHY_INIT_PRIORITY,
    )
    # Late (>900) re-resolution so dd:/dark-mode color transforms see the theme's
    # resolved dark palette + dark body-text color (theme resolves dark @900).
    app.connect(
        "config-inited",
        _typography.on_config_inited_typography_late,
        _typography.TYPOGRAPHY_LATE_INIT_PRIORITY,
    )
    _nodes.register_nodes(app)
    register_html_visitors()
    register_latex_visitors()
    register_epub_visitors()
    register_latex_preamble_seam(app)
    _typography.register_latex_typography_contributor()
    _theme_interop.register_theme_interop(app)
    app.add_directive("song", SongDirective)
    app.add_directive("chord-line", ChordLineDirective)
    app.add_directive("chord-progression", ChordProgressionDirective)
    app.add_directive("song-include", SongIncludeDirective)
    app.add_directive("import-musicxml", ImportMusicXMLDirective)
    app.add_directive("import-abc", ImportABCDirective)
    app.add_directive("song-list", SongListDirective)
    app.add_directive("song-index", SongIndexDirective)
    register_roles(app)
    _registry.connect_env_handlers(app)
    connect_resolve_handlers(app)
    app.connect("builder-inited", _register_static_assets)
    app.connect("html-page-context", _add_provenance_meta)
    app.connect("html-page-context", _typography.add_global_typography_style)
    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
