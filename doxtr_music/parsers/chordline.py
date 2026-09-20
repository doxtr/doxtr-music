"""chord-line parser — legacy "chords-over-lyrics" (Ultimate Guitar) → tokens.

:func:`parse_chord_line` translates monospaced text where a **chord row** sits
directly above a **lyric row** and chords anchor to lyric characters *strictly by
character column*. It is a **pure alternate front-end** (front-end convergence
invariant, CHUNK-3-1): it converges on the locked token vocabulary (CHUNK-1-1)
and returns the same ``(tokens, song_meta)`` contract as
:func:`doxtr_music.parsers.chordpro.parse_chordpro`, so all three formats render
a chord-line block identically to a ``.. song::``. It never renders and never
introduces a chord-line-specific token/node type.

Shared seams consumed (LOCKED):

* :func:`doxtr_music.parsers._lyrics.parse_directive_line` — single metadata /
  section / singer authority (``{title}``/``{soc}``/``{singer:}`` → full parity).
* :func:`doxtr_music.parsers._lyrics.scan_chord_row` — unbracketed chord-row →
  ``(chord_text, codepoint_column)`` (the chord-line alignment authority).
* :func:`doxtr_music.parsers._lyrics.tokenize_lyric_line` — word-splitting +
  per-word lyric-relative column authority.

It MUST NOT use ``chord_column_in_lyric`` (bracket-specific de-bracketing; the
chord row is separate and unbracketed).

Documented parse-time limitations (see the line-classification / robustness
notes below): tab handling, ragged columns, wide/combining codepoints, and
strong-RTL lyrics are best-effort with a ``_warnings`` note — never a crash.

No Sphinx/Docutils/``doxtr_pdf_theme_core`` import (pure, CLI-reusable).
"""

from __future__ import annotations

import re
import unicodedata

from doxtr_music.parsers._lyrics import (
    parse_directive_line,
    scan_chord_row,
    tokenize_lyric_line,
)
from doxtr_music.tokens import (
    ChordToken,
    LineBreakToken,
    LyricToken,
    SectionToken,
    Token,
)

__all__ = ["parse_chord_line", "CHORD_RE", "is_plausible_chord"]

#: Fixed tab stop width used to expand tabs on BOTH the chord row and the lyric
#: row against the same stops before any column math (files mix tabs/spaces).
_TAB_WIDTH = 8

#: Plausible-chord recognition (LOCKED reference form). Anchored, no anchors on a
#: root/accidental/quality/extension/optional-bass shape. Used to (a) classify a
#: whole line as a chord row and (b) reject bracket content that is really a
#: chord (``[Am]`` is a chord, ``[Chorus]`` is a section).
CHORD_RE = re.compile(
    r"^[A-G](#|b|##|bb)?"           # root + optional accidental
    r"(m|maj|min|dim|aug|sus|add)?"  # optional quality
    r"[0-9]*"                        # optional extension digits
    r"(/[A-G](#|b)?)?$"              # optional slash-bass
)

#: Common Ultimate-Guitar bracket section labels → SectionToken kind. Anything
#: else non-chord in brackets becomes a generic section with the literal label.
_UG_SECTION_KINDS = {
    "verse": "verse",
    "chorus": "chorus",
    "bridge": "bridge",
    "intro": "section",
    "outro": "section",
    "solo": "section",
    "interlude": "section",
    "pre-chorus": "section",
    "prechorus": "section",
    "refrain": "chorus",
    "coda": "section",
    "instrumental": "section",
    "breakdown": "section",
}

_BRACKET_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def is_plausible_chord(token: str) -> bool:
    """Return ``True`` iff ``token`` matches the plausible-chord shape."""
    return bool(token) and bool(CHORD_RE.match(token))


def _expand_tabs(line: str) -> str:
    """Expand tabs against fixed 8-column stops (both rows use the same stops)."""
    return line.expandtabs(_TAB_WIDTH)


def _is_chord_row(line: str) -> bool:
    """Return ``True`` iff every whitespace-separated token is a plausible chord.

    A blank line is not a chord row. A single token that is a plausible chord
    (``Am``) counts; a bracketed ``[Am]`` line is handled by the section rule.
    """
    parts = line.split()
    if not parts:
        return False
    return all(is_plausible_chord(p) for p in parts)


def _classify_bracket_section(line: str):
    """Return a ``SectionToken`` for a non-chord ``[label]`` line, else ``None``.

    A bracketed line whose interior *is* a plausible chord (``[Am]``) returns
    ``None`` (it is a chord-only row, not a section).
    """
    m = _BRACKET_SECTION_RE.match(line)
    if not m:
        return None
    label = m.group(1).strip()
    if is_plausible_chord(label):
        return None  # ``[Am]`` — chord, not a section.
    key = label.lower()
    # Strip a trailing number (``Verse 1`` → ``verse``) for kind mapping only;
    # the visible label keeps its number.
    base = re.sub(r"\s*\d+\s*$", "", key).strip()
    kind = _UG_SECTION_KINDS.get(key) or _UG_SECTION_KINDS.get(base) or "section"
    return SectionToken(label=label, kind=kind)


def _has_wide_or_combining(text: str) -> bool:
    """Return ``True`` if ``text`` has wide (2-cell) or combining (0-cell) chars.

    Column math is codepoint-based; wide/combining codepoints break the
    codepoint==cell assumption chord-line authors rely on.
    """
    for ch in text:
        if unicodedata.combining(ch):
            return True
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            return True
    return False


def _has_strong_rtl(text: str) -> bool:
    """Return ``True`` if ``text`` has a strong right-to-left codepoint.

    Delegates to the single RTL authority in :mod:`doxtr_music.engine.i18n`
    (CHUNK-3-4) so parser + render-time detection never drift.
    """
    from doxtr_music.engine.i18n import has_strong_rtl

    return has_strong_rtl(text)


