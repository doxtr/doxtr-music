"""Unit tests for the doxtr-music Docutils node model (CHUNK-1-2).

Covers:

* ``build_nodes`` structural assembly incl. mid-line singer switch + ignored
  BarToken; well-formed nesting (no cross-line/section spans).
* Lyric DOM/logical order preserved.
* Pickle round-trip with a realistic ``options`` payload.
* annotation → attr propagation for ``roman``/``transposed``/``duration``.
* Format-neutrality static scan of ``nodes.py``.
* Instantiation + attr storage for every node class (incl. reserved ones).
"""

from __future__ import annotations

import os
import pickle
import re

import pytest

from doxtr_music.nodes import (
    ChordNode,
    ChordProgressionNode,
    KeyNode,
    LineNode,
    LyricNode,
    ProgressionCellNode,
    ProgressionRowNode,
    RomanNode,
    SectionNode,
    SingerSpanNode,
    SongIndexNode,
    SongListNode,
    SongNode,
    _VISITORS,
    _resolve_format,
    build_nodes,
    register_nodes,
)
from doxtr_music.tokens import (
    BarToken,
    ChordToken,
    LineBreakToken,
    LyricToken,
    SectionToken,
    SingerToken,
)


# ---------------------------------------------------------------------------
# Instantiation + attr storage for every class (incl. reserved)
# ---------------------------------------------------------------------------


def test_all_node_classes_instantiate_and_store_attrs():
    song = SongNode()
    song["song_meta"] = {"title": "T"}
    song["options"] = {"transpose": 0}
    assert song["song_meta"]["title"] == "T"

    sec = SectionNode()
    sec["label"] = "Verse 1"
    sec["kind"] = "verse"
    assert sec["kind"] == "verse"

    line = LineNode()
    assert isinstance(line, LineNode)

    chord = ChordNode()
    chord["chord"] = "Am"
    chord["column"] = 6
    assert chord["chord"] == "Am"

    # column may be None (off-lyric role/progression contexts).
    chord2 = ChordNode()
    chord2["chord"] = "C"
    chord2["column"] = None
    assert chord2["column"] is None

    lyric = LyricNode("world", "world")
    lyric["column"] = 6
    assert lyric.astext() == "world"
    assert lyric["column"] == 6

    roman = RomanNode()
    roman["roman"] = "IV"
    assert roman["roman"] == "IV"

    span = SingerSpanNode()
    span["singer"] = "A"
    assert span["singer"] == "A"

    key = KeyNode()
    key["key"] = "G"
    assert key["key"] == "G"

    prog = ChordProgressionNode()
    prog["columns"] = 4
    row = ProgressionRowNode()
    cell = ProgressionCellNode()
    cell["cell_kind"] = "chord"
    assert prog["columns"] == 4
    assert cell["cell_kind"] == "chord"
    assert isinstance(row, ProgressionRowNode)

    slist = SongListNode()
    slist["filter"] = "key == 'G'"
    sindex = SongIndexNode()
    sindex["group-by"] = "artist"
    assert slist["filter"] == "key == 'G'"
    assert sindex["group-by"] == "artist"


# ---------------------------------------------------------------------------
# build_nodes structural assembly
# ---------------------------------------------------------------------------


def _sample_tokens():
    """A section, two lines with chords+lyrics, a mid-line singer switch, and
    an ignored BarToken."""
    return [
        SectionToken(label="Verse 1", kind="verse"),
        # line 0: [Am]Hello [C]world
        ChordToken(text="Am", column=0),
        LyricToken(text="Hello", column=0),
        ChordToken(text="C", column=6),
        LyricToken(text="world", column=6),
        LineBreakToken(),
        # line 1: mid-line singer switch + ignored bar token
        LyricToken(text="Sing", column=0),
        BarToken(),
        SingerToken(singer="B"),
        ChordToken(text="G", column=5),
        LyricToken(text="along", column=5),
    ]


