"""ABC notation importer — ``parse_abc(text) -> (tokens, song_meta)``.

A **pure** parser (no Sphinx/Docutils/``doxtr_pdf_theme_core`` import,
CLI-reusable) that converts ABC notation text into the locked doxtr-music token
vocabulary (:mod:`doxtr_music.tokens`), converging on the same
``(tokens, song_meta)`` contract every front-end targets (front-end
convergence, CHUNK-3-1 / CHUNK-6-1). The resulting tokens flow through the
ordinary ``ImportDirectiveBase`` → ``SongDirectiveBase`` pipeline and
``build_nodes``, so an imported tune renders **exactly like a** ``.. song::``
in HTML/LaTeX/EPUB.

Scope (LOCKED — CHUNK-6-2 import fidelity)
------------------------------------------

ABC notation is an information-field header (``X:`` tune number, ``T:`` title,
``C:`` composer, ``K:`` key, ``M:`` meter, ``Q:`` tempo, ``L:`` unit note
length, ``w:`` lyrics-aligned-to-notes) followed by a tune body of
notes/bars. v1 imports the **chord + lyric layer**:

* quoted chord symbols ``"Am"`` before notes → English chord text
  (:class:`ChordToken`);
* ``w:`` lyric lines aligned to the melody → lyric tokens (via the shared
  ``tokenize_lyric_line`` seam);
* ``|`` bar lines → :class:`BarToken` (**metadata-only**, per CHUNK-6-1 — dropped
  by ``build_nodes``, rendered by no builder);
* header fields → ``song_meta`` (``K:`` feeds transpose/roman).

Full melody/rhythm rendering (pitches/durations as notated music) is **out of
scope** for v1.

**Bar/duration metadata-only** (inherited invariant from CHUNK-6-1): ``BarToken``
+ ``ChordToken.duration`` populate the token stream but are dropped by
``build_nodes`` and rendered by no builder — imported ABC renders its chords +
lyrics, never a bar-node error. Repeat bars (``:|``/``|:``) carry a repeat hint
via ``BarToken.annotations`` (best-effort). ``duration`` is left ``None`` in v1
(``L:`` × per-note multiplier is a documented deferral).

Chords vs text annotations (LOCKED)
-----------------------------------

A ``"..."`` quoted string beginning with ``^``/``_``/``<``/``>``/``@`` is a
**positioned text annotation** (e.g. ``"^Slowly"``), *not* a chord → routed to
``_warnings`` (never into the chord stream). All other ``"..."`` strings are
stored **verbatim as English chord text** (ABC chord symbols are English, incl.
slash ``"C/E"``). :func:`doxtr_music.engine.theory.parse_chord` is
**validation-only**: an unrecognized result → ``_warnings`` and the text is kept
verbatim, never dropped (CHUNK-3-2 graceful contract).

Security / robustness
---------------------

ABC is plain text — no XML-bomb/entity attack class. The parser scans linearly
(no catastrophic-backtracking regex in the ``w:``-alignment logic) and degrades
gracefully: malformed ABC yields ``_warnings`` + a partial/empty token stream,
never a crash.
"""

from __future__ import annotations

from typing import Optional

from doxtr_music.parsers._lyrics import tokenize_lyric_line
from doxtr_music.tokens import (
    BarToken,
    ChordToken,
    LineBreakToken,
    LyricToken,
    SectionToken,
    Token,
)

__all__ = ["parse_abc"]

#: ABC information-field letter → ``song_meta`` key. ``X`` (tune number) is used
#: only for tune-boundary detection and is dropped (not a rendered field).
#: A second ``T:`` maps to ``subtitle`` (handled specially below).
_FIELD_TO_META = {
    "T": "title",
    "C": "artist",
    "K": "key",
    "M": "time",
    "Q": "tempo",
    "L": "_unit_note_length",  # internal: only used if duration is attempted
}

#: Leading characters that mark a ``"..."`` quoted string as a positioned text
#: annotation (ABC decoration/annotation syntax) rather than a chord symbol.
_ANNOTATION_LEADERS = frozenset("^_<>@")

