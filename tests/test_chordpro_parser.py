"""Tests for the ChordPro parser and shared ``_lyrics`` tokenization seam.

Pure-function tests (no Sphinx build). They lock the CHUNK-1-3 contract:
lyric-relative codepoint columns, verbatim-English chords, the LOCKED
``song_meta`` shape, section/singer/comment handling, robustness, and the
shared-seam API that CHUNK-3-1/6-1/6-2 will import.
"""

from __future__ import annotations

import pathlib

import doxtr_music.parsers._lyrics as lyrics_mod
import doxtr_music.parsers.chordpro as chordpro_mod
from doxtr_music.parsers import parse_chordpro
from doxtr_music.parsers._lyrics import (
    chord_column_in_lyric,
    parse_directive_line,
    scan_chord_row,
    tokenize_lyric_line,
)
from doxtr_music.tokens import (
    ChordToken,
    LineBreakToken,
    LyricToken,
    SectionToken,
    SingerToken,
)


def _chords(tokens):
    return [t for t in tokens if isinstance(t, ChordToken)]


def _lyric_tokens(tokens):
    return [t for t in tokens if isinstance(t, LyricToken)]


def _sections(tokens):
    return [t for t in tokens if isinstance(t, SectionToken)]


def _singers(tokens):
    return [t for t in tokens if isinstance(t, SingerToken)]


# --------------------------------------------------------------------------
# Exit criterion 1 & 6 & 7: inline chords, columns, line breaks, empty input
# --------------------------------------------------------------------------


def test_am_hello_c_world_columns():
    tokens, meta = parse_chordpro("[Am]Hello [C]world")
    chords = _chords(tokens)
    assert [(c.text, c.column) for c in chords] == [("Am", 0), ("C", 6)]
    words = _lyric_tokens(tokens)
    assert [(w.text, w.column) for w in words] == [("Hello", 0), ("world", 6)]


def test_mid_word_chord_columns():
    # [C]Hel[G]lo -> de-bracketed lyric "Hello"; chords at 0 and 3.
    tokens, meta = parse_chordpro("[C]Hel[G]lo")
    chords = _chords(tokens)
    assert [(c.text, c.column) for c in chords] == [("C", 0), ("G", 3)]
    words = _lyric_tokens(tokens)
    assert [(w.text, w.column) for w in words] == [("Hello", 0)]
    # Builders recover the intra-word split via chord.column - word.column.
    assert chords[1].column - words[0].column == 3


def test_chord_at_line_end():
    tokens, meta = parse_chordpro("Hello[C]")
    chords = _chords(tokens)
    assert [(c.text, c.column) for c in chords] == [("C", 5)]
    words = _lyric_tokens(tokens)
    assert [(w.text, w.column) for w in words] == [("Hello", 0)]


def test_chord_only_instrumental_line():
    tokens, meta = parse_chordpro("[Am] [C]")
    chords = _chords(tokens)
    assert [(c.text, c.column) for c in chords] == [("Am", 0), ("C", 1)]
    # De-bracketed text is " " (single space) → no word lyric tokens.
    assert _lyric_tokens(tokens) == []


def test_linebreak_between_lines_and_line_index():
    tokens, meta = parse_chordpro("[Am]Hello\n[C]world")
    # A LineBreakToken separates the two source lines.
    assert any(isinstance(t, LineBreakToken) for t in tokens)
    lbs = [t for t in tokens if isinstance(t, LineBreakToken)]
    assert len(lbs) == 1
    chords = _chords(tokens)
    assert chords[0].line == 0
    assert chords[1].line == 1
    words = _lyric_tokens(tokens)
    assert words[0].line == 0
    assert words[1].line == 1


def test_empty_input_returns_empty():
    assert parse_chordpro("") == ([], {})
    assert parse_chordpro("   \n  \t") == ([], {})
    assert parse_chordpro(None) == ([], {})


def test_crlf_normalized():
    tokens, meta = parse_chordpro("a\r\nb\rc")
    lbs = [t for t in tokens if isinstance(t, LineBreakToken)]
    assert len(lbs) == 2  # three lines → two breaks


# --------------------------------------------------------------------------
# Exit criterion 3: metadata → top-level song_meta (verbatim), {meta:} promote
# --------------------------------------------------------------------------


