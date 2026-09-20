"""Unit tests for CHUNK-4-2 — multi-singer ``{singer: X}`` + singer→color.

Covers the LOCKED contracts:

* distinct colors per singer id (global + per-song merge; per-id override);
* mid-line switch → multiple colored runs within one line;
* singer color WINS over typography color (resolved in Python, emitted once),
  while typography font/size survive — across all three formats;
* unmapped id → ``None`` stamp (typography color survives) + debug log; invalid
  color → warn + fallback (Python time);
* LaTeX ``\\dmsinger`` sets the run's indirection color macros;
* COPY_SAFE_ORDER_HTML + COPY_SAFE_ORDER_EPUB_PRE on a multi-singer fixture;
* i18n compose: a localized chord inside a ``{singer}`` span keeps the localized
  text + the singer color (text-vs-style orthogonal).
"""

from __future__ import annotations

import pytest

from doxtr_music.nodes import (
    ChordNode,
    LineNode,
    LyricNode,
    SingerSpanNode,
    build_nodes,
)
from doxtr_music.singer import (
    resolve_singer_colors,
    stamp_singer_colors,
    validate_singer_colors,
)
from doxtr_music.tokens import (
    ChordToken,
    LineBreakToken,
    LyricToken,
    SingerToken,
)


class _Config:
    """Minimal stand-in for a Sphinx ``config`` (attribute lookups only)."""

    def __init__(self, singer_colors=None):
        self.doxtr_music_singer_colors = singer_colors or {}


# ---------------------------------------------------------------------------
# resolve_singer_colors / validate_singer_colors
# ---------------------------------------------------------------------------

def test_resolve_merges_global_and_per_song():
    config = _Config({"A": "#999999", "B": "orange"})
    eff = resolve_singer_colors(config, per_song={"A": "#1a53a1", "C": "teal"})
    # Per-song overrides A per-id; B stays from global; C added per-song.
    assert eff == {"A": "#1a53a1", "B": "orange", "C": "teal"}


def test_resolve_per_song_overrides_per_id_only():
    config = _Config({"A": "red", "B": "green"})
    eff = resolve_singer_colors(config, per_song={"A": "blue"})
    assert eff["A"] == "blue"  # overridden
    assert eff["B"] == "green"  # untouched


def test_validate_drops_unsafe_and_empty_colors():
    warned = []
    cleaned = validate_singer_colors(
        {"A": "red", "B": "  ", "C": "col;or}", "": "x", 5: "y"},
        warn=warned.append,
    )
    assert cleaned == {"A": "red"}
    # B empty is silently dropped; C unsafe, "" id, and 5 non-str id all warn.
    assert len(warned) >= 2


def test_validate_non_dict_returns_empty():
    warned = []
    assert validate_singer_colors("nope", warn=warned.append) == {}
    assert warned  # truthy non-dict warns


# ---------------------------------------------------------------------------
# stamp_singer_colors: distinct colors, unmapped, precedence
# ---------------------------------------------------------------------------

def test_stamp_distinct_colors_per_singer():
    tokens = [
        SingerToken(singer="A"),
        ChordToken(text="C", column=0),
        LyricToken(text="Hello", column=0),
        LineBreakToken(),
        SingerToken(singer="B"),
        ChordToken(text="F", column=0),
        LyricToken(text="Bye", column=0),
        LineBreakToken(),
    ]
    node = build_nodes(tokens, {}, {"singer_colors": {"A": "#1a53a1", "B": "#e07b00"}})
    stamp_singer_colors(node, _Config())
    spans = list(node.findall(SingerSpanNode))
    assert len(spans) == 2
    by_singer = {s.get("singer"): s for s in spans}
    assert by_singer["A"].get("singer_color") == "#1a53a1"
    assert by_singer["B"].get("singer_color") == "#e07b00"
    # The stamp reaches the run's chord + lyric children.
    for s in spans:
        color = s.get("singer_color")
        for child in s.findall(ChordNode):
            assert child.get("singer_color") == color
        for child in s.findall(LyricNode):
            assert child.get("singer_color") == color


