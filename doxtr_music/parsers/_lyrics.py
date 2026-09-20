"""Shared tokenization seam — the single inline-chord/lyric parsing authority.

This module factors the hardest, most drift-prone tokenization logic out of the
ChordPro parser so that every input front-end targets **one** authority instead
of forking column math (which would break alignment identically across HTML,
LaTeX and EPUB). Locked consumption rules:

* **ChordPro** (:mod:`doxtr_music.parsers.chordpro`) uses
  :func:`tokenize_lyric_line` + :func:`chord_column_in_lyric` +
  :func:`parse_directive_line`.
* **chord-line** (CHUNK-3-1) uses :func:`tokenize_lyric_line` +
  :func:`scan_chord_row` + :func:`parse_directive_line`, and MUST NOT use
  :func:`chord_column_in_lyric` (de-bracketing does not apply to a separate,
  unbracketed chord row).
* **importers** (CHUNK-6-1/6-2) reuse :func:`tokenize_lyric_line` /
  :func:`scan_chord_row` as applicable.

``column`` is always a 0-based **codepoint** offset into the *logical*
(reading-order) de-bracketed lyric text of its line. This module performs no
bidi/RTL processing — visual mirroring is a render-time concern (CHUNK-3-4).

No Sphinx/Docutils/``doxtr_pdf_theme_core`` import (pure, CLI-reusable).
"""

from __future__ import annotations

from typing import Callable, Optional

from doxtr_music.tokens import (
    LyricToken,
    SectionToken,
    SingerToken,
    Token,
)

__all__ = [
    "tokenize_lyric_line",
    "chord_column_in_lyric",
    "scan_chord_row",
    "parse_directive_line",
    "STANDARD_META_KEYS",
]

#: Standard ChordPro directive keys promoted to top-level ``song_meta`` (stored
#: verbatim as strings). A custom ``{meta:}`` key must not clobber one of these.
STANDARD_META_KEYS = frozenset(
    {
        "title",
        "subtitle",
        "artist",
        "album",
        "key",
        "tempo",
        "time",
        "capo",
        "transpose",
    }
)

#: Section-open directives → ``(kind, default_label)``. Long + short aliases.
_SECTION_OPEN = {
    "start_of_verse": ("verse", "Verse"),
    "sov": ("verse", "Verse"),
    "start_of_chorus": ("chorus", "Chorus"),
    "soc": ("chorus", "Chorus"),
    "start_of_bridge": ("bridge", "Bridge"),
    "sob": ("bridge", "Bridge"),
}

#: Section-close directives → emit ``SectionToken(kind="none")``.
_SECTION_CLOSE = frozenset(
    {
        "end_of_verse",
        "eov",
        "end_of_chorus",
        "eoc",
        "end_of_bridge",
        "eob",
    }
)

#: Comment directives (ChordPro standard). Never a section label.
_COMMENT_KEYS = frozenset({"comment", "c", "comment_italic", "ci", "comment_box", "cb"})

#: Chord-definition directives → reserved ``song_meta["_chord_defs"]``.
_CHORD_DEF_KEYS = frozenset({"define", "chord"})

#: Reserved / out-of-scope directives — routed to ``_unknown`` (never crash).
_RESERVED_UNSUPPORTED = frozenset(
    {
        "start_of_tab",
        "sot",
        "end_of_tab",
        "eot",
        "start_of_grid",
        "sog",
        "end_of_grid",
        "eog",
        "new_song",
        "ns",
    }
)


def _custom_section_kind(name):
    """Recognize a generic ``start_of_<kind>`` / ``end_of_<kind>`` directive.

    ChordPro allows arbitrary section kinds beyond verse/chorus/bridge, so a
    songwriter may introduce any kind (``{start_of_highlight}``,
    ``{start_of_intro}``, …). Returns ``(is_open, kind)`` where ``kind`` is the
    normalized suffix (lower-case, spaces/hyphens → underscores), or ``None``
    when ``name`` is not a generic section directive. Only the explicit
    ``start_of_`` / ``end_of_`` prefixes are matched (the short ``so``/``eo``
    forms are reserved for the known aliases to avoid ambiguity).
    """
    for prefix, is_open in (("start_of_", True), ("end_of_", False)):
        if name.startswith(prefix) and len(name) > len(prefix):
            suffix = name[len(prefix):]
            kind = suffix.strip().lower().replace("-", "_").replace(" ", "_")
            # A kind must be a simple identifier-ish token (defensive).
            if kind and all(ch.isalnum() or ch == "_" for ch in kind):
                return (is_open, kind)
    return None


