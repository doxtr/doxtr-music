"""
doxtr-music — Test Harness Assertion Types

Reusable assertion functions for validating rendered output. Each assertion
checks one aspect of a built page/document. Assertions are HTML-first for this
chunk; reserved LaTeX/EPUB assertions are declared (and constructible) now, and
their check bodies are filled by the chunk that owns the feature.

Usage in features.py::

    expected_markers={"html": [r"my_regex_pattern"]},
    assertions={"html": ["META_TAG_PRESENT", "HTML_WELL_FORMED"]},

New assertions are added by:
    1. Adding a value to ``AssertType``.
    2. Adding a description in ``ASSERTION_DESCRIPTIONS`` (keeps every member
       constructible / describable).
    3. Implementing the check branch in ``_check_single_assertion``.

The runner tolerates *unknown* assertion strings in ``features.py`` (parse and
skip) so a chunk can name an assertion before its check body exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from html.parser import HTMLParser
from typing import Optional


class AssertType(Enum):
    """Types of assertions that can be checked against rendered output."""

    # --- HTML assertions (implemented in this chunk) ---
    META_TAG_PRESENT = "meta_tag_present"
    HTML_WELL_FORMED = "html_well_formed"
    FILE_SIZE_RANGE = "file_size_range"

    # --- Reserved HTML assertions (implemented in their owning chunk) ---
    POSITION_ABSOLUTE_CSS = "position_absolute_css"
    COPY_SAFE_ORDER_HTML = "copy_safe_order_html"
    ARIA_LABEL_PRESENT = "aria_label_present"
    ROLE_GROUP_PRESENT = "role_group_present"
    DIR_AUTO_PRESENT = "dir_auto_present"

    # --- Reserved EPUB assertions (implemented in their owning chunk) ---
    COPY_SAFE_ORDER_EPUB_PRE = "copy_safe_order_epub_pre"
    EPUB_PRE_FALLBACK = "epub_pre_fallback"

    # --- Reserved LaTeX assertions (implemented in their owning chunk) ---
    NEEDSPACE_PRESENT = "needspace_present"
    LATEX_PACKAGE_LOADED = "latex_package_loaded"

    # --- Transpose assertions (CHUNK-3-2, per-format shifted-chord checks) ---
    TRANSPOSE_SHIFTED_HTML = "transpose_shifted_html"
    TRANSPOSE_SHIFTED_LATEX = "transpose_shifted_latex"
    TRANSPOSE_SHIFTED_EPUB = "transpose_shifted_epub"

    # --- Roman-numeral assertions (CHUNK-3-3, per-format replace-mode checks) ---
    ROMAN_REPLACE_HTML = "roman_replace_html"
    ROMAN_REPLACE_LATEX = "roman_replace_latex"
    ROMAN_REPLACE_EPUB = "roman_replace_epub"

    # --- i18n chord-system localization (CHUNK-3-4, per-format german map) ---
    I18N_GERMAN_HTML = "i18n_german_html"
    I18N_GERMAN_LATEX = "i18n_german_latex"
    I18N_GERMAN_EPUB = "i18n_german_epub"

    # --- RTL support / documented fallbacks (CHUNK-3-4) ---
    RTL_LOGICAL_CSS = "rtl_logical_css"
    RTL_FALLBACK_LATEX = "rtl_fallback_latex"
    RTL_FALLBACK_EPUB = "rtl_fallback_epub"

    # --- Inline roles :chord:/:key:/:roman: (CHUNK-3-5, per-format checks) ---
    ROLES_HTML = "roles_html"
    ROLES_LATEX = "roles_latex"
    ROLES_EPUB = "roles_epub"

    # --- Typography (CHUNK-4-1, per-format granular styling checks) ---
    TYPOGRAPHY_APPLIED_HTML = "typography_applied_html"
    TYPOGRAPHY_APPLIED_LATEX = "typography_applied_latex"
    TYPOGRAPHY_APPLIED_EPUB = "typography_applied_epub"

    # --- Multi-singer color (CHUNK-4-2, per-format singer-wins checks) ---
    SINGER_COLOR_APPLIED_HTML = "singer_color_applied_html"
    SINGER_COLOR_APPLIED_LATEX = "singer_color_applied_latex"
    SINGER_COLOR_APPLIED_EPUB = "singer_color_applied_epub"

    # --- Chord-progression grid (CHUNK-4-4, per-format semantic-table checks) ---
    PROGRESSION_TABLE_HTML = "progression_table_html"
    PROGRESSION_TABLE_LATEX = "progression_table_latex"
    PROGRESSION_TABLE_EPUB = "progression_table_epub"

    # --- Song-list / song-index xref resolution (CHUNK-5-3) ---
    SONG_LIST_XREF_RESOLVES = "song_list_xref_resolves"
    SONG_LIST_EMPTY_STATE = "song_list_empty_state"
    SONG_LIST_XREF_LATEX = "song_list_xref_latex"

    # --- Plugin hooks (CHUNK-5-4, HTML html_visit injection + copy-safety) ---
    HOOK_INJECTED_HTML = "hook_injected_html"


# Description mapping for reporting. Every AssertType member (including reserved
# ones) MUST have an entry so it is describable and constructible.
ASSERTION_DESCRIPTIONS: dict[AssertType, str] = {
    AssertType.META_TAG_PRESENT: "Provenance <meta> tag present in HTML",
    AssertType.HTML_WELL_FORMED: "Output parses as well-formed HTML",
    AssertType.FILE_SIZE_RANGE: "Output file size in a sane range",
    AssertType.POSITION_ABSOLUTE_CSS: "Chord absolute-positioning CSS present",
    AssertType.COPY_SAFE_ORDER_HTML: "HTML copy-safe DOM order preserved",
    AssertType.ARIA_LABEL_PRESENT: "aria-label present on chord element",
    AssertType.ROLE_GROUP_PRESENT: "role=group present on song wrapper",
    AssertType.DIR_AUTO_PRESENT: "dir=auto present for RTL support",
    AssertType.COPY_SAFE_ORDER_EPUB_PRE: "EPUB <pre> copy-safe order preserved",
    AssertType.EPUB_PRE_FALLBACK: "EPUB reflow-safe <pre> fallback present",
    AssertType.NEEDSPACE_PRESENT: "LaTeX \\needspace present",
    AssertType.LATEX_PACKAGE_LOADED: "LaTeX package loaded in preamble",
    AssertType.TRANSPOSE_SHIFTED_HTML: (
        "Transposed chords render in HTML (shifted labels present, originals absent)"
    ),
    AssertType.TRANSPOSE_SHIFTED_LATEX: (
        "Transposed chords render in LaTeX \\dmchord (shifted present, originals absent)"
    ),
    AssertType.TRANSPOSE_SHIFTED_EPUB: (
        "Transposed chords render in EPUB <pre> (shifted present, originals absent)"
    ),
    AssertType.ROMAN_REPLACE_HTML: (
        "Roman numerals replace chord labels in the visible HTML chord text"
    ),
    AssertType.ROMAN_REPLACE_LATEX: (
        "Roman numerals replace chord labels in LaTeX \\dmchord args"
    ),
    AssertType.ROMAN_REPLACE_EPUB: (
        "Roman numerals replace chord labels in the EPUB <pre> chord row"
    ),
    AssertType.I18N_GERMAN_HTML: (
        "German chord-system localization applied in HTML chord text (B->H, Bb->B, ...)"
    ),
    AssertType.I18N_GERMAN_LATEX: (
        "German chord-system localization applied in LaTeX \\dmchord args"
    ),
    AssertType.I18N_GERMAN_EPUB: (
        "German chord-system localization applied in the EPUB <pre> chord row"
    ),
    AssertType.RTL_LOGICAL_CSS: (
        "RTL HTML: dir=auto present + logical CSS only (no physical left/right)"
    ),
    AssertType.RTL_FALLBACK_LATEX: (
        "RTL LaTeX documented fallback: song macros emitted verbatim, no crash"
    ),
    AssertType.RTL_FALLBACK_EPUB: (
        "RTL EPUB documented fallback: reflow-safe <pre> + dir=auto, no crash"
    ),
    AssertType.ROLES_HTML: (
        "Inline roles in HTML: .doxtr-chord-inline (no aria-hidden), .doxtr-key, "
        ".doxtr-roman spans present"
    ),
    AssertType.ROLES_LATEX: (
        "Inline roles in LaTeX: \\dmchordinline / \\dmkey / \\dmroman emitted"
    ),
    AssertType.ROLES_EPUB: (
        "Inline roles in EPUB: .doxtr-chord-inline / .doxtr-key / .doxtr-roman "
        "inline spans (not the song <pre> layout)"
    ),
    AssertType.TYPOGRAPHY_APPLIED_HTML: (
        "HTML typography: global element-class <style> block + per-song inline "
        "style on chord/lyric spans (per-attr merge; others inherit)"
    ),
    AssertType.TYPOGRAPHY_APPLIED_LATEX: (
        "LaTeX typography: global preamble indirection-macro \\renewcommand + a "
        "per-song scoped \\begingroup...\\def...\\endgroup group"
    ),
    AssertType.TYPOGRAPHY_APPLIED_EPUB: (
        "EPUB typography: global element-class <style> block + per-song inline "
        "style on the <pre> chord/lyric row spans (relative sizes)"
    ),
    AssertType.SINGER_COLOR_APPLIED_HTML: (
        "Singer color wins over typography color in HTML (one inline color/element)"
    ),
    AssertType.SINGER_COLOR_APPLIED_LATEX: (
        "Singer color sets the run's LaTeX indirection color macros (singer wins)"
    ),
    AssertType.SINGER_COLOR_APPLIED_EPUB: (
        "Singer color colors both <pre> row cell sub-ranges (singer wins)"
    ),
    AssertType.PROGRESSION_TABLE_HTML: (
        "Chord progression renders as a semantic HTML <table> (caption + <td>)"
    ),
    AssertType.PROGRESSION_TABLE_LATEX: (
        "Chord progression renders as a LaTeX tabular (\\dmchordinline/\\dmroman)"
    ),
    AssertType.PROGRESSION_TABLE_EPUB: (
        "Chord progression renders as a semantic EPUB <table> (caption + <td>)"
    ),
    AssertType.SONG_LIST_XREF_RESOLVES: (
        "song-list/index links target a real in-document anchor (href to an id "
        "that exists), rendered in the doxtr-song-list/doxtr-song-index container"
    ),
    AssertType.SONG_LIST_EMPTY_STATE: (
        "song-list/index empty state renders the container with no <li> links"
    ),
    AssertType.SONG_LIST_XREF_LATEX: (
        "song-list renders a LaTeX list with a resolving \\hyperref link"
    ),
    AssertType.HOOK_INJECTED_HTML: (
        "html_visit hook injected markup inside a copy-neutral .doxtr-hook "
        "wrapper; the copy-safe lyric stream is unaffected"
    ),
}


@dataclass
class AssertionResult:
    """Result of a single assertion check."""
    assertion_type: AssertType
    passed: bool
    description: str
    details: Optional[str] = None


def check_assertions(
    content: str,
    assertions: list[AssertType],
    file_size: Optional[int] = None,
    build_css_path: Optional[str] = None,
) -> list[AssertionResult]:
    """Check a list of assertions against rendered ``content``.

    Args:
        content: The rendered output (HTML text for this chunk).
        assertions: List of ``AssertType`` values to check.
        file_size: Optional output size in bytes for ``FILE_SIZE_RANGE``.
        build_css_path: Optional path to the build's delivered
            ``_static/doxtr_music.css`` so ``POSITION_ABSOLUTE_CSS`` gates on
            what the build actually shipped (falls back to the package copy).

    Returns:
        A list of ``AssertionResult`` objects.
    """
    return [
        _check_single_assertion(a, content, file_size, build_css_path)
        for a in assertions
    ]


def _result(assertion: AssertType, passed: bool, details: str) -> AssertionResult:
    return AssertionResult(
        assertion_type=assertion,
        passed=passed,
        description=ASSERTION_DESCRIPTIONS.get(assertion, str(assertion.value)),
        details=details,
    )


def _html_well_formed(content: str) -> bool:
    """Very light tag-balance heuristic (lxml optional, not required).

    Counts opening vs closing tags of a few structural elements. This is a
    guard against truncated/empty builds, not a full HTML validator.
    """
    if "<html" not in content.lower():
        return False
    # Balance of a handful of block tags that must nest cleanly in a page.
    for tag in ("html", "head", "body"):
        opens = len(re.findall(rf"<{tag}\b", content, re.IGNORECASE))
        closes = len(re.findall(rf"</{tag}>", content, re.IGNORECASE))
        if opens != closes or opens == 0:
            return False
    return True


def _check_single_assertion(
    assertion: AssertType,
    content: str,
    file_size: Optional[int] = None,
    build_css_path: Optional[str] = None,
) -> AssertionResult:
    """Check a single assertion type against ``content``."""
    if assertion == AssertType.META_TAG_PRESENT:
        found = '<meta name="doxtr-music"' in content
        return _result(
            assertion, found,
            "Found provenance meta tag" if found else "No provenance meta tag found",
        )

    if assertion == AssertType.HTML_WELL_FORMED:
        found = _html_well_formed(content)
        return _result(
            assertion, found,
            "Output is well-formed HTML" if found else "Output not well-formed HTML",
        )

    if assertion == AssertType.FILE_SIZE_RANGE:
        if file_size is None:
            return _result(assertion, False, "No file size provided for check")
        # A sane built HTML page: between 256 bytes and 10 MB.
        passed = 256 <= file_size <= 10 * 1024 * 1024
        return _result(
            assertion, passed,
            f"File size: {file_size} bytes" if passed
            else f"File size {file_size} out of range",
        )

    if assertion == AssertType.POSITION_ABSOLUTE_CSS:
        return _position_absolute_css(content, build_css_path)

    if assertion == AssertType.COPY_SAFE_ORDER_HTML:
        return _copy_safe_order_html(content)

    if assertion == AssertType.NEEDSPACE_PRESENT:
        return _needspace_present(content)

    if assertion == AssertType.LATEX_PACKAGE_LOADED:
        return _latex_package_loaded(content)

    if assertion == AssertType.EPUB_PRE_FALLBACK:
        return _epub_pre_fallback(content)

    if assertion == AssertType.COPY_SAFE_ORDER_EPUB_PRE:
        return _copy_safe_order_epub_pre(content)

    if assertion == AssertType.TRANSPOSE_SHIFTED_HTML:
        return _transpose_shifted_html(content)

    if assertion == AssertType.TRANSPOSE_SHIFTED_LATEX:
        return _transpose_shifted_latex(content)

    if assertion == AssertType.TRANSPOSE_SHIFTED_EPUB:
        return _transpose_shifted_epub(content)

    if assertion == AssertType.ROMAN_REPLACE_HTML:
        return _roman_replace_html(content)

    if assertion == AssertType.ROMAN_REPLACE_LATEX:
        return _roman_replace_latex(content)

    if assertion == AssertType.ROMAN_REPLACE_EPUB:
        return _roman_replace_epub(content)

    if assertion == AssertType.I18N_GERMAN_HTML:
        return _i18n_german_html(content)

    if assertion == AssertType.I18N_GERMAN_LATEX:
        return _i18n_german_latex(content)

    if assertion == AssertType.I18N_GERMAN_EPUB:
        return _i18n_german_epub(content)

    if assertion == AssertType.DIR_AUTO_PRESENT:
        return _dir_auto_present(content)

    if assertion == AssertType.RTL_LOGICAL_CSS:
        return _rtl_logical_css(content)

    if assertion == AssertType.RTL_FALLBACK_LATEX:
        return _rtl_fallback_latex(content)

    if assertion == AssertType.RTL_FALLBACK_EPUB:
        return _rtl_fallback_epub(content)

    if assertion == AssertType.ROLES_HTML:
        return _roles_html(content)

    if assertion == AssertType.ROLES_LATEX:
        return _roles_latex(content)

    if assertion == AssertType.ROLES_EPUB:
        return _roles_epub(content)

    if assertion == AssertType.TYPOGRAPHY_APPLIED_HTML:
        return _typography_applied_html(content)

    if assertion == AssertType.TYPOGRAPHY_APPLIED_LATEX:
        return _typography_applied_latex(content)

    if assertion == AssertType.TYPOGRAPHY_APPLIED_EPUB:
        return _typography_applied_epub(content)

    if assertion == AssertType.SINGER_COLOR_APPLIED_HTML:
        return _singer_color_applied_html(content)

    if assertion == AssertType.SINGER_COLOR_APPLIED_LATEX:
        return _singer_color_applied_latex(content)

    if assertion == AssertType.SINGER_COLOR_APPLIED_EPUB:
        return _singer_color_applied_epub(content)

    if assertion == AssertType.ARIA_LABEL_PRESENT:
        return _aria_label_present(content)

    if assertion == AssertType.PROGRESSION_TABLE_HTML:
        return _progression_table_html(content)

    if assertion == AssertType.PROGRESSION_TABLE_LATEX:
        return _progression_table_latex(content)

    if assertion == AssertType.PROGRESSION_TABLE_EPUB:
        return _progression_table_epub(content)

    if assertion == AssertType.SONG_LIST_XREF_RESOLVES:
        return _song_list_xref_resolves(content)

    if assertion == AssertType.SONG_LIST_EMPTY_STATE:
        return _song_list_empty_state(content)

    if assertion == AssertType.SONG_LIST_XREF_LATEX:
        return _song_list_xref_latex(content)

    if assertion == AssertType.HOOK_INJECTED_HTML:
        return _hook_injected_html(content)

    if assertion == AssertType.ROLE_GROUP_PRESENT:
        return _role_group_present(content)

    # Reserved assertions: constructible now, check body filled by owning chunk.
    return _result(
        assertion, False,
        f"Assertion not yet implemented: {assertion.value} (reserved)",
    )


# ---------------------------------------------------------------------------
# CHUNK-1-4 assertion bodies: POSITION_ABSOLUTE_CSS + COPY_SAFE_ORDER_HTML
# ---------------------------------------------------------------------------

def _packaged_css() -> Optional[str]:
    """Return the shipped ``doxtr_music.css`` text, or ``None`` if unavailable.

    The stylesheet is a package resource; reading it directly verifies the
    *actual shipped* positioning rules rather than a page-inlined copy. This is
    the fallback when the build's delivered ``_static`` copy is unavailable.
    """
    try:
        import os

        import doxtr_music

        css_path = os.path.join(
            os.path.dirname(doxtr_music.__file__), "static", "doxtr_music.css"
        )
        with open(css_path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return None


def _delivered_css(build_css_path: Optional[str]) -> Optional[str]:
    """Return the CSS the build actually delivered, else ``None``.

    Reads the build output's ``_static/doxtr_music.css`` so the gate reflects
    what the build shipped (not merely the installed package copy). Returns
    ``None`` when no build path is supplied or the file is missing, so the
    caller can fall back to :func:`_packaged_css`.
    """
    if not build_css_path:
        return None
    try:
        with open(build_css_path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return None


def _position_absolute_css(
    content: str, build_css_path: Optional[str] = None
) -> AssertionResult:
    """Chords are absolutely positioned via CSS *and* the page delivers the CSS.

    Two conditions, both required:

    1. The built page links the packaged ``doxtr_music.css`` (delivery wiring
       reaches this format).
    2. The stylesheet the build **delivered** into ``_static/doxtr_music.css``
       declares ``position: absolute`` + ``user-select: none`` on
       ``.doxtr-chord`` using CSS *logical* properties (no physical
       ``left``/``right``) — the LOCKED positioning + i18n seam. Reading the
       delivered copy (falling back to the packaged resource) means the gate
       reflects what the build actually shipped, not just the installed package.
    """
    a = AssertType.POSITION_ABSOLUTE_CSS
    if "doxtr_music.css" not in content:
        return _result(a, False, "page does not link doxtr_music.css")

    css = _delivered_css(build_css_path)
    css_source = "build _static"
    if css is None:
        css = _packaged_css()
        css_source = "packaged resource"
    if css is None:
        return _result(a, False, "could not read doxtr_music.css")

    m = re.search(r"\.doxtr-chord\s*\{([^}]*)\}", css, re.DOTALL)
    if not m:
        return _result(a, False, "no .doxtr-chord CSS rule found")
    block = m.group(1)
    has_absolute = re.search(r"position\s*:\s*absolute", block) is not None
    has_no_select = re.search(r"user-select\s*:\s*none", block) is not None
    physical = re.search(r"(^|;)\s*(left|right)\s*:", block) is not None

    passed = has_absolute and has_no_select and not physical
    details = (
        "css=%s position:absolute=%s user-select:none=%s physical-offset=%s"
        % (css_source, has_absolute, has_no_select, physical)
    )
    return _result(a, passed, details)


class _CopySafeParser(HTMLParser):
    """Extract the copy-safe residual text of a ``.doxtr-song`` subtree.

    Operational definition (LOCKED PERMANENT GATE): after removing every
    ``.doxtr-chord``, ``.doxtr-singer`` and ``.doxtr-hook`` wrapper element, the
    residual text inside a ``.doxtr-song`` equals the concatenated lyric stream
    in logical order. Text is collected only while inside a ``.doxtr-song`` and
    NOT inside a stripped chord/singer/hook wrapper. ``.doxtr-hook`` is the
    copy-neutral wrapper the CHUNK-5-4 ``html_visit`` plugin hook injects into,
    so custom HTML injection can never pollute the copyable lyric stream.

    Song *chrome* that is not part of the lyric stream is also stripped: the
    song title (``.doxtr-song-title``) and the metadata block
    (``.doxtr-song-meta-list``). These are styled song metadata rows (title /
    key / tempo / …), rendered outside any lyric line, so a metadata value that
    happens to equal a chord glyph (e.g. ``{key: C}``) is not a lyric-stream
    leak.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._song_depth = 0        # >0 while inside any .doxtr-song
        self._strip_stack = []      # open stripped wrapper tag names
        self._tag_stack = []        # (tag, is_song, is_strip)
        self.residual_parts: list = []
        self.found_song = False

    @staticmethod
    def _classes(attrs):
        for name, value in attrs:
            if name == "class" and value:
                return value.split()
        return []

    def handle_starttag(self, tag, attrs):
        classes = self._classes(attrs)
        is_song = "doxtr-song" in classes
        is_strip = (
            "doxtr-chord" in classes
            or "doxtr-singer" in classes
            or "doxtr-hook" in classes
            or "doxtr-song-title" in classes
            or "doxtr-song-meta-list" in classes
        )
        if is_song:
            self._song_depth += 1
            self.found_song = True
        if is_strip:
            self._strip_stack.append(tag)
        self._tag_stack.append((tag, is_song, is_strip))

    def handle_startendtag(self, tag, attrs):
        classes = self._classes(attrs)
        if "doxtr-song" in classes:
            self.found_song = True

    def handle_endtag(self, tag):
        while self._tag_stack:
            open_tag, is_song, is_strip = self._tag_stack.pop()
            if is_song and self._song_depth > 0:
                self._song_depth -= 1
            if is_strip and self._strip_stack:
                self._strip_stack.pop()
            if open_tag == tag:
                break

    def handle_data(self, data):
        if self._song_depth > 0 and not self._strip_stack:
            self.residual_parts.append(data)

    @property
    def residual_text(self) -> str:
        return "".join(self.residual_parts)


