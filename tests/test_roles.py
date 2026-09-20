"""Unit + integration tests for CHUNK-3-5 inline roles (:chord:/:key:/:roman:).

Covers the exit criteria:

* ``:chord:`` builds a standalone ``ChordNode`` (``column=None``, ``inline_role``)
  rendered via ``resolve_chord_display`` into a distinct ``.doxtr-chord-inline``
  span with NO ``aria-hidden``.
* ``:key:`` builds a ``KeyNode`` localized as a note name (incl. ``Bm`` → ``Hm``
  in German) with free-text passthrough for a non-note key.
* ``:roman:`` builds an **author-literal** ``RomanNode`` (never analyzed, never
  letter-localized).
* Standalone role nodes render in all three formats (LaTeX args escaped).
"""

from __future__ import annotations

from pathlib import Path

import pytest

sphinx = pytest.importorskip("sphinx")
from sphinx.application import Sphinx  # noqa: E402

from doxtr_music import roles  # noqa: E402
from doxtr_music.engine.i18n import localize_chord  # noqa: E402
from doxtr_music.nodes import ChordNode, KeyNode, RomanNode  # noqa: E402


# ---------------------------------------------------------------------------
# Role node construction (pure, no Sphinx build)
# ---------------------------------------------------------------------------

def test_chord_role_builds_inline_chordnode():
    nodes, msgs = roles.chord_role("chord", ":chord:`G7`", "G7", 0, None)
    node = nodes[0]
    assert isinstance(node, ChordNode)
    assert node["chord"] == "G7"
    assert node["column"] is None
    assert node.get("inline_role") is True
    # Author-literal role chords never carry transpose/roman analysis.
    assert node.get("transposed") is None
    assert node.get("roman") is None


def test_key_role_builds_keynode():
    nodes, _msgs = roles.key_role("key", ":key:`Bb`", "Bb", 0, None)
    assert isinstance(nodes[0], KeyNode)
    assert nodes[0]["key"] == "Bb"


def test_roman_role_builds_author_literal_romannode(monkeypatch):
    """:roman: is author-literal — it never calls roman_for_chord."""
    import doxtr_music.engine.roman as roman_engine

    called = {"n": 0}
    orig = roman_engine.roman_for_chord

    def _spy(*a, **k):  # pragma: no cover - must not be called
        called["n"] += 1
        return orig(*a, **k)

    monkeypatch.setattr(roman_engine, "roman_for_chord", _spy)
    nodes, _msgs = roles.roman_role("roman", ":roman:`IV`", "IV", 0, None)
    assert isinstance(nodes[0], RomanNode)
    assert nodes[0]["roman"] == "IV"
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# :key: note-name localization + free-text passthrough (via localize_chord)
# ---------------------------------------------------------------------------

def test_key_localizes_minor_key_german():
    """A minor key localizes its root as a note name: Bm -> Hm (german)."""
    assert localize_chord("Bm", "german") == "Hm"


def test_key_freetext_passthrough():
    """A non-note key passes through unchanged (graceful)."""
    assert localize_chord("Nashville", "german") == "Nashville"
    assert localize_chord("Bb", "english") == "Bb"


# ---------------------------------------------------------------------------
# Rendering — all three formats
# ---------------------------------------------------------------------------

_ROLES_RST = (
    "Roles\n=====\n\n"
    "Play :chord:`G7` in :key:`Bb`, resolving to :roman:`IV`.\n"
)


def _make_project(root: Path, index_rst: str, confpy: str) -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "conf.py").write_text(confpy, encoding="utf-8")
    (src / "index.rst").write_text(index_rst, encoding="utf-8")
    return src


def _build(root: Path, index_rst: str, builder: str, confpy: str):
    src = _make_project(root, index_rst, confpy)
    out = root / builder
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(root / "doctrees"),
        buildername=builder,
        freshenv=True,
    )
    app.build(force_all=True)
    return out


_CONF = (
    'project = "s"\nauthor = "s"\n'
    'extensions = ["doxtr_music"]\n'
    'html_theme = "basic"\n'
)


def test_roles_render_html(tmp_path):
    out = _build(tmp_path / "h", _ROLES_RST, "html", _CONF)
    html = (out / "index.html").read_text(encoding="utf-8")
    # :chord: -> distinct inline class, NO aria-hidden on the inline chord span.
    import re

    spans = re.findall(r'<span[^>]*class="[^"]*doxtr-chord-inline[^"]*"[^>]*>', html)
    assert spans, "no .doxtr-chord-inline span rendered"
    assert all("aria-hidden" not in s for s in spans)
    assert 'class="doxtr-chord-inline" data-chord="G7">G7</span>' in html
    assert '<span class="doxtr-key">Bb</span>' in html
    assert '<span class="doxtr-roman">IV</span>' in html


def test_roles_render_latex(tmp_path):
    out = _build(tmp_path / "l", _ROLES_RST, "latex", _CONF)
    tex = next(out.glob("*.tex")).read_text(encoding="utf-8")
    assert "\\dmchordinline{G7}" in tex
    assert "\\dmkey{Bb}" in tex
    assert "\\dmroman{IV}" in tex


def test_roles_render_epub(tmp_path):
    out = _build(tmp_path / "e", _ROLES_RST, "epub", _CONF)
    xhtml = "".join(
        p.read_text(encoding="utf-8") for p in out.glob("*.xhtml")
    )
    assert "doxtr-chord-inline" in xhtml
    assert 'class="doxtr-key">Bb</span>' in xhtml
    assert 'class="doxtr-roman">IV</span>' in xhtml


def test_chord_role_localizes_via_resolve_display(tmp_path):
    """:chord: routes through resolve_chord_display: localizes under german."""
    confpy = _CONF + 'doxtr_music_chord_system = "german"\n'
    rst = "Roles\n=====\n\nPlay :chord:`Bb` and :key:`Bm`.\n"
    out = _build(tmp_path / "g", rst, "html", confpy)
    html = (out / "index.html").read_text(encoding="utf-8")
    # Bb localizes to B (german), Bm key localizes to Hm.
    assert 'class="doxtr-chord-inline" data-chord="Bb">B</span>' in html
    assert '<span class="doxtr-key">Hm</span>' in html


def test_latex_role_escaping(tmp_path):
    """A chord/key with a LaTeX-special char is escaped at the visitor boundary."""
    rst = "Roles\n=====\n\nPlay :chord:`C#m7`.\n"
    out = _build(tmp_path / "esc", rst, "latex", _CONF)
    tex = next(out.glob("*.tex")).read_text(encoding="utf-8")
    # '#' is LaTeX-special; the escaper must protect it inside \dmchordinline.
    assert "\\dmchordinline{" in tex
    assert "C#m7" not in tex  # raw '#' must not appear unescaped
    assert "\\#" in tex
