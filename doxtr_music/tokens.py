"""Intermediate token model for doxtr-music.

This module defines the *token* vocabulary that sits between raw input parsers
(ChordPro, chord-line, MusicXML, ABC) and the Docutils node builder:

    raw strings  ->  [Token]  ->  Docutils nodes  ->  HTML / LaTeX / EPUB

Locking this contract lets every input parser target one stable token
vocabulary and lets a single node builder feed all three output formats.

Design constraints (LOCKED for downstream chunks):

* **Chords are stored English-only.** ``ChordToken.text`` is parser-neutral
  English notation (``"Am"``, ``"G7"``, ``"C/E"``). i18n rendering (CHUNK-3-4)
  and transposition (CHUNK-3-2) never localize or mutate ``text``; they attach
  overlay data through ``annotations`` or resolve at render time.
* **``column`` is authoritative for alignment** — a 0-based, lyric-relative,
  *logical* (reading-order) offset into the emitted, de-bracketed lyric text of
  its line. RTL visual mirroring is a render-time concern (CHUNK-3-4) and is
  never encoded in a token.
* **Tokens are immutable.** All types are ``@dataclass(frozen=True)`` so they
  are hashable and safe to share. Engine steps (transpose/roman) return *new*
  tokens; nothing mutates in place.

Song-level metadata (``{title}``, ``{key}``, ``{tempo}``, ...) is **not** a
token. Parsers return ``(tokens, song_meta: dict)``; metadata is song-scoped and
flows to ``SongNode`` attributes + ``env.song_data``, never into the token
stream. Engine functions that need the root key take it explicitly, e.g.
``transpose(tokens, key=...)``.

This module imports nothing from Sphinx, Docutils, or ``doxtr_pdf_theme_core``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

__all__ = [
    "TokenKind",
    "ChordToken",
    "LyricToken",
    "SectionToken",
    "SingerToken",
    "BarToken",
    "LineBreakToken",
    "Token",
    "token_kind",
]


class TokenKind(Enum):
    """Discriminator for the concrete token types.

    ``CHORD``/``LYRIC``/``SECTION``/``LINEBREAK``/``SINGER``/``BAR`` each map to
    a concrete dataclass below. ``DIRECTIVE``/``COMMENT``/``MARKER`` are
    reserved placeholders for possible future token types; no current parser
    emits them and they have no concrete dataclass yet.
    """

    CHORD = "chord"
    LYRIC = "lyric"
    SECTION = "section"
    LINEBREAK = "linebreak"
    SINGER = "singer"
    BAR = "bar"
    # Reserved future placeholders (no emitter, no concrete type yet).
    DIRECTIVE = "directive"
    COMMENT = "comment"
    MARKER = "marker"


@dataclass(frozen=True)
class ChordToken:
    """A chord anchored to a lyric-relative column.

    ``text`` is the raw chord in parser-neutral English notation and is never
    localized or transposed in place. ``annotations`` is a reserved overlay for
    engine-derived per-chord data (e.g. ``(("transposed", "D"),)`` from
    CHUNK-3-2, ``(("roman", "IV"),)`` from CHUNK-3-3) attached without mutating
    ``text``. Keys and values must be hashable (str/int/tuple) so the frozen
    token stays hashable.
    """

    text: str
    column: int
    line: int = 0
    #: Reserved: populated only by timed notations (MusicXML/ABC); ``None`` for
    #: ChordPro/chord-line.
    duration: Optional[float] = None
    #: Reserved overlay of hashable ``(key, value)`` pairs. Reserved key
    #: namespace: ``"transposed"`` (CHUNK-3-2), ``"roman"`` (CHUNK-3-3).
    annotations: tuple = ()


@dataclass(frozen=True)
class LyricToken:
    """A lyric text fragment anchored to a lyric-relative column.

    ``annotations`` mirrors :class:`ChordToken` (reserved for import-derived
    per-syllable data in CHUNK-6-1/6-2 and any lyric-level overlay). Hashable
    keys/values only.
    """

    text: str
    column: int
    line: int = 0
    annotations: tuple = ()


@dataclass(frozen=True)
class SectionToken:
    """A section boundary marker.

    ``kind`` is the section subtype (``"verse"``/``"chorus"``/``"bridge"``/
    ``"section"``) mapping to LaTeX songbook environments. The reserved subtype
    ``"none"`` is a *return-to-unlabeled* marker: parsers emit
    ``SectionToken(label="", kind="none")`` to close the current section and
    return to top-level content (e.g. on ChordPro ``{end_of_verse}``). This
    lets the open-only section model in ``build_nodes`` (CHUNK-1-2) represent
    "content outside any section" without a dedicated close token.
    """

    label: str
    kind: str = "section"
    annotations: tuple = ()


@dataclass(frozen=True)
class SingerToken:
    """A stream token marking a singer/voice context change.

    Like :class:`SectionToken`, this marks "singer context changes to ``singer``
    here" at its position; the node builder opens/closes singer spans as it
    walks the stream (mirrors ChordPro's positional ``{singer:}`` semantics).
    Consumed by CHUNK-4-2.
    """

    singer: str
    annotations: tuple = ()


@dataclass(frozen=True)
class BarToken:
    """A reserved measure/bar boundary.

    Emitted only by timed-notation parsers (CHUNK-6-1/6-2); untimed builders
    ignore it. Empty payload aside from the reserved ``annotations`` overlay.
    """

    annotations: tuple = ()


@dataclass(frozen=True)
class LineBreakToken:
    """An explicit line boundary (also carries stanza-break semantics).

    Emitted between lyric lines.
    """

    annotations: tuple = ()


Token = Union[
    ChordToken,
    LyricToken,
    SectionToken,
    SingerToken,
    BarToken,
    LineBreakToken,
]

# Map each concrete token type to its discriminator. Kept in lockstep with the
# ``Token`` union and the concrete dataclasses above.
_TOKEN_KIND_MAP = {
    ChordToken: TokenKind.CHORD,
    LyricToken: TokenKind.LYRIC,
    SectionToken: TokenKind.SECTION,
    SingerToken: TokenKind.SINGER,
    BarToken: TokenKind.BAR,
    LineBreakToken: TokenKind.LINEBREAK,
}


def token_kind(tok: Token) -> TokenKind:
    """Return the :class:`TokenKind` for a concrete token instance.

    Uses a ``{type: TokenKind}`` map (no ``isinstance`` chains). Raises
    ``TypeError`` for anything that is not a known concrete token type.
    """

    try:
        return _TOKEN_KIND_MAP[type(tok)]
    except KeyError:
        raise TypeError(f"not a doxtr-music token: {tok!r}") from None