#: Repeat-bar tokens whose hint is carried on ``BarToken.annotations``.
_REPEAT_BARS = {
    ":|": "repeat-end",
    "|:": "repeat-start",
    ":|:": "repeat-both",
    "::": "repeat-both",
}


def parse_abc(text: str) -> tuple:
    """Parse ABC ``text`` into ``(tokens, song_meta)``.

    Pure function (no Sphinx import). Never raises on malformed input: a
    pathological or unparseable tune yields ``([], {"_warnings": [...]})`` so the
    directive renders nothing and the reporter surfaces the note.

    Multi-tune files (multiple ``X:``) import the **first tune only** plus a
    ``_warnings`` note. Multi-verse ``w:`` (and ``+:`` continuation) lines import
    the **first verse only** plus a ``_warnings`` note.

    Returns a list of :class:`~doxtr_music.tokens.Token` and a ``song_meta`` dict
    sharing the CHUNK-1-3 shape (``_``-prefixed internals like ``_warnings``).
    """
    song_meta: dict = {}
    warnings = song_meta.setdefault("_warnings", [])

    if text is None or not text.strip():
        return [], song_meta

    lines = text.splitlines()

    # --- pass 1: split off the first tune (multi-tune = first + warn) -------
    tune_lines, extra_tune = _first_tune(lines)
    if extra_tune:
        warnings.append((0, "multiple tunes (X:) in ABC file; importing the first only"))

    # --- pass 2: pair each body line with its following w: verse line -------
    #
    # A ``w:`` line applies to the immediately preceding music line. We walk the
    # tune, extracting header fields into song_meta and grouping music lines with
    # their (first) w: line.
    tokens: list = []
    line_index = 0
    pending_music: Optional[str] = None
    saw_first_title = False
    multiverse_warned = False

    def flush(music: Optional[str], lyric: Optional[str]) -> None:
        nonlocal line_index
        if music is None:
            return
        line_tokens = _tokenize_music_line(music, lyric, line_index, warnings)
        if line_tokens:
            if tokens:
                tokens.append(LineBreakToken())
            tokens.extend(line_tokens)
            line_index += 1

    i = 0
    n = len(tune_lines)
    while i < n:
        raw = tune_lines[i]
        stripped = raw.strip()
        i += 1

        if not stripped or stripped.startswith("%"):
            # Blank line / comment: a blank line is a stanza/tune-structure
            # break; flush any pending music first.
            flush(pending_music, None)
            pending_music = None
            continue

        field = _information_field(stripped)
        if field is not None:
            letter, value = field
            if letter == "w":
                # Lyric line applies to the pending music line.
                if pending_music is None:
                    warnings.append((0, "w: lyric line with no preceding music line; ignored"))
                    continue
                # Look ahead for additional w:/+: verses on this music line.
                verse_count = 1
                while i < n:
                    nxt = tune_lines[i].strip()
                    nf = _information_field(nxt)
                    if nf is not None and nf[0] in ("w", "+"):
                        verse_count += 1
                        i += 1
                    else:
                        break
                if verse_count > 1 and not multiverse_warned:
                    warnings.append((0, "multiple w: verses; importing the first verse only"))
                    multiverse_warned = True
                flush(pending_music, value)
                pending_music = None
                continue
            if letter == "+":
                # Bare +: continuation with no active w: — ignore.
                continue
            # A header/inline information field → song_meta.
            _apply_field(letter, value, song_meta, warnings, saw_first_title)
            if letter == "T":
                saw_first_title = True
            continue

        # A music (body) line. Flush any prior music that had no lyric.
        flush(pending_music, None)
        pending_music = raw

    # Flush trailing music line (no lyric).
    flush(pending_music, None)

    # ``_unit_note_length`` is an internal field; drop it from rendered meta but
    # keep it out of the public surface (it never fed duration in v1).
    song_meta.pop("_unit_note_length", None)

    return tokens, song_meta