def test_build_nodes_structure_and_nesting():
    song = build_nodes(_sample_tokens(), {"title": "Test"})
    assert isinstance(song, SongNode)

    # SongNode › SectionNode › LineNode ...
    assert len(song.children) == 1
    section = song.children[0]
    assert isinstance(section, SectionNode)
    assert section["label"] == "Verse 1"
    assert section["kind"] == "verse"

    lines = section.children
    assert len(lines) == 2
    assert all(isinstance(ln, LineNode) for ln in lines)

    # Line 0: no singer -> chords/lyrics attach directly to the line.
    line0 = lines[0]
    assert all(isinstance(c, (ChordNode, LyricNode)) for c in line0.children)
    assert [type(c).__name__ for c in line0.children] == [
        "ChordNode",
        "LyricNode",
        "ChordNode",
        "LyricNode",
    ]
    assert not any(isinstance(c, SingerSpanNode) for c in line0.children)

    # Line 1: "Sing" (no singer) then singer B switch -> SingerSpanNode wraps
    # the [G]along run only. BarToken ignored.
    line1 = lines[1]
    # First child is the pre-switch lyric "Sing".
    assert isinstance(line1.children[0], LyricNode)
    assert line1.children[0].astext() == "Sing"
    # A SingerSpanNode holds the after-switch run.
    spans = [c for c in line1.children if isinstance(c, SingerSpanNode)]
    assert len(spans) == 1
    span = spans[0]
    assert span["singer"] == "B"
    assert [type(c).__name__ for c in span.children] == ["ChordNode", "LyricNode"]

    # No SingerSpanNode ever crosses a line or section.
    for ln in lines:
        for child in ln.children:
            if isinstance(child, SingerSpanNode):
                # its children are all inline chord/lyric, no LineNode/SectionNode.
                assert all(
                    isinstance(c, (ChordNode, LyricNode, RomanNode))
                    for c in child.children
                )


def test_bartoken_ignored():
    song = build_nodes(
        [ChordToken(text="C", column=0), BarToken(), LyricToken(text="hi", column=0)],
        {},
    )
    # No node corresponds to the BarToken anywhere in the tree.
    line = song.children[0]
    kinds = [type(c).__name__ for c in line.children]
    assert "BarToken" not in kinds
    assert kinds == ["ChordNode", "LyricNode"]


def test_section_none_returns_to_toplevel():
    tokens = [
        SectionToken(label="Verse", kind="verse"),
        LyricToken(text="in-section", column=0),
        SectionToken(label="", kind="none"),
        LyricToken(text="top-level", column=0),
    ]
    song = build_nodes(tokens, {})
    # First child: the SectionNode; then a top-level LineNode attached directly.
    assert isinstance(song.children[0], SectionNode)
    assert song.children[0].children[0].children[0].astext() == "in-section"
    # After kind="none", content attaches directly under SongNode (a LineNode).
    top_lines = [c for c in song.children if isinstance(c, LineNode)]
    assert len(top_lines) == 1
    assert top_lines[0].children[0].astext() == "top-level"


def test_singer_span_reopens_across_lines():
    """A singer set on one line must reopen (not cross) on the next line."""
    tokens = [
        SingerToken(singer="A"),
        LyricToken(text="one", column=0),
        LineBreakToken(),
        LyricToken(text="two", column=0),
    ]
    song = build_nodes(tokens, {})
    lines = [c for c in song.children if isinstance(c, LineNode)]
    assert len(lines) == 2
    # Each line has its own SingerSpanNode (no span crosses the linebreak).
    for ln in lines:
        spans = [c for c in ln.children if isinstance(c, SingerSpanNode)]
        assert len(spans) == 1
        assert spans[0]["singer"] == "A"


# ---------------------------------------------------------------------------
# Lyric DOM/logical order
# ---------------------------------------------------------------------------


def test_lyric_dom_order_preserved():
    song = build_nodes(_sample_tokens(), {})
    line0 = song.children[0].children[0]
    lyrics = [c.astext() for c in line0.children if isinstance(c, LyricNode)]
    assert lyrics == ["Hello", "world"]


# ---------------------------------------------------------------------------
# annotation → attr propagation
# ---------------------------------------------------------------------------


def test_annotation_to_attr_propagation():
    tok = ChordToken(
        text="Am",
        column=0,
        annotations=(("roman", "vi"), ("transposed", "Bm"), ("duration", 2)),
    )
    song = build_nodes([tok], {})
    chord = song.children[0].children[0]
    assert isinstance(chord, ChordNode)
    assert chord["roman"] == "vi"
    assert chord["transposed"] == "Bm"
    assert chord["duration"] == 2