def test_stamp_global_map_applies_without_per_song():
    tokens = [
        SingerToken(singer="A"),
        ChordToken(text="C", column=0),
        LyricToken(text="Hi", column=0),
        LineBreakToken(),
    ]
    node = build_nodes(tokens, {}, {})  # no per-song option
    stamp_singer_colors(node, _Config({"A": "purple"}))
    span = next(node.findall(SingerSpanNode))
    assert span.get("singer_color") == "purple"


def test_mid_line_switch_two_runs_one_line():
    # A SingerToken with no surrounding LineBreak switches mid-line: build_nodes
    # closes and reopens the span, yielding two runs inside ONE LineNode.
    tokens = [
        SingerToken(singer="A"),
        LyricToken(text="Hello", column=0),
        ChordToken(text="C", column=0),
        SingerToken(singer="B"),
        LyricToken(text="world", column=6),
        ChordToken(text="G", column=6),
        LineBreakToken(),
    ]
    node = build_nodes(tokens, {}, {"singer_colors": {"A": "red", "B": "blue"}})
    stamp_singer_colors(node, _Config())
    line = next(node.findall(LineNode))
    spans = list(line.findall(SingerSpanNode))
    assert len(spans) == 2
    assert [s.get("singer_color") for s in spans] == ["red", "blue"]


def test_unmapped_singer_stamps_none_and_logs(caplog):
    import logging

    tokens = [
        SingerToken(singer="Z"),
        ChordToken(text="C", column=0),
        LyricToken(text="Hi", column=0),
        LineBreakToken(),
    ]
    node = build_nodes(tokens, {}, {})
    with caplog.at_level(logging.DEBUG, logger="sphinx.doxtr_music.singer"):
        stamp_singer_colors(node, _Config({"A": "red"}))
    span = next(node.findall(SingerSpanNode))
    # Unmapped id → stamp nothing (None) → typography color survives downstream.
    assert span.get("singer_color") is None
    for child in span.findall(ChordNode):
        assert child.get("singer_color") is None


def test_invalid_color_warns_and_falls_back():
    warned = []
    # An unsafe color string is dropped at validation, so the id ends unmapped.
    eff = resolve_singer_colors(
        _Config({"A": "col;or"}), per_song=None, warn=warned.append
    )
    assert "A" not in eff
    assert warned


# ---------------------------------------------------------------------------
# Per-format rendering: singer wins on color, font stays
# ---------------------------------------------------------------------------

def _duet_song_rst():
    return (
        ".. song::\n"
        "   :chord-color: #cc0000\n"
        "   :chord-font: monospace\n"
        "   :singer-colors: A: #1a53a1, B: #e07b00\n"
        "\n"
        "   {title: Duet}\n"
        "   {start_of_verse}\n"
        "   {singer: A}\n"
        "   [C]Hello [Am]world\n"
        "   {singer: B}\n"
        "   [F]Goodbye [G]now\n"
        "   {end_of_verse}\n"
    )


@pytest.fixture()
def duet_builds(tmp_path):
    """Build the duet song to HTML, LaTeX and EPUB; return the output text."""
    sphinx = pytest.importorskip("sphinx.application")
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        'project = "t"\nauthor = "t"\n'
        'extensions = ["doxtr_music"]\n'
        'html_theme = "basic"\n'
    )
    (src / "index.rst").write_text("Duet\n====\n\n" + _duet_song_rst())

    out = {}
    for builder in ("html", "latex", "epub"):
        bdir = tmp_path / builder
        app = sphinx.Sphinx(
            srcdir=str(src),
            confdir=str(src),
            outdir=str(bdir),
            doctreedir=str(tmp_path / "doctrees" / builder),
            buildername=builder,
            status=None,
            warning=None,
        )
        app.build()
        if builder == "html":
            out["html"] = (bdir / "index.html").read_text(encoding="utf-8")
        elif builder == "latex":
            tex = list(bdir.glob("*.tex"))
            out["latex"] = tex[0].read_text(encoding="utf-8") if tex else ""
        else:
            xhtml = list(bdir.glob("index.xhtml"))
            out["epub"] = xhtml[0].read_text(encoding="utf-8") if xhtml else ""
    return out