# ---------------------------------------------------------------------------
# Tune / field splitting
# ---------------------------------------------------------------------------

def _first_tune(lines: list) -> tuple:
    """Return ``(first_tune_lines, had_extra_tune)``.

    A tune begins at an ``X:`` field. If the file has no ``X:`` at all, the whole
    input is treated as a single (header-less) tune. A second ``X:`` starts the
    next tune (dropped in v1).
    """
    x_indices = [
        idx for idx, ln in enumerate(lines)
        if _information_field(ln.strip()) is not None
        and _information_field(ln.strip())[0] == "X"
    ]
    if not x_indices:
        return lines, False
    start = x_indices[0]
    end = x_indices[1] if len(x_indices) > 1 else len(lines)
    return lines[start:end], len(x_indices) > 1


def _information_field(stripped: str) -> Optional[tuple]:
    """Return ``(letter, value)`` if ``stripped`` is an ABC information field.

    An information field is ``X:value`` — a single letter (or ``+`` continuation)
    followed by ``:``. Returns ``None`` for a music/body line. The letter is kept
    as-is (case-sensitive: ABC fields are single upper/lower letters; ``w`` is
    lyrics, ``W`` is unaligned words — only ``w`` is honored here).
    """
    if len(stripped) >= 2 and stripped[1] == ":":
        letter = stripped[0]
        if letter.isalpha() or letter == "+":
            return letter, stripped[2:].strip()
    return None


def _apply_field(
    letter: str,
    value: str,
    song_meta: dict,
    warnings: list,
    saw_first_title: bool,
) -> None:
    """Apply one information field to ``song_meta`` (CHUNK-1-3 shape, verbatim strings).

    ``T:`` → ``title`` (a second ``T:`` → ``subtitle``); ``C:`` → ``artist``;
    ``K:`` → ``key`` (feeds transpose/roman); ``M:`` → ``time``; ``Q:`` → ``tempo``;
    ``L:`` → internal ``_unit_note_length``; ``X:`` (tune number) is dropped.
    Unknown fields are ignored (no crash).
    """
    if letter == "X":
        return  # tune number — boundary detection only, not rendered
    if letter == "T":
        if saw_first_title:
            if "subtitle" not in song_meta:
                song_meta["subtitle"] = value
            return
        song_meta["title"] = value
        return
    key = _FIELD_TO_META.get(letter)
    if key is None:
        return  # unknown/out-of-scope field, ignored
    if key not in song_meta:
        song_meta[key] = value


# ---------------------------------------------------------------------------
# Music line → tokens (chords + w:-aligned lyrics; the core deliverable)
# ---------------------------------------------------------------------------

