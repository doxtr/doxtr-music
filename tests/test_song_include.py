"""Unit + integration tests for CHUNK-3-5 ``.. song-include::``.

Covers the exit criteria:

* ``.. song-include:: example.cho`` produces the **same node-tree shape** as the
  file's content pasted into ``.. song::`` (ids/provenance may differ).
* ``env.note_dependency`` is registered for the resolved absolute ``.cho`` path
  (inspected via ``env.dependencies[docname]``).
* Missing file → Sphinx error (no crash); a ``..`` escape, a symlink escape, and
  an absolute-path argument are all rejected via ``realpath`` + ``commonpath``.
* UTF-8 (BOM-tolerant) read.
* Inherited ``:transpose:`` option applies (shared ``_options.py``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sphinx = pytest.importorskip("sphinx")
from sphinx.application import Sphinx  # noqa: E402

from doxtr_music.directives._fileload import (  # noqa: E402
    ConfinementError,
    _resolve_confined_path,
)
from doxtr_music.nodes import ChordNode, LyricNode, SectionNode, SongNode  # noqa: E402


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------

def _make_project(root: Path, index_rst: str, files: dict | None = None) -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music"]\n'
        'html_theme = "basic"\n',
        encoding="utf-8",
    )
    (src / "index.rst").write_text(index_rst, encoding="utf-8")
    for rel, content in (files or {}).items():
        target = src / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    return src


def _build_html(root: Path, index_rst: str, files=None, warnings_buf=None):
    src = _make_project(root, index_rst, files)
    out = root / "out"
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(root / "doctrees"),
        buildername="html",
        freshenv=True,
        warning=warnings_buf,
    )
    app.build(force_all=True)
    return app, out


def _shape(node):
    """A structural (shape-only) signature of a node subtree.

    Captures node classes + the salient content attrs (chord/lyric text, section
    kind/label) in document order, deliberately ignoring ids/names/provenance so
    two independently-built trees can be compared for *shape* equivalence.
    """
    sig = [type(node).__name__]
    if isinstance(node, ChordNode):
        sig.append(("chord", node.get("chord"), node.get("column")))
    elif isinstance(node, LyricNode):
        sig.append(("lyric", node.astext(), node.get("column")))
    elif isinstance(node, SectionNode):
        sig.append(("section", node.get("kind"), node.get("label")))
    children = [_shape(c) for c in getattr(node, "children", [])]
    return (tuple(sig), tuple(children))


_CHO = (
    "{title: Included Song}\n"
    "{key: C}\n\n"
    "{start_of_verse}\n"
    "[Am]Hello [C]world\n"
    "[G]Line two [F]here\n"
    "{end_of_verse}\n"
)


# ---------------------------------------------------------------------------
# Node-tree-shape equivalence
# ---------------------------------------------------------------------------

def test_song_include_shape_matches_inline_song(tmp_path):
    """song-include of a .cho == same SongNode shape as inline .. song::."""
    body = "\n".join("   " + line for line in _CHO.splitlines())
    inline_rst = "Title\n=====\n\n.. song::\n\n%s\n" % body
    app_i, _ = _build_html(tmp_path / "inline", inline_rst)
    inline_tree = app_i.env.get_doctree("index")
    inline_songs = list(inline_tree.findall(SongNode))

    include_rst = "Title\n=====\n\n.. song-include:: song.cho\n"
    app_x, _ = _build_html(
        tmp_path / "include", include_rst, files={"song.cho": _CHO}
    )
    include_tree = app_x.env.get_doctree("index")
    include_songs = list(include_tree.findall(SongNode))

    assert len(inline_songs) == 1 and len(include_songs) == 1
    assert _shape(include_songs[0]) == _shape(inline_songs[0])


# ---------------------------------------------------------------------------
# Build-dependency registration
# ---------------------------------------------------------------------------

def test_song_include_registers_dependency(tmp_path):
    """The resolved absolute .cho path is registered in env.dependencies."""
    include_rst = "Title\n=====\n\n.. song-include:: nested/song.cho\n"
    app, _ = _build_html(
        tmp_path / "dep", include_rst, files={"nested/song.cho": _CHO}
    )
    deps = app.env.dependencies.get("index", set())
    resolved = os.path.realpath(os.path.join(app.srcdir, "nested", "song.cho"))
    # Dependencies are stored relative to srcdir; compare on realpath.
    dep_abs = {os.path.realpath(os.path.join(app.srcdir, d)) for d in deps}
    assert resolved in dep_abs


# ---------------------------------------------------------------------------
# Security confinement
# ---------------------------------------------------------------------------

class _FakeEnv:
    def __init__(self, srcdir):
        self.srcdir = str(srcdir)

    def relfn2path(self, arg):
        # Mimic Sphinx: resolve relative to srcdir (docname at root).
        abs_path = os.path.normpath(os.path.join(self.srcdir, arg))
        return arg, abs_path

    def note_dependency(self, path):  # pragma: no cover - not reached on escape
        pass


def test_confinement_rejects_parent_traversal(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (tmp_path / "secret.cho").write_text("{title: leak}\n", encoding="utf-8")
    env = _FakeEnv(src)
    with pytest.raises(ConfinementError):
        _resolve_confined_path(env, "../secret.cho")


def test_confinement_rejects_absolute_path(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    env = _FakeEnv(src)
    with pytest.raises(ConfinementError):
        _resolve_confined_path(env, str(tmp_path / "anything.cho"))


@pytest.mark.skipif(os.name == "nt", reason="symlink semantics differ on Windows")
def test_confinement_rejects_symlink_escape(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    outside = tmp_path / "outside.cho"
    outside.write_text("{title: leak}\n", encoding="utf-8")
    link = src / "link.cho"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):  # pragma: no cover - env-dependent
        pytest.skip("symlinks not permitted in this environment")
    env = _FakeEnv(src)
    with pytest.raises(ConfinementError):
        _resolve_confined_path(env, "link.cho")


def test_confinement_accepts_in_tree(tmp_path):
    src = tmp_path / "src"
    (src / "nested").mkdir(parents=True)
    (src / "nested" / "ok.cho").write_text("{title: ok}\n", encoding="utf-8")
    env = _FakeEnv(src)
    real = _resolve_confined_path(env, "nested/ok.cho")
    assert real == os.path.realpath(str(src / "nested" / "ok.cho"))


# ---------------------------------------------------------------------------
# Missing file → error (no crash)
# ---------------------------------------------------------------------------

def test_song_include_missing_file_errors(tmp_path):
    """A missing include file yields a Sphinx warning/error, not a crash."""
    import io

    include_rst = "Title\n=====\n\n.. song-include:: does_not_exist.cho\n"
    buf = io.StringIO()
    # The build must complete (no unhandled exception); the directive reports an
    # error via the reporter (captured in the warning stream).
    app, _ = _build_html(tmp_path / "missing", include_rst, warnings_buf=buf)
    log = buf.getvalue()
    assert "doxtr-music" in log and "does_not_exist.cho" in log


# ---------------------------------------------------------------------------
# UTF-8 (BOM) read
# ---------------------------------------------------------------------------

def test_song_include_utf8_bom(tmp_path):
    """A BOM-prefixed UTF-8 .cho reads cleanly and renders the title."""
    bom_cho = ("\ufeff" + _CHO).encode("utf-8")
    include_rst = "Title\n=====\n\n.. song-include:: bom.cho\n"
    app, out = _build_html(
        tmp_path / "bom", include_rst, files={"bom.cho": bom_cho}
    )
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Included Song" in html


# ---------------------------------------------------------------------------
# Inherited options (:transpose:)
# ---------------------------------------------------------------------------

def test_song_include_inherits_transpose(tmp_path):
    """:transpose: on song-include shifts chords (shared _options.py)."""
    include_rst = (
        "Title\n=====\n\n.. song-include:: song.cho\n   :transpose: 2\n"
    )
    app, out = _build_html(
        tmp_path / "tr", include_rst, files={"song.cho": _CHO}
    )
    html = (out / "index.html").read_text(encoding="utf-8")
    # Am +2 -> Bm, C +2 -> D. Shifted labels must appear in data-chord.
    assert 'data-chord="Bm"' in html
    assert 'data-chord="D"' in html
