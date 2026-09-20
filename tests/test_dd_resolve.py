"""``dd:`` color-expression resolution via doxtr-pdf-theme-core.

``dd:`` expressions derive a color from the active theme's semantic palette.
They require doxtr-pdf-theme-core; a ``dd:`` value used without the theme raises
an actionable error (no silent fallback).
"""
from __future__ import annotations

import sys
import types

import pytest

from doxtr_music import dd_resolve

import importlib.util
HAS_THEME = importlib.util.find_spec("doxtr_pdf_theme_core") is not None


def _cfg(**attrs):
    base = {"doxtr_theme_defaults": {}}
    base.update(attrs)
    return types.SimpleNamespace(**base)


def test_has_dd_expression():
    assert dd_resolve.has_dd_expression({"chord": {"color": "dd:primary"}})
    assert dd_resolve.has_dd_expression({"title": {"background": "dd:page:lighten:80"}})
    assert not dd_resolve.has_dd_expression({"chord": {"color": "#fff"}})
    assert not dd_resolve.has_dd_expression({"chord": {"size": "1em"}})
    assert not dd_resolve.has_dd_expression({})


def test_no_dd_is_identity_fast_path():
    typo = {"chord": {"color": "#b00020"}, "lyrics": {"size": "1.1em"}}
    # No dd: values -> returned unchanged, no theme import needed.
    assert dd_resolve.resolve_dd_in_typography(typo, _cfg()) is typo


@pytest.mark.skipif(not HAS_THEME, reason="doxtr-pdf-theme-core not installed")
def test_dd_resolves_against_theme_palette():
    typo = {
        "title": {"color": "dd:primary"},
        "chord": {"color": "dd:secondary:contrast:fg:page"},
        "section-verse-title": {"background": "dd:primary:lighten:85"},
        "meta-tempo": {"background": "#eee"},  # static passes through
    }
    out = dd_resolve.resolve_dd_in_typography(typo, _cfg())
    # Each dd: value became a static hex color.
    assert out["title"]["color"].startswith("#")
    assert out["chord"]["color"].startswith("#")
    assert out["section-verse-title"]["background"].startswith("#")
    # The contrast-adjusted chord color is NOT the raw light secondary.
    assert out["chord"]["color"].lower() != "#78d8f0"
    # Static value untouched.
    assert out["meta-tempo"]["background"] == "#eee"
    # Input not mutated.
    assert typo["title"]["color"] == "dd:primary"


@pytest.mark.skipif(not HAS_THEME, reason="doxtr-pdf-theme-core not installed")
def test_dd_honors_user_palette_overrides():
    typo = {"title": {"color": "dd:primary"}}
    cfg = _cfg(doxtr_theme_defaults={"semantic_palette": {"primary": "#010203"}})
    out = dd_resolve.resolve_dd_in_typography(typo, cfg)
    assert out["title"]["color"].lower() == "#010203"


def test_dd_without_theme_raises_actionable_error(monkeypatch):
    from sphinx.errors import ExtensionError

    # Simulate the theme being absent by blocking its import.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def _blocked_import(name, *a, **k):
        if name.startswith("doxtr_pdf_theme_core"):
            raise ImportError("blocked for test")
        return real_import(name, *a, **k)

    for m in list(sys.modules):
        if m.startswith("doxtr_pdf_theme_core"):
            monkeypatch.delitem(sys.modules, m, raising=False)
    monkeypatch.setattr("builtins.__import__", _blocked_import)

    with pytest.raises(ExtensionError) as exc:
        dd_resolve.resolve_dd_in_typography({"chord": {"color": "dd:primary"}}, _cfg())
    msg = str(exc.value)
    assert "doxtr-pdf-theme-core is not installed" in msg
    assert "pip install doxtr-pdf-theme-core" in msg
    assert "#" in msg  # gives a static-color example


