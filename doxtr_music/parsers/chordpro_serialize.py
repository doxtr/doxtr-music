"""Tokens → ChordPro serializer — the single ``tokens_to_chordpro`` authority.

The **inverse** of the forward tokenization seam
(:mod:`doxtr_music.parsers._lyrics` / :mod:`doxtr_music.parsers.chordpro`): given
the locked token vocabulary (:mod:`doxtr_music.tokens`) it reconstructs inline
ChordPro text. This is the *sole* tokens → ChordPro authority (mirrors the
forward "single parsing authority" discipline); no consumer — including
``doxtr_music.cli`` — hand-rolls ChordPro emission. Because it is a pure function
in the ``parsers/`` layer (no Sphinx import), the CLI and the importers
(CHUNK-6-1/6-2) all gain ChordPro export through this one authority.

Correctness invariants (LOCKED — CHUNK-6-3)
-------------------------------------------

* **Right-to-left chord re-insertion.** ``[Chord]`` markers are inserted into the
  reconstructed lyric text at each ``ChordToken.column`` (a lyric-relative
  codepoint offset) in **descending column order**, so inserting one bracket
  never shifts a later chord's column — the multi-chord column-shift trap the
  serializer owns once.
* **Inter-word spacing** is reconstructed from the column gaps between successive
  :class:`~doxtr_music.tokens.LyricToken`\\ s (the inverse of CHUNK-1-3
  de-bracketing). Chord-only / instrumental lines emit chords over an
  empty/space lyric line.
* **Section round-trip.** ``SectionToken(kind="verse"|"chorus"|"bridge")`` →
  ``{start_of_verse}``/``{start_of_chorus}``/``{start_of_bridge}`` (a label
  becomes the directive value); ``SectionToken(kind="none")`` closes the open
  section with ``{end_of_<current>}``. Deterministic — the emitted directives
  re-parse to the same ``SectionToken`` shape.
* **Singer round-trip.** ``SingerToken("A")`` → ``{singer: A}``.
* **Metadata round-trip.** ``song_meta`` re-emits as ChordPro directives so
  metadata is not silently lost; ``_``-prefixed internal keys (``_warnings`` …)
  are never emitted.
* **Literal-character handling.** Lyric text may contain literal ``[ ] { }``.
  The forward ChordPro parser (CHUNK-1-3, LOCKED) has **no** backslash de-escape
  convention, so the serializer emits such text **as-is** (backslash escaping
  would not round-trip). Detection is exposed via :func:`has_literal_brackets`
  so the CLI can emit a ``_warnings``-style stderr note when a literal ``[`` /
  ``{`` in a lyric might be misinterpreted as a chord/directive (the chunk's
  sanctioned alternative to escaping; keeps the locked 1-3 parser closed).
"""

from __future__ import annotations

from doxtr_music.parsers._lyrics import STANDARD_META_KEYS
from doxtr_music.tokens import (
    BarToken,
    ChordToken,
    LineBreakToken,
    LyricToken,
    SectionToken,
    SingerToken,
)

__all__ = ["tokens_to_chordpro", "has_literal_brackets"]

#: Section ``kind`` → ChordPro open-directive base name. ``"none"`` is the close
#: marker (handled specially). ``"section"`` (generic) has no standard open
#: directive, so it is emitted as a labeled ``{start_of_verse}`` fallback only
#: when it carries a label; otherwise it is skipped (best-effort).
_KIND_TO_OPEN = {
    "verse": "start_of_verse",
    "chorus": "start_of_chorus",
    "bridge": "start_of_bridge",
}

#: The metadata keys re-emitted (ordered) as leading ChordPro directives. Kept in
#: a stable order so output is deterministic. Only keys present in ``song_meta``
#: are emitted; ``subtitle`` is emitted after ``title``.
_META_EMIT_ORDER = (
    "title",
    "subtitle",
    "artist",
    "album",
    "key",
    "tempo",
    "time",
    "capo",
    "transpose",
)


