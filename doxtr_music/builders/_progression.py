"""Shared classification for chord-progression grid cells (CHUNK-4-4).

Single authority for interpreting a :class:`ProgressionCellNode`: it resolves
the chord display string (via :func:`resolve_chord_display`), locates the
optional computed roman numeral, and finds the :class:`RomanNode` numeral for
roman cells — **once**, so the HTML, LaTeX, and EPUB progression visitors share
one classify pass and only differ in format-specific markup emission.

Introduced by the maintainability review to remove the triplicated
classify-and-render logic that previously lived independently in
``builders/html.py``, ``builders/latex.py`` and ``builders/epub.py`` (the one
place a new cell kind had to be edited in three files and could silently drift).

The rendered output is unchanged: each builder keeps its own markup, but the
``(kind, ...)`` decision + display/roman/numeral values now come from here.
"""

from doxtr_music import nodes as _nodes


def classify_progression_cell(cell, config):
    """Classify one progression cell into a normalized render descriptor.

    Returns a tuple whose first element is the cell kind:

    - ``("chord", display, computed_roman)`` — ``display`` is the resolved
      chord display string; ``computed_roman`` is the optional side-by-side
      roman numeral (``""`` when absent). If the cell is marked ``"chord"`` but
      holds no :class:`ChordNode` (should not happen), returns
      ``("empty", "")`` so callers emit a blank cell.
    - ``("roman", numeral)`` — ``numeral`` is the roman numeral text (``""``
      when the :class:`RomanNode` is missing).
    - ``("empty", text)`` — spacer / literal passthrough; ``text`` is the
      cell's plain text.

    Resolving the chord display and locating the child nodes happens here so the
    three format builders never re-implement it.
    """
    from doxtr_music.engine.i18n import resolve_chord_display

    kind = cell.get("cell_kind", "empty")
    if kind == "chord":
        chord_node = next(
            (ch for ch in cell.children
             if isinstance(ch, _nodes.ChordNode)), None)
        if chord_node is None:  # pragma: no cover - chord cell always has one
            return ("empty", "")
        display = resolve_chord_display(chord_node, config)
        roman = cell.get("computed_roman") or ""
        return ("chord", display, roman)
    if kind == "roman":
        roman_node = next(
            (ch for ch in cell.children
             if isinstance(ch, _nodes.RomanNode)), None)
        numeral = roman_node.get("roman", "") if roman_node is not None else ""
        return ("roman", numeral)
    # empty / spacer / literal passthrough
    return ("empty", cell.astext())