def tokenize_lyric_line(lyric_text: str, line: int = 0) -> list:
    """Split a de-bracketed lyric line into word :class:`LyricToken`\\ s.

    THE authority for word-splitting + per-word lyric-relative column. Splits on
    runs of whitespace; each token stores its word text and the 0-based codepoint
    column of the word's first character in ``lyric_text``. Trailing/inter-word
    spacing is **not** stored — it is reconstructed downstream from the column
    gap between adjacent words, which preserves both copy-safety and alignment.

    Empty / whitespace-only input yields ``[]``.
    """
    tokens = []
    i = 0
    n = len(lyric_text)
    while i < n:
        # Skip a run of whitespace.
        if lyric_text[i].isspace():
            i += 1
            continue
        # Accumulate a word (run of non-whitespace).
        start = i
        while i < n and not lyric_text[i].isspace():
            i += 1
        tokens.append(LyricToken(text=lyric_text[start:i], column=start, line=line))
    return tokens


def chord_column_in_lyric(source_bracket_pos: int, stripped_before: int) -> int:
    """Translate a bracketed source ``[`` position to a lyric-relative column.

    ChordPro-only. ``source_bracket_pos`` is the index of ``[`` in the raw source
    line; ``stripped_before`` is the total number of source characters (the
    ``[...]`` bracket spans, inclusive of both brackets) removed from the text
    *before* this bracket. The lyric-relative column is therefore
    ``source_bracket_pos - stripped_before``.

    Not applicable to unbracketed input; chord-line uses :func:`scan_chord_row`.
    """
    return source_bracket_pos - stripped_before


def scan_chord_row(chord_line: str) -> list:
    """Scan a whitespace-separated **chord row** into ``(chord_text, column)``.

    THE authority for unbracketed chord rows (chord-line CHUNK-3-1, and any
    monospaced/timed importer with a separate chord row). ``column`` is the
    0-based codepoint offset of the chord's first character in ``chord_line``.
    Returns pairs in source order; whitespace-only input yields ``[]``.
    """
    pairs: list = []
    i = 0
    n = len(chord_line)
    while i < n:
        if chord_line[i].isspace():
            i += 1
            continue
        start = i
        while i < n and not chord_line[i].isspace():
            i += 1
        pairs.append((chord_line[start:i], start))
    return pairs


def _split_directive(body: str) -> tuple:
    """Split a directive interior ``name`` or ``name: value`` / ``name value``.

    Returns ``(name_lower, value_or_None)``. The name is lower-cased and stripped;
    the value (if any) is stripped but otherwise verbatim. Both ``:`` and the
    first run of whitespace act as the name/value separator (ChordPro accepts
    ``{title: X}`` and ``{title X}``; the short forms use ``:``).
    """
    body = body.strip()
    # Prefer an explicit ``:`` separator; fall back to first whitespace.
    colon = body.find(":")
    space = -1
    for idx, ch in enumerate(body):
        if ch.isspace():
            space = idx
            break
    if colon == -1 and space == -1:
        return body.lower(), None
    if colon == -1:
        sep = space
    elif space == -1:
        sep = colon
    else:
        sep = min(colon, space)
    name = body[:sep].strip().lower()
    value = body[sep + 1 :].strip()
    return name, value