def test_dd_module_imports_theme_only_lazily():
    # theme_interop must NOT import the theme (contract); dd_resolve MAY, but only
    # lazily inside a function (never at module top level).
    import ast
    from pathlib import Path

    source = Path(dd_resolve.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:  # top-level statements only
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "doxtr_pdf_theme_core" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or "doxtr_pdf_theme_core" not in node.module


# ---------------------------------------------------------------------------
# Dark-mode color transform + lyrics body-text-color default
# ---------------------------------------------------------------------------

def _sphinx_config(dark=False):
    """Build a real Sphinx config with the theme active (light or dark)."""
    import tempfile
    from pathlib import Path

    from sphinx.application import Sphinx

    root = Path(tempfile.mkdtemp())
    src = root / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        'extensions = ["doxtr_music", "doxtr_pdf_theme_core"]\n', encoding="utf-8"
    )
    (src / "index.rst").write_text("t\n=\n\ntext\n", encoding="utf-8")
    overrides = {"doxtr_dark_mode": True} if dark else {}
    app = Sphinx(
        srcdir=str(src), confdir=str(src), outdir=str(root / "out"),
        doctreedir=str(root / "dt"), buildername="latex",
        status=None, warning=None, confoverrides=overrides,
    )
    return app.config


@pytest.mark.skipif(not HAS_THEME, reason="doxtr-pdf-theme-core not installed")
def test_theme_body_text_color_light_and_dark():
    assert dd_resolve.theme_body_text_color(_sphinx_config(dark=False)) == "#000000"
    dark = dd_resolve.theme_body_text_color(_sphinx_config(dark=True))
    # Dark body text is a light color (not black).
    assert dark and dark.lower() != "#000000"


@pytest.mark.skipif(not HAS_THEME, reason="doxtr-pdf-theme-core not installed")
def test_dark_mode_resolves_dd_against_dark_palette():
    light = dd_resolve.resolve_dd_in_typography(
        {"title": {"color": "dd:primary"}}, _sphinx_config(dark=False)
    )["title"]["color"]
    dark = dd_resolve.resolve_dd_in_typography(
        {"title": {"color": "dd:primary"}}, _sphinx_config(dark=True)
    )["title"]["color"]
    # dd:primary resolves to DIFFERENT colors in light vs dark (dark palette).
    assert light.lower() != dark.lower()


@pytest.mark.skipif(not HAS_THEME, reason="doxtr-pdf-theme-core not installed")
def test_dark_mode_inverts_static_hex_color():
    out = dd_resolve.resolve_dd_in_typography(
        {"chord": {"color": "#b00020"}}, _sphinx_config(dark=True)
    )
    # A hardcoded hex color is soft-inverted for dark mode (adapts like body text).
    assert out["chord"]["color"].lower() != "#b00020"


@pytest.mark.skipif(not HAS_THEME, reason="doxtr-pdf-theme-core not installed")
def test_dark_mode_fills_lyrics_with_body_color_light_does_not():
    light = dd_resolve.fill_lyrics_body_color(
        {"lyrics": {"font": "Lato"}}, _sphinx_config(dark=False)
    )
    dark = dd_resolve.fill_lyrics_body_color(
        {"lyrics": {"font": "Lato"}}, _sphinx_config(dark=True)
    )
    # Light: lyrics color left unset (inherits the default black). Dark: filled
    # with the dark body text color so lyrics stay readable on the dark page.
    assert "color" not in light.get("lyrics", {})
    assert dark["lyrics"].get("color") and dark["lyrics"]["color"].lower() != "#000000"


@pytest.mark.skipif(not HAS_THEME, reason="doxtr-pdf-theme-core not installed")
def test_dark_mode_does_not_override_explicit_lyric_color():
    dark = dd_resolve.resolve_dd_in_typography(
        {"lyrics": {"color": "#112233"}}, _sphinx_config(dark=True)
    )
    # An explicit color is (inverted but) present; the body-color default does
    # not clobber it.
    assert dark["lyrics"]["color"].lower() != "#000000"