def _copy_safe_order_html(content: str) -> AssertionResult:
    """Copy-safety gate: stripping chord/singer wrappers leaves the lyric stream.

    Checks (all required):

    * A ``.doxtr-song`` exists.
    * After removing ``.doxtr-chord`` / ``.doxtr-singer`` wrappers, no parsed
      ``data-chord`` glyph survives in the residual (copyable) song text —
      chords are DOM-adjacent, never interleaved into lyric text.
    * ``.doxtr-chord`` declares ``user-select:none`` in the shipped CSS.
    """
    a = AssertType.COPY_SAFE_ORDER_HTML

    parser = _CopySafeParser()
    try:
        parser.feed(content)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(a, False, "HTML parse error: %s" % exc)

    if not parser.found_song:
        return _result(a, False, "no .doxtr-song wrapper found")

    residual = parser.residual_text

    chord_values = re.findall(r'data-chord="([^"]+)"', content)
    leaked = [c for c in chord_values if c and c in residual]
    if leaked:
        return _result(
            a, False,
            "chord glyph(s) leaked into copyable lyric stream: %r" % leaked,
        )

    css = _packaged_css()
    non_select = False
    if css is not None:
        m = re.search(r"\.doxtr-chord\s*\{([^}]*)\}", css, re.DOTALL)
        if m and re.search(r"user-select\s*:\s*none", m.group(1)):
            non_select = True
    if not non_select:
        return _result(a, False, ".doxtr-chord lacks user-select:none in CSS")

    return _result(
        a, True,
        "copy-safe: residual lyric stream chord-free; chords user-select:none",
    )