def _tokenize_music_line(
    music: str,
    lyric: Optional[str],
    line_index: int,
    warnings: list,
) -> list:
    """Convert one ABC body line (+ optional ``w:`` verse) into anchored tokens.

    ``w:`` alignment algorithm (LOCKED — CHUNK-6-2):

    1. **Note-event enumeration** — walk ``music`` and enumerate *note events*:
       a bare note, an accidental-prefixed note (``^``/``_``/``=``), and a
       ``[CEG]`` note-chord each count as **one** event. Grace notes ``{...}``,
       decorations (``!...!`` / ``.``), spaces, and ``|`` bars are **skipped**
       (not events). A quoted ``"chord"`` attaches to the *next* note event; a
       trailing chord with no following note anchors at end-of-line.
    2. **``w:`` syllable stream** — tokenize ``lyric`` into syllables: ``-``
       splits a word into syllables (a within-word syllable break, *not*
       "continue"); ``_`` extends the previous syllable across the next note
       (hold — consumes a note event with no new syllable); ``*`` = one blank
       syllable (skip a note); ``|`` advances to the next bar (alignment
       checkpoint); whitespace separates words.
    3. **Note→syllable pairing** — pair note events with syllables left-to-right
       honoring ``_``/``*``/``|``; each note event gets the syllable over it.
    4. **Synthetic lyric line + column** — join paired syllables into a synthetic
       lyric line (``-``-joined syllables reconstruct a word; blank/``*`` → a
       space gap), tokenize it via the shared ``tokenize_lyric_line`` seam, and
       set each chord's lyric-relative codepoint ``column`` to the offset of the
       syllable over the note it precedes. Chords over note events without a
       syllable (instrumental/melisma) anchor over an empty/space position.
    """
    events, chord_anchors, bar_tokens = _scan_music(music, warnings)

    syllables = _scan_lyric_syllables(lyric) if lyric else []

    # Pair note events with syllables left-to-right, honoring hold/blank/bar.
    _assign_syllables(events, syllables)

    # Build the synthetic lyric line + per-event columns.
    synthetic_line, end_col = _build_synthetic_line(events)

    out: list = []

    # Emit chords at their anchored columns.
    for ev_index, chord_text in chord_anchors:
        if ev_index < 0 or ev_index >= len(events):
            col = end_col
        else:
            col = events[ev_index]["column"]
        out.append(
            ChordToken(text=chord_text, column=col, line=line_index, duration=None)
        )

    # Emit lyric word tokens via the shared seam.
    if synthetic_line.strip():
        for lyric_tok in tokenize_lyric_line(synthetic_line, line=line_index):
            out.append(lyric_tok)

    # Bars are metadata-only (dropped by build_nodes); emit after the render
    # tokens so the line's visible content is intact.
    out.extend(bar_tokens)

    return out


def _scan_music(music: str, warnings: list) -> tuple:
    """Linear scan of a music line → ``(events, chord_anchors, bar_tokens)``.

    * ``events`` — list of ``{"syllable": str|None, "column": int}`` note events.
    * ``chord_anchors`` — list of ``(event_index_or_-1, chord_text)``; ``-1``
      means "anchor at end-of-line" (trailing chord with no following note).
    * ``bar_tokens`` — list of :class:`BarToken` (metadata-only), one per bar
      line, with a repeat hint in ``annotations`` where applicable.

    Note-event rule (LOCKED): a bare note, an accidental-prefixed note, and a
    ``[...]`` note-chord each count as one event; grace notes ``{...}``,
    decorations (``!...!`` / leading ``.``), ``"chords"``, spaces and ``|`` bars
    are not events.
    """
    events: list = []
    chord_anchors: list = []
    bar_tokens: list = []
    pending_chords: list = []  # chords seen before the next note event

    i = 0
    n = len(music)
    note_letters = set("ABCDEFGabcdefg")
    rest_letters = set("zZxX")

    while i < n:
        ch = music[i]

        # Quoted chord symbol or text annotation.
        if ch == '"':
            end = music.find('"', i + 1)
            if end == -1:
                # Unterminated quote → consume to EOL, warn.
                warnings.append((0, "unterminated quoted chord in ABC line; ignored"))
                break
            inner = music[i + 1:end]
            i = end + 1
            if inner and inner[0] in _ANNOTATION_LEADERS:
                # Positioned text annotation, not a chord — never a chord token.
                warnings.append((0, "text annotation %r excluded from chords" % inner))
            elif inner.strip():
                chord_text = inner.strip()
                _validate_chord(chord_text, warnings)
                pending_chords.append(chord_text)
            continue

        # Grace-note group {...} — skipped (not a note event).
        if ch == "{":
            end = music.find("}", i + 1)
            i = (end + 1) if end != -1 else n
            continue

        # Decoration group !...! — skipped.
        if ch == "!":
            end = music.find("!", i + 1)
            i = (end + 1) if end != -1 else n
            continue

        # Note-chord [CEG] — one event.
        if ch == "[":
            end = music.find("]", i + 1)
            i = (end + 1) if end != -1 else n
            _push_event(events, chord_anchors, pending_chords)
            pending_chords = []
            continue

        # Bar lines (incl. repeats). Order matters: check longer tokens first.
        if ch in "|:[]":
            bar, adv = _match_bar(music, i)
            if bar is not None:
                bar_tokens.append(_bar_token(bar))
                i += adv
                continue

        # Accidental prefix (^ _ =) directly before a note → part of the note event.
        if ch in "^_=":
            j = i + 1
            # Allow doubled accidentals (^^, __).
            while j < n and music[j] in "^_=":
                j += 1
            if j < n and music[j] in note_letters:
                _push_event(events, chord_anchors, pending_chords)
                pending_chords = []
                i = j + 1
                i = _skip_note_tail(music, i, n)
                continue
            # Stray accidental — skip it.
            i = j
            continue

        # Bare note letter → one event.
        if ch in note_letters:
            _push_event(events, chord_anchors, pending_chords)
            pending_chords = []
            i += 1
            i = _skip_note_tail(music, i, n)
            continue

        # Rest (z/x/Z/X) — a note-position placeholder; counts as an event so a
        # ``*`` blank syllable / instrumental gap lines up, but carries no chord
        # unless one is pending.
        if ch in rest_letters:
            _push_event(events, chord_anchors, pending_chords)
            pending_chords = []
            i += 1
            i = _skip_note_tail(music, i, n)
            continue

        # Anything else (spaces, decorations '.', broken-rhythm '<'/'>', ties,
        # tuplet markers, etc.) is skipped.
        i += 1

    # Trailing chords with no following note anchor at end-of-line.
    for ct in pending_chords:
        chord_anchors.append((-1, ct))

    return events, chord_anchors, bar_tokens


