"""MusicXML importer — ``parse_musicxml(text) -> (tokens, song_meta)``.

A **pure** parser (no Sphinx/Docutils/``doxtr_pdf_theme_core`` import,
CLI-reusable) that converts *uncompressed* MusicXML text into the locked
doxtr-music token vocabulary (:mod:`doxtr_music.tokens`), converging on the same
``(tokens, song_meta)`` contract every front-end targets (front-end convergence,
CHUNK-3-1 / CHUNK-6-1). The resulting tokens flow through the ordinary
``ImportDirectiveBase`` → ``SongDirectiveBase`` pipeline and ``build_nodes``, so
an imported score renders **exactly like a** ``.. song::`` in HTML/LaTeX/EPUB.

Scope (LOCKED — CHUNK-6-1 import fidelity)
------------------------------------------

v1 imports the **chord + lyric layer** of a score: chord symbols
(``<harmony>``), lyrics (``<lyric>``), best-effort section structure, and
**metadata-only** bar boundaries (``BarToken`` at each ``<measure>``) and note
durations (``ChordToken.duration``). Full rhythmic/score fidelity (beaming,
voices, dynamics, staves) is out of scope and ignored with a ``_warnings`` note.

**Bar/duration are metadata-only in v1 (LOCKED — stated for 6-1/6-2):**
``BarToken`` and ``ChordToken.duration`` are emitted on the token stream but are
dropped by ``build_nodes`` and rendered by **no** builder. There is no
``BarNode`` and no builder amendment — an imported song with bars/durations
renders its chords + lyrics correctly and never hits an unhandled-node error
(the tokens are dropped pre-node). They are forward-compatibility payload for a
future timed-rendering chunk.

**``.mxl`` (compressed) is deferred (LOCKED):** v1 accepts only *uncompressed*
``.xml``/``.musicxml`` text (keeps the ``str`` loader contract intact and
sidesteps the zip-bomb surface). ``.mxl`` input produces a clear ``_warnings``
note.

XML security posture (LOCKED — definite, not "if available")
------------------------------------------------------------

Imported MusicXML is **untrusted input** (a real XXE / billion-laughs /
entity-expansion surface). ``defusedxml`` is a **hard requirement of the import
feature**, declared as the optional-dependency extra ``doxtr-music[musicxml]``
(never in ``install_requires``); :func:`parse_musicxml` imports it lazily with a
clear actionable error if absent. ``defusedxml`` rejects DTDs / external
entities / entity bombs by default. There is no stdlib fallback (stdlib
``xml.etree`` exposes no switch to disable entity resolution).
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

__all__ = ["parse_musicxml", "KIND_TO_QUALITY"]


#: MusicXML ``<kind>`` value → English chord-quality suffix (the fidelity-
#: critical surface — inlined, not deferred). Unmapped kinds fall back to a
#: best-effort text derivation + a ``_warnings`` note (never a silently wrong
#: chord). ``none`` is the explicit "no chord" marker → ``N.C.``.
KIND_TO_QUALITY = {
    "major": "",
    "minor": "m",
    "dominant": "7",
    "major-seventh": "maj7",
    "minor-seventh": "m7",
    "half-diminished": "m7b5",
    "diminished": "dim",
    "diminished-seventh": "dim7",
    "augmented": "aug",
    "suspended-fourth": "sus4",
    "suspended-second": "sus2",
    "dominant-ninth": "9",
    "major-ninth": "maj9",
    "minor-ninth": "m9",
    "dominant-11th": "11",
    "dominant-13th": "13",
    "major-sixth": "6",
    "minor-sixth": "m6",
    "power": "5",
    "none": "N.C.",
}

#: ``<syllabic>`` values that continue a word (no space before the next
#: syllable). ``begin``/``middle`` mean "more of this word follows"; ``end`` and
#: ``single`` terminate a word.
_SYLLABIC_CONTINUE = frozenset({"begin", "middle"})

#: ``<degree-type>`` → textual glue for a best-effort ``<degree>`` suffix.
_DEGREE_PREFIX = {"add": "add", "alter": "", "subtract": "no"}


def parse_musicxml(text: str) -> tuple:
    """Parse uncompressed MusicXML ``text`` into ``(tokens, song_meta)``.

    Pure function (no Sphinx import). Never raises on malformed input: an
    unparseable document yields ``([], {"_warnings": [...]})`` so the directive
    renders nothing and the reporter surfaces the note. ``defusedxml`` is
    required (raises a clear actionable ``RuntimeError`` if missing).

    Returns a list of :class:`~doxtr_music.tokens.Token` and a ``song_meta``
    dict sharing the CHUNK-1-3 shape (``_``-prefixed internals like
    ``_warnings``).
    """
    song_meta: dict = {}
    warnings = song_meta.setdefault("_warnings", [])

    if text is None or not text.strip():
        return [], song_meta

    # Compressed .mxl is a ZIP container, not text; it arrives here only if the
    # loader was bypassed, but guard anyway (deferred to a future chunk).
    if text.lstrip().startswith("PK\x03\x04") or text[:2] == "PK":
        warnings.append(
            (0, "compressed MusicXML (.mxl) is not supported in v1; "
                "unzip to .musicxml")
        )
        return [], song_meta

    root = _parse_xml(text, warnings)
    if root is None:
        return [], song_meta

    _extract_metadata(root, song_meta)

    tokens: list = []
    tag = _localname(root.tag)
    if tag == "score-timewise":
        measures = _timewise_measures(root, warnings)
    elif tag == "score-partwise":
        measures = _partwise_measures(root, warnings)
    else:
        warnings.append(
            (0, "unrecognized MusicXML root <%s>; expected score-partwise or "
                "score-timewise" % tag)
        )
        return [], song_meta

    _emit_measures(measures, tokens, warnings)
    return tokens, song_meta


# ---------------------------------------------------------------------------
# XML loading (security-critical)
# ---------------------------------------------------------------------------

def _parse_xml(text: str, warnings: list):
    """Parse ``text`` to an element tree root via ``defusedxml``; ``None`` on error.

    ``defusedxml`` is a hard requirement of the import feature (optional-dep
    ``doxtr-music[musicxml]``). Missing → actionable ``RuntimeError``. A
    malformed document / entity attack → ``_warnings`` + ``None`` (never raise
    past this function, so the build never crashes on untrusted input).
    """
    try:
        from defusedxml.ElementTree import fromstring as _fromstring
    except ImportError:  # pragma: no cover - env has defusedxml
        raise RuntimeError(
            "MusicXML import requires the 'defusedxml' package; install it with "
            "`pip install doxtr-music[musicxml]`."
        )

    try:
        return _fromstring(text)
    except Exception as exc:  # noqa: BLE001 - any parse/entity failure is non-fatal
        warnings.append((0, "could not parse MusicXML: %s" % exc))
        return None


def _localname(tag: str) -> str:
    """Strip an XML namespace ``{ns}local`` prefix (MusicXML is usually un-namespaced)."""
    if tag and tag[0] == "{":
        return tag.split("}", 1)[1]
    return tag


def _find(el, name):
    """First direct child with local name ``name`` (namespace-insensitive)."""
    for child in el:
        if _localname(child.tag) == name:
            return child
    return None


def _findall(el, name):
    """All direct children with local name ``name`` (namespace-insensitive)."""
    return [child for child in el if _localname(child.tag) == name]


def _text(el):
    """Stripped text of ``el`` or ``""`` when ``el`` is ``None``/empty."""
    if el is None or el.text is None:
        return ""
    return el.text.strip()


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def _extract_metadata(root, song_meta: dict) -> None:
    """Populate ``song_meta`` title/artist/lyricist/key from score headers.

    ``<work><work-title>`` → title; ``<identification><creator>`` composer →
    artist, lyricist → lyricist; the first ``<attributes><key><fifths>`` found
    → ``song_meta['key']`` (feeds roman analysis, CHUNK-3-3). Shares the
    CHUNK-1-3 ``song_meta`` shape (verbatim string values).
    """
    work = _find(root, "work")
    if work is not None:
        title = _text(_find(work, "work-title"))
        if title:
            song_meta["title"] = title
    # <movement-title> is a common alternative title carrier.
    if "title" not in song_meta:
        mv = _text(_find(root, "movement-title"))
        if mv:
            song_meta["title"] = mv

    ident = _find(root, "identification")
    if ident is not None:
        for creator in _findall(ident, "creator"):
            ctype = (creator.get("type") or "").strip().lower()
            value = _text(creator)
            if not value:
                continue
            if ctype == "composer" and "artist" not in song_meta:
                song_meta["artist"] = value
            elif ctype in ("lyricist", "poet") and "lyricist" not in song_meta:
                song_meta["lyricist"] = value

    key_name = _first_key(root)
    if key_name and "key" not in song_meta:
        song_meta["key"] = key_name


#: Circle-of-fifths → major key spelling (``<fifths>`` count → tonic).
_FIFTHS_TO_MAJOR = {
    -7: "Cb", -6: "Gb", -5: "Db", -4: "Ab", -3: "Eb", -2: "Bb", -1: "F",
    0: "C", 1: "G", 2: "D", 3: "A", 4: "E", 5: "B", 6: "F#", 7: "C#",
}
#: Circle-of-fifths → minor key spelling (relative minor of the same signature).
_FIFTHS_TO_MINOR = {
    -7: "Abm", -6: "Ebm", -5: "Bbm", -4: "Fm", -3: "Cm", -2: "Gm", -1: "Dm",
    0: "Am", 1: "Em", 2: "Bm", 3: "F#m", 4: "C#m", 5: "G#m", 6: "D#m", 7: "A#m",
}


def _first_key(root) -> Optional[str]:
    """Find the first ``<key>`` in any part/measure and spell it as a key name.

    Reads ``<fifths>`` (+ optional ``<mode>``) and maps it through the
    circle-of-fifths tables. Returns e.g. ``"G"`` / ``"Em"`` / ``"Bb"``; ``None``
    when no key signature is present.
    """
    for key_el in root.iter():
        if _localname(key_el.tag) != "key":
            continue
        fifths_txt = _text(_find(key_el, "fifths"))
        if not fifths_txt:
            continue
        try:
            fifths = int(fifths_txt)
        except ValueError:
            continue
        mode = _text(_find(key_el, "mode")).lower()
        table = _FIFTHS_TO_MINOR if mode == "minor" else _FIFTHS_TO_MAJOR
        return table.get(fifths)
    return None


# ---------------------------------------------------------------------------
# Measure collection (partwise vs timewise)
# ---------------------------------------------------------------------------

def _partwise_measures(root, warnings: list):
    """Return the chosen part's ``<measure>`` list for a score-partwise root.

    Picks the part carrying ``<harmony>``/``<lyric>`` (or the first part) and
    warns on multi-part ambiguity.
    """
    parts = _findall(root, "part")
    if not parts:
        warnings.append((0, "MusicXML has no <part>; nothing to import"))
        return []
    chosen = _choose_part(parts, warnings)
    return _findall(chosen, "measure")


def _timewise_measures(root, warnings: list):
    """Return a normalized ``<measure>`` list for a score-timewise root.

    Timewise nests ``<measure>`` above ``<part>``; we flatten to the chosen
    part's per-measure element groups so the downstream walk is identical to
    partwise. Each returned element is a synthetic container whose children are
    the chosen part's children for that measure (preserving ``number``).
    """
    outer_measures = _findall(root, "measure")
    if not outer_measures:
        warnings.append((0, "timewise MusicXML has no <measure>; nothing to import"))
        return []

    # Determine part ids present, pick one (prefer harmony/lyric carrier).
    part_measures: dict = {}
    order: list = []
    for m in outer_measures:
        for part in _findall(m, "part"):
            pid = part.get("id") or ""
            if pid not in part_measures:
                part_measures[pid] = []
                order.append(pid)
            part_measures[pid].append((m.get("number"), part))

    if not order:
        warnings.append((0, "timewise MusicXML has no <part> inside <measure>"))
        return []

    chosen_pid = _choose_part_id(part_measures, order, warnings)

    # Build lightweight measure proxies (an object exposing .get('number') and
    # iteration over the part's children).
    proxies = []
    for number, part in part_measures[chosen_pid]:
        proxies.append(_MeasureProxy(number, list(part)))
    return proxies


class _MeasureProxy:
    """Adapter presenting a timewise part-slice as a partwise ``<measure>``.

    Exposes ``.get("number")`` and iteration over the measure's child elements,
    so :func:`_emit_measures` walks partwise and timewise identically.
    """

    __slots__ = ("_number", "_children")

    def __init__(self, number, children):
        self._number = number
        self._children = children

    def get(self, key, default=None):
        if key == "number":
            return self._number
        return default

    def __iter__(self):
        return iter(self._children)


def _score_of(part_children) -> int:
    """Heuristic relevance score: +2 per <harmony>, +1 per note carrying <lyric>."""
    score = 0
    for child in part_children:
        name = _localname(child.tag)
        if name == "harmony":
            score += 2
        elif name == "note" and _find(child, "lyric") is not None:
            score += 1
    return score


def _choose_part(parts, warnings: list):
    """Pick the most chord/lyric-relevant ``<part>``; warn on ambiguity."""
    if len(parts) == 1:
        return parts[0]
    scored = [(_score_of(list(p.iter())), i, p) for i, p in enumerate(parts)]
    scored.sort(key=lambda t: (-t[0], t[1]))
    best_score = scored[0][0]
    if best_score == 0:
        warnings.append(
            (0, "multiple parts, none carrying <harmony>/<lyric>; using the first")
        )
        return parts[0]
    warnings.append(
        (0, "multiple parts; using the one carrying chords/lyrics")
    )
    return scored[0][2]


def _choose_part_id(part_measures: dict, order: list, warnings: list) -> str:
    """Timewise analog of :func:`_choose_part` keyed by part id."""
    if len(order) == 1:
        return order[0]
    scored = []
    for i, pid in enumerate(order):
        children = []
        for _num, part in part_measures[pid]:
            children.extend(list(part))
        scored.append((_score_of(children), i, pid))
    scored.sort(key=lambda t: (-t[0], t[1]))
    if scored[0][0] == 0:
        warnings.append(
            (0, "multiple parts, none carrying <harmony>/<lyric>; using the first")
        )
        return order[0]
    warnings.append((0, "multiple parts; using the one carrying chords/lyrics"))
    return scored[0][2]


# ---------------------------------------------------------------------------
# Measure walk → tokens (the core deliverable: harmony↔lyric anchoring)
# ---------------------------------------------------------------------------

def _emit_measures(measures, tokens: list, warnings: list) -> None:
    """Walk measures in order, emitting chord/lyric/section/bar/linebreak tokens.

    One synthetic **lyric line per measure** (the reconstructed sung line);
    each ``<harmony>`` is anchored to the codepoint column of the note event it
    sits over in that line (the anchoring algorithm, below). A ``BarToken`` is
    emitted at each measure boundary (metadata-only). A ``LineBreakToken``
    separates measures. Rehearsal marks open ``SectionToken``s.
    """
    line_index = 0
    n = len(measures)
    for m_idx, measure in enumerate(measures):
        # Rehearsal mark / section boundary (best-effort).
        section = _measure_section(measure)
        if section is not None:
            tokens.append(section)

        line_tokens = _tokenize_measure(measure, line_index, warnings)
        tokens.extend(line_tokens)

        # Bar boundary is metadata-only (dropped by build_nodes).
        tokens.append(BarToken())

        if m_idx < n - 1:
            tokens.append(LineBreakToken())
        line_index += 1


def _measure_section(measure) -> Optional[SectionToken]:
    """Return a ``SectionToken`` if the measure opens a rehearsal-marked section.

    Reads ``<direction><direction-type><rehearsal>`` (or ``<words>`` used as a
    section label heuristic). Returns ``None`` for an ordinary measure.
    """
    for direction in _findall(measure, "direction"):
        for dtype in _findall(direction, "direction-type"):
            rehearsal = _find(dtype, "rehearsal")
            if rehearsal is not None:
                label = _text(rehearsal) or "Section"
                return SectionToken(label=label, kind="section")
    return None


def _tokenize_measure(measure, line_index: int, warnings: list) -> list:
    """Convert one measure into anchored chord + lyric tokens.

    Anchoring algorithm (LOCKED — CHUNK-6-1):

    1. **Enumerate note events** in document order. A bare note, an
       accidental-prefixed note, and a ``<chord>``-grouped note-cluster all
       count as **one** event (a ``<note>`` carrying a ``<chord/>`` child
       continues the current event, it does not start a new one). ``<harmony>``
       elements attach to the *next* note event (MusicXML places a chord symbol
       immediately before the note it sits over); a trailing ``<harmony>`` with
       no following note anchors at end-of-line.
    2. Build a **synthetic per-line lyric string** by joining each event's
       ``<lyric><text>`` honoring ``<syllabic>`` (``begin``/``middle`` join to
       the next syllable with no space; ``end``/``single`` terminate a word);
       events with no lyric contribute a single spacer so columns stay distinct.
    3. Map each ``<harmony>``'s attach event to the **codepoint column** of that
       event's syllable start in the synthetic line.
    4. Tokenize the synthetic line with the shared ``tokenize_lyric_line`` seam;
       emit each chord as a :class:`ChordToken` at its computed lyric-relative
       column (with the event's ``duration`` where available).

    Instrumental / chord-only measures (chords, no ``<lyric>``) → chords
    anchored over an empty lyric line (consistent with CHUNK-1-3 chord-only).
    """
    # --- pass 1: collect note events + pending harmonies -------------------
    events = []  # list of dicts: {syllable, continues, column, duration}
    # harmony attachments: (event_index_it_precedes, chord_text, duration_hint)
    pending_chords = []  # chords seen before the next note event
    chord_anchors = []  # (event_index_or_-1, chord_text)

    for child in measure:
        name = _localname(child.tag)
        if name == "harmony":
            chord_text = _harmony_to_chord(child, warnings)
            if chord_text is not None:
                pending_chords.append(chord_text)
        elif name == "note":
            is_chord_member = _find(child, "chord") is not None
            if is_chord_member and events:
                # Continuation of the current note-chord cluster: same event.
                # Attach any pending chords already handled at cluster start.
                # Prefer a lyric if the cluster head lacked one.
                if not events[-1]["syllable"]:
                    syl, cont = _note_lyric(child)
                    if syl:
                        events[-1]["syllable"] = syl
                        events[-1]["continues"] = cont
                # Flush pending chords onto this cluster head event too.
                for ct in pending_chords:
                    chord_anchors.append((len(events) - 1, ct))
                pending_chords = []
                continue
            # New note event.
            syllable, continues = _note_lyric(child)
            duration = _note_duration(child)
            events.append(
                {"syllable": syllable, "continues": continues, "column": 0,
                 "duration": duration}
            )
            # Any pending chords anchor to this new event.
            for ct in pending_chords:
                chord_anchors.append((len(events) - 1, ct))
            pending_chords = []

    # Trailing chords with no following note anchor at end-of-line.
    for ct in pending_chords:
        chord_anchors.append((-1, ct))

    # --- pass 2: build the synthetic lyric line + per-event columns --------
    parts = []
    cursor = 0
    for ev in events:
        ev["column"] = cursor
        syl = ev["syllable"] or ""
        if syl:
            parts.append(syl)
            cursor += len(syl)
            if not ev["continues"]:
                parts.append(" ")
                cursor += 1
        else:
            # No lyric on this event: a single spacer keeps event columns
            # distinct (instrumental note).
            parts.append(" ")
            cursor += 1
    synthetic_line = "".join(parts)
    end_col = len(synthetic_line)

    out: list = []

    # --- pass 3: emit chords at their anchored columns ---------------------
    for ev_index, chord_text in chord_anchors:
        if ev_index < 0 or ev_index >= len(events):
            col = end_col
            duration = None
        else:
            col = events[ev_index]["column"]
            duration = events[ev_index]["duration"]
        out.append(
            ChordToken(text=chord_text, column=col, line=line_index,
                       duration=duration)
        )

    # --- pass 4: emit lyric word tokens via the shared seam ----------------
    if synthetic_line.strip():
        for lyric_tok in tokenize_lyric_line(synthetic_line, line=line_index):
            out.append(lyric_tok)

    return out


def _note_lyric(note) -> tuple:
    """Return ``(syllable_text, continues)`` for a note's first ``<lyric>``.

    ``continues`` is ``True`` when ``<syllabic>`` is ``begin``/``middle`` (the
    word continues into the next syllable with no space). No lyric → ``("", False)``.
    """
    lyric = _find(note, "lyric")
    if lyric is None:
        return "", False
    syllabic = _text(_find(lyric, "syllabic")).lower()
    text = _text(_find(lyric, "text"))
    continues = syllabic in _SYLLABIC_CONTINUE
    return text, continues


def _note_duration(note) -> Optional[float]:
    """Return the note's ``<duration>`` as a float, or ``None`` when absent.

    Metadata-only in v1 (carried on ``ChordToken.duration``, dropped by
    ``build_nodes``). A ``<rest>`` or grace note has no useful chord duration →
    ``None``.
    """
    dur = _text(_find(note, "duration"))
    if not dur:
        return None
    try:
        return float(dur)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# <harmony> → English chord text (the fidelity-critical mapping)
# ---------------------------------------------------------------------------

def _harmony_to_chord(harmony, warnings: list) -> Optional[str]:
    """Convert a ``<harmony>`` element to English chord text (or ``None``).

    Reads ``<root>`` (``<root-step>`` + ``<root-alter>``), ``<kind>`` (mapped via
    :data:`KIND_TO_QUALITY`, with a ``<kind text="...">`` display override
    respected when present), an optional bass (``<bass-step>`` + ``<bass-alter>``
    → ``/X``), and best-effort ``<degree>`` suffixes. ``kind="none"`` → ``N.C.``.

    Validates the assembled text via :func:`doxtr_music.engine.theory.parse_chord`
    (validation-only: an unrecognized result → ``_warnings`` and the text is
    kept verbatim, never dropped). An unmapped ``<kind>`` → best-effort text +
    ``_warnings``.
    """
    kind_el = _find(harmony, "kind")
    kind_val = _text(kind_el).lower() if kind_el is not None else ""

    # kind="none" is the explicit no-chord marker.
    if kind_val == "none":
        return "N.C."

    root_el = _find(harmony, "root")
    if root_el is None:
        # A <harmony> with a <function> instead of <root> is out of scope.
        warnings.append((0, "harmony without <root> ignored (function harmony "
                            "not supported)"))
        return None
    step = _text(_find(root_el, "root-step")).upper()
    if not step:
        warnings.append((0, "harmony <root> without <root-step> ignored"))
        return None
    alter = _alter_symbol(_find(root_el, "root-alter"))
    root = step + alter

    # Quality from <kind> (with optional display-text override).
    kind_text_attr = (kind_el.get("text") if kind_el is not None else None)
    if kind_val in KIND_TO_QUALITY:
        quality = KIND_TO_QUALITY[kind_val]
    elif kind_text_attr is not None:
        # Unmapped kind but an explicit display text is provided: use it.
        quality = kind_text_attr.strip()
        warnings.append(
            (0, "unmapped harmony kind %r; using display text %r"
                % (kind_val, quality))
        )
    else:
        # Best-effort: strip separators from the kind token itself.
        quality = kind_val.replace("-", "")
        warnings.append(
            (0, "unmapped harmony kind %r; best-effort quality %r"
                % (kind_val, quality))
        )

    # N.C. sentinel from the mapping (shouldn't reach here for "none", handled).
    text = root + ("" if quality in ("", "N.C.") else quality)

    # Best-effort <degree> suffixes (add/alter/subtract).
    for degree in _findall(harmony, "degree"):
        text += _degree_suffix(degree)

    # Slash bass.
    bass_el = _find(harmony, "bass")
    if bass_el is not None:
        bstep = _text(_find(bass_el, "bass-step")).upper()
        if bstep:
            balter = _alter_symbol(_find(bass_el, "bass-alter"))
            text += "/" + bstep + balter

    # Validation-only: an unrecognized chord is kept verbatim + warned.
    try:
        from doxtr_music.engine.theory import parse_chord

        if text != "N.C." and parse_chord(text) is None:
            warnings.append((0, "unrecognized chord %r kept verbatim" % text))
    except Exception:  # pragma: no cover - validation must never be fatal
        pass

    return text


def _alter_symbol(alter_el) -> str:
    """Map a ``<root-alter>``/``<bass-alter>`` semitone count to ``#``/``b`` glyphs."""
    txt = _text(alter_el)
    if not txt:
        return ""
    try:
        alter = int(float(txt))
    except ValueError:
        return ""
    if alter > 0:
        return "#" * alter
    if alter < 0:
        return "b" * (-alter)
    return ""


def _degree_suffix(degree) -> str:
    """Best-effort textual suffix for a ``<degree>`` (add/alter/subtract)."""
    value = _text(_find(degree, "degree-value"))
    if not value:
        return ""
    alter = _alter_symbol(_find(degree, "degree-alter"))
    dtype = _text(_find(degree, "degree-type")).lower()
    prefix = _DEGREE_PREFIX.get(dtype, "add")
    return "%s%s%s" % (prefix, alter, value)
