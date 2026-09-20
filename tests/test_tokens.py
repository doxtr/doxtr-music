"""Unit tests for the doxtr-music token model (CHUNK-1-1)."""

import ast
import dataclasses
import pathlib

import pytest

from doxtr_music.tokens import (
    BarToken,
    ChordToken,
    LineBreakToken,
    LyricToken,
    SectionToken,
    SingerToken,
    Token,
    TokenKind,
    token_kind,
)


def test_public_names_import():
    # All public names resolve (exit criterion #1).
    names = [
        ChordToken,
        LyricToken,
        SectionToken,
        SingerToken,
        BarToken,
        LineBreakToken,
        TokenKind,
        token_kind,
    ]
    assert all(n is not None for n in names)
    # ``Token`` is a typing Union alias, present for annotations.
    assert Token is not None


def test_chord_token_fields_roundtrip():
    c = ChordToken(text="Am", column=6)
    assert c.text == "Am"
    assert c.column == 6
    assert c.line == 0
    assert c.duration is None
    assert c.annotations == ()

    c2 = ChordToken(text="G7", column=2, line=3, duration=1.5,
                    annotations=(("roman", "V"),))
    assert c2.line == 3
    assert c2.duration == 1.5
    assert c2.annotations == (("roman", "V"),)


def test_lyric_token_fields_roundtrip():
    ly = LyricToken(text="Hello", column=0)
    assert ly.text == "Hello"
    assert ly.column == 0
    assert ly.line == 0
    assert ly.annotations == ()

    ly2 = LyricToken(text="world", column=6, line=1,
                     annotations=(("syllable", "wor"),))
    assert ly2.line == 1
    assert ly2.annotations == (("syllable", "wor"),)


def test_section_token_fields_roundtrip():
    s = SectionToken(label="Verse 1")
    assert s.label == "Verse 1"
    assert s.kind == "section"
    assert s.annotations == ()

    boundary = SectionToken(label="", kind="none")
    assert boundary.kind == "none"
    assert boundary.label == ""


def test_singer_token_fields():
    s = SingerToken(singer="Alice")
    assert s.singer == "Alice"
    assert s.annotations == ()


def test_bar_and_linebreak_tokens():
    b = BarToken()
    assert b.annotations == ()
    lb = LineBreakToken()
    assert lb.annotations == ()


@pytest.mark.parametrize(
    "tok",
    [
        ChordToken(text="C", column=0),
        LyricToken(text="hi", column=0),
        SectionToken(label="Chorus"),
        SingerToken(singer="Bob"),
        BarToken(),
        LineBreakToken(),
    ],
)
def test_tokens_are_frozen(tok):
    # Assignment to any field must raise (exit criterion #2).
    field = dataclasses.fields(tok)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(tok, field, "mutated")


def test_tokens_are_hashable_and_value_equal():
    a = ChordToken(text="Am", column=6)
    b = ChordToken(text="Am", column=6)
    assert a == b
    assert hash(a) == hash(b)
    # Usable in a set.
    s = {a, b, LyricToken(text="x", column=0), SectionToken(label="V"),
         SingerToken(singer="A"), BarToken(), LineBreakToken()}
    assert len(s) == 6  # a and b collapse to one


def test_annotated_token_stays_hashable():
    # Exit criterion #4: reserved-but-annotatable tokens stay hashable when
    # annotations holds a tuple of hashable (str, str) pairs.
    c = ChordToken(text="G", column=0, annotations=(("roman", "IV"),))
    ly = LyricToken(text="la", column=0, annotations=(("k", "v"),))
    s = {c, ly}
    assert len(s) == 2
    assert hash(c) == hash(ChordToken(text="G", column=0,
                                      annotations=(("roman", "IV"),)))


def test_token_kind_mapping():
    # Exit criterion #3: correct TokenKind for every concrete type.
    assert token_kind(ChordToken(text="C", column=0)) is TokenKind.CHORD
    assert token_kind(LyricToken(text="x", column=0)) is TokenKind.LYRIC
    assert token_kind(SectionToken(label="V")) is TokenKind.SECTION
    assert token_kind(SingerToken(singer="A")) is TokenKind.SINGER
    assert token_kind(BarToken()) is TokenKind.BAR
    assert token_kind(LineBreakToken()) is TokenKind.LINEBREAK


def test_token_kind_rejects_non_token():
    with pytest.raises(TypeError):
        token_kind("not a token")


def test_reserved_enum_members_exist():
    # Future placeholders present but with no emitter/concrete type.
    assert TokenKind.DIRECTIVE
    assert TokenKind.COMMENT
    assert TokenKind.MARKER


def test_no_forbidden_imports_static_scan():
    # Exit criterion #5 (authoritative): static source-scan over tokens.py
    # asserting no import of sphinx, docutils, or doxtr_pdf_theme_core.
    src = pathlib.Path(__file__).resolve().parents[1] / "doxtr_music" / "tokens.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    forbidden = {"sphinx", "docutils", "doxtr_pdf_theme_core"}
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_roots.add(node.module.split(".")[0])
    assert not (imported_roots & forbidden), (
        f"tokens.py must not import {forbidden & imported_roots}"
    )