def _push_event(events: list, chord_anchors: list, pending_chords: list) -> None:
    """Append a new note event and bind any pending chords to it."""
    events.append({"syllable": None, "column": 0})
    idx = len(events) - 1
    for ct in pending_chords:
        chord_anchors.append((idx, ct))


def _skip_note_tail(music: str, i: int, n: int) -> int:
    """Advance past a note's octave/length/tie tail (``,'`` octaves, digits, ``/``, ``-``).

    Consumes the characters that belong to the just-scanned note but do not start
    a new note event: octave marks ``,``/``'``, duration digits and ``/``, and a
    trailing tie ``-`` (a tie binds notes; it is not a lyric syllable break here).
    """
    while i < n and music[i] in ",'0123456789/-":
        i += 1
    return i


def _match_bar(music: str, i: int) -> tuple:
    """Match a bar token at position ``i`` → ``(bar_text, advance)`` or ``(None, 0)``.

    Recognizes (longest first) ``:|:``, ``::``, ``|:``, ``:|``, ``||``, ``|]``,
    ``[|``, ``|``. A lone ``[`` (note-chord opener) is handled before this call,
    so ``[|`` is unambiguous here.
    """
    for tok in (":|:", "::", "|:", ":|", "||", "|]", "[|", "|"):
        if music.startswith(tok, i):
            return tok, len(tok)
    return None, 0


def _bar_token(bar: str) -> BarToken:
    """Build a metadata-only :class:`BarToken`; repeat hint in ``annotations``."""
    hint = _REPEAT_BARS.get(bar)
    if hint:
        return BarToken(annotations=(("repeat", hint),))
    return BarToken()


def _validate_chord(chord_text: str, warnings: list) -> None:
    """Validation-only chord check (CHUNK-3-2 graceful contract).

    An unrecognized chord → ``_warnings`` and the text is kept verbatim (never
    dropped). Validation must never be fatal.
    """
    try:
        from doxtr_music.engine.theory import parse_chord

        if parse_chord(chord_text) is None:
            warnings.append((0, "unrecognized chord %r kept verbatim" % chord_text))
    except Exception:  # pragma: no cover - validation must never be fatal
        pass


# ---------------------------------------------------------------------------
# w: syllable stream + note→syllable pairing
# ---------------------------------------------------------------------------

