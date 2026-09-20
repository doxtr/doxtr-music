r"""``.. chord-progression::`` — a tabular chord/roman grid (CHUNK-4-4).

A **plain** :class:`docutils.parsers.rst.Directive` (NOT
:class:`~doxtr_music.directives._base.SongDirectiveBase` — a progression is not a
song, has no lyrics, and no ``title_id``). It renders a semantic grid of chords
and/or Roman numerals, e.g.::

    .. chord-progression::
       :key: C
       :roman-numerals:

       | C | F | G | C |
       | Am | Dm | G | C |

Grid syntax (LOCKED):

* one row per body line; cells split on ``|``; a leading/trailing ``|`` is
  optional; each cell is trimmed of surrounding whitespace.
* an **empty** cell (nothing between two ``|``) is a *spacer*
  (``cell_kind="empty"``).
* there is no "repeat" marker in v1 (a repeat is just the chord written again).

Cell classification (LOCKED — evaluation order):

1. empty/whitespace  → ``ProgressionCellNode(cell_kind="empty")``.
2. :func:`~doxtr_music.engine.theory.parse_chord` succeeds → a chord cell
   holding a ``ChordNode(column=None)``.
3. else matches the roman recognizer → an **author-literal** roman cell holding a
   ``RomanNode(roman=cell)`` (never re-analyzed, like the ``:roman:`` role).
4. else → literal passthrough text + a ``_warnings`` note.

``:roman-numerals:`` + ``:key:`` → each *chord* cell additionally gets a computed
roman via :func:`~doxtr_music.engine.roman.roman_for_chord` (the single 3-3
authority). Author-literal roman cells stay literal even in a mixed row.

``columns`` (LOCKED) = the max cells-per-row; ragged rows are normalized to
``columns`` cells at build time (short rows padded with ``empty`` cells) so all
three visitors receive rectangular data. A ragged row emits a ``_warnings`` note.

This module builds format-neutral nodes only; HTML/LaTeX/EPUB rendering lives in
the per-format visitors (``_VISITORS`` seam). It imports only from Docutils +
the pure engine/parsers layer at module top level (no Sphinx import), honoring
the deferred-import contract.
"""

from __future__ import annotations

import re

from docutils.nodes import Text
from docutils.parsers.rst import Directive

from doxtr_music import nodes as _nodes
from doxtr_music.directives._options import normalize_options, song_option_spec
from doxtr_music.directives._warnings import drain_warnings
from doxtr_music.engine.roman import roman_for_chord
from doxtr_music.engine.theory import parse_chord

__all__ = ["ChordProgressionDirective", "classify_cell", "parse_grid"]

#: Author-literal roman recognizer (LOCKED). Optional leading ``b``/``#``
#: accidental, one-or-more roman letters (any case), an optional quality symbol
#: (``°``/``+``/``o``) and an optional trailing extension number
#: (e.g. ``V7``, ``bVII``, ``vi``, ``ii°``).
_ROMAN_RE = re.compile(r"^[b#]?[iIvVxX]+(\u00b0|\+|o)?[0-9]*$")


