"""Unit tests for :mod:`doxtr_music.theme_interop` (CHUNK-7-1).

Covers the soft ``doxtr-pdf-theme-core`` interop contract without a Sphinx
build where possible (a light ``config`` stand-in), plus the config-attribute
gate, the conservative theme->typography mapping, the >900 handler behaviour
(active / inactive / off-switch), the LaTeX preamble patch (theme values, bidi,
before-4-1-global, idempotent), the contrast effective-background feed, and the
warn-once defensive fallback. No top-level ``doxtr_pdf_theme_core`` import is
performed anywhere in the module (asserted by AST inspection).
"""
import ast
import types
from pathlib import Path

import pytest

from doxtr_music import theme_interop as ti
from doxtr_music.typography import RESOLVED_CONFIG_ATTR, resolve_global_typography


# A representative theme-core-provided ``doxtr_theme_defaults`` shape (the stub
# the harness uses): a dark page background + text + accent palette + body font.
THEME_DEFAULTS = {
    "globals": {"light": {"main_font": "serif"}},
    "semantic_palette": {
        "page": "#1a1a1a",
        "text": "#e0e0e0",
        "accent": "#3aa0ff",
    },
}


def _config(**attrs):
    """A minimal duck-typed ``config`` stand-in (attribute reads only)."""
    base = {
        "doxtr_music_theme_interop": True,
        "doxtr_music_typography": {},
    }
    base.update(attrs)
    return types.SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _reset_warn_once():
    """Reset the per-process warn-once sentinel between tests."""
    ti._warned_once = False
    yield
    ti._warned_once = False


# --- conservative theme -> typography mapping -------------------------------

def test_map_theme_to_typography_conservative():
    mapped = ti.map_theme_to_typography(THEME_DEFAULTS)
    # Only lyric (font+color) and chord (color) are mapped; nothing else.
    assert mapped == {
        "lyrics": {"font": "serif", "color": "#e0e0e0"},
        "chord": {"color": "#3aa0ff"},
    }
    # Unmapped elements are ABSENT (fall through to core defaults, no broadcast).
    assert "title" not in mapped
    assert "roman" not in mapped
    assert "metadata" not in mapped


def test_map_theme_to_typography_empty_when_no_palette():
    assert ti.map_theme_to_typography({}) == {}
    assert ti.map_theme_to_typography({"semantic_palette": {}}) == {}


def test_map_theme_never_broadcasts_single_color():
    # A palette with only an accent -> only chord color, never every element.
    mapped = ti.map_theme_to_typography({"semantic_palette": {"accent": "#f00"}})
    assert mapped == {"chord": {"color": "#f00"}}


def test_map_theme_heading_and_panel_map_title_and_section_background():
    # A theme that exposes a DISTINCT heading color + a panel/surface color maps
    # them to the title color and the section-title background (conservative:
    # heading is never taken from accent, so a lone accent does not broadcast).
    mapped = ti.map_theme_to_typography(
        {
            "semantic_palette": {
                "accent": "#3aa0ff",
                "heading": "#102040",
                "panel": "#f4f4f8",
            }
        }
    )
    assert mapped["chord"] == {"color": "#3aa0ff"}
    assert mapped["title"] == {"color": "#102040"}
    assert mapped["section-title"] == {"background": "#f4f4f8"}


def test_map_theme_accent_alone_does_not_set_title():
    # Heading must be a DISTINCT palette key; accent alone -> chord only.
    mapped = ti.map_theme_to_typography({"semantic_palette": {"accent": "#f00"}})
    assert "title" not in mapped
    assert "section-title" not in mapped


def test_resolve_theme_background():
    assert ti.resolve_theme_background(THEME_DEFAULTS) == "#1a1a1a"
    assert ti.resolve_theme_background({}) is None
    assert ti.resolve_theme_background({"semantic_palette": {}}) is None


# --- handler: active --------------------------------------------------------