def parse_directive_line(
    line: str,
    song_meta: dict,
    line_index: int,
    emit: Callable[[Token], None],
) -> bool:
    """Handle a single ChordPro ``{...}`` metadata/section/singer directive line.

    THE authority for one ``{...}`` directive. Applies the locked ``song_meta``
    shape and pushes ``SectionToken``/``SingerToken`` through ``emit``. Returns
    ``True`` iff ``line`` was consumed as a directive (a full-line
    ``{directive}``); ``False`` means the caller should tokenize ``line`` as
    lyrics/chords.

    Only a line that is *exactly* a single ``{...}`` (optionally surrounded by
    whitespace) is treated as a directive line here; inline ``[chord]`` handling
    stays in the ChordPro parser. Malformed/unknown directives never crash; they
    append to ``song_meta`` machinery keys.
    """
    stripped = line.strip()
    if not (stripped.startswith("{") and stripped.endswith("}") and len(stripped) >= 2):
        return False
    body = stripped[1:-1]
    name, value = _split_directive(body)

    warnings = song_meta.setdefault("_warnings", [])

    # Section open.
    if name in _SECTION_OPEN:
        kind, default_label = _SECTION_OPEN[name]
        label = value if value else default_label
        emit(SectionToken(label=label, kind=kind))
        return True

    # Section close → return-to-unlabeled boundary.
    if name in _SECTION_CLOSE:
        emit(SectionToken(label="", kind="none"))
        return True

    # Generic custom section open/close (ChordPro allows ``start_of_<label>`` /
    # ``so<x>`` for arbitrary section kinds, so a songwriter may introduce any
    # kind, e.g. ``{start_of_highlight}`` / ``{start_of_intro}``). The kind is
    # the suffix; the default label is the kind title-cased. This is checked
    # AFTER the known aliases + the reserved tab/grid directives so those keep
    # their special handling.
    if name not in _RESERVED_UNSUPPORTED:
        custom_kind = _custom_section_kind(name)
        if custom_kind is not None:
            is_open, kind = custom_kind
            if is_open:
                label = value if value else kind.replace("_", " ").title()
                emit(SectionToken(label=label, kind=kind))
            else:
                emit(SectionToken(label="", kind="none"))
            return True

    # Chorus recall → annotated chorus SectionToken.
    if name == "chorus":
        emit(
            SectionToken(
                label="Chorus",
                kind="chorus",
                annotations=(("recall", "true"),),
            )
        )
        return True

    # Singer / voice context change.
    if name == "singer":
        emit(SingerToken(singer=value or ""))
        return True

    # Comment (never a section). Preserve verbatim, no CommentToken yet.
    if name in _COMMENT_KEYS:
        song_meta.setdefault("_comments", []).append((line_index, value or ""))
        return True

    # Chord definitions → reserved list.
    if name in _CHORD_DEF_KEYS:
        song_meta.setdefault("_chord_defs", []).append(value or "")
        return True

    # Reserved / out-of-scope directives → _unknown (never crash, no support).
    if name in _RESERVED_UNSUPPORTED:
        song_meta.setdefault("_unknown", []).append((line_index, stripped))
        return True

    # Custom {meta: key value...} → promote to top-level key.
    if name == "meta":
        _apply_meta_directive(value, song_meta, line_index, warnings)
        return True

    # Standard metadata directive → verbatim top-level string, last-wins.
    if name in STANDARD_META_KEYS:
        if name in song_meta:
            warnings.append(
                (line_index, f"duplicate {{{name}}} directive; last value wins")
            )
        song_meta[name] = value if value is not None else ""
        return True

    # Anything else with a recognizable {name...} shape → _unknown, never crash.
    song_meta.setdefault("_unknown", []).append((line_index, stripped))
    return True


def _apply_meta_directive(
    value: Optional[str],
    song_meta: dict,
    line_index: int,
    warnings: list,
) -> None:
    """Apply a ``{meta: key value...}`` directive to top-level ``song_meta``.

    ``{meta: tags rock, acoustic}`` → ``song_meta["tags"] = ["rock", "acoustic"]``
    (comma-separated multi-value); ``{meta: difficulty Beginner}`` →
    ``song_meta["difficulty"] = "Beginner"`` (single value). Collision rules: a
    custom key must not clobber a standard key or a ``_``-prefixed internal key;
    on collision, warn and keep the existing value. Keys starting with ``_`` are
    rejected.
    """
    if not value:
        warnings.append((line_index, "empty {meta:} directive ignored"))
        return
    parts = value.split(None, 1)
    key = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if not key:
        warnings.append((line_index, "empty {meta:} key ignored"))
        return
    if key.startswith("_"):
        warnings.append(
            (line_index, f"{{meta:}} key '{key}' starts with '_'; rejected")
        )
        return
    if key in STANDARD_META_KEYS:
        warnings.append(
            (
                line_index,
                f"{{meta:}} key '{key}' collides with standard directive; ignored",
            )
        )
        return

    if "," in rest:
        values = [v.strip() for v in rest.split(",") if v.strip()]
        song_meta[key] = values
    else:
        song_meta[key] = rest