def _scan_lyric_syllables(lyric: str) -> list:
    """Tokenize a ``w:`` line into an ordered syllable stream.

    Each element is a dict ``{"text": str, "word_end": bool, "kind": str}`` where
    ``kind`` is one of ``"syllable"``, ``"hold"`` (``_``), ``"blank"`` (``*``) or
    ``"bar"`` (``|``). ``word_end`` is ``True`` when the syllable terminates a
    word (a following space is reconstructed downstream).

    ABC ``w:`` rules (LOCKED): ``-`` splits a word into syllables (within-word
    break, so the preceding syllable does *not* end the word); ``_`` holds the
    previous syllable over the next note; ``*`` is a blank syllable (skip a note);
    ``|`` is a bar checkpoint; whitespace separates words. Linear scan (no
    catastrophic backtracking).
    """
    syllables: list = []
    i = 0
    n = len(lyric)
    while i < n:
        ch = lyric[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "_":
            syllables.append({"text": "", "word_end": False, "kind": "hold"})
            i += 1
            continue
        if ch == "*":
            syllables.append({"text": "", "word_end": True, "kind": "blank"})
            i += 1
            continue
        if ch == "|":
            syllables.append({"text": "", "word_end": False, "kind": "bar"})
            i += 1
            continue
        # A syllable runs until whitespace, '-', '_', '*' or '|'. A trailing '-'
        # is a within-word break (the word continues); no '-' before a break or
        # EOL means the word ends here.
        start = i
        while i < n and lyric[i] not in " \t-_*|":
            i += 1
        text = lyric[start:i]
        # Handle a within-word break marker.
        if i < n and lyric[i] == "-":
            # '-' → the current syllable is followed by more syllables of the
            # same word (no space). Skip the '-' and any following whitespace so
            # "sylla- ble" and "sylla-ble" behave identically.
            syllables.append({"text": text, "word_end": False, "kind": "syllable"})
            i += 1
            while i < n and lyric[i] in " \t":
                i += 1
            continue
        # Word ends here (next is space/EOL/hold/blank/bar).
        syllables.append({"text": text, "word_end": True, "kind": "syllable"})
    return syllables


def _assign_syllables(events: list, syllables: list) -> None:
    """Pair note events with syllables left-to-right, honoring ``_``/``*``/``|``.

    Walks note events and syllable stream in lockstep:

    * a ``"hold"`` (``_``) consumes an event with no new syllable (melisma
      continuation);
    * a ``"blank"`` (``*``) consumes an event, leaving it lyric-less;
    * a ``"bar"`` (``|``) is an alignment checkpoint — it does not consume an
      event, it just advances the syllable cursor;
    * a plain syllable is placed over the current event and both advance.

    Note events beyond the syllable stream stay lyric-less (instrumental tail).
    """
    ev = 0
    for syl in syllables:
        if ev >= len(events):
            break
        kind = syl["kind"]
        if kind == "bar":
            # Checkpoint only — does not consume a note event.
            continue
        if kind in ("hold", "blank"):
            # Consume an event with no visible syllable.
            events[ev]["syllable"] = ""
            events[ev]["word_end"] = True if kind == "blank" else False
            ev += 1
            continue
        # Plain syllable.
        events[ev]["syllable"] = syl["text"]
        events[ev]["word_end"] = syl["word_end"]
        ev += 1


def _build_synthetic_line(events: list) -> tuple:
    """Join note-event syllables into a synthetic lyric line + set event columns.

    ``-``-joined syllables (``word_end=False``) reconstruct a word with no gap; a
    word-ending syllable is followed by a single space; a lyric-less event
    (instrumental / blank) contributes a single spacer so event columns stay
    distinct. Returns ``(synthetic_line, end_column)``.
    """
    parts: list = []
    cursor = 0
    for ev in events:
        ev["column"] = cursor
        syl = ev.get("syllable")
        if syl:
            parts.append(syl)
            cursor += len(syl)
            if ev.get("word_end", True):
                parts.append(" ")
                cursor += 1
        else:
            # Lyric-less event (instrumental note / blank / hold): a single
            # spacer keeps event columns distinct.
            parts.append(" ")
            cursor += 1
    synthetic_line = "".join(parts)
    return synthetic_line, len(synthetic_line)