def test_handler_active_populates_theme_tier_and_background():
    config = _config(doxtr_theme_defaults=THEME_DEFAULTS)
    ti.on_config_inited_theme_interop(None, config)

    resolved = getattr(config, ti.RESOLVED_THEME_ATTR)
    assert resolved == {
        "typography": {
            "lyrics": {"font": "serif", "color": "#e0e0e0"},
            "chord": {"color": "#3aa0ff"},
        }
    }
    assert getattr(config, ti.RESOLVED_BACKGROUND_ATTR) == "#1a1a1a"


def test_handler_active_refreshes_global_typography_cache_for_html_epub():
    # The theme tier must reach HTML/EPUB: the >900 handler recomputes the
    # global-typography cache (computed at ~600, before the theme resolved).
    config = _config(doxtr_theme_defaults=THEME_DEFAULTS)
    ti.on_config_inited_theme_interop(None, config)

    cached = getattr(config, RESOLVED_CONFIG_ATTR)
    assert cached["chord"]["color"] == "#3aa0ff"
    assert cached["lyrics"]["color"] == "#e0e0e0"
    assert cached["lyrics"]["font"] == "serif"
    # Unmapped elements keep core defaults (not the theme color).
    assert cached["title"]["color"] != "#3aa0ff"


def test_handler_active_theme_below_global_config():
    # A user-set global chord color must WIN over the theme accent (theme is the
    # weaker tier). resolve_global_typography folds theme below global.
    config = _config(
        doxtr_theme_defaults=THEME_DEFAULTS,
        doxtr_music_typography={"chord": {"color": "#00ff00"}},
    )
    ti.on_config_inited_theme_interop(None, config)
    cached = getattr(config, RESOLVED_CONFIG_ATTR)
    assert cached["chord"]["color"] == "#00ff00"  # global wins over theme
    assert cached["lyrics"]["color"] == "#e0e0e0"  # theme still shows for lyric


# --- handler: inactive / off-switch (byte-identical contract) ---------------

def test_handler_inactive_when_theme_absent():
    config = _config()  # no doxtr_theme_defaults
    ti.on_config_inited_theme_interop(None, config)
    assert getattr(config, ti.RESOLVED_THEME_ATTR) == {}
    assert getattr(config, ti.RESOLVED_BACKGROUND_ATTR) is None


def test_handler_inactive_when_theme_empty():
    config = _config(doxtr_theme_defaults={})
    ti.on_config_inited_theme_interop(None, config)
    assert getattr(config, ti.RESOLVED_THEME_ATTR) == {}
    assert getattr(config, ti.RESOLVED_BACKGROUND_ATTR) is None


def test_off_switch_early_returns_even_when_theme_active():
    config = _config(
        doxtr_theme_defaults=THEME_DEFAULTS,
        doxtr_music_theme_interop=False,
    )
    ti.on_config_inited_theme_interop(None, config)
    assert getattr(config, ti.RESOLVED_THEME_ATTR) == {}
    assert getattr(config, ti.RESOLVED_BACKGROUND_ATTR) is None


def test_inactive_global_typography_matches_theme_free_resolution():
    # Byte-identical-when-inactive at the resolution level: with the theme
    # tier {}, the resolved global equals the plain (theme-free) resolution.
    config = _config()
    theme_free = resolve_global_typography(config)
    ti.on_config_inited_theme_interop(None, config)
    # Handler early-returned (inactive) and did NOT touch the cache; a fresh
    # resolution still equals the theme-free baseline.
    assert resolve_global_typography(config) == theme_free


# --- LaTeX preamble patch ---------------------------------------------------

def test_latex_preamble_patch_adds_theme_block_and_bidi():
    config = _config(
        doxtr_theme_defaults=THEME_DEFAULTS,
        latex_elements={"preamble": "% doxtr-music preamble v1\n"},
    )
    ti.on_config_inited_theme_interop(None, config)
    preamble = config.latex_elements["preamble"]
    assert ti._LATEX_THEME_SENTINEL in preamble
    assert "\\usepackage{polyglossia}" in preamble
    assert "\\usepackage{bidi}" in preamble
    # Theme colors reach the preamble via the \dm indirection macros.
    assert "3aa0ff" in preamble or "3aA0ff".lower() in preamble.lower()


