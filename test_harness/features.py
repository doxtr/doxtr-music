"""
doxtr-music — Test Harness Feature Registry

This is the SINGLE SOURCE OF TRUTH for all test cases. Every feature and
sub-test is defined here. The harness auto-discovers everything from this file.

Adding a new test case:
    1. Add a ``FeatureSubTest`` to the appropriate ``Feature`` in
       ``FEATURE_REGISTRY``.
    2. Create the RST fixture in ``source/_test_cases/`` (if ``rst_file`` is set).
    3. Create the per-feature config override in ``conf_overrides/`` following
       the ``conf_overrides/<feature>.py`` convention (if ``conf_override`` is
       set). NOTE: a ``conf_override`` must not reference a ``doxtr_music_*``
       config key before the chunk that registers it is DONE.
    4. Set ``status`` to ``FeatureStatus.COMPLETE`` when the sub-test passes.

Multi-format model (LOCKED — CHUNK-0-2):
    Each ``FeatureSubTest`` declares the output formats it exercises via
    ``formats: list[str]`` (subset of ``"html"``/``"latex"``/``"epub"``). Both
    ``expected_markers`` and ``assertions`` are **format-keyed dicts** so a
    marker can be HTML-only (e.g. the provenance ``<meta>`` tag has no
    LaTeX/EPUB analog). For this chunk only the ``"html"`` key is populated;
    CHUNK-2-3 turns on the LaTeX + EPUB lanes by adding keyed entries and
    filling the runner's resolver stubs — without editing the runner loop or
    these dataclasses.

The ``auto_include_tests`` extension reads this file to generate the Sphinx
toctree. The ``test_runner`` reads this file to know what to build and validate.
Never edit ``source/index.rst``'s generated toctree manually — it is
auto-generated from this registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enum — Feature status
# ---------------------------------------------------------------------------

class FeatureStatus(Enum):
    """Status of a test case or feature."""
    COMPLETE = "complete"       # All sub-features tested and passing
    PARTIAL = "partial"         # Some sub-features tested
    PENDING = "pending"         # No tests yet


# ---------------------------------------------------------------------------
# Data classes — Feature and sub-test definitions
# ---------------------------------------------------------------------------

@dataclass
class FeatureSubTest:
    """A single sub-test within a feature.

    ``expected_markers`` and ``assertions`` are keyed by output format
    (``"html"``/``"latex"``/``"epub"``); ``formats`` lists which format lanes
    this sub-test runs. A sub-test may omit ``assertions`` (empty dict) and
    omit non-``html`` format keys entirely.
    """
    name: str
    description: str
    rst_file: Optional[str] = None          # Relative to source/_test_cases/ (None = no RST)
    conf_override: Optional[str] = None     # Relative to conf_overrides/ (None = defaults)
    expected_markers: dict[str, list[str]] = field(default_factory=dict)
    assertions: dict[str, list[str]] = field(default_factory=dict)
    formats: list[str] = field(default_factory=lambda: ["html"])
    status: FeatureStatus = FeatureStatus.PENDING

    @property
    def has_rst(self) -> bool:
        return self.rst_file is not None


@dataclass
class Feature:
    """A testable feature area (e.g. Song directive, Chord line)."""
    name: str
    description: str
    sub_tests: list[FeatureSubTest] = field(default_factory=list)
    status: FeatureStatus = FeatureStatus.PENDING

    @property
    def all_complete(self) -> bool:
        return (
            all(st.status == FeatureStatus.COMPLETE for st in self.sub_tests)
            if self.sub_tests
            else False
        )

    @property
    def has_any_test(self) -> bool:
        return len(self.sub_tests) > 0

    @property
    def passed_count(self) -> int:
        return sum(1 for st in self.sub_tests if st.status == FeatureStatus.COMPLETE)

    @property
    def total_count(self) -> int:
        return len(self.sub_tests)


# ---------------------------------------------------------------------------
# FEATURE_REGISTRY — The single source of truth
# ---------------------------------------------------------------------------

FEATURE_REGISTRY: dict[str, Feature] = {
    # =====================================================================
    # SMOKE — provenance <meta> tag reachability (HTML-first)
    # =====================================================================
    "smoke": Feature(
        name="Smoke",
        description=(
            "Provenance <meta> tag is injected into every HTML page <head>, "
            "proving the extension loads and the basic theme renders metatags."
        ),
        sub_tests=[
            FeatureSubTest(
                name="provenance_meta",
                description="HTML <head> carries the doxtr-music provenance meta tag",
                rst_file="smoke.rst",
                conf_override=None,
                formats=["html"],
                expected_markers={
                    "html": [r'<meta name="doxtr-music" content="[^"]+"/>'],
                },
                assertions={
                    "html": ["META_TAG_PRESENT"],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # SONG — the .. song:: directive: copy-safe chords-over-lyrics HTML
    # =====================================================================
    "song": Feature(
        name="Song directive",
        description=(
            "The .. song:: directive parses inline ChordPro and renders "
            "copy-paste-safe HTML: real chord spans positioned above lyrics, "
            "selecting text copies the lyric stream only."
        ),
        sub_tests=[
            FeatureSubTest(
                name="song_basic",
                description=(
                    "Inline ChordPro renders .doxtr-song with real .doxtr-chord "
                    "spans above lyrics; copy-safe DOM order; absolute CSS. "
                    "LaTeX emits \\dmchord + \\dmneedspace under a loaded "
                    "package; EPUB emits a reflow-safe <pre> two-row layout."
                ),
                rst_file="song.rst",
                conf_override=None,
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song"',
                        r'class="doxtr-chord"',
                        r'data-chord="',
                    ],
                    "latex": [
                        r'\\usepackage(\[[^\]]*\])?\{songbook\}',
                        r'\\dmchord',
                        r'\\dmneedspace',
                    ],
                    "epub": [
                        r'<pre',
                        r'class="[^"]*\bdoxtr-song\b[^"]*"',
                    ],
                },
                assertions={
                    "html": [
                        "POSITION_ABSOLUTE_CSS",
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "NEEDSPACE_PRESENT",
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "EPUB_PRE_FALLBACK",
                        "COPY_SAFE_ORDER_EPUB_PRE",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # TRANSPOSE — :transpose: shifts chords; effective = transposed or chord
    # =====================================================================
    "transpose": Feature(
        name="Transpose",
        description=(
            "The :transpose: option shifts every chord by N semitones with "
            "correct enharmonic spelling and quality preserved. Renderers emit "
            "the effective (transposed) chord in all three formats; stored "
            "English source is untouched."
        ),
        sub_tests=[
            FeatureSubTest(
                name="transpose_basic",
                description=(
                    "A .. song:: with :transpose: 2 over [C][Am][F][G] renders "
                    "D/Bm/G/A: shifted chord labels present and pre-transpose "
                    "originals absent in HTML data-chord, LaTeX \\dmchord args, "
                    "and the EPUB <pre> chord row."
                ),
                rst_file="transpose.rst",
                conf_override=None,
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song"',
                        r'data-chord="Bm"',
                        r'data-chord="D"',
                    ],
                    "latex": [
                        r'\\dmchord\{Bm\}',
                        r'\\dmchord\{D\}',
                    ],
                    "epub": [
                        r'<pre',
                        r'class="[^"]*\bdoxtr-song\b[^"]*"',
                    ],
                },
                assertions={
                    "html": [
                        "TRANSPOSE_SHIFTED_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "TRANSPOSE_SHIFTED_LATEX",
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "TRANSPOSE_SHIFTED_EPUB",
                        "EPUB_PRE_FALLBACK",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # ROMAN — :roman-numerals: replaces chord labels with harmonic numerals
    # =====================================================================
    "roman": Feature(
        name="Roman numerals",
        description=(
            "The :roman-numerals: option analyzes every chord against the song "
            "key and REPLACES the chord label with its harmonic Roman numeral "
            "(single-row layout) in all three formats. engine/roman.py is the "
            "single roman authority; roman is notation-neutral and rides the "
            "chord-position mechanism."
        ),
        sub_tests=[
            FeatureSubTest(
                name="roman_basic",
                description=(
                    "A .. song:: with :roman-numerals: in C major over "
                    "[C][Am][F][G] renders I/vi/IV/V: the numerals replace the "
                    "chord labels in the HTML chord span text, the LaTeX "
                    "\\dmchord args, and the EPUB <pre> chord row. English chord "
                    "names are gone from the visible chord text (HTML keeps them "
                    "only in data-chord)."
                ),
                rst_file="roman.rst",
                conf_override=None,
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song"',
                        r'class="doxtr-chord"',
                        r'data-chord="C"',
                    ],
                    "latex": [
                        r'\\dmchord\{I\}',
                        r'\\dmchord\{vi\}',
                    ],
                    "epub": [
                        r'<pre',
                        r'class="[^"]*\bdoxtr-song\b[^"]*"',
                    ],
                },
                assertions={
                    "html": [
                        "ROMAN_REPLACE_HTML",
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "ROMAN_REPLACE_LATEX",
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "ROMAN_REPLACE_EPUB",
                        "EPUB_PRE_FALLBACK",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # CHORD_LINE — the .. chord-line:: directive: legacy chords-over-lyrics
    # =====================================================================
    "chord_line": Feature(
        name="Chord-line directive",
        description=(
            "The .. chord-line:: directive parses legacy Ultimate-Guitar-style "
            "chords-over-lyrics text (a chord row above a lyric row, chords "
            "anchored strictly by character column, incl. [Chorus] section "
            "headers) into the SAME SongNode tree as .. song::, so all three "
            "formats render it identically."
        ),
        sub_tests=[
            FeatureSubTest(
                name="chord_line_basic",
                description=(
                    "Monospaced chord/lyric rows + a [Chorus] section header "
                    "render the copy-safe .doxtr-song tree: real .doxtr-chord "
                    "spans above lyrics (HTML), \\dmchord + \\dmneedspace under "
                    "a loaded package (LaTeX), reflow-safe <pre> (EPUB) \u2014 "
                    "reusing the .. song:: rendering gates."
                ),
                rst_file="chord_line.rst",
                conf_override=None,
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song"',
                        r'class="doxtr-chord"',
                        r'data-chord="',
                    ],
                    "latex": [
                        r'\\usepackage(\[[^\]]*\])?\{songbook\}',
                        r'\\dmchord',
                        r'\\dmneedspace',
                    ],
                    "epub": [
                        r'<pre',
                        r'class="[^"]*\bdoxtr-song\b[^"]*"',
                    ],
                },
                assertions={
                    "html": [
                        "POSITION_ABSOLUTE_CSS",
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "NEEDSPACE_PRESENT",
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "EPUB_PRE_FALLBACK",
                        "COPY_SAFE_ORDER_EPUB_PRE",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # I18N — doxtr_music_chord_system localizes chord LETTER names (german)
    # =====================================================================
    "i18n": Feature(
        name="Chord-system i18n",
        description=(
            "doxtr_music_chord_system localizes chord LETTER names at render "
            "into regional systems (german/italian Do-Re-Mi/hungarian). "
            "Localization is the last render step on the effective "
            "(post-transpose) chord, keyed on the parsed root (no prefix bug); "
            "quality/extensions are verbatim. engine/i18n.py is the authority "
            "and resolve_chord_display is the single shared render call site "
            "for all three visitors."
        ),
        sub_tests=[
            FeatureSubTest(
                name="i18n_german",
                description=(
                    "A .. song:: over [Bb][B][F#][Eb] under chord_system=german "
                    "renders B/H/Fis/Es: the German spellings are the visible "
                    "chord label in the HTML span text, the LaTeX \\dmchord "
                    "args, and the EPUB <pre> chord row; the raw English F#/Eb "
                    "spellings are gone (localized), proving root-keyed remap."
                ),
                rst_file="i18n.rst",
                conf_override="i18n.py",
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song"',
                        r'class="doxtr-chord"',
                    ],
                    "latex": [
                        r'\\dmchord\{H\}',
                        r'\\dmchord\{Fis\}',
                        r'\\dmchord\{Es\}',
                    ],
                    "epub": [
                        r'<pre',
                        r'class="[^"]*\bdoxtr-song\b[^"]*"',
                    ],
                },
                assertions={
                    "html": [
                        "I18N_GERMAN_HTML",
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "I18N_GERMAN_LATEX",
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "I18N_GERMAN_EPUB",
                        "EPUB_PRE_FALLBACK",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # RTL — right-to-left lyrics: first-class HTML + documented L/E fallback
    # =====================================================================
    "rtl": Feature(
        name="RTL lyrics",
        description=(
            "Right-to-left (Hebrew/Arabic) lyrics. HTML is first-class: "
            'dir="auto" on the song wrapper + logical-only CSS (no physical '
            "left/right) so the layout flips correctly. LaTeX and EPUB use a "
            "documented, tested fallback: LaTeX emits verbatim (bidi deferred to "
            "CHUNK-7-1) with a warning, EPUB uses a reflow-safe <pre> + "
            'dir="auto"; neither crashes.'
        ),
        sub_tests=[
            FeatureSubTest(
                name="rtl_basic",
                description=(
                    "A .. song:: with Hebrew lyrics under [C]/[G] chords "
                    'renders dir="auto" + logical CSS in HTML, and the '
                    "documented verbatim/reflow-safe fallback in LaTeX/EPUB "
                    "without crashing."
                ),
                rst_file="rtl.rst",
                conf_override=None,
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song"',
                        r'dir="auto"',
                    ],
                    "latex": [
                        r'\\dmlyric',
                    ],
                    "epub": [
                        r'<pre',
                        r'dir="auto"',
                    ],
                },
                assertions={
                    "html": [
                        "DIR_AUTO_PRESENT",
                        "RTL_LOGICAL_CSS",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "RTL_FALLBACK_LATEX",
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "RTL_FALLBACK_EPUB",
                        "EPUB_PRE_FALLBACK",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # SONG_INCLUDE — .. song-include:: renders an external .cho identically
    # =====================================================================
    "song_include": Feature(
        name="Song include",
        description=(
            "The .. song-include:: directive pulls a raw external ChordPro .cho "
            "file and renders it identically to .. song:: (same parser, same "
            "SongDirectiveBase pipeline, same node tree), reusing the .. song:: "
            "rendering gates across all three formats. The path is confined to "
            "the source tree and registered as a build dependency."
        ),
        sub_tests=[
            FeatureSubTest(
                name="song_include_basic",
                description=(
                    ".. song-include:: ../_static/example.cho renders the "
                    "copy-safe .doxtr-song tree: real .doxtr-chord spans above "
                    "lyrics (HTML), \\dmchord + \\dmneedspace under a loaded "
                    "package (LaTeX), reflow-safe <pre> (EPUB) \u2014 reusing the "
                    ".. song:: rendering gates."
                ),
                rst_file="song_include.rst",
                conf_override=None,
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song"',
                        r'class="doxtr-chord"',
                        r'data-chord="',
                    ],
                    "latex": [
                        r'\\usepackage(\[[^\]]*\])?\{songbook\}',
                        r'\\dmchord',
                        r'\\dmneedspace',
                    ],
                    "epub": [
                        r'<pre',
                        r'class="[^"]*\bdoxtr-song\b[^"]*"',
                    ],
                },
                assertions={
                    "html": [
                        "POSITION_ABSOLUTE_CSS",
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "NEEDSPACE_PRESENT",
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "EPUB_PRE_FALLBACK",
                        "COPY_SAFE_ORDER_EPUB_PRE",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # IMPORT_MUSICXML — .. import-musicxml:: renders an external score
    # =====================================================================
    "import_musicxml": Feature(
        name="Import MusicXML",
        description=(
            "The .. import-musicxml:: directive converts an uncompressed "
            "MusicXML score into the locked token vocabulary via a pure parser "
            "and renders it identically to .. song:: (same node tree, same "
            "SongDirectiveBase pipeline), reusing the .. song:: rendering gates "
            "across all three formats. <harmony> becomes English chord text "
            "anchored over <lyric> syllables; <key> feeds roman analysis. Bars/"
            "durations are metadata-only (rendered by no builder). The XML is "
            "parsed with defusedxml and the path is confined to the source tree."
        ),
        sub_tests=[
            FeatureSubTest(
                name="import_musicxml_basic",
                description=(
                    ".. import-musicxml:: ../_static/example.musicxml renders "
                    "the copy-safe .doxtr-song tree: real .doxtr-chord spans "
                    "above lyrics (HTML), \\dmchord + \\dmneedspace under a "
                    "loaded package (LaTeX), reflow-safe <pre> (EPUB) — reusing "
                    "the .. song:: rendering gates. Assertions target chord/"
                    "lyric/section rendering, NOT bars (bars are metadata-only)."
                ),
                rst_file="import_musicxml.rst",
                conf_override=None,
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song"',
                        r'class="doxtr-chord"',
                        r'data-chord="',
                    ],
                    "latex": [
                        r'\\usepackage(\[[^\]]*\])?\{songbook\}',
                        r'\\dmchord',
                        r'\\dmneedspace',
                    ],
                    "epub": [
                        r'<pre',
                        r'class="[^"]*\bdoxtr-song\b[^"]*"',
                    ],
                },
                assertions={
                    "html": [
                        "POSITION_ABSOLUTE_CSS",
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "NEEDSPACE_PRESENT",
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "EPUB_PRE_FALLBACK",
                        "COPY_SAFE_ORDER_EPUB_PRE",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # IMPORT_ABC — .. import-abc:: renders an external ABC tune
    # =====================================================================
    "import_abc": Feature(
        name="Import ABC",
        description=(
            "The .. import-abc:: directive converts an ABC notation tune into "
            "the locked token vocabulary via a pure parser and renders it "
            "identically to .. song:: (same node tree, same SongDirectiveBase "
            "pipeline), reusing the .. song:: rendering gates across all three "
            "formats. Quoted \"chord\" symbols become English chord text anchored "
            "over w: syllables (note-event -> syllable -> column); K: feeds roman "
            "analysis. Bars/durations are metadata-only (rendered by no builder). "
            "ABC is plain text; the path is confined to the source tree."
        ),
        sub_tests=[
            FeatureSubTest(
                name="import_abc_basic",
                description=(
                    ".. import-abc:: ../_static/example.abc renders the "
                    "copy-safe .doxtr-song tree: real .doxtr-chord spans above "
                    "lyrics (HTML), \\dmchord + \\dmneedspace under a loaded "
                    "package (LaTeX), reflow-safe <pre> (EPUB) - reusing the "
                    ".. song:: rendering gates. Assertions target chord/lyric/"
                    "section rendering, NOT bars (bars are metadata-only)."
                ),
                rst_file="import_abc.rst",
                conf_override=None,
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song"',
                        r'class="doxtr-chord"',
                        r'data-chord="',
                    ],
                    "latex": [
                        r'\\usepackage(\[[^\]]*\])?\{songbook\}',
                        r'\\dmchord',
                        r'\\dmneedspace',
                    ],
                    "epub": [
                        r'<pre',
                        r'class="[^"]*\bdoxtr-song\b[^"]*"',
                    ],
                },
                assertions={
                    "html": [
                        "POSITION_ABSOLUTE_CSS",
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "NEEDSPACE_PRESENT",
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "EPUB_PRE_FALLBACK",
                        "COPY_SAFE_ORDER_EPUB_PRE",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # ROLES — inline :chord:/:key:/:roman: roles for natural prose
    # =====================================================================
    "roles": Feature(
        name="Inline roles",
        description=(
            "Inline roles :chord:/:key:/:roman: integrate chords, keys and "
            "roman numerals into running prose. :chord: renders through the "
            "shared resolve_chord_display with a DISTINCT .doxtr-chord-inline "
            "class (no aria-hidden, no positioned song-chord CSS leak); :key: "
            "renders as a localized note name; :roman: is author-literal. All "
            "three roles render in HTML/LaTeX/EPUB."
        ),
        sub_tests=[
            FeatureSubTest(
                name="roles_basic",
                description=(
                    ":chord:`G7` \u2192 inline .doxtr-chord-inline span (no "
                    "aria-hidden) / \\dmchordinline{G7}; :key:`Bb` \u2192 "
                    ".doxtr-key span / \\dmkey{Bb}; :roman:`IV` \u2192 author-literal "
                    ".doxtr-roman span / \\dmroman{IV}. Rendered across all three "
                    "formats as inline spans (HTML/EPUB) or role macros (LaTeX)."
                ),
                rst_file="roles.rst",
                conf_override=None,
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-chord-inline"',
                        r'class="doxtr-key"',
                        r'class="doxtr-roman"',
                    ],
                    "latex": [
                        r'\\dmchordinline\{G7\}',
                        r'\\dmkey\{Bb\}',
                        r'\\dmroman\{IV\}',
                    ],
                    "epub": [
                        r'class="[^"]*\bdoxtr-chord-inline\b[^"]*"',
                        r'class="[^"]*\bdoxtr-key\b[^"]*"',
                        r'class="[^"]*\bdoxtr-roman\b[^"]*"',
                    ],
                },
                assertions={
                    "html": [
                        "ROLES_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "ROLES_LATEX",
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "ROLES_EPUB",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # TYPOGRAPHY — granular per-element font/size/color (global + per-song)
    # =====================================================================
    "typography": Feature(
        name="Typography",
        description=(
            "Granular typography for the five song elements (title/metadata/"
            "roman/chord/lyrics): font/size/color, globally via "
            "doxtr_music_typography and per-song via directive options. Global "
            "typography rides scoped element-class CSS (HTML/EPUB) / a LaTeX "
            "preamble indirection-macro contributor; per-song rides inline "
            "style (HTML/EPUB) / a scoped TeX \\def group (LaTeX). Color is "
            "resolved in Python and emitted once. Styling-only: DOM order, "
            "copy-safety and the chord display string are unchanged."
        ),
        sub_tests=[
            FeatureSubTest(
                name="typography_basic",
                description=(
                    "Global chord color (#cc0000) + per-song :lyrics-color: "
                    "#0000cc / :chord-font: monospace / :title-color: #008000 "
                    "apply per element/attr (others inherit) in all three "
                    "formats: HTML/EPUB inline style + injected global <style>; "
                    "LaTeX preamble indirection macros + a per-song scoped "
                    "\\def group. Copy-safety unchanged."
                ),
                rst_file="typography.rst",
                conf_override="typography.py",
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song"',
                        r'class="doxtr-music-typography"',
                        r'style="[^"]*color:#0000cc',
                    ],
                    "latex": [
                        r'\\renewcommand\{\\dmchordcolor\}',
                        r'\\begingroup% doxtr-music song typography',
                        r'\\def\\dmlyriccolor',
                    ],
                    "epub": [
                        r'<pre',
                        r'class="[^"]*\bdoxtr-song\b[^"]*"',
                    ],
                },
                assertions={
                    "html": [
                        "TYPOGRAPHY_APPLIED_HTML",
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "TYPOGRAPHY_APPLIED_LATEX",
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "TYPOGRAPHY_APPLIED_EPUB",
                        "EPUB_PRE_FALLBACK",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),

    # -----------------------------------------------------------------------
    # Extended styling: sections + metadata + background colors
    # -----------------------------------------------------------------------
    "styling_sections_metadata": Feature(
        name="Styling: sections & metadata",
        description=(
            "The extended granular-styling surface: every song element accepts "
            "font/size/color/BACKGROUND; section titles/bodies are styled per "
            "KIND (section-<kind>-title/-body, flexible), and song-metadata rows "
            "(Key/Tempo/…) render as a visible block styled per KEY (meta-<key> "
            "over the generic metadata default). All in HTML/LaTeX/EPUB. Global "
            "styling rides element-class CSS (HTML/EPUB) / inline cell wrapping "
            "(LaTeX block elements). Copy-safety unchanged (title + metadata are "
            "song chrome, stripped from the copyable lyric stream)."
        ),
        sub_tests=[
            FeatureSubTest(
                name="styling_sections_metadata",
                description=(
                    "A song with Key + Tempo metadata and verse/chorus sections "
                    "under a config that styles the title (color + background), "
                    "per-kind section titles (verse tinted background; chorus "
                    "green), section bodies (smaller), and metadata rows "
                    "(generic size + a monospace/blue Tempo + green Key). "
                    "Renders the metadata block + per-kind section styling in "
                    "all three formats."
                ),
                rst_file="styling_sections_metadata.rst",
                conf_override="styling_sections_metadata.py",
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song-meta doxtr-song-meta-tempo"',
                        r'class="doxtr-song-meta doxtr-song-meta-key"',
                        r'font-family:monospace',
                        r'background-color:#eeeeff',
                        r'class="doxtr-section-body"',
                        r'\.doxtr-section-verse > \.doxtr-section-label',
                    ],
                    "latex": [
                        r'Tempo: 120 BPM',
                        r'Key: G',
                        r'\\colorbox',
                        r'\\dmsectionbegin\{verse\}',
                        r'\\dmsectionbegin\{chorus\}',
                    ],
                    "epub": [
                        r'class="doxtr-song-meta doxtr-song-meta-tempo"',
                        r'Tempo',
                        r'class="doxtr-section-body"',
                    ],
                },
                assertions={
                    "html": [
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "NEEDSPACE_PRESENT",
                    ],
                    "epub": [
                        "COPY_SAFE_ORDER_EPUB_PRE",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),

    # -----------------------------------------------------------------------
    # CHUNK-4-2 — Multi-singer {singer: X} + singer->color mapping
    # -----------------------------------------------------------------------
    "multi_singer": Feature(
        name="Multi-Singer",
        description=(
            "Multi-singer {singer: X} vocal-part attribution with distinct "
            "per-singer colors (duets), across HTML/LaTeX/EPUB. Colors merge a "
            "global doxtr_music_singer_colors with a per-song :singer-colors: "
            "override. The singer color WINS over the typography chord/lyric "
            "color while the typography font/size still apply -- resolved in "
            "Python and emitted once per element (one inline color HTML/EPUB; "
            "the run's scoped indirection color macros in LaTeX). Copy-safety "
            "(HTML + EPUB <pre>) is preserved on the multi-singer fixture."
        ),
        sub_tests=[
            FeatureSubTest(
                name="multi_singer_basic",
                description=(
                    "Two singer runs (A/B) render in distinct colors merged from "
                    "the global map + a per-song :singer-colors: override; the "
                    "singer color wins over the per-song :chord-color: #cc0000 "
                    "while :chord-font: monospace survives. HTML emits one inline "
                    "color per chord/lyric element (data-singer hook on the "
                    "span, no color on it); LaTeX scopes each colored word's "
                    "\\dmchordcolor/\\dmlyriccolor to the resolved winner in a "
                    "\\begingroup group; EPUB "
                    "colors both <pre> row cell sub-ranges. Copy-safety intact."
                ),
                rst_file="multi_singer.rst",
                conf_override="multi_singer.py",
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-singer" data-singer="A"',
                        r'class="doxtr-singer" data-singer="B"',
                        r'style="[^"]*color:#1a53a1',
                        r'style="[^"]*color:#e07b00',
                    ],
                    "latex": [
                        r'\\def\\dmchordcolor\{\\color\{dm@wordchordcolor\}\}',
                        r'\\def\\dmlyriccolor\{\\color\{dm@wordlyriccolor\}\}\\dmchord\{',
                        r'\\definecolor\{dm@wordlyriccolor\}\{HTML\}',
                    ],
                    "epub": [
                        r'<pre',
                        r'class="[^"]*\bdoxtr-song\b[^"]*"',
                        r'<span style="color:#1a53a1"',
                    ],
                },
                assertions={
                    "html": [
                        "SINGER_COLOR_APPLIED_HTML",
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "SINGER_COLOR_APPLIED_LATEX",
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "SINGER_COLOR_APPLIED_EPUB",
                        "COPY_SAFE_ORDER_EPUB_PRE",
                        "EPUB_PRE_FALLBACK",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # -----------------------------------------------------------------------
    # CHUNK-4-3 — WCAG 2.1 AA accessibility (HTML + EPUB)
    # -----------------------------------------------------------------------
    "wcag_a11y": Feature(
        name="WCAG Accessibility",
        description=(
            "WCAG 2.1 AA for HTML + EPUB song output: the song wrapper is a "
            "named role='group' (aria-labelledby the title id, or an "
            "aria-label='Song' fallback); each song chord announces atomically "
            "via role='img' + aria-label='Chord: <n>' (no duplicate word read); "
            "multi-singer runs carry a VISIBLE non-color cue (WCAG 1.4.1); and "
            "the EPUB two-row <pre> gets a visually-hidden chord↔word "
            "alternative emitted OUTSIDE the copyable lyric row. Copy-safety is "
            "preserved on both formats (the a11y additions live inside "
            "stripped wrappers / sibling containers). LaTeX a11y is out of "
            "scope (PDF/UA declined for v1) — no LaTeX lane by design."
        ),
        sub_tests=[
            FeatureSubTest(
                name="wcag_a11y_basic",
                description=(
                    "HTML: song role='group' aria-labelledby the title id; "
                    "chords role='img' + aria-label='Chord: G'; visible singer "
                    "cue inside the stripped .doxtr-singer wrapper; copy-safe "
                    "lyric stream excludes it. EPUB: song role='group' + label; "
                    "hidden chord↔word alternative in a .doxtr-line-a11y sibling "
                    "outside the <pre>; row-extract lyric stream excludes it."
                ),
                rst_file="wcag_a11y.rst",
                conf_override="wcag_a11y.py",
                formats=["html", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song" role="group" aria-labelledby="[^"]+"',
                        r'class="doxtr-chord" data-chord="[^"]*" role="img" '
                        r'aria-label="Chord: [^"]+"',
                        r'class="doxtr-singer-cue"',
                    ],
                    "epub": [
                        r'class="doxtr-song doxtr-song-epub" role="group"',
                        r'class="doxtr-line-a11y"',
                        r'Chord: [^,<]+, word: ',
                    ],
                },
                assertions={
                    "html": [
                        "ROLE_GROUP_PRESENT",
                        "ARIA_LABEL_PRESENT",
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "epub": [
                        "ROLE_GROUP_PRESENT",
                        "COPY_SAFE_ORDER_EPUB_PRE",
                        "EPUB_PRE_FALLBACK",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # CHORD_PROGRESSION — the .. chord-progression:: directive: a semantic
    # grid of chords / roman numerals (no lyrics) in all three formats
    #   (CHUNK-4-4). Chord cells localize; :roman-numerals: + :key: computes
    #   a roman per chord cell; author-literal roman cells stay literal.
    # =====================================================================
    "chord_progression": Feature(
        name="Chord progression grid",
        description=(
            ".. chord-progression:: renders a tabular grid of chords and/or "
            "Roman numerals WITHOUT lyrics: a semantic <table> in HTML/EPUB "
            "and a standard tabular in LaTeX. Chord cells localize via "
            "localize_chord; :roman-numerals: + :key: computes a roman per "
            "chord cell via roman_for_chord; author-literal roman cells stay "
            "literal. Ragged rows normalize to the max column count."
        ),
        sub_tests=[
            FeatureSubTest(
                name="progression_grid",
                description=(
                    "| C | F | G | C | plus an author-literal roman row and a "
                    ":key: C + :roman-numerals: row renders a semantic table "
                    "(caption + <td>) in HTML/EPUB and a tabular with "
                    "\\dmchordinline/\\dmroman cells in LaTeX. No <pre> / no "
                    "lyrics."
                ),
                rst_file="chord_progression.rst",
                conf_override=None,
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-progression"',
                        r'<td',
                    ],
                    "latex": [
                        r'\\begin\{tabular\}',
                        r'\\dmchordinline',
                        r'\\dmroman',
                    ],
                    "epub": [
                        r'class="doxtr-progression"',
                        r'<td',
                    ],
                },
                assertions={
                    "html": [
                        "PROGRESSION_TABLE_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "PROGRESSION_TABLE_LATEX",
                    ],
                    "epub": [
                        "PROGRESSION_TABLE_EPUB",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),

    # =====================================================================
    # SONG_LIST — .. song-list:: dynamic filtered directory (CHUNK-5-3)
    # =====================================================================
    "song_list": Feature(
        name="Song list",
        description=(
            ".. song-list:: emits a read-phase placeholder that a "
            "doctree-resolved handler replaces with STANDARD docutils "
            "bullet_list/reference nodes (via make_refnode). :filter: uses "
            "safe_eval (no eval); a valid-but-empty filter renders an empty "
            "container. Links resolve to real anchors in HTML/LaTeX/EPUB."
        ),
        sub_tests=[
            FeatureSubTest(
                name="song_list_filter",
                description=(
                    ":filter: \"rock\" in tags and year > 1990 renders a "
                    "doxtr-song-list of <li> reference links to the matching "
                    "songs (resolving to real in-document anchors), and a "
                    "second valid-but-empty filter renders an empty container "
                    "with no links. LaTeX emits an itemize/description list "
                    "with a resolving \\hyperref."
                ),
                rst_file="song_list.rst",
                conf_override=None,
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="[^"]*\bdoxtr-song-list\b[^"]*"',
                        r'<li',
                        r'<a[^>]*href="[^"]*#',
                    ],
                    "latex": [
                        r'\\hyperref\[',
                    ],
                    "epub": [
                        r'class="[^"]*\bdoxtr-song-list\b[^"]*"',
                        r'<li',
                        r'<a[^>]*href="[^"]*#',
                    ],
                },
                assertions={
                    "html": [
                        "SONG_LIST_XREF_RESOLVES",
                        "SONG_LIST_EMPTY_STATE",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "SONG_LIST_XREF_LATEX",
                    ],
                    "epub": [
                        "SONG_LIST_XREF_RESOLVES",
                        "SONG_LIST_EMPTY_STATE",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),

    # =====================================================================
    # SONG_INDEX — .. song-index:: grouped glossary (CHUNK-5-3)
    # =====================================================================
    "song_index": Feature(
        name="Song index",
        description=(
            ".. song-index:: :group-by: <key> groups songs by a METADATA KEY "
            "(entry.get(key), not safe_eval) into a definition_list of group "
            "headings each holding a bullet_list of reference links; a missing "
            "key lands in the single 'Other' group. Standard docutils nodes, "
            "resolving links in HTML/LaTeX/EPUB."
        ),
        sub_tests=[
            FeatureSubTest(
                name="song_index_group_by",
                description=(
                    ":group-by: artist groups the songs by their artist "
                    "metadata; the song with no artist falls into the 'Other' "
                    "group. The index renders as a doxtr-song-index container "
                    "of grouped <li> reference links resolving to real "
                    "in-document anchors. LaTeX emits a resolving \\hyperref."
                ),
                rst_file="song_index.rst",
                conf_override=None,
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="[^"]*\bdoxtr-song-index\b[^"]*"',
                        r'The Nines',
                        r'Other',
                        r'<a[^>]*href="[^"]*#',
                    ],
                    "latex": [
                        r'The Nines',
                        r'Other',
                        r'\\hyperref\[',
                    ],
                    "epub": [
                        r'class="[^"]*\bdoxtr-song-index\b[^"]*"',
                        r'The Nines',
                        r'Other',
                        r'<a[^>]*href="[^"]*#',
                    ],
                },
                assertions={
                    "html": [
                        "SONG_LIST_XREF_RESOLVES",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "SONG_LIST_XREF_LATEX",
                    ],
                    "epub": [
                        "SONG_LIST_XREF_RESOLVES",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # PLUGIN_HOOKS — html_visit custom HTML injection (CHUNK-5-4), HTML-only
    # =====================================================================
    "plugin_hooks": Feature(
        name="Plugin hooks",
        description=(
            "The html_visit plugin hook injects custom HTML during translation "
            "inside a copy-neutral .doxtr-hook wrapper (COPY_SAFE strip removes "
            "it), so injected markup never pollutes the copyable lyric stream. "
            "HTML-only (chord_preprocess/node_parsed are pipeline/AST hooks with "
            "no direct rendered marker; they are unit-tested). Registered here "
            "via a dotted-string config value (importlib, never eval)."
        ),
        sub_tests=[
            FeatureSubTest(
                name="html_visit_injection",
                description=(
                    "doxtr_music_html_visit (dotted string) fires during HTML "
                    "translation: a .doxtr-hook wrapper carries the injected "
                    "data-dm-hook sentinel, and the copy-safe lyric stream is "
                    "unaffected (the sentinel is stripped with the wrapper)."
                ),
                rst_file="plugin_hooks.rst",
                conf_override="plugin_hooks.py",
                formats=["html"],
                expected_markers={
                    "html": [
                        r'class="doxtr-hook"',
                        r'data-dm-hook="visited"',
                    ],
                },
                assertions={
                    "html": [
                        "HOOK_INJECTED_HTML",
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
    # =====================================================================
    # THEME_INTEROP — soft doxtr-pdf-theme-core palette pickup (CHUNK-7-1)
    # =====================================================================
    "theme_interop": Feature(
        name="Theme interop",
        description=(
            "When doxtr-pdf-theme-core is the active theme, songs pick up its "
            "font/palette via the theme tier of the three-tier merge (below "
            "global+per-song), a LaTeX preamble block using the existing \\dm "
            "macros (plus polyglossia/bidi for RTL), and a contrast feed of the "
            "theme page background. Presence is a config-attribute read, never "
            "an import; absent/off degrades to defaults. This fixture simulates "
            "the theme via a stub registering doxtr_theme_defaults."
        ),
        sub_tests=[
            FeatureSubTest(
                name="theme_interop_active",
                description=(
                    "Theme-active stub -> lyric color from the theme text color "
                    "(#e0e0e0) and chord color from the theme accent (#3aa0ff) "
                    "in HTML/EPUB; the LaTeX preamble loads polyglossia/bidi and "
                    "carries the theme \\dm color values. Conservative mapping: "
                    "only lyric+chord are themed; other elements keep defaults."
                ),
                rst_file="theme_interop.rst",
                conf_override="theme_interop.py",
                formats=["html", "latex", "epub"],
                expected_markers={
                    "html": [
                        r'class="doxtr-song"',
                        r'#3aa0ff',   # theme accent -> chord color
                        r'#e0e0e0',   # theme text -> lyric color
                    ],
                    "latex": [
                        r'\\usepackage\{polyglossia\}',
                        r'\\usepackage\{bidi\}',
                        r'doxtr-music theme',
                    ],
                    "epub": [
                        r'#3aa0ff',
                        r'class="[^"]*\bdoxtr-song\b[^"]*"',
                    ],
                },
                assertions={
                    "html": [
                        "COPY_SAFE_ORDER_HTML",
                        "HTML_WELL_FORMED",
                    ],
                    "latex": [
                        "LATEX_PACKAGE_LOADED",
                    ],
                    "epub": [
                        "COPY_SAFE_ORDER_EPUB_PRE",
                    ],
                },
                status=FeatureStatus.COMPLETE,
            ),
        ],
        status=FeatureStatus.COMPLETE,
    ),
}


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def get_feature_names() -> list[str]:
    """Return feature keys in registry order."""
    return list(FEATURE_REGISTRY.keys())


def get_features_with_rst() -> list[str]:
    """Return feature keys where at least one sub-test has an RST fixture."""
    return [
        name for name, feat in FEATURE_REGISTRY.items()
        if any(st.has_rst for st in feat.sub_tests)
    ]


def get_pending_features() -> list[str]:
    """Return feature keys where at least one sub-test is still pending."""
    return [
        name for name, feat in FEATURE_REGISTRY.items()
        if any(st.status == FeatureStatus.PENDING for st in feat.sub_tests)
    ]


def get_complete_features() -> list[str]:
    """Return feature keys where all sub-tests are complete."""
    return [name for name, feat in FEATURE_REGISTRY.items() if feat.all_complete]


def get_partial_features() -> list[str]:
    """Return feature keys where some (but not all) sub-tests are complete."""
    return [
        name for name, feat in FEATURE_REGISTRY.items()
        if not feat.all_complete
        and any(st.status == FeatureStatus.COMPLETE for st in feat.sub_tests)
    ]


def get_all_sub_tests() -> list[tuple[str, FeatureSubTest]]:
    """Return all (feature_name, sub_test) pairs in registry order."""
    result: list[tuple[str, FeatureSubTest]] = []
    for name in get_feature_names():
        feat = FEATURE_REGISTRY[name]
        for st in feat.sub_tests:
            result.append((name, st))
    return result


def count_by_status() -> dict[str, dict[str, int]]:
    """Count features and sub-tests by status."""
    feat_by_status: dict[str, int] = {"complete": 0, "partial": 0, "pending": 0}
    sub_by_status: dict[str, int] = {"complete": 0, "partial": 0, "pending": 0}

    for _name, feat in FEATURE_REGISTRY.items():
        if feat.all_complete:
            feat_by_status["complete"] += 1
        elif any(st.status == FeatureStatus.COMPLETE for st in feat.sub_tests):
            feat_by_status["partial"] += 1
        else:
            feat_by_status["pending"] += 1

        for st in feat.sub_tests:
            sub_by_status[st.status.value] += 1

    return {"features": feat_by_status, "sub_tests": sub_by_status}


# ---------------------------------------------------------------------------
# Summary printer (debugging / `python features.py`)
# ---------------------------------------------------------------------------

def print_summary() -> None:
    """Print a summary of the feature registry to stdout."""
    counts = count_by_status()
    print("=" * 60)
    print("doxtr-music — Test Harness Feature Registry Summary")
    print("=" * 60)
    total_feats = len(FEATURE_REGISTRY)
    total_subs = sum(f.total_count for f in FEATURE_REGISTRY.values())
    print(
        f"Features: {total_feats} total | "
        f"{counts['features']['complete']} complete | "
        f"{counts['features']['partial']} partial | "
        f"{counts['features']['pending']} pending"
    )
    print(
        f"Sub-tests: {total_subs} total | "
        f"{counts['sub_tests']['complete']} complete | "
        f"{counts['sub_tests']['partial']} partial | "
        f"{counts['sub_tests']['pending']} pending"
    )
    print("-" * 60)
    for name in get_feature_names():
        feat = FEATURE_REGISTRY[name]
        status_icon = "✓" if feat.all_complete else ("◐" if feat.has_any_test else "○")
        print(f"  [{status_icon}] {feat.name}: {feat.passed_count}/{feat.total_count} tests")
    print("=" * 60)


if __name__ == "__main__":
    print_summary()
