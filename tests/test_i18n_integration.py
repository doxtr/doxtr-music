"""Integration tests for CHUNK-3-4 render wiring (in-process Sphinx builds).

Covers the render-side of the i18n + RTL contract that the pure-engine tests in
``test_i18n.py`` cannot reach:

* German ``chord_system`` localizes the visible HTML chord text via the shared
  ``resolve_chord_display`` helper (Bb->B, B->H, F#->Fis).
* ``chord_system="roman"`` resolves at PARSE time (numerals replace labels) with
  no ``:roman-numerals:`` option set.
* RTL LaTeX documented+tested fallback: the ``.tex`` still contains the song
  macros AND a warning fires (verbatim, no crash).
* RTL EPUB documented+tested fallback: reflow-safe ``<pre>`` + ``dir="auto"`` AND
  a warning fires (no crash).
"""

from __future__ import annotations

import io
import re
import textwrap
from pathlib import Path

import pytest

sphinx = pytest.importorskip("sphinx")
from sphinx.application import Sphinx  # noqa: E402


def _make_project(root: Path, index_rst: str, extra_conf: str = "") -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music"]\n'
        'html_theme = "basic"\n'
        + extra_conf,
        encoding="utf-8",
    )
    (src / "index.rst").write_text(index_rst, encoding="utf-8")
    return src


def _build(root: Path, index_rst: str, builder: str, extra_conf: str = "",
           warnings_buf=None):
    src = _make_project(root, index_rst, extra_conf)
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(root / "out"),
        doctreedir=str(root / "doctrees"),
        buildername=builder,
        freshenv=True,
        warning=warnings_buf,
    )
    app.build(force_all=True)
    return root / "out"


_GERMAN_SONG = textwrap.dedent(
    """
    Title
    =====

    .. song::

       {title: German Song}
       {start_of_verse}
       [Bb]One [B]two
       [F#]Three [Eb]four
       {end_of_verse}
    """
)

_RTL_SONG = textwrap.dedent(
    """
    Title
    =====

    .. song::

       {title: RTL Song}
       {start_of_verse}
       [C]\u05e9\u05dc\u05d5\u05dd [G]\u05e2\u05d5\u05dc\u05dd
       {end_of_verse}
    """
)

_ROMAN_SYSTEM_SONG = textwrap.dedent(
    """
    Title
    =====

    .. song::

       {title: Roman System Song}
       {key: C}
       {start_of_verse}
       [C]Hello [Am]world
       {end_of_verse}
    """
)


def _chord_span_texts(html: str) -> list[str]:
    return [
        re.sub(r"<[^>]+>", "", t).strip()
        for t in re.findall(
            r'<span[^>]*class="[^"]*doxtr-chord[^"]*"[^>]*>(.*?)</span>', html,
            re.DOTALL,
        )
    ]


@pytest.mark.integration
def test_german_chord_system_localizes_html(tmp_path):
    out = _build(tmp_path, _GERMAN_SONG, "html",
                 extra_conf='doxtr_music_chord_system = "german"\n')
    html = (out / "index.html").read_text(encoding="utf-8")
    visible = set(_chord_span_texts(html))
    # Bb->B, B->H, F#->Fis, Eb->Es (root-keyed, quality verbatim).
    assert {"B", "H", "Fis", "Es"} <= visible, visible
    # The raw English accidental spellings must not survive as visible labels.
    assert "F#" not in visible and "Eb" not in visible
    # data-chord keeps the effective English chord for source recovery.
    assert 'data-chord="F#"' in html
    assert 'data-chord="Eb"' in html


@pytest.mark.integration
def test_chord_system_roman_resolves_at_parse_time_html(tmp_path):
    # No :roman-numerals: option — chord_system="roman" alone must trigger it.
    out = _build(tmp_path, _ROMAN_SYSTEM_SONG, "html",
                 extra_conf='doxtr_music_chord_system = "roman"\n')
    html = (out / "index.html").read_text(encoding="utf-8")
    visible = set(_chord_span_texts(html))
    assert {"I", "vi"} <= visible, visible
    # English names are gone from the visible label (kept only in data-chord).
    assert "C" not in visible and "Am" not in visible
    assert 'data-chord="C"' in html


@pytest.mark.integration
def test_rtl_html_dir_auto_present(tmp_path):
    out = _build(tmp_path, _RTL_SONG, "html")
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="doxtr-song"' in html
    assert 'dir="auto"' in html


@pytest.mark.integration
def test_rtl_latex_fallback_warns_and_emits_macros(tmp_path):
    buf = io.StringIO()
    out = _build(tmp_path, _RTL_SONG, "latex", warnings_buf=buf)
    tex = next(out.glob("*.tex")).read_text(encoding="utf-8")
    # Documented fallback: song macros emitted verbatim (no crash) ...
    assert "\\dmlyric" in tex or "\\dmchord" in tex
    # ... and a warning fired.
    assert "RTL lyrics in PDF" in buf.getvalue()


@pytest.mark.integration
def test_rtl_epub_fallback_warns_and_reflow_safe(tmp_path):
    buf = io.StringIO()
    out = _build(tmp_path, _RTL_SONG, "epub", warnings_buf=buf)
    # Reflow-safe <pre> + dir="auto" in the rendered XHTML (no crash).
    xhtml = ""
    for p in out.glob("*.xhtml"):
        xhtml += p.read_text(encoding="utf-8")
    assert "<pre" in xhtml
    assert 'dir="auto"' in xhtml
    assert "RTL lyrics in EPUB" in buf.getvalue()