def _emit_lyric_row(
    lyric_text: str,
    chord_pairs,
    line_index: int,
    song_meta: dict,
    emit,
) -> None:
    """Emit chords + lyric words for one (chord row, lyric row) pairing.

    ``chord_pairs`` is a list of ``(chord_text, column)`` from
    :func:`scan_chord_row` (may be empty for a lyric-only row, or anchored to an
    empty lyric for a chord-only row). ``lyric_text`` is the (already
    tab-expanded) lyric row; may be empty.
    """
    warnings = song_meta.setdefault("_warnings", [])

    lyric_len = len(lyric_text)
    if lyric_text:
        if _has_wide_or_combining(lyric_text):
            warnings.append(
                (
                    line_index,
                    "chord-line alignment is exact only for single-cell text; "
                    "wide/combining characters may misalign chords",
                )
            )
        if _has_strong_rtl(lyric_text):
            warnings.append(
                (
                    line_index,
                    "chord-line does not support right-to-left lyrics "
                    "(chords may be misattributed); use .. song:: with inline "
                    "[C]chord binding for RTL",
                )
            )

    # Emit chords at their columns; clamp ragged columns to lyric end + warn.
    for chord_text, col in chord_pairs:
        anchor = col
        if lyric_len and col > lyric_len:
            warnings.append(
                (
                    line_index,
                    "chord '%s' at column %d is past the end of the lyric line; "
                    "anchored at line end" % (chord_text, col),
                )
            )
            anchor = lyric_len
        emit(ChordToken(text=chord_text, column=anchor, line=line_index))

    # Emit lyric words via the shared authority (identical columns to ChordPro).
    for tok in tokenize_lyric_line(lyric_text, line=line_index):
        emit(tok)


def parse_chord_line(text: str) -> tuple:
    """Parse chords-over-lyrics ``text`` into ``(tokens, song_meta)``.

    Same return contract as
    :func:`doxtr_music.parsers.chordpro.parse_chordpro`. Empty / whitespace-only
    input returns ``([], {})``.
    """
    if text is None or not text.strip():
        return [], {}

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = normalized.split("\n")

    tokens: list = []
    song_meta: dict = {}

    def emit(tok: Token) -> None:
        tokens.append(tok)

    # Pre-expand tabs on every line against the SAME fixed stops so the chord row
    # and its lyric row share a coordinate system.
    lines = [_expand_tabs(ln) for ln in raw_lines]

    # ``line_index`` (0-based logical line) is used for token ``line`` + warning
    # provenance. A (chord, lyric) pair collapses to the *lyric* line's index so
    # the single-line grouping model (CHUNK-1-2) sees one line.
    i = 0
    n = len(lines)
    # Track whether the previous emitted logical unit needs a trailing break.
    emitted_units = 0

    def emit_break():
        nonlocal emitted_units
        if emitted_units:
            emit(LineBreakToken())

    while i < n:
        raw = raw_lines[i]
        line = lines[i]
        stripped = line.strip()

        # 1. ChordPro directive line ({...}) — metadata/section/singer authority.
        if parse_directive_line(raw, song_meta, i, emit):
            emit_break()
            emitted_units += 1
            i += 1
            continue

        # 2. Blank line → stanza break (no tokens, but a LineBreak boundary).
        if not stripped:
            emit_break()
            emitted_units += 1
            i += 1
            continue

        # 3. Bracketed non-chord section header ([Chorus], [Verse 1], ...).
        section = _classify_bracket_section(line)
        if section is not None:
            emit_break()
            emit(section)
            emitted_units += 1
            i += 1
            continue

        # 3b. Bracketed single chord ([Am], [C]) => chord-only row.
        bracket_chord = _BRACKET_SECTION_RE.match(line)
        if bracket_chord and is_plausible_chord(bracket_chord.group(1).strip()):
            chord_text = bracket_chord.group(1).strip()
            col = line.index("[")
            emit_break()
            _emit_lyric_row("", [(chord_text, col)], i, song_meta, emit)
            emitted_units += 1
            i += 1
            continue

        # 4. Chord row?
        if _is_chord_row(line):
            chord_pairs = scan_chord_row(line)
            # Look at the next line to decide pairing.
            nxt = lines[i + 1] if i + 1 < n else None
            nxt_stripped = nxt.strip() if nxt is not None else ""
            nxt_is_directive_or_section = False
            if nxt is not None and nxt_stripped:
                # A following {..} directive or [section]/[chord] is NOT a lyric.
                if nxt_stripped.startswith("{") and nxt_stripped.endswith("}"):
                    nxt_is_directive_or_section = True
                elif _BRACKET_SECTION_RE.match(nxt):
                    nxt_is_directive_or_section = True
                elif _is_chord_row(nxt):
                    nxt_is_directive_or_section = True

            if (
                nxt is not None
                and nxt_stripped
                and not nxt_is_directive_or_section
            ):
                # Pair chord row with the immediately following lyric row.
                emit_break()
                _emit_lyric_row(nxt, chord_pairs, i + 1, song_meta, emit)
                emitted_units += 1
                i += 2
                continue

            # Chord-only row (EOF, stacked chord rows, or followed by a
            # directive/section): anchor to an empty lyric.
            emit_break()
            _emit_lyric_row("", chord_pairs, i, song_meta, emit)
            emitted_units += 1
            i += 1
            continue

        # 5. Lyric line (no chord row above it).
        emit_break()
        _emit_lyric_row(line, [], i, song_meta, emit)
        emitted_units += 1
        i += 1

    return tokens, song_meta