def test_standard_metadata_verbatim():
    src = (
        "{title: My Song}\n"
        "{subtitle: Live}\n"
        "{artist: Band}\n"
        "{album: Record}\n"
        "{key: G}\n"
        "{tempo: 120 swing}\n"
        "{time: 4/4}\n"
        "{capo: 2}\n"
    )
    tokens, meta = parse_chordpro(src)
    assert meta["title"] == "My Song"
    assert meta["subtitle"] == "Live"
    assert meta["artist"] == "Band"
    assert meta["album"] == "Record"
    assert meta["key"] == "G"
    # No numeric coercion here — verbatim string kept.
    assert meta["tempo"] == "120 swing"
    assert meta["time"] == "4/4"
    assert meta["capo"] == "2"
    # No section/singer tokens emitted from metadata.
    assert _sections(tokens) == []


def test_transpose_and_key_stored_verbatim():
    tokens, meta = parse_chordpro("{transpose: 2}\n{key: Bb}")
    assert meta["transpose"] == "2"
    # {key} not enharmonically normalized here.
    assert meta["key"] == "Bb"


def test_meta_promotion_single_and_multi():
    tokens, meta = parse_chordpro(
        "{meta: tags rock, acoustic}\n{meta: difficulty Beginner}"
    )
    assert meta["tags"] == ["rock", "acoustic"]
    assert meta["difficulty"] == "Beginner"


def test_meta_collision_with_standard_key_warns_keeps_standard():
    tokens, meta = parse_chordpro("{title: Real Title}\n{meta: title Fake}")
    assert meta["title"] == "Real Title"
    assert any("collides with standard" in m for _, m in meta["_warnings"])


def test_meta_underscore_key_rejected():
    tokens, meta = parse_chordpro("{meta: _secret value}")
    assert "_secret" not in meta
    assert any("starts with '_'" in m for _, m in meta["_warnings"])


def test_duplicate_standard_directive_last_wins():
    tokens, meta = parse_chordpro("{title: First}\n{title: Second}")
    assert meta["title"] == "Second"
    assert any("duplicate" in m for _, m in meta["_warnings"])


# --------------------------------------------------------------------------
# Exit criterion 4: section / singer / comment
# --------------------------------------------------------------------------


def test_start_of_chorus_short_alias():
    tokens, meta = parse_chordpro("{soc}")
    sections = _sections(tokens)
    assert len(sections) == 1
    assert sections[0].kind == "chorus"
    assert sections[0].label == "Chorus"


def test_start_of_verse_with_explicit_label():
    tokens, meta = parse_chordpro("{start_of_verse: Intro Verse}")
    sections = _sections(tokens)
    assert sections[0].kind == "verse"
    assert sections[0].label == "Intro Verse"


def test_start_of_bridge_default_label():
    tokens, meta = parse_chordpro("{sob}")
    sections = _sections(tokens)
    assert sections[0].kind == "bridge"
    assert sections[0].label == "Bridge"


def test_custom_section_kind_open_and_close():
    # ChordPro allows arbitrary section kinds: {start_of_<kind>} / {end_of_<kind>}.
    tokens, meta = parse_chordpro(
        "{start_of_highlight}\n[C]la\n{end_of_highlight}"
    )
    sections = _sections(tokens)
    assert sections[0].kind == "highlight"
    assert sections[0].label == "Highlight"  # default label = kind title-cased
    assert sections[-1].kind == "none"  # close returns to unlabeled boundary


def test_custom_section_kind_explicit_label():
    tokens, meta = parse_chordpro("{start_of_intro: Intro Riff}\n[C]la")
    sec = _sections(tokens)[0]
    assert sec.kind == "intro"
    assert sec.label == "Intro Riff"


def test_custom_section_kind_normalizes_hyphen():
    tokens, meta = parse_chordpro("{start_of_pre-chorus}\n[C]la")
    sec = _sections(tokens)[0]
    assert sec.kind == "pre_chorus"


def test_reserved_tab_directive_is_not_a_custom_section():
    # start_of_tab is reserved/unsupported, NOT a custom section kind.
    tokens, meta = parse_chordpro("{start_of_tab}\nsome tab\n{end_of_tab}")
    assert _sections(tokens) == []


def test_end_of_chorus_emits_kind_none():
    tokens, meta = parse_chordpro("{soc}\n[C]la\n{end_of_chorus}")
    sections = _sections(tokens)
    kinds = [s.kind for s in sections]
    assert kinds == ["chorus", "none"]
    assert sections[-1].label == ""


def test_chorus_recall_annotated():
    tokens, meta = parse_chordpro("{chorus}")
    sec = _sections(tokens)[0]
    assert sec.kind == "chorus"
    assert sec.label == "Chorus"
    assert ("recall", "true") in sec.annotations