def test_html_singer_wins_on_color_font_stays(duet_builds):
    import re

    html = duet_builds["html"]
    # data-singer hook on the span, no color on the span itself.
    assert 'class="doxtr-singer" data-singer="A"' in html
    assert 'class="doxtr-singer" data-singer="B"' in html
    styles = re.findall(
        r'<span class="doxtr-(?:chord|lyric)"[^>]*style="([^"]*)"', html
    )
    joined = " ".join(styles).replace(" ", "")
    # Singer colors win on color.
    assert "color:#1a53a1" in joined
    assert "color:#e07b00" in joined
    # Typography chord color must NOT survive on a singer-colored element.
    assert "color:#cc0000" not in joined
    # Typography font survives (font/size collision is not owned by singer).
    assert "font-family:monospace" in joined


def test_latex_dmsinger_sets_indirection_macros(duet_builds):
    import re

    tex = duet_builds["latex"]
    # CHUNK-4-2: the WINNING singer color is applied per rendered word by scoping
    # the run's indirection color macros inside a \begingroup group, so
    # \dmchord / \dmlyric pick up the winner from their own indirection (never an
    # outer \color losing to the inner \dmchordcolor). The song line is rendered
    # in column order with reconstructed spacing (the chord/lyric words are
    # collected per line, not emitted inline), so there is no \dmsinger{id}{...}
    # content wrapper — the color scoping wraps each word directly.
    # The color scoping is emitted comment-free (a trailing % would comment out
    # the next inline word's \begingroup), as a \begingroup ... \endgroup group.
    assert "\\begingroup " in tex
    assert "\\endgroup " in tex
    # The chord + lyric indirection colors are scoped per word (independent
    # \definecolor names for chord vs lyric); for a singer run BOTH resolve to
    # the same singer color.
    assert re.search(r"\\def\\dmchordcolor\{\\color\{dm@word(chord|lyric)color\}\}", tex)
    assert re.search(r"\\def\\dmlyriccolor\{\\color\{dm@wordlyriccolor\}\}", tex)
    # The color scopes an actual rendered word (\dmchord / \dmlyric) inside the
    # group — not an empty \dmsinger wrapper.
    assert re.search(
        r"\\def\\dmlyriccolor\{\\color\{dm@wordlyriccolor\}\}\\dmchord\{", tex
    )
    # Both singer colors defined (hex uppercased).
    assert "{HTML}{1A53A1}" in tex
    assert "{HTML}{E07B00}" in tex


def test_epub_colors_both_rows(duet_builds):
    import re

    xhtml = duet_builds["epub"]
    blocks = re.findall(r"<pre class=\"doxtr-line-epub\">(.*?)</pre>", xhtml, re.DOTALL)
    assert blocks
    chord_rows = " ".join(
        re.search(r'doxtr-chordrow[^>]*>(.*?)</span>', b, re.DOTALL).group(1)
        for b in blocks
        if re.search(r'doxtr-chordrow[^>]*>(.*?)</span>', b, re.DOTALL)
    )
    lyric_rows = " ".join(
        re.search(r'doxtr-lyricrow[^>]*>(.*?)</span>', b, re.DOTALL).group(1)
        for b in blocks
        if re.search(r'doxtr-lyricrow[^>]*>(.*?)</span>', b, re.DOTALL)
    )
    # Both rows carry the singer-colored cell sub-ranges (two-row model).
    for color in ("#1a53a1", "#e07b00"):
        assert color in chord_rows.replace(" ", "")
        assert color in lyric_rows.replace(" ", "")


def test_copy_safety_html_and_epub(duet_builds):
    from test_harness.assertions import AssertType, check_assertions

    html_res = check_assertions(
        duet_builds["html"], [AssertType.COPY_SAFE_ORDER_HTML]
    )
    assert all(r.passed for r in html_res), [r.details for r in html_res]

    epub_res = check_assertions(
        duet_builds["epub"], [AssertType.COPY_SAFE_ORDER_EPUB_PRE]
    )
    assert all(r.passed for r in epub_res), [r.details for r in epub_res]