@pytest.mark.skipif(not HAS_THEME, reason="doxtr-pdf-theme-core not installed")
@pytest.mark.integration
def test_dark_latex_preamble_bakes_dark_global_colors(tmp_path):
    """Regression: the LaTeX global-typography preamble must be DARK-correct.

    The preamble injection was previously assembled at config-inited ~700,
    before doxtr-pdf-theme-core resolves dark mode (@900), so a dark build baked
    the LIGHT global colors into ``\\definecolor{dm@titlecolor}`` etc. (unreadable
    dark-navy lyrics on a dark page). The injection now runs after 900, so the
    global colors are the dark-adjusted palette values.
    """
    import re

    from sphinx.application import Sphinx

    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music", "doxtr_pdf_theme_core"]\n'
        'doxtr_music_typography = {"title": {"color": "dd:primary"}}\n'
        'latex_documents = [("index", "s.tex", "S", "A", "manual")]\n',
        encoding="utf-8",
    )
    (src / "index.rst").write_text(
        "S\n=\n\n.. song::\n\n   {title: T}\n   [C]Hello [D]world\n", encoding="utf-8"
    )

    def _title_color(dark):
        out = tmp_path / ("dark" if dark else "light")
        app = Sphinx(
            srcdir=str(src), confdir=str(src), outdir=str(out),
            doctreedir=str(tmp_path / "dt" / ("d" if dark else "l")),
            buildername="latex", status=None, warning=None,
            confoverrides={"doxtr_dark_mode": True} if dark else {},
            freshenv=True,
        )
        app.build(force_all=True)
        tex = next(out.glob("*.tex")).read_text(encoding="utf-8")
        m = re.search(r"\\definecolor\{dm@titlecolor\}\{HTML\}\{([0-9A-Fa-f]{6})\}", tex)
        return m.group(1).upper() if m else None

    light = _title_color(False)
    dark = _title_color(True)
    assert light and dark
    # dd:primary bakes DIFFERENT hex in light vs dark (dark palette used at >900).
    assert light != dark


@pytest.mark.skipif(not HAS_THEME, reason="doxtr-pdf-theme-core not installed")
def test_dark_mode_no_double_inversion_of_dd_colors():
    """Regression: a dd: color must be transformed exactly ONCE.

    stamp_typography starts from the already-dark-resolved global cache and
    merges a per-song delta; it must NOT re-run the dark transform over the
    whole merged dict (that soft-inverts the global's already-dark static hex a
    second time, e.g. #183060 -> #AABBDE -> #4A566F, an unreadable dark slate).
    A section-title dd:primary must equal the title dd:primary, not its inverse.
    """
    from doxtr_music.nodes import SectionNode, build_nodes
    from doxtr_music.parsers.chordpro import parse_chordpro
    from doxtr_music.typography import (
        RESOLVED_CONFIG_ATTR,
        resolve_global_typography,
        stamp_typography,
    )

    cfg = _sphinx_config(dark=True)
    # Both title and section-title use dd:primary; inject the global config.
    cfg.doxtr_music_typography = {
        "title": {"color": "dd:primary"},
        "section-title": {"color": "dd:primary"},
    }
    resolved_global = resolve_global_typography(cfg)
    from doxtr_music.dd_resolve import resolve_dd_in_typography

    resolved_global = resolve_dd_in_typography(resolved_global, cfg)
    setattr(cfg, RESOLVED_CONFIG_ATTR, resolved_global)

    toks, meta = parse_chordpro("{start_of_verse}\n[C]Hi\n{end_of_verse}")
    song = build_nodes(toks, meta)
    stamp_typography(song, resolved_global, config=cfg)

    title_color = song["typography"]["title"]["color"]
    section = list(song.findall(SectionNode))[0]
    section_color = section.get("typography_title", {}).get("color")
    # Single resolution: section title color == title color (both dd:primary).
    assert section_color == title_color
    # And it is the dark-palette value, not the double-inverted dark slate.
    assert section_color.lower() != "#4a566f"


# ---------------------------------------------------------------------------
# Contrast fix: a color must be readable on its OWN background
# ---------------------------------------------------------------------------

def test_ensure_contrast_no_theme_or_nonhex_is_noop(monkeypatch):
    # Non-hex (xcolor name) is left unchanged.
    assert dd_resolve.ensure_contrast("blue", "#ffffff", _cfg()) == "blue"
    assert dd_resolve.ensure_contrast("#111", "navy", _cfg()) == "#111"


