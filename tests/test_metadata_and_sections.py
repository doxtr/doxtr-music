"""Song-metadata rendering + section-kind styling across HTML/LaTeX/EPUB.

Exercises the extended typography surface: a visible song-metadata block
(key/tempo/…) with per-metadata-key styling, and per-section-kind title/body
styling (verse/chorus/custom) — including background colors — rendered in all
three formats.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sphinx.application")
from sphinx.application import Sphinx  # noqa: E402


_CONF = (
    'project = "s"\nauthor = "s"\n'
    'extensions = ["doxtr_music"]\n'
    'html_theme = "basic"\n'
    "doxtr_music_autoload_theme = False\n"
    "doxtr_music_typography = {\n"
    '  "title": {"color": "#1a3d7a", "background": "#eeeeff"},\n'
    '  "metadata": {"size": "0.9em"},\n'
    '  "meta-tempo": {"color": "#0000aa", "font": "monospace"},\n'
    '  "section-verse-title": {"color": "#aa0000", "background": "#ffeeee"},\n'
    '  "section-chorus-title": {"color": "#00aa00"},\n'
    '  "section-body": {"size": "0.98em"},\n'
    "}\n"
)

_RST = (
    "S\n=\n\n"
    ".. song::\n\n"
    "   {title: Test Song}\n"
    "   {key: G}\n"
    "   {tempo: 120 BPM}\n"
    "   {start_of_verse}\n"
    "   [C]Hello [Am]world\n"
    "   {end_of_verse}\n"
    "   {start_of_chorus}\n"
    "   [F]Sing [G]along\n"
    "   {end_of_chorus}\n"
)


def _build(root: Path, builder: str) -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "conf.py").write_text(_CONF, encoding="utf-8")
    if builder == "latex":
        (src / "conf.py").write_text(
            _CONF + 'latex_documents = [("index", "s.tex", "S", "A", "manual")]\n',
            encoding="utf-8",
        )
    (src / "index.rst").write_text(_RST, encoding="utf-8")
    out = root / builder
    app = Sphinx(
        srcdir=str(src), confdir=str(src), outdir=str(out),
        doctreedir=str(root / "dt" / builder), buildername=builder,
        status=None, warning=None, freshenv=True,
    )
    app.build(force_all=True)
    return out


def test_html_renders_metadata_block_with_per_key_style(tmp_path):
    html = (_build(tmp_path, "html") / "index.html").read_text(encoding="utf-8")
    # Metadata rows render with friendly labels + values.
    assert "doxtr-song-meta-list" in html
    assert "doxtr-song-meta-tempo" in html
    assert "doxtr-song-meta-key" in html
    assert "Tempo" in html and "120 BPM" in html
    assert "Key" in html and "G" in html
    # Per-key style: tempo gets monospace + blue (meta-tempo) merged with the
    # generic 0.9em (metadata).
    assert "font-family:monospace" in html
    assert "color:#0000aa" in html
    # Title background from the title cell.
    assert "background-color:#eeeeff" in html


def test_html_section_kind_title_styling(tmp_path):
    html = (_build(tmp_path, "html") / "index.html").read_text(encoding="utf-8")
    assert "doxtr-section-verse" in html
    assert "doxtr-section-chorus" in html
    # Verse title background + color; a body wrapper exists.
    assert "background-color:#ffeeee" in html
    assert "color:#aa0000" in html
    assert "doxtr-section-body" in html


def test_latex_renders_metadata_and_section_styling(tmp_path):
    tex = next((_build(tmp_path, "latex")).glob("*.tex")).read_text(encoding="utf-8")
    # Metadata rows via \dmmeta (Label: value).
    assert "Tempo: 120 BPM" in tex
    assert "Key: G" in tex
    # Per-key + title/section colors defined + applied (hex uppercased).
    assert "\\textcolor" in tex
    assert "\\colorbox" in tex  # a background (title/section) becomes a colorbox
    # Section label routed through \dmsectionbegin still present.
    assert "\\dmsectionbegin{verse}" in tex
    assert "\\dmsectionbegin{chorus}" in tex


def test_epub_renders_metadata_block(tmp_path):
    out = _build(tmp_path, "epub")
    xhtmls = list(out.rglob("index.xhtml")) + list(out.rglob("index.html"))
    assert xhtmls
    content = xhtmls[0].read_text(encoding="utf-8")
    assert "doxtr-song-meta-tempo" in content
    assert "Tempo" in content and "120 BPM" in content
    # Reflow-safe: no absolute font-size leaked (metadata size is relative).
    assert "doxtr-section-body" in content


# ---------------------------------------------------------------------------
# Per-section lyric highlight: a section-body background cascades onto that
# section's lyric words (a marker-pen effect) in all three formats.
# ---------------------------------------------------------------------------

_HL_CONF = (
    'project = "s"\nauthor = "s"\n'
    'extensions = ["doxtr_music"]\n'
    'html_theme = "basic"\n'
    "doxtr_music_autoload_theme = False\n"
    'doxtr_music_typography = {"section-highlight-body": {"background": "#fff59d"}}\n'
)

_HL_RST = (
    "S\n=\n\n"
    ".. song::\n\n"
    "   {title: Marked}\n"
    "   {start_of_verse}\n"
    "   [C]Plain [Am]line\n"
    "   {end_of_verse}\n"
    "   {start_of_highlight}\n"
    "   [F]Line [G]here two\n"
    "   {end_of_highlight}\n"
)


def _build_hl(root: Path, builder: str) -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    conf = _HL_CONF
    if builder == "latex":
        conf += 'latex_documents = [("index", "s.tex", "S", "A", "manual")]\n'
    (src / "conf.py").write_text(conf, encoding="utf-8")
    (src / "index.rst").write_text(_HL_RST, encoding="utf-8")
    out = root / builder
    app = Sphinx(
        srcdir=str(src), confdir=str(src), outdir=str(out),
        doctreedir=str(root / "dt" / builder), buildername=builder,
        status=None, warning=None, freshenv=True,
    )
    app.build(force_all=True)
    return out


def test_html_section_highlight_lyric_background(tmp_path):
    html = (_build_hl(tmp_path, "html") / "index.html").read_text(encoding="utf-8")
    # The highlight section's lyric words carry the yellow background inline.
    assert "doxtr-section-highlight" in html
    assert "background-color:#fff59d" in html
    # The plain verse lyrics do NOT get the background.
    import re
    verse = re.search(r'doxtr-section-verse.*?</section>', html, re.S)
    assert verse and "background-color:#fff59d" not in verse.group(0)


def test_latex_section_highlight_lyric_colorbox(tmp_path):
    tex = next((_build_hl(tmp_path, "latex")).glob("*.tex")).read_text(encoding="utf-8")
    # The highlighted lyrics are wrapped in a \colorbox (marker effect).
    assert "\\colorbox" in tex
    assert "\\dmsectionbegin{highlight}" in tex


def test_epub_section_highlight_lyric_background(tmp_path):
    out = _build_hl(tmp_path, "epub")
    xhtmls = list(out.rglob("index.xhtml")) + list(out.rglob("index.html"))
    assert xhtmls
    content = xhtmls[0].read_text(encoding="utf-8")
    assert "doxtr-section-highlight" in content
