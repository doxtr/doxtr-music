"""Unit + integration tests for CHUNK-4-1 (granular typography).

Covers the exit criteria:

* Per-element/per-attr merge (core -> global -> per-song); ``:chord-color:``
  overrides only chord color; other cells inherit.
* All five elements + each attr independently, resolved to the right cell.
* HTML/EPUB per-song rides an inline ``style`` (not shared class CSS); the
  global rides an injected element-class ``<style>`` block; EPUB sizes relative.
* LaTeX: the global preamble contributor ``\\renewcommand``s the indirection
  macros; a per-song scoped ``\\begingroup...\\def...\\endgroup`` group
  redefines only the overridden attr-macros; ``\\definecolor`` is HTML-model.
* Invalid element/attr -> warn + ignore; invalid LaTeX color -> warn + fallback.
* 4-1 does NOT edit ``_options.py`` (single parse point).
* Styling-only: a typography-styled song still passes ``COPY_SAFE_ORDER_HTML``.
* singer-vs-typography color precedence contract is documented (4-2 inherits);
  here we assert typography font/size always apply and color is the collision.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from doxtr_music import nodes as _nodes
from doxtr_music.typography import (
    ATTRS,
    CORE_TYPOGRAPHY,
    ELEMENTS,
    css_declarations,
    global_typography_style_block,
    latex_typography_contributor,
    normalize_latex_color,
    resolve_global_typography,
    resolve_song_typography,
    song_typography_latex_group,
    stamp_typography,
    validate_typography,
)
from doxtr_music.tokens import (
    ChordToken,
    LineBreakToken,
    LyricToken,
    SectionToken,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "test_harness"))


# ---------------------------------------------------------------------------
# validate_typography
# ---------------------------------------------------------------------------

def test_validate_drops_unknown_element_and_attr():
    warnings = []
    cleaned = validate_typography(
        {
            "chord": {"color": "#c00", "bogusattr": "x"},
            "boguselement": {"color": "red"},
        },
        warn=warnings.append,
    )
    assert cleaned == {"chord": {"color": "#c00"}}
    assert any("bogusattr" in w for w in warnings)
    assert any("boguselement" in w for w in warnings)


def test_validate_drops_css_unsafe_values():
    warnings = []
    cleaned = validate_typography(
        {"chord": {"color": "red; } body {"}}, warn=warnings.append
    )
    assert cleaned == {}
    assert warnings


def test_validate_non_dict_is_ignored():
    warnings = []
    assert validate_typography("nope", warn=warnings.append) == {}
    assert warnings


def test_validate_empty_string_treated_as_unset():
    assert validate_typography({"chord": {"color": "  "}}) == {}


# ---------------------------------------------------------------------------
# Merge: core -> global -> per-song, per-attr
# ---------------------------------------------------------------------------

def test_core_defaults_complete_5x3():
    assert set(CORE_TYPOGRAPHY) == set(ELEMENTS)
    for element in ELEMENTS:
        assert set(CORE_TYPOGRAPHY[element]) == set(ATTRS)


def test_per_attr_merge_chord_color_only():
    resolved_global = resolve_song_typography(  # global tier only
        CORE_TYPOGRAPHY, {"chord": {"color": "#c00"}}
    )
    # A per-song :lyrics-color: overrides only lyrics color; chord keeps global.
    merged = resolve_song_typography(resolved_global, {"lyrics": {"color": "blue"}})
    assert merged["chord"]["color"] == "#c00"
    assert merged["lyrics"]["color"] == "blue"
    # Other cells still inherit (None).
    assert merged["chord"]["font"] is None
    assert merged["lyrics"]["size"] is None
    assert merged["title"]["color"] is None


def test_per_song_overrides_single_attr_not_whole_element():
    base = resolve_song_typography(
        CORE_TYPOGRAPHY, {"chord": {"color": "#c00", "font": "serif"}}
    )
    merged = resolve_song_typography(base, {"chord": {"color": "green"}})
    # color overridden, font inherited from the global.
    assert merged["chord"]["color"] == "green"
    assert merged["chord"]["font"] == "serif"


def test_all_five_elements_each_attr_independently():
    spec = {el: {attr: "%s-%s" % (el, attr) for attr in ATTRS} for el in ELEMENTS}
    # Sizes must be plausible CSS to survive validation; use em values.
    for el in ELEMENTS:
        spec[el]["size"] = "1.2em"
        spec[el]["color"] = "#010101"
        spec[el]["font"] = "serif"
    merged = resolve_song_typography(CORE_TYPOGRAPHY, spec)
    for el in ELEMENTS:
        assert merged[el]["color"] == "#010101"
        assert merged[el]["font"] == "serif"
        assert merged[el]["size"] == "1.2em"


# ---------------------------------------------------------------------------
# css_declarations (HTML/EPUB emission)
# ---------------------------------------------------------------------------

def test_css_declarations_all_attrs():
    css = css_declarations({"font": "serif", "size": "1.2em", "color": "#c00"})
    assert "font-family:serif" in css
    assert "font-size:1.2em" in css
    assert "color:#c00" in css


def test_css_declarations_empty_cell_is_blank():
    assert css_declarations({}) == ""
    assert css_declarations({"color": None}) == ""


def test_epub_absolute_size_downgraded_to_relative():
    warnings = []
    css = css_declarations({"size": "14pt"}, relative_size=True, warn=warnings.append)
    assert "em" in css and "pt" not in css
    assert warnings  # downgrade warned


def test_epub_relative_size_preserved():
    css = css_declarations({"size": "1.5em"}, relative_size=True)
    assert "font-size:1.5em" in css


# ---------------------------------------------------------------------------
# Global HTML/EPUB <style> block
# ---------------------------------------------------------------------------

def test_global_style_block_html_targets_chord_class():
    block = global_typography_style_block({"chord": {"color": "#c00"}})
    assert ".doxtr-chord" in block
    assert "#c00" in block
    assert 'class="doxtr-music-typography"' in block


def test_global_style_block_epub_targets_row_class():
    block = global_typography_style_block({"lyrics": {"color": "blue"}}, epub=True)
    assert ".doxtr-lyricrow" in block
    assert "color:blue" in block


def test_global_style_block_empty_when_nothing_set():
    assert global_typography_style_block({}) == ""
    assert global_typography_style_block(CORE_TYPOGRAPHY) == ""  # all None


# ---------------------------------------------------------------------------
# LaTeX color normalization + preamble contributor + per-song group
# ---------------------------------------------------------------------------

def test_normalize_hex_color_definecolor_html_model():
    expr, defline = normalize_latex_color("#c00", define_name="dm@chordcolor")
    assert expr == "dm@chordcolor"
    assert "\\definecolor{dm@chordcolor}{HTML}{CC0000}" == defline


def test_normalize_named_color_no_definecolor():
    expr, defline = normalize_latex_color("red", define_name="dm@x")
    assert expr == "red"
    assert defline == ""


def test_normalize_bad_color_warns_and_falls_back():
    warnings = []
    expr, defline = normalize_latex_color(
        "not-a-color", define_name="dm@x", warn=warnings.append
    )
    assert expr is None and defline == ""
    assert warnings


class _FakeConfig:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_latex_global_contributor_renewcommands():
    cfg = _FakeConfig(doxtr_music_typography_resolved=resolve_song_typography(
        CORE_TYPOGRAPHY, {"chord": {"color": "#c00"}, "lyrics": {"font": "serif"}}
    ))
    tex = latex_typography_contributor(cfg)
    assert "\\renewcommand{\\dmchordcolor}" in tex
    assert "\\definecolor{dm@chordcolor}{HTML}{CC0000}" in tex
    assert "\\renewcommand{\\dmlyricfont}" in tex


def test_latex_global_contributor_empty_when_unset():
    cfg = _FakeConfig(doxtr_music_typography_resolved=dict(CORE_TYPOGRAPHY))
    assert latex_typography_contributor(cfg) == ""


def test_latex_per_song_group_defs_only_overridden():
    open_tex, close_tex = song_typography_latex_group({"lyrics": {"color": "#0000cc"}})
    assert open_tex.startswith("\\begingroup% doxtr-music song typography")
    assert "\\def\\dmlyriccolor" in open_tex
    # Only the overridden attr is \def'd (no chord macro).
    assert "\\dmchordcolor" not in open_tex
    assert close_tex.strip() == "\\endgroup% doxtr-music song typography"


def test_latex_per_song_group_no_override_is_just_begingroup():
    open_tex, close_tex = song_typography_latex_group({})
    assert open_tex.strip() == "\\begingroup% doxtr-music song typography"
    assert "\\endgroup" in close_tex


def test_latex_arity_unchanged_indirection_macros_are_arity0():
    # The redefinitions target arity-0 \dmXcolor macros, never the \dmchord{}{}
    # arity-2 content macro.
    open_tex, _ = song_typography_latex_group({"chord": {"color": "#c00"}})
    assert "\\dmchord{" not in open_tex
    assert "\\def\\dmchordcolor" in open_tex


# ---------------------------------------------------------------------------
# Stamping onto child nodes (build-time, node-local)
# ---------------------------------------------------------------------------

def _build_song(options=None):
    tokens = [
        SectionToken(label="Verse", kind="verse"),
        ChordToken(text="C", column=0),
        LyricToken(text="Hello", column=0),
        LineBreakToken(),
    ]
    return _nodes.build_nodes(tokens, {"title": "T"}, options=options)


def test_stamp_applies_resolved_cells_to_children():
    song = _build_song(options={"typography": {"lyrics": {"color": "#0000cc"}}})
    resolved_global = resolve_song_typography(CORE_TYPOGRAPHY, {"chord": {"color": "#c00"}})
    stamp_typography(song, resolved_global)
    chords = list(song.findall(_nodes.ChordNode))
    lyrics = list(song.findall(_nodes.LyricNode))
    assert chords and lyrics
    assert chords[0]["typography"] == {"color": "#c00"}
    assert lyrics[0]["typography"] == {"color": "#0000cc"}


def test_stamp_leaves_unset_children_without_typography_attr():
    song = _build_song(options={"typography": {"chord": {"color": "#c00"}}})
    stamp_typography(song, resolve_global_typography(_FakeConfig(doxtr_music_typography={})))
    lyrics = list(song.findall(_nodes.LyricNode))
    # No lyric typography set anywhere -> no stamp.
    assert "typography" not in lyrics[0]


def test_reduce_options_preserves_nested_typography():
    # build_nodes reduces options to plain data; the nested typography dict must
    # survive (CHUNK-1-2 amendment for CHUNK-4-1).
    song = _build_song(options={"typography": {"chord": {"color": "#c00"}}})
    assert song["options"]["typography"] == {"chord": {"color": "#c00"}}


# ---------------------------------------------------------------------------
# singer-vs-typography precedence contract (4-2 inherits)
# ---------------------------------------------------------------------------

def test_typography_font_size_independent_of_color():
    # Typography font/size always apply; color is the only collision with a
    # future singer color (4-2). Here we assert font/size resolve independently.
    merged = resolve_song_typography(
        CORE_TYPOGRAPHY, {"chord": {"font": "serif", "size": "1.2em"}}
    )
    assert merged["chord"]["font"] == "serif"
    assert merged["chord"]["size"] == "1.2em"
    assert merged["chord"]["color"] is None


# ---------------------------------------------------------------------------
# Integration: real Sphinx builds (HTML/EPUB/LaTeX)
# ---------------------------------------------------------------------------

sphinx = pytest.importorskip("sphinx")
from sphinx.application import Sphinx  # noqa: E402

_TYPO_RST = textwrap.dedent(
    """\
    Typo
    ====

    .. song::
       :lyrics-color: #0000cc
       :chord-font: monospace
       :title-color: #008000

       {title: Styled}
       {key: C}

       {start_of_verse}
       [C]Hello [Am]world
       {end_of_verse}
    """
)


def _make_project(root: Path, *, global_typo=True):
    src = root / "src"
    src.mkdir(parents=True)
    conf = (
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music"]\n'
        'html_theme = "basic"\n'
    )
    if global_typo:
        conf += 'doxtr_music_typography = {"chord": {"color": "#cc0000"}}\n'
    (src / "conf.py").write_text(conf, encoding="utf-8")
    (src / "index.rst").write_text(_TYPO_RST, encoding="utf-8")
    return src


def _build(root: Path, builder: str, warnings_buf=None):
    src = _make_project(root)
    app = Sphinx(
        srcdir=str(src), confdir=str(src),
        outdir=str(root / ("out-" + builder)),
        doctreedir=str(root / "doctrees"),
        buildername=builder, freshenv=True, warning=warnings_buf,
    )
    app.build(force_all=True)
    return root / ("out-" + builder)


def test_html_build_global_style_and_per_song_inline(tmp_path):
    out = _build(tmp_path, "html")
    html = (out / "index.html").read_text(encoding="utf-8")
    # Global chord color rides the injected element-class <style> block.
    assert 'class="doxtr-music-typography"' in html
    assert "#cc0000" in html.replace(" ", "")
    # Per-song lyric color rides an inline style on the lyric span.
    assert "#0000cc" in html.replace(" ", "")
    assert 'class="doxtr-lyric"' in html


def test_html_typography_assertion_passes(tmp_path):
    import assertions as A

    out = _build(tmp_path, "html")
    html = (out / "index.html").read_text(encoding="utf-8")
    res = A.check_assertions(html, [A.AssertType.TYPOGRAPHY_APPLIED_HTML])[0]
    assert res.passed, res.details
    copy = A.check_assertions(html, [A.AssertType.COPY_SAFE_ORDER_HTML])[0]
    assert copy.passed, copy.details  # styling-only: copy-safety intact


def test_latex_build_two_mechanisms(tmp_path):
    out = _build(tmp_path, "latex")
    tex = next(out.glob("*.tex")).read_text(encoding="utf-8")
    import assertions as A

    res = A.check_assertions(tex, [A.AssertType.TYPOGRAPHY_APPLIED_LATEX])[0]
    assert res.passed, res.details


def test_epub_build_typography(tmp_path):
    out = _build(tmp_path, "epub")
    # Read a content doc from the epub output tree.
    xhtmls = list(out.rglob("index.xhtml")) + list(out.rglob("index.html"))
    assert xhtmls, "no epub content document built"
    content = xhtmls[0].read_text(encoding="utf-8")
    import assertions as A

    res = A.check_assertions(content, [A.AssertType.TYPOGRAPHY_APPLIED_EPUB])[0]
    assert res.passed, res.details


# ---------------------------------------------------------------------------
# Extended styling: background attr, section-kind styling, per-metadata-key
# (font/size/color/background for title/chord/section title+body/metadata).
# ---------------------------------------------------------------------------

def test_validate_accepts_background_and_dynamic_elements():
    from doxtr_music.typography import validate_typography

    cleaned = validate_typography(
        {
            "chord": {"background": "#ffd"},
            "section-verse-title": {"color": "#a00", "background": "#fee"},
            "section-body": {"size": "0.95em"},
            "meta-tempo": {"color": "#00a", "font": "monospace"},
            "metadata": {"size": "0.9em"},
        }
    )
    assert cleaned["chord"] == {"background": "#ffd"}
    assert cleaned["section-verse-title"] == {"color": "#a00", "background": "#fee"}
    assert cleaned["meta-tempo"] == {"color": "#00a", "font": "monospace"}


def test_validate_rejects_unknown_dynamic_element():
    from doxtr_music.typography import validate_typography

    warnings = []
    cleaned = validate_typography(
        {"section-verse-footer": {"color": "#a00"}, "meta-": {"color": "#0a0"}},
        warn=warnings.append,
    )
    # Neither is a valid element name → dropped with a warning.
    assert cleaned == {}
    assert len(warnings) == 2


def test_section_element_names_fallback_chain():
    from doxtr_music.typography import section_element_names

    title_chain, body_chain = section_element_names("chorus")
    assert title_chain == ["section-chorus-title", "section-title"]
    assert body_chain == ["section-chorus-body", "section-body"]
    # kind="none" (unlabeled) uses only the generic element.
    assert section_element_names("none") == (["section-title"], ["section-body"])


def test_meta_element_names_fallback_chain():
    from doxtr_music.typography import meta_element_names

    assert meta_element_names("tempo") == ["meta-tempo", "metadata"]
    assert meta_element_names("KEY") == ["meta-key", "metadata"]


def test_resolve_element_cell_merges_specific_over_generic():
    from doxtr_music.typography import resolve_element_cell

    resolved = {
        "section-title": {"color": "#111", "font": "serif", "size": None},
        "section-verse-title": {"color": "#a00"},
    }
    cell = resolve_element_cell(resolved, ["section-verse-title", "section-title"])
    # verse color wins; generic font fills in; no size set anywhere.
    assert cell == {"color": "#a00", "font": "serif"}


def test_css_declarations_emits_background():
    from doxtr_music.typography import css_declarations

    decls = css_declarations({"color": "#a00", "background": "#eee"})
    assert "color:#a00" in decls
    assert "background-color:#eee" in decls


def test_stamp_stamps_section_title_and_body_cells():
    from doxtr_music.tokens import (
        ChordToken,
        LineBreakToken,
        LyricToken,
        SectionToken,
    )
    from doxtr_music.typography import resolve_song_typography, stamp_typography

    tokens = [
        SectionToken(label="Chorus", kind="chorus"),
        ChordToken(text="C", column=0),
        LyricToken(text="Hi", column=0),
        LineBreakToken(),
    ]
    song = _nodes.build_nodes(tokens, {"title": "T"})
    resolved = resolve_song_typography(
        CORE_TYPOGRAPHY,
        {
            "section-title": {"color": "#111"},
            "section-chorus-title": {"background": "#ffe"},
            "section-body": {"size": "0.9em"},
        },
    )
    stamp_typography(song, resolved)
    section = list(song.findall(_nodes.SectionNode))[0]
    # Chorus title merges the chorus background over the generic color.
    assert section["typography_title"] == {"color": "#111", "background": "#ffe"}
    assert section["typography_body"] == {"size": "0.9em"}


# ---------------------------------------------------------------------------
# Named fonts (fontspec) — Lato/Anton/Dekko/Kavoon/SirinStencil etc.
# ---------------------------------------------------------------------------

def test_is_named_font_distinguishes_generic_from_named():
    from doxtr_music.typography import _is_named_font

    assert _is_named_font("Lato")
    assert _is_named_font("Sirin Stencil")
    assert not _is_named_font("serif")
    assert not _is_named_font("monospace")
    assert not _is_named_font("")


def test_font_face_command_is_letters_only():
    from doxtr_music.typography import _font_face_command

    assert _font_face_command("Lato") == "\\dmfontfaceLato"
    assert _font_face_command("Sirin Stencil") == "\\dmfontfaceSirinStencil"
    assert _font_face_command("Anton") == "\\dmfontfaceAnton"


def test_latex_font_switch_named_vs_generic():
    from doxtr_music.typography import latex_font_switch

    assert latex_font_switch("serif") == "\\rmfamily"
    assert latex_font_switch("monospace") == "\\ttfamily"
    assert latex_font_switch("Lato") == "\\dmfontfaceLato"
    assert latex_font_switch("") == ""


def test_collect_named_fonts_unique_sorted():
    from doxtr_music.typography import collect_named_fonts

    resolved = {
        "lyrics": {"font": "Lato"},
        "chord": {"font": "Anton"},
        "title": {"font": "serif"},          # generic -> excluded
        "meta-tempo": {"font": "Lato"},       # dup -> collapsed
        "section-verse-title": {"font": "Dekko"},
    }
    assert collect_named_fonts(resolved) == ["Anton", "Dekko", "Lato"]


def test_fontface_declarations_guarded_by_fontspec():
    from doxtr_music.typography import _fontface_declarations

    tex = _fontface_declarations({"lyrics": {"font": "Lato"}, "chord": {"font": "Anton"}})
    # fontspec-guarded \newfontfamily for each named font + a no-op fallback.
    assert "\\@ifpackageloaded{fontspec}" in tex
    assert "\\newfontfamily\\dmfontfaceLato{Lato}" in tex
    assert "\\newfontfamily\\dmfontfaceAnton{Anton}" in tex
    assert "\\providecommand{\\dmfontfaceLato}{\\relax}" in tex
    # No named fonts -> empty.
    assert _fontface_declarations({"title": {"font": "serif"}}) == ""


def test_latex_typography_contributor_emits_font_faces():
    from doxtr_music.typography import latex_typography_contributor

    class _Cfg:
        doxtr_music_typography_resolved = {
            "lyrics": {"font": "Lato", "color": None, "size": None, "background": None},
            "chord": {"font": "Anton", "color": None, "size": None, "background": None},
        }

    out = latex_typography_contributor(_Cfg())
    assert "\\newfontfamily\\dmfontfaceLato{Lato}" in out
    assert "\\renewcommand{\\dmlyricfont}{\\dmfontfaceLato}" in out
    assert "\\renewcommand{\\dmchordfont}{\\dmfontfaceAnton}" in out