# ---------------------------------------------------------------------------
# CHUNK-2-3 assertion bodies: LaTeX + EPUB per-format gates
# ---------------------------------------------------------------------------
#
# All CHUNK-2-3 assertions operate on Sphinx *write-stage* output (``.tex``
# text / EPUB XHTML) — never a compiled PDF or ``epubcheck`` — so a failure
# points at a doxtr-music emission regression, not external-toolchain drift.

# ``\usepackage`` with an optional ``[opts]`` argument, e.g.
# ``\usepackage[chordbk]{songbook}`` or ``\usepackage{needspace}``.
_USEPACKAGE_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}")


def _needspace_present(content: str) -> AssertionResult:
    """The LaTeX page-break guard ``\\dmneedspace`` is emitted.

    Asserts on ``\\dmneedspace`` (the backend-neutral macro doxtr-music emits
    before each song/section block). The bare ``\\needspace`` primitive lives
    inside the preamble macro *definition*, not at the emission site, so we
    gate on ``\\dmneedspace`` specifically per the CHUNK-2-1 contract.
    """
    a = AssertType.NEEDSPACE_PRESENT
    found = re.search(r"\\dmneedspace\b", content) is not None
    return _result(
        a, found,
        "\\dmneedspace present" if found else "\\dmneedspace not found in .tex",
    )


def _latex_package_loaded(content: str) -> AssertionResult:
    """A LaTeX package is loaded in the preamble.

    Prefers the default ``songbook`` backend (matching the ``song`` feature's
    default ``doxtr_music_latex_package``), accepting the ``[chordbk]``-style
    optional argument. Falls back to *any* ``\\usepackage{...}`` presence so the
    assertion stays config-agnostic (its signature carries no config).
    """
    a = AssertType.LATEX_PACKAGE_LOADED
    packages = _USEPACKAGE_RE.findall(content)
    if "songbook" in packages:
        return _result(a, True, "\\usepackage{songbook} loaded")
    if packages:
        return _result(a, True, "\\usepackage present: %r" % packages[:5])
    return _result(a, False, "no \\usepackage{...} found in preamble")