def tokens_to_chordpro(tokens, song_meta=None) -> str:
    """Serialize ``tokens`` (+ ``song_meta``) to inline ChordPro text.

    Pure function (no Sphinx import). Walks the token stream, grouping
    chord/lyric tokens into logical lines separated by
    :class:`~doxtr_music.tokens.LineBreakToken`, and reconstructs each line by
    inserting ``[Chord]`` markers into the reconstructed lyric text
    right-to-left. Section/singer tokens become ChordPro directives; ``song_meta``
    is re-emitted as leading directives. Returns a newline-terminated string
    (empty tokens + empty meta → ``""``).
    """
    song_meta = song_meta or {}
    out_lines: list = []

    # --- leading metadata directives ---------------------------------------
    out_lines.extend(_emit_metadata(song_meta))

    # --- walk the token stream, grouping into logical lines ----------------
    open_section = None  # kind of the currently open section (for {end_of_*})
    line_chords: list = []   # (column, text) pending for the current line
    line_lyrics: list = []   # LyricToken pending for the current line

    def flush_line():
        nonlocal line_chords, line_lyrics
        if line_chords or line_lyrics:
            out_lines.append(_render_line(line_chords, line_lyrics))
        line_chords = []
        line_lyrics = []

    for tok in tokens:
        if isinstance(tok, ChordToken):
            line_chords.append((tok.column, tok.text))
        elif isinstance(tok, LyricToken):
            line_lyrics.append(tok)
        elif isinstance(tok, LineBreakToken):
            flush_line()
            out_lines.append("")  # a blank line marks the stanza/line break
        elif isinstance(tok, SectionToken):
            flush_line()
            if tok.kind == "none":
                if open_section is not None:
                    out_lines.append("{end_of_%s}" % open_section)
                    open_section = None
                continue
            base = _KIND_TO_OPEN.get(tok.kind)
            if base is not None:
                # Close a prior open section first (deterministic nesting).
                if open_section is not None:
                    out_lines.append("{end_of_%s}" % open_section)
                label = (tok.label or "").strip()
                if label and label.lower() != tok.kind:
                    out_lines.append("{%s: %s}" % (base, label))
                else:
                    out_lines.append("{%s}" % base)
                open_section = tok.kind
            elif (tok.label or "").strip():
                # Generic labeled section with no standard directive: emit a
                # comment so the label is not lost (best-effort, re-parses to a
                # comment, never a bogus section).
                out_lines.append("{comment: %s}" % tok.label.strip())
        elif isinstance(tok, SingerToken):
            flush_line()
            out_lines.append("{singer: %s}" % tok.singer)
        elif isinstance(tok, BarToken):
            # Metadata-only (CHUNK-6-1/6-2): bars are not rendered in ChordPro.
            continue

    flush_line()
    if open_section is not None:
        out_lines.append("{end_of_%s}" % open_section)

    # Collapse a trailing run of blank lines to a single newline terminator.
    while out_lines and out_lines[-1] == "":
        out_lines.pop()

    if not out_lines:
        return ""
    return "\n".join(out_lines) + "\n"


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def _emit_metadata(song_meta: dict) -> list:
    """Return leading ChordPro directive lines for ``song_meta`` (deterministic order).

    Standard keys are emitted in :data:`_META_EMIT_ORDER`; any remaining
    non-``_``-prefixed keys (custom ``{meta:}`` keys) follow in sorted order as
    ``{meta: key value}``. ``_``-prefixed internals are never emitted.
    """
    lines: list = []
    for key in _META_EMIT_ORDER:
        if key in song_meta:
            value = song_meta[key]
            lines.append("{%s: %s}" % (key, _meta_value_str(value)))
    for key in sorted(song_meta):
        if key.startswith("_") or key in _META_EMIT_ORDER:
            continue
        value = song_meta[key]
        lines.append("{meta: %s %s}" % (key, _meta_value_str(value)))
    return lines


def _meta_value_str(value) -> str:
    """Render a ``song_meta`` value (str or list) as a directive value string."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


# ---------------------------------------------------------------------------
# Line reconstruction (the correctness core)
# ---------------------------------------------------------------------------

def _render_line(chords: list, lyrics: list) -> str:
    """Reconstruct one ChordPro line from its chords + lyric words.

    ``chords`` is ``[(column, text), ...]``; ``lyrics`` is a list of
    :class:`LyricToken`. The lyric words are placed at their codepoint columns
    (inter-word gaps reconstructed as spaces), then ``[Chord]`` markers are
    inserted **right-to-left** so earlier columns stay valid. Literal ``[ ] { }``
    in the lyric text are emitted **as-is** (the forward parser has no
    de-escape convention); the CLI surfaces a warning via
    :func:`has_literal_brackets`.
    """
    lyric_text = _reconstruct_lyric_text(lyrics)

    # Insert chords right-to-left (descending column) so an earlier insertion
    # does not shift a later chord's column.
    line = lyric_text
    for col, text in sorted(chords, key=lambda c: c[0], reverse=True):
        pos = col if 0 <= col <= len(lyric_text) else (0 if col < 0 else len(lyric_text))
        line = line[:pos] + "[" + text + "]" + line[pos:]

    return line


def has_literal_brackets(tokens) -> bool:
    """Return ``True`` if any :class:`LyricToken` carries a literal ``[`` or ``{``.

    Used by the CLI to emit a ``_warnings``-style note: because the forward
    ChordPro parser has no backslash de-escape convention, an emitted literal
    ``[later]`` / ``{x}`` in a lyric could be misread as a chord/directive when
    the output is pasted into ``.. song::``. Only the *opening* delimiters
    (``[`` / ``{``) can create a bogus chord/directive, so those are what we
    flag.
    """
    for tok in tokens:
        if isinstance(tok, LyricToken) and ("[" in tok.text or "{" in tok.text):
            return True
    return False


def _reconstruct_lyric_text(lyrics: list) -> str:
    """Rebuild the logical lyric string from ordered :class:`LyricToken`\\ s.

    Each word is placed at its ``column`` (codepoint offset); the gap between the
    end of one word and the start of the next is filled with spaces (the inverse
    of the tokenizer, which stores only word columns). Empty input → ``""``.
    """
    if not lyrics:
        return ""
    ordered = sorted(lyrics, key=lambda t: t.column)
    parts: list = []
    cursor = 0
    for tok in ordered:
        if tok.column > cursor:
            parts.append(" " * (tok.column - cursor))
            cursor = tok.column
        elif tok.column < cursor:
            # Overlapping columns (shouldn't happen for well-formed input);
            # ensure at least one separating space so words don't fuse.
            parts.append(" ")
            cursor += 1
        parts.append(tok.text)
        cursor += len(tok.text)
    return "".join(parts)