# ---------------------------------------------------------------------------
# i18n compose: localized chord inside a singer span keeps text + color
# ---------------------------------------------------------------------------

def test_i18n_localized_chord_in_singer_span(tmp_path):
    import re

    sphinx = pytest.importorskip("sphinx.application")
    src = tmp_path / "src"
    src.mkdir()
    # German chord system localizes B->H / Bb->B etc.; the chord text is German
    # while the singer color is orthogonal styling.
    (src / "conf.py").write_text(
        'project = "t"\nauthor = "t"\n'
        'extensions = ["doxtr_music"]\n'
        'html_theme = "basic"\n'
        'doxtr_music_chord_system = "german"\n'
    )
    (src / "index.rst").write_text(
        "T\n=\n\n"
        ".. song::\n"
        "   :singer-colors: A: #1a53a1\n"
        "\n"
        "   {start_of_verse}\n"
        "   {singer: A}\n"
        "   [Bm7]Word\n"
        "   {end_of_verse}\n"
    )
    bdir = tmp_path / "html"
    app = sphinx.Sphinx(
        srcdir=str(src), confdir=str(src), outdir=str(bdir),
        doctreedir=str(tmp_path / "dt"), buildername="html",
        status=None, warning=None,
    )
    app.build()
    html = (bdir / "index.html").read_text(encoding="utf-8")
    # German localization applied to the visible chord text (Bm7 -> Hm7).
    chord = re.search(r'<span class="doxtr-chord"[^>]*>([^<]*)</span>', html)
    assert chord is not None
    assert "Hm7" in chord.group(1)
    # ...and the singer color still rides the same chord element (orthogonal).
    assert "#1a53a1" in re.search(
        r'<span class="doxtr-chord"[^>]*style="([^"]*)"', html
    ).group(1)


# ---------------------------------------------------------------------------
# Singer colors: dd: expressions + dark-mode transform (theme integration)
# ---------------------------------------------------------------------------

import importlib.util as _ilu  # noqa: E402

_HAS_THEME = _ilu.find_spec("doxtr_pdf_theme_core") is not None


def _theme_config(dark=False):
    import tempfile
    from pathlib import Path

    from sphinx.application import Sphinx

    root = Path(tempfile.mkdtemp())
    src = root / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        'extensions = ["doxtr_music", "doxtr_pdf_theme_core"]\n', encoding="utf-8"
    )
    (src / "index.rst").write_text("t\n=\n\nx\n", encoding="utf-8")
    app = Sphinx(
        srcdir=str(src), confdir=str(src), outdir=str(root / "out"),
        doctreedir=str(root / "dt"), buildername="latex",
        status=None, warning=None,
        confoverrides={"doxtr_dark_mode": True} if dark else {},
    )
    return app.config


def _duet(colors):
    tokens = [
        SingerToken(singer="A"),
        ChordToken(text="C", column=0),
        LyricToken(text="Hi", column=0),
        LineBreakToken(),
    ]
    return build_nodes(tokens, {}, options={"singer_colors": colors})


@pytest.mark.skipif(not _HAS_THEME, reason="doxtr-pdf-theme-core not installed")
def test_singer_static_color_inverted_in_dark_mode():
    song = _duet({"A": "#1a6e1a"})
    light = stamp_singer_colors(song, _theme_config(dark=False))["A"]
    song2 = _duet({"A": "#1a6e1a"})
    dark = stamp_singer_colors(song2, _theme_config(dark=True))["A"]
    assert light.lower() == "#1a6e1a"            # unchanged in light
    assert dark.lower() != "#1a6e1a"             # soft-inverted for dark


@pytest.mark.skipif(not _HAS_THEME, reason="doxtr-pdf-theme-core not installed")
def test_singer_dd_expression_resolves_against_palette():
    song = _duet({"A": "dd:primary"})
    light = stamp_singer_colors(song, _theme_config(dark=False))["A"]
    song2 = _duet({"A": "dd:primary"})
    dark = stamp_singer_colors(song2, _theme_config(dark=True))["A"]
    assert light.startswith("#") and not light.startswith("dd:")
    # dd:primary resolves to different hex in light vs dark (dark palette).
    assert light.lower() != dark.lower()
