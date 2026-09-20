"""Integration test for CHUNK-1-2 exit criterion #5.

A write-only ``-b latex`` / ``-b epub`` build of a document containing a
``SongNode`` must complete without an *unhandled-node* exception. This proves
the ``_VISITORS["latex"]``/``["epub"]`` no-op stubs (no ``SkipNode``) let the
dispatcher traverse the song subtree in every format before CHUNK-2-1/2-2 fill
the real visitors.

No TeX toolchain is exercised — the LaTeX build only reaches the doctree→``.tex``
write step. Marked ``integration`` so the fast unit lane can skip it if desired.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

sphinx = pytest.importorskip("sphinx")
from sphinx.application import Sphinx  # noqa: E402


# A tiny throwaway extension that registers a ``.. testsong::`` directive
# emitting a doxtr-music SongNode built from a synthetic token stream. This lets
# us validate the node visitors before CHUNK-1-4's real ``.. song::`` exists.
_TEST_EXT = textwrap.dedent(
    '''
    from docutils.parsers.rst import Directive
    from doxtr_music.nodes import build_nodes
    from doxtr_music.tokens import (
        ChordToken, LyricToken, SectionToken, LineBreakToken,
        SingerToken, BarToken,
    )


    class TestSong(Directive):
        has_content = False

        def run(self):
            tokens = [
                SectionToken(label="Verse", kind="verse"),
                ChordToken(text="Am", column=0),
                LyricToken(text="Hello", column=0),
                ChordToken(text="C", column=6),
                LyricToken(text="world", column=6),
                LineBreakToken(),
                SingerToken(singer="B"),
                BarToken(),
                ChordToken(text="G", column=0),
                LyricToken(text="again", column=0),
            ]
            song = build_nodes(tokens, {"title": "Test Song"})
            return [song]


    def setup(app):
        app.setup_extension("doxtr_music")
        app.add_directive("testsong", TestSong)
        return {"parallel_read_safe": True, "parallel_write_safe": True}
    '''
)

_INDEX_RST = textwrap.dedent(
    """
    Test
    ====

    .. testsong::
    """
)


def _make_project(root: Path) -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\n'
        'extensions = ["testext"]\n'
        'html_theme = "basic"\n'
        'latex_documents = [("index", "test.tex", "T", "A", "manual")]\n'
        'epub_title = "T"\nepub_author = "A"\n',
        encoding="utf-8",
    )
    (src / "index.rst").write_text(_INDEX_RST, encoding="utf-8")
    (src / "testext.py").write_text(_TEST_EXT, encoding="utf-8")
    return src


def _build(root: Path, builder: str) -> None:
    src = _make_project(root / builder)
    out = root / builder / "out"
    doctrees = root / builder / "doctrees"
    # Make the throwaway extension importable.
    import sys

    sys.path.insert(0, str(src))
    try:
        app = Sphinx(
            srcdir=str(src),
            confdir=str(src),
            outdir=str(out),
            doctreedir=str(doctrees),
            buildername=builder,
            freshenv=True,
        )
        app.build(force_all=True)
    finally:
        sys.path.remove(str(src))


@pytest.mark.integration
def test_latex_write_only_build_of_song_no_crash(tmp_path):
    # If this raised an unhandled node, Sphinx would abort the build.
    _build(tmp_path, "latex")
    assert (tmp_path / "latex" / "out" / "test.tex").exists()


@pytest.mark.integration
def test_epub_write_only_build_of_song_no_crash(tmp_path):
    _build(tmp_path, "epub")
    # EPUB emits the package container; the build completing is the assertion.
    assert (tmp_path / "epub" / "out").exists()


@pytest.mark.integration
def test_html_build_of_song_no_crash(tmp_path):
    _build(tmp_path, "html")
    html = (tmp_path / "html" / "out" / "index.html").read_text(encoding="utf-8")
    # Placeholder HTML visitors render children as text; the lyric text is
    # present in DOM/logical order (copy-safety precondition for CHUNK-1-4).
    assert "Hello" in html
    assert html.index("Hello") < html.index("world")