def test_unknown_annotation_dropped_with_warning():
    warnings = []
    tok = ChordToken(
        text="Am", column=0, annotations=(("mystery", "x"), ("roman", "vi"))
    )
    song = build_nodes([tok], {}, warn=warnings.append)
    chord = song.children[0].children[0]
    assert chord["roman"] == "vi"
    assert "mystery" not in chord.attributes
    assert any("mystery" in w for w in warnings)


# ---------------------------------------------------------------------------
# Pickle round-trip with realistic options
# ---------------------------------------------------------------------------


def test_pickle_round_trip_with_realistic_options():
    options = {
        "transpose": 2,
        "chord_system": "english",
        "show_chords": True,
        "roman_numerals": False,
        "singers": ["A", "B"],
        "typography": {"color": "#c00"},
    }
    song = build_nodes(_sample_tokens(), {"title": "T", "key": "G"}, options=options)
    blob = pickle.dumps(song)
    restored = pickle.loads(blob)
    assert isinstance(restored, SongNode)
    assert restored["song_meta"]["key"] == "G"
    assert restored["options"]["transpose"] == 2
    assert restored["options"]["show_chords"] is True
    assert restored["options"]["singers"] == ["A", "B"]
    assert restored["options"]["typography"] == {"color": "#c00"}


def test_options_reduced_drops_callables():
    """A callable in options must not survive into node attrs (would break the
    pickle/parallel-safety invariant)."""

    def _hook():  # pragma: no cover - never called
        return None

    song = build_nodes([], {}, options={"ok": "v", "bad": _hook})
    assert song["options"] == {"ok": "v"}
    # And the reduced result still pickles.
    pickle.loads(pickle.dumps(song))


# ---------------------------------------------------------------------------
# Format-neutrality static scan
# ---------------------------------------------------------------------------


def test_nodes_source_is_format_neutral():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = os.path.join(here, "doxtr_music", "nodes.py")
    with open(src_path, "r", encoding="utf-8") as fh:
        # Strip comments + docstrings so documentation prose does not trip the
        # scan; we only care about executable format-markup literals.
        src = fh.read()

    import ast

    tree = ast.parse(src)
    # Collect string-literal *values* used in code (not docstrings).
    string_values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            string_values.append(node.value)
    # Remove module/class/function docstrings from the set (they are the first
    # statement's Constant; the walk includes them, so filter by content used).
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)
    code_strings = [s for s in string_values if s not in docstrings]

    forbidden = ["<", "\\begin", "::before"]
    for s in code_strings:
        for marker in forbidden:
            assert marker not in s, (
                "format-markup literal %r found in code string %r" % (marker, s)
            )


# ---------------------------------------------------------------------------
# Visitor seam
# ---------------------------------------------------------------------------


def test_visitors_registry_shape():
    assert set(_VISITORS.keys()) == {"html", "latex", "epub"}
    # HTML bucket is populated (placeholder no-ops at load, real bodies after
    # register_html_visitors). The latex bucket is filled by CHUNK-2-1's
    # register_latex_visitors(); the epub bucket by CHUNK-2-2's
    # register_epub_visitors(). All three are plain dicts (the seam), filled by
    # dict assignment (never add_node override).
    assert _VISITORS["html"], "html bucket should have placeholder visitors"
    assert isinstance(_VISITORS["latex"], dict)
    assert isinstance(_VISITORS["epub"], dict)


@pytest.mark.parametrize(
    "builder_name,expected",
    [
        ("html", "html"),
        ("singlehtml", "html"),
        ("dirhtml", "html"),
        ("latex", "latex"),
        ("epub", "epub"),
        ("epub3", "epub"),
        ("", "html"),
    ],
)
def test_resolve_format(builder_name, expected):
    class _B:
        name = builder_name

    assert _resolve_format(_B()) == expected


def test_register_nodes_uses_add_node_once_per_node():
    calls = []

    class _FakeApp:
        def add_node(self, node_class, **kwargs):
            calls.append((node_class, kwargs))

    register_nodes(_FakeApp())
    # One registration per visible node, each with html/latex/epub dispatchers.
    assert len(calls) == 13
    for _nc, kwargs in calls:
        assert set(kwargs.keys()) == {"html", "latex", "epub"}
        for fmt in ("html", "latex", "epub"):
            v, d = kwargs[fmt]
            assert callable(v) and callable(d)
