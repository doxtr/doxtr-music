"""Unit tests for doxtr_music.config (no Sphinx build required)."""
import ast
import copy
import warnings
from pathlib import Path

from doxtr_music import config as cfg


# --- deep_update ------------------------------------------------------------
def test_deep_update_merges_nested_without_mutating_inputs():
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    over = {"b": 2, "nested": {"y": 20, "z": 3}}
    base_snapshot = copy.deepcopy(base)
    over_snapshot = copy.deepcopy(over)

    result = cfg.deep_update(base, over)

    assert result == {"a": 1, "b": 2, "nested": {"x": 1, "y": 20, "z": 3}}
    # Inputs unchanged.
    assert base == base_snapshot
    assert over == over_snapshot
    # Result is isolated from inputs.
    result["nested"]["x"] = 999
    assert base["nested"]["x"] == 1


# --- three_tier_merge -------------------------------------------------------
def test_three_tier_merge_precedence_user_over_theme_over_core():
    core = {"color": "black", "size": 10, "font": "serif"}
    theme = {"color": "navy", "size": 12}
    user = {"color": "red"}

    result = cfg.three_tier_merge(core, theme, user)

    assert result == {"color": "red", "size": 12, "font": "serif"}


def test_three_tier_merge_deep_copy_isolation():
    core = {"nested": {"a": 1}}
    theme = {}
    user = {}
    result = cfg.three_tier_merge(core, theme, user)
    result["nested"]["a"] = 99
    assert core["nested"]["a"] == 1


def test_three_tier_merge_empty_theme_is_clean_two_tier():
    core = {"a": 1, "b": 2}
    user = {"b": 20, "c": 3}
    assert cfg.three_tier_merge(core, {}, user) == {"a": 1, "b": 20, "c": 3}


# --- validate_config_keys ---------------------------------------------------
class _FakeConfig:
    """Minimal config stand-in exposing attributes via ``dir()``."""

    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            setattr(self, key, val)


def test_validate_config_keys_silent_on_known(caplog):
    config = _FakeConfig(
        doxtr_music_chord_system="english",
        doxtr_music_typography={},
    )
    with caplog.at_level("WARNING"):
        cfg.validate_config_keys(config)
    assert "Unknown configuration value" not in caplog.text


def test_validate_config_keys_warns_on_unknown(caplog):
    config = _FakeConfig(doxtr_music_bogus=1)
    with caplog.at_level("WARNING"):
        cfg.validate_config_keys(config)
    assert "Unknown configuration value" in caplog.text
    assert "doxtr_music_bogus" in caplog.text


def test_validate_config_keys_excludes_resolved_suffix(caplog):
    config = _FakeConfig(doxtr_music_theme_defaults_resolved={})
    with caplog.at_level("WARNING"):
        cfg.validate_config_keys(config)
    assert "doxtr_music_theme_defaults_resolved" not in caplog.text


# --- manifest drift guard (Python-value equality) ---------------------------
def test_manifest_has_exactly_thirteen_documented_values():
    # Grew from the 8-row CHUNK-0-3 snapshot via recorded amendments:
    # +latex_backend_path (7-1), +autoload_theme, +roman_display/+roman_format
    # (Roman-numeral display modes), +index_page_format (configurable song-index
    # / song page-number format). Recorded amendments, not silent creep.
    expected = {
        "doxtr_music_chord_system": ("english", "env"),
        "doxtr_music_latex_package": ("songbook", "env"),
        "doxtr_music_typography": ({}, "env"),
        "doxtr_music_singer_colors": ({}, "env"),
        "doxtr_music_roman_display": ("off", "env"),
        "doxtr_music_roman_format": ("{chord} ({roman})", "env"),
        "doxtr_music_index_page_format": ("{page}", "env"),
        "doxtr_music_theme_interop": (True, "env"),
        "doxtr_music_chord_preprocess": (None, "env"),
        "doxtr_music_node_parsed": (None, "env"),
        "doxtr_music_html_visit": (None, "html"),
        "doxtr_music_latex_backend_path": (None, "env"),
        "doxtr_music_autoload_theme": (True, "env"),
    }
    assert cfg.CONFIG_MANIFEST == expected
    assert set(cfg.MANIFEST_NAMES) == set(expected)
    assert len(cfg.CONFIG_MANIFEST) == 13


def test_valid_chord_systems():
    assert cfg.VALID_CHORD_SYSTEMS == frozenset(
        {"english", "german", "italian", "hungarian", "roman"}
    )


# --- soft dependency: no top-level import of doxtr_pdf_theme_core -----------
def test_config_module_does_not_import_theme_core():
    source = Path(cfg.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "doxtr_pdf_theme_core" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or "doxtr_pdf_theme_core" not in node.module


# --- register_config wiring -------------------------------------------------
def test_register_config_registers_all_manifest_values():
    registered = {}

    class _FakeApp:
        def add_config_value(self, name, default, rebuild):
            registered[name] = (default, rebuild)

    cfg.register_config(_FakeApp())
    assert registered == cfg.CONFIG_MANIFEST


# --- on_config_inited: chord-system fallback --------------------------------
def test_on_config_inited_invalid_chord_system_falls_back(caplog):
    config = _FakeConfig(doxtr_music_chord_system="klingon")
    with caplog.at_level("WARNING"):
        cfg.on_config_inited(None, config)
    assert config.doxtr_music_chord_system == "english"
    assert "Invalid doxtr_music_chord_system" in caplog.text


def test_on_config_inited_valid_chord_system_unchanged():
    config = _FakeConfig(doxtr_music_chord_system="german")
    cfg.on_config_inited(None, config)
    assert config.doxtr_music_chord_system == "german"


def test_on_config_inited_roman_chord_system_is_valid():
    config = _FakeConfig(doxtr_music_chord_system="roman")
    cfg.on_config_inited(None, config)
    assert config.doxtr_music_chord_system == "roman"