def test_singer_directive():
    tokens, meta = parse_chordpro("{singer: B}")
    singers = _singers(tokens)
    assert len(singers) == 1
    assert singers[0].singer == "B"


def test_comment_preserved_not_section():
    tokens, meta = parse_chordpro("{comment: play x2}")
    # No section, no singer emitted.
    assert _sections(tokens) == []
    assert _singers(tokens) == []
    assert meta["_comments"] == [(0, "play x2")]


def test_short_comment_alias_c_is_comment_not_section():
    tokens, meta = parse_chordpro("{c: Chorus}")
    assert _sections(tokens) == []
    assert meta["_comments"] == [(0, "Chorus")]


def test_chord_defs_reserved():
    tokens, meta = parse_chordpro("{define: Am base-fret 1 frets X 0 2 2 1 0}")
    assert meta["_chord_defs"]
    # Never treated as lyrics / never crashes.
    assert _lyric_tokens(tokens) == []


# --------------------------------------------------------------------------
# Exit criterion 5: robustness (never crash), _warnings shape (line, message)
# --------------------------------------------------------------------------


def test_unbalanced_bracket_recovers():
    tokens, meta = parse_chordpro("[Am Hello world")
    # No chord parsed; the '[...' is treated as lyric text.
    assert _chords(tokens) == []
    words = _lyric_tokens(tokens)
    assert words[0].text.startswith("[Am")
    assert any("unbalanced '['" in m for _, m in meta["_warnings"])


def test_stray_close_bracket_recovers():
    tokens, meta = parse_chordpro("Hello] world")
    assert any("stray ']'" in m for _, m in meta["_warnings"])
    # Lyrics still present.
    assert _lyric_tokens(tokens)


def test_stray_brace_recovers():
    tokens, meta = parse_chordpro("Hello } world")
    assert any("stray '}'" in m for _, m in meta["_warnings"])


def test_warnings_shape_is_line_message_tuples():
    tokens, meta = parse_chordpro("[Am world")
    for entry in meta["_warnings"]:
        assert isinstance(entry, tuple) and len(entry) == 2
        assert isinstance(entry[0], int)
        assert isinstance(entry[1], str)


def test_unknown_directive_routed_to_unknown_never_crash():
    tokens, meta = parse_chordpro("{start_of_tab}\n{totally_made_up: x}")
    assert "_unknown" in meta
    assert len(meta["_unknown"]) == 2


# --------------------------------------------------------------------------
# Shared-seam API (so CHUNK-3-1/6-1/6-2 can import these authorities)
# --------------------------------------------------------------------------


def test_tokenize_lyric_line_authority():
    toks = tokenize_lyric_line("Hello  world", line=3)
    assert [(t.text, t.column, t.line) for t in toks] == [
        ("Hello", 0, 3),
        ("world", 7, 3),
    ]
    assert tokenize_lyric_line("   ") == []


def test_scan_chord_row_authority():
    pairs = scan_chord_row("Am    C   G7")
    assert pairs == [("Am", 0), ("C", 6), ("G7", 10)]
    assert scan_chord_row("   ") == []


def test_chord_column_in_lyric_authority():
    # source '[' at 6, 5 chars stripped before → lyric column 1.
    assert chord_column_in_lyric(6, 5) == 1


def test_parse_directive_line_sink_and_return():
    emitted = []
    meta = {}
    consumed = parse_directive_line("{soc}", meta, 0, emitted.append)
    assert consumed is True
    assert isinstance(emitted[0], SectionToken)

    consumed2 = parse_directive_line("[Am]Hello", meta, 1, emitted.append)
    assert consumed2 is False


# --------------------------------------------------------------------------
# Exit criterion 8: no Sphinx/Docutils/theme import (static source-scan)
# --------------------------------------------------------------------------


def test_no_sphinx_docutils_theme_import_static():
    import ast

    root = pathlib.Path(chordpro_mod.__file__).parent
    forbidden_roots = {"sphinx", "docutils", "doxtr_pdf_theme_core"}
    for py in root.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top not in forbidden_roots, (
                        f"{py.name} must not import {alias.name!r}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                assert top not in forbidden_roots, (
                    f"{py.name} must not import from {node.module!r}"
                )


def test_lyrics_module_is_shared_authority():
    # The seam functions live in _lyrics and are re-exported/importable.
    assert lyrics_mod.tokenize_lyric_line is tokenize_lyric_line
    assert lyrics_mod.scan_chord_row is scan_chord_row
    assert lyrics_mod.parse_directive_line is parse_directive_line