def _split_cells(line):
    """Split one grid line into trimmed cells on ``|`` (leading/trailing bar
    optional). ``"| C | F |"`` and ``"C | F"`` both yield ``["C", "F"]``; an
    empty inter-bar span yields ``""`` (a spacer)."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def classify_cell(text):
    """Classify one raw cell → ``(kind, payload)``.

    * ``("empty", None)`` — blank/whitespace spacer.
    * ``("chord", ChordParts_root_display)`` — parses as a chord; payload is the
      original chord text (kept verbatim for localization at render).
    * ``("roman", numeral)`` — author-literal roman numeral.
    * ``("literal", text)`` — unrecognized; rendered as-is + a warning.
    """
    cell = (text or "").strip()
    if not cell:
        return ("empty", None)
    if parse_chord(cell) is not None:
        return ("chord", cell)
    if _ROMAN_RE.match(cell):
        return ("roman", cell)
    return ("literal", cell)


def parse_grid(content):
    """Parse the directive body lines into a classified, rectangular grid.

    Returns ``(rows, columns, warnings)`` where ``rows`` is a list of rows, each
    a list of ``(kind, payload)`` cells; ``columns`` is the max cells-per-row;
    and ``warnings`` is a list of ``(body_line, message)`` pairs. Ragged rows are
    padded with ``("empty", None)`` cells to ``columns`` and each padded row adds
    a warning; literal (unrecognized) cells add a warning.
    """
    raw_rows = []
    warnings = []
    for body_line, line in enumerate(content):
        if not line.strip():
            continue  # blank body lines separate nothing; skip
        cells = [classify_cell(c) for c in _split_cells(line)]
        for kind, payload in cells:
            if kind == "literal":
                warnings.append(
                    (body_line, "unrecognized progression cell %r (rendered as-is)"
                     % payload)
                )
        raw_rows.append((body_line, cells))

    columns = max((len(cells) for _, cells in raw_rows), default=0)

    rows = []
    for body_line, cells in raw_rows:
        if len(cells) < columns:
            warnings.append(
                (body_line, "ragged progression row padded from %d to %d cells"
                 % (len(cells), columns))
            )
            cells = cells + [("empty", None)] * (columns - len(cells))
        rows.append(cells)

    return rows, columns, warnings


class ChordProgressionDirective(Directive):
    """``.. chord-progression::`` → a :class:`ChordProgressionNode` grid.

    Reuses the locked song-family ``option_spec`` (so ``:key:`` /
    ``:roman-numerals:`` + the typography options parse identically) but consumes
    only the grid-relevant ones. Assigns an ``id`` (for cross-ref) but no
    ``title_id`` (it is not a song). Reuses :func:`drain_warnings` for parse-time
    warnings.
    """

    has_content = True
    required_arguments = 0
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec = song_option_spec()

    def run(self):
        options = normalize_options(self.options)
        key = options.get("key")
        roman_numerals = options.get("roman_numerals", False)

        rows, columns, warnings = parse_grid(list(self.content))

        prog = _nodes.ChordProgressionNode()
        prog["columns"] = columns
        prog["ids"] = [self.state.document.set_id(prog)]

        for cells in rows:
            row_node = _nodes.ProgressionRowNode()
            for kind, payload in cells:
                row_node += self._build_cell(kind, payload, key, roman_numerals)
            prog += row_node

        # Reuse the standalone warning-drain authority (content-relative math).
        drain_warnings(self, {"_warnings": warnings})

        return [prog]

    def _build_cell(self, kind, payload, key, roman_numerals):
        """Build one :class:`ProgressionCellNode` per the LOCKED classification.

        Chord cells hold a ``ChordNode(column=None)``. When ``:roman-numerals:``
        is on and a ``:key:`` is given, the chord cell's ``roman`` annotation is
        computed via :func:`roman_for_chord` (the chord visitor renders it in
        replace mode). Author-literal roman cells hold a ``RomanNode`` and are
        never re-analyzed. Literal passthrough cells render as-is text.
        """
        cell = _nodes.ProgressionCellNode()
        if kind == "empty":
            cell["cell_kind"] = "empty"
            return cell
        if kind == "chord":
            cell["cell_kind"] = "chord"
            chord = _nodes.ChordNode()
            chord["chord"] = payload
            chord["column"] = None  # a grid chord has no lyric context
            if roman_numerals and key:
                computed = roman_for_chord(payload, key)
                if computed is not None:
                    # Stored on the CELL (not the ChordNode.roman replace-mode
                    # slot) so the chord cell shows the localized chord AND its
                    # computed numeral side by side (separate-roman-cell model),
                    # and resolve_chord_display still yields the localized chord.
                    cell["computed_roman"] = computed
            cell += chord
            return cell
        if kind == "roman":
            cell["cell_kind"] = "roman"
            roman = _nodes.RomanNode()
            roman["roman"] = payload  # author-literal, never analyzed
            cell += roman
            return cell
        # literal passthrough (unrecognized): render as-is text (warned in
        # parse_grid); classified as an empty-kind cell holding a Text node so
        # the visitors emit its content without treating it as a chord/roman.
        cell["cell_kind"] = "empty"
        cell += Text(payload)
        return cell