@pytest.mark.skipif(not HAS_THEME, reason="doxtr-pdf-theme-core not installed")
def test_ensure_contrast_darkens_light_on_light():
    # Light foreground on a light background -> darkened to meet contrast.
    fixed = dd_resolve.ensure_contrast("#AABBDE", "#F2F5FA", _cfg())
    assert fixed.lower() != "#aabbde"


@pytest.mark.skipif(not HAS_THEME, reason="doxtr-pdf-theme-core not installed")
def test_contrast_fix_typography_fixes_color_on_background():
    typo = {
        # light color on light background -> color must change
        "section-verse-title": {"color": "#AABBDE", "background": "#F2F5FA"},
        # color with NO background -> untouched
        "title": {"color": "#AABBDE"},
    }
    out = dd_resolve.contrast_fix_typography(typo, _cfg())
    assert out["section-verse-title"]["color"].lower() != "#aabbde"
    assert out["section-verse-title"]["background"] == "#F2F5FA"
    assert out["title"]["color"] == "#AABBDE"  # no background -> unchanged


@pytest.mark.skipif(not HAS_THEME, reason="doxtr-pdf-theme-core not installed")
@pytest.mark.integration
def test_dark_highlight_lyrics_readable_on_marker_background(tmp_path):
    """Regression: highlighted lyrics/chords must contrast against the marker bg.

    A section-body background (a highlight marker) cascades onto the section's
    chord + lyric words; each word's color must be adjusted to contrast against
    that background so light body text on a light marker (dark mode) becomes
    dark + readable. The per-word color must also REACH the LaTeX output (the
    line-flow renderer scopes it), not just the global \\dmlyriccolor.
    """
    import re

    from sphinx.application import Sphinx

    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music", "doxtr_pdf_theme_core"]\n'
        'doxtr_music_typography = {"section-highlight-body": {"background": "dd:warning:lighten:70"}}\n'
        'latex_documents = [("index", "s.tex", "S", "A", "manual")]\n',
        encoding="utf-8",
    )
    (src / "index.rst").write_text(
        "S\n=\n\n.. song::\n\n   {start_of_highlight}\n   [F]Line here two\n"
        "   {end_of_highlight}\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    app = Sphinx(
        srcdir=str(src), confdir=str(src), outdir=str(out),
        doctreedir=str(tmp_path / "dt"), buildername="latex",
        status=None, warning=None, confoverrides={"doxtr_dark_mode": True},
        freshenv=True,
    )
    app.build(force_all=True)
    tex = next(out.glob("*.tex")).read_text(encoding="utf-8")

    # The highlight background color used by the \colorbox.
    bgm = re.search(r"\\definecolor\{dm@wordbg\}\{HTML\}\{([0-9A-Fa-f]{6})\}", tex)
    assert bgm, "no highlight \\colorbox background emitted"
    bg = bgm.group(1)
    # Every per-word color scoped inside a highlight \colorbox must contrast
    # against that background (WCAG AA >= 4.5), i.e. NOT stay the light body color.
    from doxtr_pdf_theme_core.utils import get_highest_contrast_color

    # Collect every per-word chord/lyric color hex inside a highlight box.
    word_colors = re.findall(
        r"\\colorbox\{dm@wordbg\}\{\\begingroup ((?:\\definecolor\{dm@word"
        r"(?:chord|lyric)color\}\{HTML\}\{[0-9A-Fa-f]{6}\} )+)",
        tex,
    )
    hexes = []
    for grp in word_colors:
        hexes += re.findall(r"\{HTML\}\{([0-9A-Fa-f]{6})\}", grp)
    assert hexes, "no per-word color scoped inside the highlight colorbox"
    for wc in hexes:
        # A contrast-safe color equals what get_highest_contrast_color returns
        # (already fixed) — assert it is not the untouched light body color.
        fixed = get_highest_contrast_color("#" + wc, "#" + bg, target="foreground")
        assert fixed.lower() == ("#" + wc).lower(), (
            "word color #%s not contrast-safe on #%s (would fix to %s)"
            % (wc, bg, fixed)
        )
