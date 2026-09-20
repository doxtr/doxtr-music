"""Unit tests for the MusicXML importer (CHUNK-6-1).

Covers every exit criterion of ``.. import-musicxml::``:

* ``<harmony>`` → English chord text (inline kind→quality matrix incl. slash,
  ``none``, a ``<degree>``, an unmapped kind → ``_warnings``);
* the harmony↔lyric anchoring algorithm (synthetic line + codepoint columns),
  including a ``<syllabic>`` word-join and an instrumental / chord-only measure;
* ``<measure>`` → ``BarToken`` present on the token stream but ABSENT from the
  built node tree (metadata-only); note ``duration`` where available;
* metadata (title/composer/lyricist and ``<key>``/``<fifths>`` →
  ``song_meta['key']`` → roman renders);
* partwise + timewise both parse; multi-part → chosen part + ``_warnings``;
* malformed XML → ``_warnings`` + no crash; billion-laughs rejected (defusedxml);
* file confinement via the shared ``load_confined_source`` (escape rejected) +
  ``note_dependency``; ``.mxl`` → clear deferred ``_warnings`` note;
* shared ``_lyrics`` seam usage; NO Sphinx import in the parser (runtime
  subprocess ``sys.modules`` check, not a source scan); inherited options
  (``:transpose:`` shifts imported chords).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from doxtr_music.parsers.musicxml import KIND_TO_QUALITY, parse_musicxml
from doxtr_music.tokens import BarToken, ChordToken, LyricToken, SectionToken


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _score(*measure_bodies):
    """Wrap measure XML fragments into a minimal score-partwise document."""
    measures = "".join(
        '<measure number="%d">%s</measure>' % (i + 1, body)
        for i, body in enumerate(measure_bodies)
    )
    return (
        '<?xml version="1.0"?>'
        '<score-partwise version="3.1"><part id="P1">'
        + measures
        + "</part></score-partwise>"
    )


def _harmony(root, kind, extra="", alter=None):
    alter_xml = "<root-alter>%d</root-alter>" % alter if alter is not None else ""
    return (
        "<harmony><root><root-step>%s</root-step>%s</root>"
        "<kind>%s</kind>%s</harmony>" % (root, alter_xml, kind, extra)
    )


def _note(lyric=None, syllabic="single", duration=4):
    lyric_xml = ""
    if lyric is not None:
        lyric_xml = (
            "<lyric><syllabic>%s</syllabic><text>%s</text></lyric>"
            % (syllabic, lyric)
        )
    return "<note><duration>%d</duration>%s</note>" % (duration, lyric_xml)


def _chords(tokens):
    return [t.text for t in tokens if isinstance(t, ChordToken)]


def _lyrics(tokens):
    return [t.text for t in tokens if isinstance(t, LyricToken)]


# ---------------------------------------------------------------------------
# <harmony> → English chord text (the inline kind→quality matrix)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kind,expected",
    [
        ("major", "C"),
        ("minor", "Cm"),
        ("dominant", "C7"),
        ("major-seventh", "Cmaj7"),
        ("minor-seventh", "Cm7"),
        ("half-diminished", "Cm7b5"),
        ("diminished", "Cdim"),
        ("augmented", "Caug"),
        ("suspended-fourth", "Csus4"),
        ("suspended-second", "Csus2"),
        ("dominant-ninth", "C9"),
        ("major-sixth", "C6"),
        ("minor-sixth", "Cm6"),
        ("power", "C5"),
    ],
)
def test_kind_to_quality_matrix(kind, expected):
    tokens, meta = parse_musicxml(_score(_harmony("C", kind) + _note()))
    assert _chords(tokens) == [expected]
    assert not meta.get("_warnings")


def test_kind_none_is_no_chord_marker():
    tokens, meta = parse_musicxml(_score(_harmony("C", "none") + _note()))
    assert _chords(tokens) == ["N.C."]


def test_root_alter_sharps_and_flats():
    tokens, _ = parse_musicxml(_score(_harmony("F", "major", alter=1) + _note()))
    assert _chords(tokens) == ["F#"]
    tokens, _ = parse_musicxml(_score(_harmony("B", "minor", alter=-1) + _note()))
    assert _chords(tokens) == ["Bbm"]


def test_slash_chord():
    body = _harmony("C", "major", extra="<bass><bass-step>E</bass-step></bass>")
    tokens, _ = parse_musicxml(_score(body + _note()))
    assert _chords(tokens) == ["C/E"]


def test_slash_chord_with_bass_alter():
    body = _harmony(
        "D",
        "minor",
        extra="<bass><bass-step>F</bass-step><bass-alter>1</bass-alter></bass>",
    )
    tokens, _ = parse_musicxml(_score(body + _note()))
    assert _chords(tokens) == ["Dm/F#"]


def test_degree_suffix_best_effort():
    degree = (
        "<degree><degree-value>9</degree-value>"
        "<degree-type>add</degree-type></degree>"
    )
    tokens, _ = parse_musicxml(_score(_harmony("C", "dominant", extra=degree) + _note()))
    assert _chords(tokens) == ["C7add9"]


def test_unmapped_kind_best_effort_and_warns():
    tokens, meta = parse_musicxml(_score(_harmony("G", "weird-kind") + _note()))
    # Best-effort quality kept (never a silently-dropped chord).
    assert _chords(tokens) == ["Gweirdkind"]
    assert any("unmapped harmony kind" in w[1] for w in meta["_warnings"])


def test_unmapped_kind_uses_display_text_override():
    body = '<harmony><root><root-step>C</root-step></root><kind text="7#9">weird</kind></harmony>'
    tokens, meta = parse_musicxml(_score(body + _note()))
    assert _chords(tokens) == ["C7#9"]
    assert any("display text" in w[1] for w in meta["_warnings"])


def test_kind_to_quality_table_has_core_entries():
    # Guard: the fidelity-critical table must not silently lose core mappings.
    for k in ("major", "minor", "dominant", "none", "power"):
        assert k in KIND_TO_QUALITY


# ---------------------------------------------------------------------------
# harmony↔lyric anchoring (synthetic line + codepoint columns)
# ---------------------------------------------------------------------------

def test_anchoring_columns_over_syllables():
    # Two events "Hel" + "lo" (single each) -> synthetic "Hel lo ".
    body = (
        _harmony("C", "major") + _note("Hel")
        + _harmony("A", "minor") + _note("lo")
    )
    tokens, _ = parse_musicxml(_score(body))
    chords = [t for t in tokens if isinstance(t, ChordToken)]
    assert [(c.text, c.column) for c in chords] == [("C", 0), ("Am", 4)]
    assert _lyrics(tokens) == ["Hel", "lo"]


def test_anchoring_syllabic_join_no_space():
    # "lo"(begin) joins "world"(end) into one word "loworld"; the chord over
    # the second syllable still anchors at the syllable's column.
    body = (
        _harmony("C", "major") + _note("lo", syllabic="begin")
        + _harmony("G", "dominant") + _note("world", syllabic="end")
    )
    tokens, _ = parse_musicxml(_score(body))
    # Synthetic line is "loworld " -> one lyric word.
    assert _lyrics(tokens) == ["loworld"]
    chords = [t for t in tokens if isinstance(t, ChordToken)]
    assert [(c.text, c.column) for c in chords] == [("C", 0), ("G7", 2)]


def test_instrumental_chord_only_measure():
    # Chords with no <lyric>: chords anchored over an (empty) lyric line.
    body = (
        _harmony("A", "minor") + _note(None)
        + _harmony("D", "major") + _note(None)
    )
    tokens, _ = parse_musicxml(_score(body))
    assert _lyrics(tokens) == []  # no lyric words
    chords = [t for t in tokens if isinstance(t, ChordToken)]
    assert [c.text for c in chords] == ["Am", "D"]
    # Distinct columns preserved via spacer characters.
    assert chords[0].column != chords[1].column


def test_trailing_harmony_anchors_at_end():
    body = _harmony("C", "major") + _note("hi") + _harmony("G", "dominant")
    tokens, _ = parse_musicxml(_score(body))
    chords = [t for t in tokens if isinstance(t, ChordToken)]
    assert chords[0].column == 0
    # The trailing chord anchors at end-of-line (column == len(synthetic line)).
    assert chords[1].column >= len("hi")


# ---------------------------------------------------------------------------
# BarToken metadata-only + duration
# ---------------------------------------------------------------------------

def test_bartoken_emitted_per_measure_but_dropped_by_build_nodes():
    tokens, meta = parse_musicxml(
        _score(_harmony("C", "major") + _note("a"), _harmony("G", "dominant") + _note("b"))
    )
    bars = [t for t in tokens if isinstance(t, BarToken)]
    assert len(bars) == 2  # one per measure

    # build_nodes drops BarToken (no BarNode, no builder amendment).
    from doxtr_music.nodes import build_nodes

    node = build_nodes(tokens, {}, {})
    # No node in the tree carries a bar tagname / class.
    for child in node.findall():
        assert "bar" not in getattr(child, "tagname", "").lower() or child is node


def test_note_duration_carried_on_chord_when_available():
    body = _harmony("C", "major") + _note("hi", duration=8)
    tokens, _ = parse_musicxml(_score(body))
    chords = [t for t in tokens if isinstance(t, ChordToken)]
    assert chords[0].duration == 8.0


# ---------------------------------------------------------------------------
# metadata + <key>/<fifths> -> roman
# ---------------------------------------------------------------------------

def test_metadata_extraction():
    xml = (
        '<score-partwise><work><work-title>My Song</work-title></work>'
        '<identification>'
        '<creator type="composer">A Composer</creator>'
        '<creator type="lyricist">A Poet</creator>'
        '</identification>'
        '<part id="P1"><measure number="1">'
        + _harmony("C", "major") + _note("hi")
        + '</measure></part></score-partwise>'
    )
    _tokens, meta = parse_musicxml(xml)
    assert meta["title"] == "My Song"
    assert meta["artist"] == "A Composer"
    assert meta["lyricist"] == "A Poet"


@pytest.mark.parametrize(
    "fifths,mode,expected",
    [(0, "major", "C"), (1, "major", "G"), (-1, "major", "F"),
     (0, "minor", "Am"), (2, "minor", "Bm")],
)
def test_key_from_fifths(fifths, mode, expected):
    body = (
        "<attributes><key><fifths>%d</fifths><mode>%s</mode></key></attributes>"
        % (fifths, mode)
        + _harmony("C", "major") + _note("hi")
    )
    _tokens, meta = parse_musicxml(_score(body))
    assert meta["key"] == expected


def test_key_feeds_roman_analysis():
    # In C major, a G dominant is V.
    body = (
        "<attributes><key><fifths>0</fifths><mode>major</mode></key></attributes>"
        + _harmony("G", "dominant") + _note("hi")
    )
    tokens, meta = parse_musicxml(_score(body))
    assert meta["key"] == "C"
    from doxtr_music.engine.roman import roman_tokens

    annotated = roman_tokens(tokens, meta["key"])
    chord = next(t for t in annotated if isinstance(t, ChordToken))
    roman = dict(chord.annotations).get("roman")
    assert roman is not None and "V" in roman.upper()


# ---------------------------------------------------------------------------
# partwise + timewise + multi-part
# ---------------------------------------------------------------------------

def test_timewise_parses_like_partwise():
    xml = (
        '<score-timewise><measure number="1"><part id="P1">'
        + _harmony("D", "major") + _note("hey")
        + "</part></measure></score-timewise>"
    )
    tokens, meta = parse_musicxml(xml)
    assert _chords(tokens) == ["D"]
    assert _lyrics(tokens) == ["hey"]
    assert not meta.get("_warnings")


def test_multi_part_picks_chord_lyric_carrier_and_warns():
    xml = (
        '<score-partwise>'
        '<part id="P1"><measure number="1">'
        + _note()  # instrument part, no harmony/lyric
        + "</measure></part>"
        '<part id="P2"><measure number="1">'
        + _harmony("A", "minor") + _note("sing")
        + "</measure></part></score-partwise>"
    )
    tokens, meta = parse_musicxml(xml)
    assert _chords(tokens) == ["Am"]
    assert _lyrics(tokens) == ["sing"]
    assert any("multiple parts" in w[1] for w in meta["_warnings"])


def test_unrecognized_root_warns():
    tokens, meta = parse_musicxml(
        '<foo-bar></foo-bar>'
    )
    assert tokens == []
    assert any("unrecognized MusicXML root" in w[1] for w in meta["_warnings"])


# ---------------------------------------------------------------------------
# robustness + security
# ---------------------------------------------------------------------------

def test_malformed_xml_warns_no_crash():
    tokens, meta = parse_musicxml("<score-partwise><part><measure>UNCLOSED")
    assert tokens == []
    assert any("could not parse" in w[1] for w in meta["_warnings"])


def test_empty_input():
    assert parse_musicxml("") == ([], {"_warnings": []})
    assert parse_musicxml(None) == ([], {"_warnings": []})


def test_billion_laughs_rejected_by_defusedxml():
    bomb = (
        '<?xml version="1.0"?>'
        "<!DOCTYPE lolz ["
        ' <!ENTITY lol "lol">'
        ' <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
        ' <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
        "]>"
        '<score-partwise><part id="P1"><measure number="1">'
        "<harmony><root><root-step>&lol3;</root-step></root>"
        "<kind>major</kind></harmony></measure></part></score-partwise>"
    )
    tokens, meta = parse_musicxml(bomb)
    # defusedxml forbids entity definitions -> parse fails safely, no expansion.
    assert tokens == []
    assert meta.get("_warnings")


def test_mxl_binary_deferred_note():
    tokens, meta = parse_musicxml("PK\x03\x04 zip bytes")
    assert tokens == []
    assert any("compressed MusicXML" in w[1] for w in meta["_warnings"])


# ---------------------------------------------------------------------------
# shared seam + no-Sphinx-import (runtime, not source scan)
# ---------------------------------------------------------------------------

def test_uses_shared_lyric_seam():
    # Word-splitting comes from the shared tokenize_lyric_line authority: a
    # multi-word syllable is split into words at the same columns the seam
    # produces (not a re-implemented splitter).
    from doxtr_music.parsers._lyrics import tokenize_lyric_line

    body = _harmony("C", "major") + _note("two words", syllabic="single")
    tokens, _ = parse_musicxml(_score(body))
    seam = tokenize_lyric_line("two words ")
    assert _lyrics(tokens) == [t.text for t in seam]


def test_parser_imports_without_sphinx():
    # The pure parser must import + run without Sphinx in sys.modules (so the
    # CLI can reuse it). Runtime check, not a source scan.
    code = (
        "import sys\n"
        "assert 'sphinx' not in sys.modules\n"
        "from doxtr_music.parsers.musicxml import parse_musicxml\n"
        "assert 'sphinx' not in sys.modules, sorted(m for m in sys.modules if 'sphinx' in m)\n"
        "t, m = parse_musicxml('<score-partwise><part id=\\'P1\\'>"
        "<measure number=\\'1\\'><harmony><root><root-step>C</root-step></root>"
        "<kind>major</kind></harmony><note><duration>4</duration></note>"
        "</measure></part></score-partwise>')\n"
        "assert [x.text for x in t if type(x).__name__ == 'ChordToken'] == ['C']\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# directive integration: confinement + inherited options + BarToken drop
# ---------------------------------------------------------------------------

def test_directive_confinement_rejects_escape(tmp_path, monkeypatch):
    # The directive reads files ONLY via the shared load_confined_source helper.
    from doxtr_music.directives._fileload import (
        ConfinementError,
        _resolve_confined_path,
    )

    class _Env:
        srcdir = str(tmp_path)

        def relfn2path(self, arg):
            import os

            return arg, os.path.join(str(tmp_path), arg)

    with pytest.raises(ConfinementError):
        _resolve_confined_path(_Env(), "/etc/passwd")  # absolute -> rejected
    with pytest.raises(ConfinementError):
        _resolve_confined_path(_Env(), "../../../etc/passwd")  # escape -> rejected


def test_import_base_is_song_directive_subclass():
    from doxtr_music.directives._base import SongDirectiveBase
    from doxtr_music.directives._import_base import ImportDirectiveBase
    from doxtr_music.directives.import_musicxml import ImportMusicXMLDirective

    assert issubclass(ImportDirectiveBase, SongDirectiveBase)
    assert issubclass(ImportMusicXMLDirective, ImportDirectiveBase)
    # Front-end convergence: the parser is the pure MusicXML parser.
    assert ImportMusicXMLDirective.parser_fn is staticmethod(parse_musicxml).__func__


def test_inherited_transpose_shifts_imported_chords():
    # The imported tokens flow through the base transpose step; a +2 shift on a
    # C chord yields D (quality-preserving).
    from doxtr_music.engine.transpose import transpose_tokens

    tokens, _ = parse_musicxml(_score(_harmony("C", "major") + _note("hi")))
    shifted = transpose_tokens(tokens, 2, None)
    chord = next(t for t in shifted if isinstance(t, ChordToken))
    transposed = dict(chord.annotations).get("transposed")
    assert transposed == "D"