def test_latex_preamble_patch_idempotent_on_rerun():
    config = _config(
        doxtr_theme_defaults=THEME_DEFAULTS,
        latex_elements={"preamble": "% doxtr-music preamble v1\n"},
    )
    ti.on_config_inited_theme_interop(None, config)
    first = config.latex_elements["preamble"]
    ti.on_config_inited_theme_interop(None, config)  # rerun (autobuild)
    assert config.latex_elements["preamble"] == first  # sentinel-guarded


def test_latex_theme_block_before_global_typography_block():
    # Theme is weaker: its block must be emitted BEFORE 4-1's global block so
    # a later global \def overrides (LaTeX last-def-wins == theme-below-global).
    marker = "% doxtr-music global typography"
    config = _config(
        doxtr_theme_defaults=THEME_DEFAULTS,
        latex_elements={"preamble": "% doxtr-music preamble v1\n" + marker + "\n"},
    )
    ti.on_config_inited_theme_interop(None, config)
    preamble = config.latex_elements["preamble"]
    assert preamble.index(ti._LATEX_THEME_SENTINEL) < preamble.index(marker)


def test_latex_no_block_when_theme_inactive():
    config = _config(latex_elements={"preamble": "% doxtr-music preamble v1\n"})
    original = config.latex_elements["preamble"]
    ti.on_config_inited_theme_interop(None, config)
    assert config.latex_elements["preamble"] == original
    assert ti._LATEX_THEME_SENTINEL not in config.latex_elements["preamble"]


# --- defensive: warn-once + never crash -------------------------------------

def test_malformed_palette_warns_once_and_falls_back(caplog):
    # A structurally-hostile ``doxtr_theme_defaults`` must not crash; it warns
    # once per process and falls back to an inert tier.
    class Hostile(dict):
        def get(self, *a, **k):  # noqa: D401
            raise RuntimeError("boom")

    config = _config(doxtr_theme_defaults=Hostile({"x": 1}))
    with caplog.at_level("WARNING"):
        ti.on_config_inited_theme_interop(None, config)
        ti.on_config_inited_theme_interop(None, config)  # second call: no 2nd warn
    assert getattr(config, ti.RESOLVED_THEME_ATTR) == {}
    assert getattr(config, ti.RESOLVED_BACKGROUND_ATTR) is None
    # Warn-once (per process): the warning text appears at most once.
    assert caplog.text.count("doxtr-pdf-theme-core palette") <= 1


def test_non_dict_theme_defaults_treated_as_absent():
    config = _config(doxtr_theme_defaults="not a dict")
    ti.on_config_inited_theme_interop(None, config)
    assert getattr(config, ti.RESOLVED_THEME_ATTR) == {}


# --- soft-dependency discipline ---------------------------------------------

def test_handler_priority_after_theme_core():
    # >900 so it runs AFTER theme-core's ~900 palette resolution.
    assert ti.THEME_INTEROP_INIT_PRIORITY > 900


def test_resolved_attr_uses_reserved_resolved_suffix():
    # Stored under a ``_resolved`` attr so the 0-3 typo-guard excludes it.
    assert ti.RESOLVED_THEME_ATTR.endswith("_resolved")
    assert ti.RESOLVED_BACKGROUND_ATTR.endswith("_resolved")


def test_module_does_not_import_theme_core_at_top_level():
    source = Path(ti.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "doxtr_pdf_theme_core" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or "doxtr_pdf_theme_core" not in node.module


def test_gate_is_config_attribute_not_find_spec():
    # The module must gate on the resolved config attribute, never importlib
    # find_spec / import machinery (detects active-theme, not merely installed).
    # Check for actual *usage* (a call / an importlib import), not docstring
    # mentions that explain why find_spec is deliberately avoided.
    source = Path(ti.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr != "find_spec"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "importlib" not in alias.name
        if isinstance(node, ast.ImportFrom):
            assert node.module is None or "importlib" not in node.module
    assert "getattr(config" in source
