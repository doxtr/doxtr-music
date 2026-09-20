"""ChordPro parser — the primary input path and tokenization authority.

:func:`parse_chordpro` turns raw ChordPro text into the locked
``(tokens, song_meta)`` contract (see :mod:`doxtr_music.tokens`). It is a pure
function with no Sphinx/Docutils/``doxtr_pdf_theme_core`` dependency so the CLI
(CHUNK-6-3) and song-include (CHUNK-3-5) can call it directly.

The hardest, drift-prone logic (lyric word-splitting, per-word lyric-relative
columns, single-line ``{...}`` directives) lives in
:mod:`doxtr_music.parsers._lyrics` so every front-end shares one authority.

Contract highlights (all LOCKED by CHUNK-1-1/1-3):

* Inline ``[Chord]lyric``; ``column`` is a 0-based codepoint offset into the
  de-bracketed *logical* line text (mid-word chords supported).
* Chord text stored **verbatim English** — no transpose/localize here.
* Song-level metadata never becomes a token; it flows into ``song_meta``.
* ``song_meta`` uses ``_``-prefixed internal keys (``_warnings``/``_comments``/
  ``_unknown``/``_chord_defs``); CHUNK-1-4 drains + strips them before render.
* Never crashes: malformed input recovers with a ``_warnings`` entry.
"""

from __future__ import annotations

from doxtr_music.parsers._lyrics import (
    chord_column_in_lyric,
    parse_directive_line,
    tokenize_lyric_line,
)
from doxtr_music.tokens import (
    ChordToken,
    LineBreakToken,
    Token,
)

__all__ = ["parse_chordpro"]


def parse_chordpro(text: str) -> tuple:
    """Parse ChordPro ``text`` into ``(tokens, song_meta)``.

    Returns a list of :class:`~doxtr_music.tokens.Token` and a ``song_meta``
    dict. Empty / whitespace-only input returns ``([], {})`` (no keys added).
    """
    if text is None or not text.strip():
        return [], {}

    # Normalize line endings to \n (CRLF / bare CR).
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    source_lines = normalized.split("\n")

    tokens: list = []
    song_meta: dict = {}

    def emit(tok: Token) -> None:
        tokens.append(tok)

    # ``line`` is the 0-based *logical* body line index (only lyric/chord/section
    # lines advance it; a full-line directive still occupies its own logical
    # line for provenance). We use the source-line index directly so warning
    # provenance matches the author's file.
    total = len(source_lines)
    for idx, raw_line in enumerate(source_lines):
        # A full-line {directive}? _lyrics owns the metadata authority.
        if parse_directive_line(raw_line, song_meta, idx, emit):
            # Preserve line boundary between source lines.
            if idx < total - 1:
                emit(LineBreakToken())
            continue

        # Otherwise tokenize inline chords + lyrics for this line.
        _parse_body_line(raw_line, idx, song_meta, emit)

        if idx < total - 1:
            emit(LineBreakToken())

    return tokens, song_meta


def _parse_body_line(
    raw_line: str,
    line_index: int,
    song_meta: dict,
    emit,
) -> None:
    """Tokenize one body line of inline ``[chord]lyric`` text.

    De-brackets the line into logical lyric text, emitting a
    :class:`~doxtr_music.tokens.ChordToken` at each bracket's lyric-relative
    column and word :class:`~doxtr_music.tokens.LyricToken`\\ s (via the shared
    ``tokenize_lyric_line`` authority). Mid-word chords land at absolute columns
    inside a word span; builders recover the split via ``chord.column −
    word.column``.
    """
    warnings = song_meta.setdefault("_warnings", [])

    lyric_chars: list = []
    chords: list = []  # (chord_text, lyric_relative_column)
    i = 0
    n = len(raw_line)
    # ``stripped_before`` = count of source characters removed (bracket spans)
    # before the current position, used to map source ``[`` → lyric column.
    stripped_before = 0

    while i < n:
        ch = raw_line[i]
        if ch == "[":
            close = raw_line.find("]", i + 1)
            if close == -1:
                # Unbalanced '[': treat the rest as literal lyric text.
                warnings.append(
                    (line_index, "unbalanced '[' in line; treated as lyric text")
                )
                lyric_chars.append(raw_line[i:])
                i = n
                break
            chord_text = raw_line[i + 1 : close]
            # Lyric-relative column: source '[' position minus removed chars.
            col = chord_column_in_lyric(i, stripped_before)
            chords.append((chord_text, col))
            span = close - i + 1  # includes both brackets
            stripped_before += span
            i = close + 1
            continue
        if ch == "]":
            # Stray ']' with no opening '[': keep literal, warn.
            warnings.append((line_index, "stray ']' in line; treated as literal"))
            lyric_chars.append(ch)
            i += 1
            continue
        if ch == "}":
            # Stray '}' outside a directive: keep literal, warn.
            warnings.append((line_index, "stray '}' in line; treated as literal"))
            lyric_chars.append(ch)
            i += 1
            continue
        if ch == "{":
            # Inline '{' that was not a full-line directive: keep literal, warn.
            warnings.append(
                (line_index, "unmatched '{' in line; treated as literal")
            )
            lyric_chars.append(ch)
            i += 1
            continue
        lyric_chars.append(ch)
        i += 1

    lyric_text = "".join(lyric_chars)

    # Emit chords (verbatim English text) at their lyric-relative columns.
    for chord_text, col in chords:
        emit(ChordToken(text=chord_text, column=col, line=line_index))

    # Emit word lyric tokens via the shared authority.
    for lyric_tok in tokenize_lyric_line(lyric_text, line=line_index):
        emit(lyric_tok)
