"""Dependency-free bootstrap tests for the doxtr_music package.

These tests must pass with only ``pip install -e .`` (no Sphinx build): they
lock the single version token and the parallel-safety contract from CHUNK-0-1.
"""

import doxtr_music


def test_version_token():
    """__version__ is the single source-of-truth PEP 440 token."""
    assert doxtr_music.__version__ == "0.1.1"


class _FakeApp:
    """Minimal stand-in for the Sphinx application in setup()."""

    def __init__(self):
        self.required_sphinx = None
        self.connections = []
        self.config_values = {}
        self.nodes = []
        self.directives = {}
        self.roles = {}
        self.css_files = []

    def require_sphinx(self, version):
        self.required_sphinx = version

    def connect(self, event, handler, priority=500):
        # Real Sphinx accepts an optional priority (CHUNK-2-1 uses it for the
        # preamble-injection handler at ~700). Accept + ignore it here.
        self.connections.append((event, handler))

    def add_config_value(self, name, default, rebuild):
        self.config_values[name] = (default, rebuild)

    def add_node(self, node_class, **kwargs):
        self.nodes.append((node_class, kwargs))

    def add_directive(self, name, cls):
        self.directives[name] = cls

    def add_role(self, name, fn):
        self.roles[name] = fn

    def add_css_file(self, filename, **kwargs):
        self.css_files.append(filename)


def test_setup_returns_contract_dict():
    """setup() returns the version + parallel-safety metadata contract."""
    app = _FakeApp()
    meta = doxtr_music.setup(app)

    assert {"version", "parallel_read_safe", "parallel_write_safe"}.issubset(
        meta.keys()
    )
    assert meta["version"] == "0.1.1"
    assert meta["parallel_read_safe"] is True
    assert meta["parallel_write_safe"] is True

    # setup() wires the required Sphinx floor and the provenance hook.
    assert app.required_sphinx == "5.0"
    assert ("html-page-context", doxtr_music._add_provenance_meta) in app.connections

    # CHUNK-0-3 + CHUNK-7-1: config manifest registered + validation hook connected.
    # (13 values: +roman_display/+roman_format/+index_page_format.)
    assert len(app.config_values) == 13
    assert "doxtr_music_chord_system" in app.config_values
    connected_events = [event for event, _ in app.connections]
    assert "config-inited" in connected_events

    # CHUNK-1-2: node model registered (one add_node per visible node class).
    assert len(app.nodes) == 13
    for _nc, kwargs in app.nodes:
        assert set(kwargs.keys()) == {"html", "latex", "epub"}

    # CHUNK-1-4: the .. song:: directive is registered and the builder-inited
    # CSS-delivery hook is connected.
    assert "song" in app.directives
    assert "builder-inited" in connected_events


def test_provenance_meta_concatenates_string():
    """The provenance hook concatenates onto the metatags string."""
    context = {}
    doxtr_music._add_provenance_meta(None, "index", "page.html", context, None)
    assert context["metatags"] == (
        '<meta name="doxtr-music" content="0.1.1"/>\n'
    )

    # Idempotent concatenation onto an existing string (never list append).
    doxtr_music._add_provenance_meta(None, "other", "page.html", context, None)
    assert context["metatags"].count('name="doxtr-music"') == 2


def test_autoload_theme_core_opt_out_via_raw_config():
    """``doxtr_music_autoload_theme = False`` in conf.py skips the auto-load."""
    import types

    calls = []

    class _App:
        def __init__(self, raw):
            self.config = types.SimpleNamespace(_raw_config=raw)

        def setup_extension(self, name):  # pragma: no cover - must NOT be called
            calls.append(name)

    # Opt-out: the raw conf.py disables auto-load → setup_extension never called.
    doxtr_music._maybe_autoload_theme_core(_App({"doxtr_music_autoload_theme": False}))
    assert calls == []


def test_autoload_theme_core_defensive_without_setup_extension():
    """A lightweight app double lacking setup_extension is tolerated (no crash)."""
    import types

    class _App:
        config = types.SimpleNamespace(_raw_config={})

    # No setup_extension attribute → skipped silently (no exception).
    doxtr_music._maybe_autoload_theme_core(_App())
