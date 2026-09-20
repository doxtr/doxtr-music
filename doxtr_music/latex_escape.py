"""LaTeX string escaping for doxtr-music (own copy — no core import).

doxtr-music treats ``doxtr-pdf-theme-core`` as a *soft* dependency and must
never import it at module scope. This module is an independent implementation
of the same escaping algorithm the core theme ships, so the LaTeX visitors can
neutralize untrusted chord/lyric/metadata content without a hard dependency.

Escaping happens **only at the LaTeX visitor boundary** (CHUNK-2-1). Nodes store
UNESCAPED text (the 1-1/1-2 contract); escaping in ``build_nodes`` would corrupt
HTML/EPUB output. Only *content arguments* passed into ``\\dm…`` macros are
escaped — never the control words themselves.

Algorithm (LOCKED):

* ``\\`` is escaped **first** (to ``\\textbackslash{}``) so subsequently
  introduced backslashes (from ``~``/``^`` replacements) are not re-escaped.
* ``~`` → ``\\textasciitilde{}`` and ``^`` → ``\\textasciicircum{}`` (these
  are active/superscript in LaTeX and need the text-command form).
* ``# $ % & _ { }`` get a single leading backslash.
"""

from __future__ import annotations

from typing import Optional

__all__ = ["esc_latex", "LATEX_ESCAPE_MAP"]

#: Mapping of LaTeX special characters to their escaped equivalents. Backslash
#: is listed first for documentation; :func:`esc_latex` processes per-character
#: so ordering in the dict is not load-bearing (a char is replaced at most once).
LATEX_ESCAPE_MAP = {
    "\\": r"\textbackslash{}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "_": r"\_",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "&": r"\&",
    "{": r"\{",
    "}": r"\}",
}


def esc_latex(s: Optional[str]) -> str:
    """Escape ``s`` for safe inclusion as a LaTeX content argument.

    Returns ``""`` for ``None``/empty input. Newlines are collapsed to spaces
    (a chord/lyric/label is single-line content). Because the replacement is
    performed character-by-character, an introduced special (e.g. the ``\\`` in
    ``\\textasciitilde{}``) is never re-escaped — this is why ``\\`` does not
    need to be handled "first" via string passes.
    """
    if not s:
        return ""
    out = []
    for ch in str(s):
        if ch == "\n":
            out.append(" ")
        elif ch in LATEX_ESCAPE_MAP:
            out.append(LATEX_ESCAPE_MAP[ch])
        else:
            out.append(ch)
    return "".join(out)