# EPUB song ``<pre>`` rows (CHUNK-2-2 reflow-safe model): a chord row carrying
# ``aria-hidden`` and a lyric row.
_EPUB_PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.DOTALL)
_CHORDROW_RE = re.compile(r'<span[^>]*class="[^"]*doxtr-chordrow[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
_LYRICROW_RE = re.compile(r'<span[^>]*class="[^"]*doxtr-lyricrow[^"]*"[^>]*>(.*?)</span>', re.DOTALL)


def _strip_tags(fragment: str) -> str:
    """Remove tags, unescape a few entities; used for row text extraction."""
    text = re.sub(r"<[^>]+>", "", fragment)
    for ent, ch in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#160;", " "), ("&nbsp;", " ")):
        text = text.replace(ent, ch)
    return text


def _epub_pre_fallback(content: str) -> AssertionResult:
    """EPUB renders the song as a reflow-safe ``<pre>`` with no absolute CSS.

    Two conditions:

    * The song content includes at least one ``<pre>`` block (the reflow-safe
      fallback that avoids fragile absolute positioning in EPUB readers).
    * No ``position:absolute`` appears anywhere in the EPUB song markup — EPUB
      must not depend on the HTML chord-over-lyric absolute layout.
    """
    a = AssertType.EPUB_PRE_FALLBACK
    if "doxtr-song" not in content:
        return _result(a, False, "no .doxtr-song wrapper found in EPUB XHTML")
    if not _EPUB_PRE_RE.search(content):
        return _result(a, False, "no <pre> reflow-safe block found in EPUB song")
    if re.search(r"position\s*:\s*absolute", content):
        return _result(a, False, "position:absolute present in EPUB song markup")
    return _result(a, True, "reflow-safe <pre> present; no absolute positioning")


def _copy_safe_order_epub_pre(content: str) -> AssertionResult:
    """EPUB ``<pre>`` copy-safety: the lyric row is the copyable lyric stream.

    Operational definition (per the CHUNK-2-2 per-format copy contract):

    * At least one song ``<pre>`` block exists with a ``doxtr-chordrow`` and a
      ``doxtr-lyricrow`` — chords and lyrics are **separate runs**, not
      interleaved on one line.
    * The chord row carries ``aria-hidden`` (non-copyable/AT-hidden decoration)
      and the lyric row does NOT declare ``user-select:none`` (it stays
      selectable/copyable text).
    """
    a = AssertType.COPY_SAFE_ORDER_EPUB_PRE
    blocks = _EPUB_PRE_RE.findall(content)
    if not blocks:
        return _result(a, False, "no <pre> song block found")

    saw_pair = False
    for block in blocks:
        chord_m = _CHORDROW_RE.search(block)
        lyric_m = _LYRICROW_RE.search(block)
        if not (chord_m and lyric_m):
            continue
        saw_pair = True
        # Chord run must be the decorative (aria-hidden) run.
        chord_span = re.search(r'<span[^>]*doxtr-chordrow[^>]*>', block)
        if not chord_span or "aria-hidden" not in chord_span.group(0):
            return _result(a, False, "chord row not marked aria-hidden")
        # Lyric run must remain selectable (not user-select:none).
        lyric_span = re.search(r'<span[^>]*doxtr-lyricrow[^>]*>', block)
        if lyric_span and re.search(r"user-select\s*:\s*none", lyric_span.group(0)):
            return _result(a, False, "lyric row marked user-select:none (not copyable)")

    if not saw_pair:
        return _result(a, False, "no chordrow/lyricrow pair in any <pre> block")
    return _result(
        a, True,
        "copy-safe: chord row aria-hidden decoration; lyric row selectable",
    )


# ---------------------------------------------------------------------------
# CHUNK-3-2 assertion bodies: per-format transposed-chord checks
# ---------------------------------------------------------------------------

# The transpose harness song uses {key: C} + :transpose: 2 over chords
# [C] [Am] [F] [G]. Shifted (up 2 semitones): C→D, Am→Bm, F→G, G→A.
# Discriminators unique to the *shifted* set: Bm, D, A. Discriminators unique
# to the *original* set (must be ABSENT as rendered chord labels): C, Am, F.
_TRANSPOSE_SHIFTED = ("Bm", "D", "A")
_TRANSPOSE_ORIGINAL_ABSENT = ("Am", "C", "F")


def _html_chord_labels(content: str) -> list:
    """Extract rendered chord labels from HTML ``data-chord`` attributes."""
    return re.findall(r'data-chord="([^"]*)"', content)


def _transpose_shifted_html(content: str) -> AssertionResult:
    """HTML shows transposed chord labels, not the pre-transpose originals.

    Reads the rendered ``data-chord`` labels (which reflect the effective
    displayed chord, CHUNK-3-2 render contract): every shifted discriminator
    must be present and every original discriminator absent.
    """
    a = AssertType.TRANSPOSE_SHIFTED_HTML
    labels = _html_chord_labels(content)
    if not labels:
        return _result(a, False, "no data-chord labels found in HTML")
    label_set = set(labels)
    missing = [c for c in _TRANSPOSE_SHIFTED if c not in label_set]
    if missing:
        return _result(a, False, "shifted chords missing: %r (got %r)" % (missing, labels))
    leaked = [c for c in _TRANSPOSE_ORIGINAL_ABSENT if c in label_set]
    if leaked:
        return _result(a, False, "pre-transpose originals still present: %r" % leaked)
    return _result(a, True, "transposed labels present, originals gone: %r" % labels)


def _transpose_shifted_latex(content: str) -> AssertionResult:
    """LaTeX ``\\dmchord`` args show transposed chords, not originals."""
    a = AssertType.TRANSPOSE_SHIFTED_LATEX
    args = re.findall(r"\\dmchord\s*\{([^}]*)\}", content)
    if not args:
        return _result(a, False, "no \\dmchord{...} chord args found in LaTeX")
    arg_set = set(a_.strip() for a_ in args)
    missing = [c for c in _TRANSPOSE_SHIFTED if c not in arg_set]
    if missing:
        return _result(a, False, "shifted chords missing in \\dmchord: %r (got %r)" % (missing, args))
    leaked = [c for c in _TRANSPOSE_ORIGINAL_ABSENT if c in arg_set]
    if leaked:
        return _result(a, False, "pre-transpose originals still in \\dmchord: %r" % leaked)
    return _result(a, True, "transposed \\dmchord args present, originals gone: %r" % args)


def _transpose_shifted_epub(content: str) -> AssertionResult:
    """EPUB ``<pre>`` chord rows show transposed chords, not originals."""
    a = AssertType.TRANSPOSE_SHIFTED_EPUB
    blocks = _EPUB_PRE_RE.findall(content)
    if not blocks:
        return _result(a, False, "no <pre> song block found in EPUB")
    chord_text = ""
    for block in blocks:
        for m in _CHORDROW_RE.finditer(block):
            chord_text += _strip_tags(m.group(1)) + " "
    if not chord_text.strip():
        # Fall back to whole-pre text if chordrow spans are laid out differently.
        chord_text = " ".join(_strip_tags(b) for b in blocks)
    tokens = set(chord_text.split())
    missing = [c for c in _TRANSPOSE_SHIFTED if c not in tokens]
    if missing:
        return _result(a, False, "shifted chords missing in EPUB chord row: %r (got %r)" % (missing, chord_text.strip()))
    leaked = [c for c in _TRANSPOSE_ORIGINAL_ABSENT if c in tokens]
    if leaked:
        return _result(a, False, "pre-transpose originals still in EPUB chord row: %r" % leaked)
    return _result(a, True, "transposed chords present in EPUB chord row, originals gone")


# ---------------------------------------------------------------------------
# CHUNK-3-3 assertion bodies: ROMAN_REPLACE_{HTML,LATEX,EPUB}
# ---------------------------------------------------------------------------
#
# The roman fixture is [C][Am][F][G] in C major with :roman-numerals:. Replace
# mode (LOCKED): the chord-row content becomes the numeral. Expected numerals:
#   C  -> I     Am -> vi    F -> IV    G -> V
# Discriminators: the numerals must appear as the visible chord label; the
# English chord names must NOT appear as the visible chord text (HTML keeps them
# only in ``data-chord``; LaTeX/EPUB drop them entirely).
_ROMAN_EXPECTED = ("I", "vi", "IV", "V")

# Visible chord-span text in HTML: <span class=doxtr-chord ...>TEXT</span>.
_HTML_CHORD_TEXT_RE = re.compile(
    r'<span[^>]*class="[^"]*doxtr-chord[^"]*"[^>]*>(.*?)</span>', re.DOTALL
)


def _roman_replace_html(content: str) -> AssertionResult:
    """HTML chord-row shows the roman numerals as the visible chord text.

    The numerals must be the *visible* span text (replace mode); the English
    chord names stay in ``data-chord`` (source recoverability) but must not be
    the visible label.
    """
    a = AssertType.ROMAN_REPLACE_HTML
    visible = [_strip_tags(t).strip() for t in _HTML_CHORD_TEXT_RE.findall(content)]
    visible = [v for v in visible if v]
    if not visible:
        return _result(a, False, "no visible .doxtr-chord text found in HTML")
    vis_set = set(visible)
    missing = [r for r in _ROMAN_EXPECTED if r not in vis_set]
    if missing:
        return _result(a, False, "roman numerals missing from chord text: %r (got %r)"
                       % (missing, visible))
    # English chord names must not be the visible chord text (data-chord is fine).
    leaked = [c for c in ("C", "Am", "F", "G") if c in vis_set]
    if leaked:
        return _result(a, False, "English chord names still visible as chord text: %r"
                       % leaked)
    return _result(a, True, "roman numerals replace chord labels in HTML: %r" % visible)


def _roman_replace_latex(content: str) -> AssertionResult:
    """LaTeX ``\\dmchord`` args show the roman numerals, not the English chords."""
    a = AssertType.ROMAN_REPLACE_LATEX
    args = re.findall(r"\\dmchord\s*\{([^}]*)\}", content)
    if not args:
        return _result(a, False, "no \\dmchord{...} args found in LaTeX")
    arg_set = set(a_.strip() for a_ in args)
    missing = [r for r in _ROMAN_EXPECTED if r not in arg_set]
    if missing:
        return _result(a, False, "roman numerals missing in \\dmchord: %r (got %r)"
                       % (missing, args))
    leaked = [c for c in ("C", "Am", "F", "G") if c in arg_set]
    if leaked:
        return _result(a, False, "English chords still in \\dmchord args: %r" % leaked)
    return _result(a, True, "roman numerals in \\dmchord args: %r" % args)


def _roman_replace_epub(content: str) -> AssertionResult:
    """EPUB ``<pre>`` chord row shows the roman numerals, not the English chords."""
    a = AssertType.ROMAN_REPLACE_EPUB
    blocks = _EPUB_PRE_RE.findall(content)
    if not blocks:
        return _result(a, False, "no <pre> song block found in EPUB")
    chord_text = ""
    for block in blocks:
        for m in _CHORDROW_RE.finditer(block):
            chord_text += _strip_tags(m.group(1)) + " "
    if not chord_text.strip():
        chord_text = " ".join(_strip_tags(b) for b in blocks)
    tokens = set(chord_text.split())
    missing = [r for r in _ROMAN_EXPECTED if r not in tokens]
    if missing:
        return _result(a, False, "roman numerals missing in EPUB chord row: %r (got %r)"
                       % (missing, chord_text.strip()))
    leaked = [c for c in ("C", "Am", "F", "G") if c in tokens]
    if leaked:
        return _result(a, False, "English chords still in EPUB chord row: %r" % leaked)
    return _result(a, True, "roman numerals replace chord labels in EPUB chord row")


# ---------------------------------------------------------------------------
# CHUNK-3-4 assertion bodies: I18N_GERMAN_{HTML,LATEX,EPUB} + RTL fallbacks
# ---------------------------------------------------------------------------
#
# The i18n fixture is [Bb] [B] [F#] [Eb] under doxtr_music_chord_system="german".
# German localization (LOCKED map): Bb->B, B->H, F#->Fis, Eb->Es. Discriminators:
#   * the German spellings appear as the VISIBLE chord label (HTML span text,
#     LaTeX \dmchord arg, EPUB chord row);
#   * H / Fis / Es must be present (proving the map fired, root-keyed);
#   * the raw English "B" (natural) and "F#" must NOT be the visible label
#     (they localized to H / Fis). "Bb" localizes to "B", which is a legitimate
#     German label, so we assert on the distinctive H/Fis/Es forms.
_GERMAN_EXPECTED = ("B", "H", "Fis", "Es")
#: English spellings that must NOT survive as the visible label (they localize).
_GERMAN_ENGLISH_LEAK = ("F#", "Eb")


def _i18n_german_html(content: str) -> AssertionResult:
    """HTML chord spans show the German-localized labels (B/H/Fis/Es)."""
    a = AssertType.I18N_GERMAN_HTML
    visible = [_strip_tags(t).strip() for t in _HTML_CHORD_TEXT_RE.findall(content)]
    visible = [v for v in visible if v]
    if not visible:
        return _result(a, False, "no visible .doxtr-chord text found in HTML")
    vis_set = set(visible)
    missing = [g for g in _GERMAN_EXPECTED if g not in vis_set]
    if missing:
        return _result(a, False, "German labels missing from chord text: %r (got %r)"
                       % (missing, visible))
    leaked = [c for c in _GERMAN_ENGLISH_LEAK if c in vis_set]
    if leaked:
        return _result(a, False, "English spellings still visible (not localized): %r"
                       % leaked)
    return _result(a, True, "German localization applied in HTML chord text: %r" % visible)


def _i18n_german_latex(content: str) -> AssertionResult:
    """LaTeX \\dmchord args show the German-localized labels."""
    a = AssertType.I18N_GERMAN_LATEX
    args = re.findall(r"\\dmchord\s*\{([^}]*)\}", content)
    if not args:
        return _result(a, False, "no \\dmchord{...} args found in LaTeX")
    arg_set = set(a_.strip() for a_ in args)
    missing = [g for g in _GERMAN_EXPECTED if g not in arg_set]
    if missing:
        return _result(a, False, "German labels missing in \\dmchord: %r (got %r)"
                       % (missing, args))
    leaked = [c for c in _GERMAN_ENGLISH_LEAK if c in arg_set]
    if leaked:
        return _result(a, False, "English spellings still in \\dmchord args: %r" % leaked)
    return _result(a, True, "German localization in \\dmchord args: %r" % args)


def _i18n_german_epub(content: str) -> AssertionResult:
    """EPUB <pre> chord row shows the German-localized labels."""
    a = AssertType.I18N_GERMAN_EPUB
    blocks = _EPUB_PRE_RE.findall(content)
    if not blocks:
        return _result(a, False, "no <pre> song block found in EPUB")
    chord_text = ""
    for block in blocks:
        for m in _CHORDROW_RE.finditer(block):
            chord_text += _strip_tags(m.group(1)) + " "
    if not chord_text.strip():
        chord_text = " ".join(_strip_tags(b) for b in blocks)
    tokens = set(chord_text.split())
    missing = [g for g in _GERMAN_EXPECTED if g not in tokens]
    if missing:
        return _result(a, False, "German labels missing in EPUB chord row: %r (got %r)"
                       % (missing, chord_text.strip()))
    leaked = [c for c in _GERMAN_ENGLISH_LEAK if c in tokens]
    if leaked:
        return _result(a, False, "English spellings still in EPUB chord row: %r" % leaked)
    return _result(a, True, "German localization applied in EPUB chord row")


# --- RTL ---------------------------------------------------------------------
#
# The RTL fixture is a .. song:: with Hebrew lyrics under a chord. HTML keeps the
# ``dir="auto"`` wrapper + logical-only CSS; LaTeX/EPUB use a documented+tested
# fallback (song macros / reflow-safe <pre> present, build never crashes).

# Physical-direction CSS properties that MUST NOT appear (logical-only mandate).
_PHYSICAL_CSS_RE = re.compile(
    r"(?<![-\w])(?:left|right)\s*:", re.IGNORECASE
)
#: Logical properties the chord layout must use instead.
_LOGICAL_CSS_TOKENS = ("inset-inline-start", "text-align: start", "text-align:start")


def _dir_auto_present(content: str) -> AssertionResult:
    """``dir="auto"`` is present on the song wrapper (RTL support)."""
    a = AssertType.DIR_AUTO_PRESENT
    found = 'dir="auto"' in content
    return _result(
        a, found,
        'dir="auto" present' if found else 'no dir="auto" on song wrapper',
    )


def _rtl_logical_css(content: str) -> AssertionResult:
    """RTL HTML: dir=auto present AND the packaged CSS uses logical props only."""
    a = AssertType.RTL_LOGICAL_CSS
    if 'dir="auto"' not in content:
        return _result(a, False, 'no dir="auto" on song wrapper')
    css = _packaged_css()
    if css is None:
        return _result(a, False, "packaged CSS not found for logical-property check")
    # No physical left:/right: rules (physical alignment would break RTL flip).
    physical = _PHYSICAL_CSS_RE.findall(css)
    if physical:
        return _result(a, False, "physical CSS direction props present: %r" % physical)
    # At least one logical property must be used for chord positioning.
    if not any(tok in css for tok in _LOGICAL_CSS_TOKENS):
        return _result(a, False, "no logical CSS positioning props found")
    return _result(a, True, 'dir="auto" + logical-only CSS (no physical left/right)')


def _rtl_fallback_latex(content: str) -> AssertionResult:
    """RTL LaTeX documented fallback: song macros emitted verbatim, no crash.

    The build completing (content non-empty) proves no crash; the presence of the
    ``\\dmchord`` / ``\\dmlyric`` macros proves the song rendered verbatim. The
    RTL warning itself is asserted at the build/runner level (stderr), not here.
    """
    a = AssertType.RTL_FALLBACK_LATEX
    if not content.strip():
        return _result(a, False, "empty LaTeX output (build did not complete)")
    has_macro = ("\\dmchord" in content) or ("\\dmlyric" in content)
    if not has_macro:
        return _result(a, False, "no \\dmchord/\\dmlyric song macros in LaTeX")
    return _result(a, True, "RTL lyrics emitted verbatim via song macros (no crash)")


def _rtl_fallback_epub(content: str) -> AssertionResult:
    """RTL EPUB documented fallback: reflow-safe <pre> + dir=auto, no crash."""
    a = AssertType.RTL_FALLBACK_EPUB
    if not content.strip():
        return _result(a, False, "empty EPUB output (build did not complete)")
    if not _EPUB_PRE_RE.search(content):
        return _result(a, False, "no reflow-safe <pre> song block in EPUB")
    if 'dir="auto"' not in content:
        return _result(a, False, 'no dir="auto" on EPUB song wrapper')
    return _result(a, True, 'RTL EPUB reflow-safe <pre> + dir="auto" (no crash)')


# ---------------------------------------------------------------------------
# CHUNK-3-5 assertion bodies: ROLES_{HTML,LATEX,EPUB}
# ---------------------------------------------------------------------------
#
# The roles fixture uses :chord:`G7`, :key:`Bb`, :roman:`IV`, :key:`Bm`,
# :chord:`Cmaj7` under the default (english) chord system. Discriminators:
#   * HTML  — a .doxtr-chord-inline span (NOT aria-hidden), a .doxtr-key span,
#            a .doxtr-roman span; the role chord must NOT carry the positioned
#            song .doxtr-chord class markers (aria-hidden) around its glyph.
#   * LaTeX — \dmchordinline{G7}, \dmkey{Bb}, \dmroman{IV} emitted.
#   * EPUB  — inline .doxtr-chord-inline / .doxtr-key / .doxtr-roman spans,
#            outside any song two-row <pre> block.

_CHORD_INLINE_RE = re.compile(
    r'<span[^>]*class="[^"]*doxtr-chord-inline[^"]*"[^>]*>(.*?)</span>', re.DOTALL
)
_KEY_SPAN_RE = re.compile(
    r'<span[^>]*class="[^"]*doxtr-key[^"]*"[^>]*>(.*?)</span>', re.DOTALL
)
_ROMAN_SPAN_RE = re.compile(
    r'<span[^>]*class="[^"]*doxtr-roman[^"]*"[^>]*>(.*?)</span>', re.DOTALL
)


def _roles_html(content: str) -> AssertionResult:
    """HTML inline roles: distinct chord-inline (no aria-hidden), key, roman."""
    a = AssertType.ROLES_HTML
    chord_spans = re.findall(
        r'(<span[^>]*class="[^"]*doxtr-chord-inline[^"]*"[^>]*>)', content
    )
    if not chord_spans:
        return _result(a, False, "no .doxtr-chord-inline span found in HTML")
    # The prose chord span must NOT carry aria-hidden (readable prose, not a
    # positioned song chord).
    leaked = [s for s in chord_spans if "aria-hidden" in s]
    if leaked:
        return _result(a, False, "prose chord span carries aria-hidden: %r" % leaked)
    chord_text = [_strip_tags(t).strip() for t in _CHORD_INLINE_RE.findall(content)]
    if "G7" not in chord_text:
        return _result(a, False, "inline chord G7 not rendered: %r" % chord_text)
    key_text = [_strip_tags(t).strip() for t in _KEY_SPAN_RE.findall(content)]
    if "Bb" not in key_text:
        return _result(a, False, "inline key Bb not rendered: %r" % key_text)
    roman_text = [_strip_tags(t).strip() for t in _ROMAN_SPAN_RE.findall(content)]
    if "IV" not in roman_text:
        return _result(a, False, "inline roman IV not rendered: %r" % roman_text)
    return _result(
        a, True,
        "inline chord/key/roman spans present; chord-inline has no aria-hidden",
    )


def _roles_latex(content: str) -> AssertionResult:
    """LaTeX inline roles: \\dmchordinline / \\dmkey / \\dmroman emitted."""
    a = AssertType.ROLES_LATEX
    inline = re.findall(r"\\dmchordinline\s*\{([^}]*)\}", content)
    keys = re.findall(r"\\dmkey\s*\{([^}]*)\}", content)
    romans = re.findall(r"\\dmroman\s*\{([^}]*)\}", content)
    if "G7" not in [x.strip() for x in inline]:
        return _result(a, False, "\\dmchordinline{G7} not found: %r" % inline)
    if "Bb" not in [x.strip() for x in keys]:
        return _result(a, False, "\\dmkey{Bb} not found: %r" % keys)
    if "IV" not in [x.strip() for x in romans]:
        return _result(a, False, "\\dmroman{IV} not found: %r" % romans)
    return _result(
        a, True,
        "inline role macros present: \\dmchordinline/\\dmkey/\\dmroman",
    )


def _roles_epub(content: str) -> AssertionResult:
    """EPUB inline roles: chord-inline / key / roman inline spans, not in <pre>.

    The role spans must be rendered inline in normal flow, NOT inside the song
    two-row ``<pre>`` layout (which is for song lines). We check the spans exist
    and that they are not swallowed inside a ``<pre>`` block.
    """
    a = AssertType.ROLES_EPUB
    chord_text = [_strip_tags(t).strip() for t in _CHORD_INLINE_RE.findall(content)]
    key_text = [_strip_tags(t).strip() for t in _KEY_SPAN_RE.findall(content)]
    roman_text = [_strip_tags(t).strip() for t in _ROMAN_SPAN_RE.findall(content)]
    if "G7" not in chord_text:
        return _result(a, False, "inline chord G7 not rendered in EPUB: %r" % chord_text)
    if "Bb" not in key_text:
        return _result(a, False, "inline key Bb not rendered in EPUB: %r" % key_text)
    if "IV" not in roman_text:
        return _result(a, False, "inline roman IV not rendered in EPUB: %r" % roman_text)
    # The role chord must not be laid out inside a song <pre> two-row block.
    for block in _EPUB_PRE_RE.findall(content):
        if "doxtr-chord-inline" in block:
            return _result(a, False, "inline chord role wrongly placed inside a <pre> block")
    return _result(a, True, "inline chord/key/roman spans present in normal EPUB flow")


# ---------------------------------------------------------------------------
# CHUNK-4-1 assertion bodies: TYPOGRAPHY_APPLIED_{HTML,LATEX,EPUB}
# ---------------------------------------------------------------------------
#
# The typography fixture sets a GLOBAL chord color (#cc0000) and per-song
# overrides (:lyrics-color: #0000cc, :chord-font: monospace, :title-color:
# #008000). The per-format checks verify BOTH mechanisms: the global element
# rule AND the per-song per-attr override, with the per-song override NOT
# leaking onto the element it did not target.

# Per-song colors chosen so they can't be confused with the global chord color.
_TYPO_GLOBAL_CHORD_COLOR = "#cc0000"
_TYPO_SONG_LYRIC_COLOR = "#0000cc"
_TYPO_SONG_TITLE_COLOR = "#008000"

# The injected global <style> block + a per-song inline style carrying the
# lyric color (proves per-song rides inline style, not shared class CSS).
_TYPO_STYLE_BLOCK_RE = re.compile(
    r'<style[^>]*class="doxtr-music-typography"[^>]*>(.*?)</style>', re.DOTALL
)
_LYRIC_SPAN_STYLE_RE = re.compile(
    r'<span class="doxtr-lyric"([^>]*)>', re.DOTALL
)


def _typography_applied_html(content: str) -> AssertionResult:
    """HTML: global <style> block colors chords; per-song inline styles lyrics.

    Verifies both LaTeX-analog mechanisms in HTML terms:
      * GLOBAL: an injected ``.doxtr-music-typography`` <style> block carrying
        the global chord color rule.
      * PER-SONG: at least one ``.doxtr-lyric`` span with an inline
        ``style`` carrying the per-song lyric color (proves inline, not class).
      * Styling-only: the chord's per-song ``:chord-font:`` did NOT set a lyric
        color and vice versa (per-attr merge, no cross-leak).
    """
    a = AssertType.TYPOGRAPHY_APPLIED_HTML
    blocks = _TYPO_STYLE_BLOCK_RE.findall(content)
    if not blocks:
        return _result(a, False, "no injected .doxtr-music-typography <style> block found")
    global_css = "\n".join(blocks)
    if _TYPO_GLOBAL_CHORD_COLOR not in global_css.replace(" ", ""):
        return _result(a, False,
                       "global chord color %s not in <style> block: %r"
                       % (_TYPO_GLOBAL_CHORD_COLOR, global_css))
    # Per-song lyric color must appear as an INLINE style on a lyric span.
    lyric_styles = [m for m in _LYRIC_SPAN_STYLE_RE.findall(content) if "style=" in m]
    joined = " ".join(lyric_styles).replace(" ", "")
    if _TYPO_SONG_LYRIC_COLOR not in joined:
        return _result(a, False,
                       "per-song lyric color %s not found as inline style on a "
                       ".doxtr-lyric span: %r"
                       % (_TYPO_SONG_LYRIC_COLOR, lyric_styles))
    # Cross-leak guard: the global chord color must NOT be inlined onto lyrics.
    if _TYPO_GLOBAL_CHORD_COLOR in joined:
        return _result(a, False,
                       "global chord color leaked onto lyric inline style")
    return _result(a, True,
                   "global chord <style> + per-song inline lyric color applied "
                   "(per-attr merge, no cross-leak)")


def _typography_applied_latex(content: str) -> AssertionResult:
    r"""LaTeX: global \renewcommand of \dmchordcolor + per-song scoped \def group.

    Verifies the LOCKED two-mechanism model:
      * GLOBAL: a preamble ``\renewcommand{\dmchordcolor}{...}`` (from the
        typography preamble contributor) — proves the indirection macro is set
        globally, not via raw ``latex_elements``.
      * PER-SONG: a ``\begingroup% doxtr-music song typography`` scoped group
        that ``\def``s only the overridden attr-macros (e.g. ``\dmlyriccolor``
        for :lyrics-color:), inheriting global for the rest, and a matching
        ``\endgroup``.
    """
    a = AssertType.TYPOGRAPHY_APPLIED_LATEX
    if not content.strip():
        return _result(a, False, "empty LaTeX output (build did not complete)")
    if not re.search(r"\\renewcommand\{\\dmchordcolor\}", content):
        return _result(a, False,
                       r"no global \renewcommand{\dmchordcolor} in preamble")
    if "\\begingroup% doxtr-music song typography" not in content:
        return _result(a, False,
                       "no per-song scoped typography \\begingroup group")
    if "\\endgroup% doxtr-music song typography" not in content:
        return _result(a, False,
                       "per-song typography group not closed with \\endgroup")
    # The per-song group must \def the overridden lyric color macro.
    if not re.search(r"\\def\\dmlyriccolor", content):
        return _result(a, False,
                       r"per-song :lyrics-color: did not \def \dmlyriccolor")
    return _result(a, True,
                   r"global \renewcommand + per-song scoped \def group present")


def _typography_applied_epub(content: str) -> AssertionResult:
    """EPUB: global <style> block + per-song inline style on the <pre> rows.

    Verifies the EPUB two-row model carries typography:
      * GLOBAL: an injected ``.doxtr-music-typography`` <style> block.
      * PER-SONG: an inline ``style`` on the lyric-row span carrying the
        per-song lyric color, with a RELATIVE (em/rem/%) size when a size is
        present (reflow-safe) — here we only assert the color rides inline.
    """
    a = AssertType.TYPOGRAPHY_APPLIED_EPUB
    blocks = _TYPO_STYLE_BLOCK_RE.findall(content)
    if not blocks:
        return _result(a, False, "no injected .doxtr-music-typography <style> block in EPUB")
    # Per-song lyric color inline on the .doxtr-lyricrow span.
    rows = re.findall(r'<span class="doxtr-lyricrow"([^>]*)>', content)
    joined = " ".join(rows).replace(" ", "")
    if _TYPO_SONG_LYRIC_COLOR not in joined:
        return _result(a, False,
                       "per-song lyric color %s not found as inline style on a "
                       ".doxtr-lyricrow span: %r"
                       % (_TYPO_SONG_LYRIC_COLOR, rows))
    # No absolute pt should ride an EPUB inline style (reflow-safe downgrade).
    if re.search(r"font-size:\s*[0-9.]+pt", " ".join(rows)):
        return _result(a, False,
                       "absolute pt font-size leaked into EPUB inline style")
    return _result(a, True,
                   "global <style> + per-song inline lyric color on <pre> rows")


# ---------------------------------------------------------------------------
# CHUNK-4-2 assertion bodies: SINGER_COLOR_APPLIED_{HTML,LATEX,EPUB}
# ---------------------------------------------------------------------------
#
# The multi_singer fixture sets a per-song :chord-color: #cc0000 typography and
# a :chord-font: monospace, then attributes two runs to singers A and B whose
# colors come from :singer-colors: A: #1a53a1, B: #e07b00. The per-format checks
# verify the LOCKED "resolve in Python, emit once + singer wins on color, font
# stays" invariant: the singer colors appear on the chord/lyric elements, the
# typography chord color #cc0000 does NOT win on those elements, and the
# typography font (monospace) is still applied.

_SINGER_COLOR_A = "#1a53a1"
_SINGER_COLOR_B = "#e07b00"
_SINGER_TYPO_CHORD_COLOR = "#cc0000"


def _singer_color_applied_html(content: str) -> AssertionResult:
    """HTML: singer color wins over typography color, emitted once per element.

    Requires (all):
      * A ``data-singer`` hook on a ``.doxtr-singer`` span (the machine hook).
      * Both singer colors appear as an INLINE ``style`` color on chord/lyric
        elements (resolved in Python, one inline color per element).
      * The typography chord color (#cc0000) does NOT appear on any element that
        also carries a singer color (singer wins on color).
      * The typography font (monospace) is still applied (font/size unchanged).
    """
    a = AssertType.SINGER_COLOR_APPLIED_HTML
    if "data-singer=" not in content:
        return _result(a, False, "no data-singer hook on a .doxtr-singer span")
    # Collect inline styles on chord + lyric elements.
    styles = re.findall(
        r'<span class="doxtr-(?:chord|lyric)"[^>]*style="([^"]*)"[^>]*>',
        content,
    )
    joined = " ".join(styles).replace(" ", "")
    if _SINGER_COLOR_A not in joined or _SINGER_COLOR_B not in joined:
        return _result(
            a, False,
            "singer colors %s/%s not both present as inline chord/lyric colors: %r"
            % (_SINGER_COLOR_A, _SINGER_COLOR_B, styles),
        )
    # Singer wins: no chord/lyric element should carry the typography chord
    # color once a singer color applies (every song element here is in a singer
    # run, so the typography color must be fully overridden).
    if ("color:%s" % _SINGER_TYPO_CHORD_COLOR) in joined:
        return _result(
            a, False,
            "typography color %s survived on a singer-colored element "
            "(singer must win on color)" % _SINGER_TYPO_CHORD_COLOR,
        )
    # Font from typography still applies (styling-only collision is color).
    if "font-family:monospace" not in joined:
        return _result(
            a, False,
            "typography font (monospace) missing on singer-colored elements "
            "(font/size must survive)",
        )
    return _result(
        a, True,
        "singer colors win on color, emitted once inline; typography font kept",
    )


def _singer_color_applied_latex(content: str) -> AssertionResult:
    r"""LaTeX: \dmsinger scopes the run's indirection color macros to the winner.

    Requires (all):
      * A scoped ``\begingroup``…``\endgroup`` singer-color group around each
        colored word (emitted comment-free so inline words never comment out a
        following ``\begingroup``).
      * A ``\definecolor{dm@word*color}{HTML}{...}`` for each singer color and
        a ``\def\dmchordcolor{\color{dm@wordchordcolor}}`` +
        ``\def\dmlyriccolor{\color{dm@wordlyriccolor}}`` inside the group
        (the run scopes the per-word indirection macros -- NOT an outer \color).
    """
    a = AssertType.SINGER_COLOR_APPLIED_LATEX
    if not content.strip():
        return _result(a, False, "empty LaTeX output (build did not complete)")
    # The colored word is scoped by \def'ing the indirection macros inside a
    # \begingroup group; the group wraps a rendered \dmchord / \dmlyric word.
    if not re.search(
        r"\\def\\dmlyriccolor\{\\color\{dm@wordlyriccolor\}\}\\dm(chord|lyric)",
        content,
    ):
        return _result(
            a, False, "no scoped singer-color group around a rendered word"
        )
    # Both singer colors defined (HTML hex uppercased by normalize_latex_color).
    hexa = _SINGER_COLOR_A[1:].upper()
    hexb = _SINGER_COLOR_B[1:].upper()
    if not (("{HTML}{%s}" % hexa) in content and ("{HTML}{%s}" % hexb) in content):
        return _result(
            a, False,
            "missing \\definecolor for a singer color (%s/%s)" % (hexa, hexb),
        )
    # The run sets the indirection color macros (singer wins via \dmchord's own
    # indirection), not an outer \color.
    if not re.search(r"\\def\\dmchordcolor\{\\color\{dm@wordchordcolor\}\}", content):
        return _result(
            a, False,
            r"singer run did not \def \dmchordcolor to the resolved color",
        )
    if not re.search(r"\\def\\dmlyriccolor\{\\color\{dm@wordlyriccolor\}\}", content):
        return _result(
            a, False,
            r"singer run did not \def \dmlyriccolor to the resolved color",
        )
    return _result(
        a, True,
        r"\dmsinger scopes \dmchordcolor/\dmlyriccolor to the resolved winner",
    )


def _singer_color_applied_epub(content: str) -> AssertionResult:
    """EPUB: both <pre> rows carry singer-colored cell sub-ranges (singer wins).

    Requires (all):
      * At least one song ``<pre>`` block with a chord row + lyric row.
      * Both singer colors appear as inner ``<span style="color:...">`` segments
        inside the row spans -- proving the run is colored on BOTH the chord row
        and the lyric row (the two-row model, not "same as HTML").
      * The lyric row is still selectable (not user-select:none) -- copy-safety.
    """
    a = AssertType.SINGER_COLOR_APPLIED_EPUB
    blocks = _EPUB_PRE_RE.findall(content)
    if not blocks:
        return _result(a, False, "no <pre> song block found in EPUB XHTML")
    chord_row_text = []
    lyric_row_text = []
    for block in blocks:
        cm = _CHORDROW_RE.search(block)
        lm = _LYRICROW_RE.search(block)
        if cm:
            chord_row_text.append(cm.group(1))
        if lm:
            lyric_row_text.append(lm.group(1))
        # Lyric row must remain selectable.
        lyric_span = re.search(r'<span[^>]*doxtr-lyricrow[^>]*>', block)
        if lyric_span and re.search(r"user-select\s*:\s*none", lyric_span.group(0)):
            return _result(a, False, "lyric row marked user-select:none")
    chord_joined = " ".join(chord_row_text).replace(" ", "")
    lyric_joined = " ".join(lyric_row_text).replace(" ", "")
    # Both singer colors must appear on the CHORD row (chord-row cell ranges).
    if _SINGER_COLOR_A not in chord_joined or _SINGER_COLOR_B not in chord_joined:
        return _result(
            a, False,
            "singer colors not both present as chord-row cell sub-ranges",
        )
    # ...and on the LYRIC row (proving BOTH rows are colored, not just HTML-like).
    if _SINGER_COLOR_A not in lyric_joined or _SINGER_COLOR_B not in lyric_joined:
        return _result(
            a, False,
            "singer colors not both present as lyric-row cell sub-ranges "
            "(both rows must be colored)",
        )
    return _result(
        a, True,
        "singer colors applied to both chord-row and lyric-row cell sub-ranges",
    )


# ---------------------------------------------------------------------------
# CHUNK-4-3 assertion bodies: WCAG a11y (HTML + EPUB)
# ---------------------------------------------------------------------------

#: A ``.doxtr-chord`` song-chord span (NOT the ``.doxtr-chord-inline`` prose
#: chord, which is exempt). Matches the opening tag so we can inspect its attrs.
_CHORD_SPAN_RE = re.compile(r'<span\b([^>]*\bclass="[^"]*\bdoxtr-chord\b[^"]*"[^>]*)>')
_SONG_DIV_RE = re.compile(r'<div\b([^>]*\bclass="[^"]*\bdoxtr-song\b[^"]*"[^>]*)>')


def _attr(tag_attrs: str, name: str):
    """Return the value of attribute ``name`` in a tag's attr string, or None."""
    m = re.search(r'\b%s="([^"]*)"' % re.escape(name), tag_attrs)
    return m.group(1) if m else None


def _aria_label_present(content: str) -> AssertionResult:
    """Every song-chord span carries ``role="img"`` + a non-empty ``aria-label``.

    Pinned DOM check (CHUNK-4-3 exit criterion): scans every ``.doxtr-chord``
    span (the positioned song chord; the ``.doxtr-chord-inline`` prose chord is
    exempt and not matched here). Each must declare ``role="img"`` and a
    non-empty ``aria-label`` so screen readers announce the chord atomically. At
    least one chord span must exist.
    """
    a = AssertType.ARIA_LABEL_PRESENT
    # Exclude the inline prose chord class from the song-chord scan.
    spans = [
        attrs for attrs in _CHORD_SPAN_RE.findall(content)
        if "doxtr-chord-inline" not in (_attr(attrs, "class") or "")
    ]
    if not spans:
        return _result(a, False, "no .doxtr-chord song-chord span found")
    for attrs in spans:
        if _attr(attrs, "role") != "img":
            return _result(a, False, 'a .doxtr-chord lacks role="img"')
        label = _attr(attrs, "aria-label")
        if not label or not label.strip():
            return _result(a, False, "a .doxtr-chord has empty/missing aria-label")
    return _result(
        a, True,
        'all %d .doxtr-chord spans have role="img" + non-empty aria-label'
        % len(spans),
    )


def _role_group_present(content: str) -> AssertionResult:
    """Each song wrapper is a named ``role="group"``.

    Pinned DOM check (CHUNK-4-3 exit criterion): every ``.doxtr-song`` wrapper
    must declare ``role="group"`` AND be named either by ``aria-labelledby``
    pointing at an existing, non-empty ``id`` in the document, or by a non-empty
    ``aria-label`` (the titleless fallback). At least one song wrapper must
    exist.
    """
    a = AssertType.ROLE_GROUP_PRESENT
    songs = _SONG_DIV_RE.findall(content)
    if not songs:
        return _result(a, False, "no .doxtr-song wrapper found")
    all_ids = set(re.findall(r'\bid="([^"]+)"', content))
    for attrs in songs:
        if _attr(attrs, "role") != "group":
            return _result(a, False, 'a .doxtr-song lacks role="group"')
        labelledby = _attr(attrs, "aria-labelledby")
        label = _attr(attrs, "aria-label")
        if labelledby and labelledby.strip():
            # Every referenced id must exist and be non-empty.
            refs = [r for r in labelledby.split() if r]
            if not refs or any(r not in all_ids for r in refs):
                return _result(
                    a, False,
                    "aria-labelledby %r points at a missing id" % labelledby,
                )
        elif not (label and label.strip()):
            return _result(
                a, False,
                "a .doxtr-song has neither a valid aria-labelledby nor aria-label",
            )
    return _result(
        a, True,
        "all %d .doxtr-song wrappers are named role=group" % len(songs),
    )


def _progression_table_html(content: str) -> AssertionResult:
    """CHUNK-4-4: HTML progression is a semantic ``<table>``.

    Verifies the ``doxtr-progression`` class, a ``<caption>`` (data-table
    semantics for a11y), and at least one ``<td>`` cell. Also confirms the grid
    contains NO chord-over-lyric ``<pre>`` (a progression has no lyrics).
    """
    a = AssertType.PROGRESSION_TABLE_HTML
    if 'class="doxtr-progression"' not in content:
        return _result(a, False, 'no class="doxtr-progression" table found')
    if "<caption" not in content:
        return _result(a, False, "progression table has no <caption> (a11y)")
    if "<td" not in content:
        return _result(a, False, "progression table has no <td> cells")
    return _result(
        a, True, "semantic <table> with caption + <td> cells present"
    )


def _progression_table_latex(content: str) -> AssertionResult:
    """CHUNK-4-4: LaTeX progression is a standard ``tabular`` with cell macros.

    Verifies ``\\begin{tabular}`` and at least one cell macro
    (``\\dmchordinline`` or ``\\dmroman``).
    """
    a = AssertType.PROGRESSION_TABLE_LATEX
    if "\\begin{tabular}" not in content:
        return _result(a, False, "no \\begin{tabular} found for progression")
    if "\\dmchordinline" not in content and "\\dmroman" not in content:
        return _result(
            a, False,
            "tabular present but no \\dmchordinline/\\dmroman cell macro",
        )
    return _result(a, True, "tabular with \\dmchordinline/\\dmroman cells present")


def _progression_table_epub(content: str) -> AssertionResult:
    """CHUNK-4-4: EPUB progression is a genuine XHTML ``<table>`` (not ``<pre>``).

    Verifies the ``doxtr-progression`` class, a ``<caption>`` and ``<td>`` cells.
    """
    a = AssertType.PROGRESSION_TABLE_EPUB
    if 'class="doxtr-progression"' not in content:
        return _result(a, False, 'no class="doxtr-progression" table found')
    if "<caption" not in content:
        return _result(a, False, "progression table has no <caption> (a11y)")
    if "<td" not in content:
        return _result(a, False, "progression table has no <td> cells")
    return _result(
        a, True, "semantic XHTML <table> with caption + <td> cells present"
    )


# ---------------------------------------------------------------------------
# CHUNK-5-3 assertion bodies: SONG_LIST_XREF_RESOLVES / EMPTY_STATE / XREF_LATEX
# ---------------------------------------------------------------------------
#
# The resolved song-list/index output is STANDARD docutils nodes rendered by
# Sphinx's own writers, wrapped in a container carrying the
# ``doxtr-song-list``/``doxtr-song-index`` class. These checks confirm the
# resolve-phase replacement fired (no leftover placeholder) and that the
# emitted links target real in-document anchors.

_HREF_RE = re.compile(r'<a[^>]*\bhref="([^"]*)"', re.DOTALL)
_ID_ATTR_RE = re.compile(r'\bid="([^"]+)"')


def _song_list_container(content: str) -> bool:
    """True when a resolved song-list/index container is present."""
    return (
        "doxtr-song-list" in content or "doxtr-song-index" in content
    )


def _song_list_xref_resolves(content: str) -> AssertionResult:
    """HTML/EPUB: song-list/index links target a real in-document anchor.

    Confirms (1) the resolved container class is present (placeholder was
    replaced), (2) at least one ``<li>`` link exists, and (3) each fragment
    ``href="#id"`` (or ``file#id``) targets an ``id`` that actually exists in the
    page. Same-page fixture, so the anchors resolve within this document.
    """
    a = AssertType.SONG_LIST_XREF_RESOLVES
    if not _song_list_container(content):
        return _result(a, False, "no doxtr-song-list/doxtr-song-index container found")
    if "<li" not in content:
        return _result(a, False, "resolved list has no <li> link items")
    ids = set(_ID_ATTR_RE.findall(content))
    hrefs = _HREF_RE.findall(content)
    fragment_links = [h for h in hrefs if "#" in h]
    if not fragment_links:
        return _result(a, False, "resolved list has no fragment (anchor) links: %r" % hrefs)
    unresolved = []
    for href in fragment_links:
        anchor = href.split("#", 1)[1]
        if anchor and anchor not in ids:
            unresolved.append(href)
    if unresolved:
        return _result(
            a, False,
            "song-list link(s) target a missing anchor: %r (ids present: %r)"
            % (unresolved, sorted(ids)),
        )
    return _result(
        a, True,
        "song-list/index links resolve to real in-document anchors (%d link(s))"
        % len(fragment_links),
    )


def _song_list_empty_state(content: str) -> AssertionResult:
    """HTML/EPUB: an empty (valid-but-zero-match) song-list renders no links.

    Confirms the resolved container is present but carries no ``<li>`` link
    items — the documented empty state (distinct from a crash or all-songs).
    """
    a = AssertType.SONG_LIST_EMPTY_STATE
    if not _song_list_container(content):
        return _result(a, False, "no doxtr-song-list/doxtr-song-index container found")
    # Scope the check to the container region to avoid counting unrelated <li>.
    idx = content.find("doxtr-song-list")
    if idx == -1:
        idx = content.find("doxtr-song-index")
    region = content[idx: idx + 4000]
    if "<li" in region:
        return _result(a, False, "empty-state container unexpectedly contains <li> links")
    return _result(a, True, "empty-state song-list container present with no links")


def _song_list_xref_latex(content: str) -> AssertionResult:
    r"""LaTeX: song-list renders a list with at least one resolving \hyperref link.

    Sphinx's LaTeX writer emits ``reference`` nodes to internal targets as
    ``\hyperref[...]{...}`` (or ``\hyperlink``); an itemized/description list
    wraps them. Confirms both are present.
    """
    a = AssertType.SONG_LIST_XREF_LATEX
    if not content.strip():
        return _result(a, False, "empty LaTeX output (build did not complete)")
    has_link = bool(
        re.search(r"\\hyperref\[", content) or re.search(r"\\hyperlink\{", content)
    )
    if not has_link:
        return _result(a, False, r"no \hyperref/\hyperlink link in LaTeX song-list output")
    has_list = (
        "\\begin{itemize}" in content
        or "\\begin{description}" in content
        or "\\item" in content
    )
    if not has_list:
        return _result(a, False, "no itemize/description list wrapping the song-list links")
    return _result(a, True, r"LaTeX song-list list with resolving \hyperref link present")


# ---------------------------------------------------------------------------
# CHUNK-5-4 assertion body: HOOK_INJECTED_HTML
# ---------------------------------------------------------------------------

def _hook_injected_html(content: str) -> AssertionResult:
    """Verify the ``html_visit`` hook injected markup copy-safely (CHUNK-5-4).

    Two conditions:

    1. A ``.doxtr-hook`` copy-neutral wrapper is present carrying the fixture's
       injected sentinel (``data-dm-hook="visited"``) — proving the hook fired
       during HTML translation.
    2. Copy-safety is intact: the copy-safe residual lyric stream (after the
       COPY_SAFE strip, which removes ``.doxtr-hook``) is unchanged — the
       injected sentinel text does NOT leak into the copyable lyric stream.
    """
    a = AssertType.HOOK_INJECTED_HTML
    if 'class="doxtr-hook"' not in content:
        return _result(a, False, "no .doxtr-hook wrapper found (html_visit did not fire)")
    if 'data-dm-hook="visited"' not in content:
        return _result(
            a, False,
            'the .doxtr-hook wrapper lacks the injected data-dm-hook="visited" sentinel',
        )
    # Copy-safety: the injected sentinel token must NOT survive into the
    # residual lyric stream (the .doxtr-hook wrapper is stripped).
    parser = _CopySafeParser()
    try:
        parser.feed(content)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(a, False, "HTML parse error: %s" % exc)
    residual = parser.residual_text
    if "DMHOOKSENTINEL" in residual:
        return _result(
            a, False,
            "injected hook text leaked into the copy-safe lyric stream: %r"
            % residual,
        )
    return _result(
        a, True,
        "html_visit injected inside a copy-neutral .doxtr-hook wrapper; "
        "lyric stream unaffected",
    )


def format_assertion_results(results: list[AssertionResult]) -> list[str]:
    """Format assertion results for display in reports."""
    lines = []
    for result in results:
        icon = "✓" if result.passed else "✗"
        line = f"    [{icon}] {result.description}"
        if result.details:
            line += f" — {result.details}"
        lines.append(line)
    return lines
