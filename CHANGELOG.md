# Changelog

## 0.1.0 — 2026-09-21

### New Features

- `.. song-index:: :style: index` — a book-style **alphabetical index**: songs
  grouped under a letter heading (a `#` bucket for non-alphabetic leads), each
  entry linking to the song and, in LaTeX/PDF, showing a hyperlinked page
  number. `:style: list` (default) keeps the existing `:group-by:` definition
  list. HTML/EPUB show the linked titles under each letter (no page numbers,
  which do not exist there). The song's LaTeX visitor emits a
  `\phantomsection\label` for its id so cross-references **and** page
  references resolve.
- `doxtr_music_index_page_format` — configurable page-number template for the
  alphabetical index (LaTeX/PDF): a single `{page}` placeholder (default
  `"{page}"`, e.g. `"page {page}"`). The whole formatted phrase is one
  hyperlink to the song's page; literal text is LaTeX-escaped and the template is
  validated (exactly one `{page}`, else a warning + fallback).
- Roman-numeral `alongside` display mode (`doxtr_music_roman_display` /
  `:roman-display:` = `off`/`replace`/`alongside`) with a formattable combo
  template `doxtr_music_roman_format` (`{chord}`/`{roman}`; a newline stacks the
  chord over the numeral). The numeral part is styled by the `roman` typography
  element independently of the chord. The legacy `:roman-numerals:` flag is an
  alias for `replace`.
- Theme-adaptive `dd:` color expressions: any `color`/`background` may be a
  `dd:` expression (e.g. `dd:primary`, `dd:secondary:contrast:fg:page`,
  `dd:primary:lighten:85`) resolved by `doxtr-pdf-theme-core` against its
  semantic palette, so songs re-color automatically with the active theme. A
  `dd:` value without the theme raises an actionable error (install the theme,
  or use a static color). Named-font support for song elements.
- Dark mode: every doxtr-music color transforms with the document in dark builds
  — `dd:` expressions resolve against the theme's dark palette, static hex
  colors (incl. singer colors) are soft-inverted, and default lyrics track the
  dark body-text color. The LaTeX preamble is assembled after the theme resolves
  dark so global colors bake correctly.
- Custom section kinds (`{start_of_<kind>}`), per-section-kind and per-metadata
  styling, per-word lyric highlight backgrounds, and configurable backgrounds.
- `.. song::` — the primary song container: parses ChordPro (inline `[chord]`
  markers, `{directive}` metadata, `{singer:X}` spans) into the locked token
  vocabulary and renders it as real, copy-safe chord spans positioned over the
  lyric they precede (HTML), `\dmchord` macros with page-break avoidance
  (LaTeX/PDF), and a reflow-safe two-row `<pre>` block (EPUB). Per-song
  directive options (transpose, roman, chord-system, typography) are parsed at a
  single point (`_options.py`).
- Transposition (`:transpose:`): shifts every chord by a signed semitone/step
  amount, enharmonically correct and quality-preserving, resolved at parse time
  against `engine/theory.py` (the single chord/key-parsing authority) so the
  shifted chord flows unchanged through all three formats.
- `.. chord-line::`: legacy column-aligned chords-over-lyrics input, converged
  onto the same token pipeline and rendering as `.. song::` via the shared
  `SongDirectiveBase` (pure alternate parser, no format-specific rendering).
- `.. song-include::`: pulls a confined `.cho`/ChordPro file from the source
  tree via the shared `load_confined_source` helper (absolute-path/traversal/
  symlink-guarded, `note_dependency` for rebuilds) and renders it as a song.
- `.. chord-progression::`: a chord / roman-numeral grid rendered as a semantic
  table (HTML `<table>` with an SR-only caption, LaTeX `tabular`, EPUB XHTML
  table); cell classification is a single shared authority across the three
  builders.
- `.. song-list::` / `.. song-index::`: filtered list / index over the
  `env.song_data` registry, resolved in a `doctree-resolved` handler that emits
  standard docutils nodes; `:filter:` uses the safe AST allow-list interpreter
  (`safe_eval` — no arithmetic, no `eval`), `:group-by:`/`:sort:` are metadata
  key names.
- `.. import-abc::`: imports ABC notation into the locked token vocabulary via a
  pure `(text) -> (tokens, song_meta)` parser and renders it identically to
  `.. song::` across all three formats (front-end convergence via
  `ImportDirectiveBase`; bar boundaries / durations metadata-only in v1).
- Inline roles `:chord:`, `:key:`, `:roman:`: render a single chord, key name,
  or roman numeral inline in running text across all three formats, reusing the
  shared chord/roman display resolution.
- Multi-singer `{singer:X}` color: resolves each singer ID to a color in Python
  (per-song `:singer-colors:` overriding the global `doxtr_music_singer_colors`)
  and emits it once (one inline color for HTML/EPUB, one indirection-macro value
  for LaTeX); singer color wins over typography color within a span.
- Soft `doxtr-pdf-theme-core` interop (`doxtr_music_theme_interop`): when the
  theme is the active theme, songs pick up its font/palette via the theme tier
  of the three-tier merge (below global + per-song), a LaTeX preamble block
  (plus `polyglossia`/`bidi` for RTL), and a contrast feed of the theme page
  background. Presence is a config-attribute read (`doxtr_theme_defaults`),
  **never** an import; absent/off degrades to defaults — `doxtr-pdf-theme-core`
  is never in `install_requires`.
- Accessibility (WCAG 2.1 AA-oriented, HTML + EPUB): song container
  `role="group"`, chords as `role="img"` + `aria-label`, a **visible** non-color
  cue for multi-singer spans (WCAG 1.4.1), and a warn-not-fail contrast check
  (WCAG 1.4.3) against a documented background heuristic. LaTeX/PDF a11y is out
  of scope for v1.
- `doxtr-music-convert` CLI: converts monospaced chords-over-lyrics text into
  inline ChordPro (via the single `tokens_to_chordpro` serialization authority)
  for pasting into a `.. song::` directive; reads a file / stdin / clipboard and
  imports **without Sphinx** (the pure parser layer is standalone).
- `.. import-musicxml::` imports an uncompressed MusicXML score into the locked
  token vocabulary via a pure `parse_musicxml(text) -> (tokens, song_meta)`
  parser and renders it identically to `.. song::` across HTML, LaTeX/PDF and
  EPUB (front-end convergence: no new node/token type, no format-specific code).
  `<harmony>` becomes English chord text via an inline `<kind>`→quality matrix
  (slash chords, `<degree>` suffixes, `<kind text>` overrides; unmapped kinds
  fall back best-effort with a warning, never a silently wrong chord);
  `<lyric>` syllables are anchored over their note events (synthetic per-measure
  line + codepoint columns honoring `<syllabic>`); `<key>`/`<fifths>` feeds
  roman analysis. Bar boundaries (`BarToken`) and note durations
  (`ChordToken.duration`) are metadata-only in v1 (emitted on the stream,
  dropped by `build_nodes`, rendered by no builder). Untrusted XML is parsed
  with `defusedxml` (XXE / billion-laughs safe) — an optional-dependency extra
  `doxtr-music[musicxml]`, never in `install_requires`; `.mxl` (compressed) is
  deferred with a clear note. The path is confined to the source tree via the
  shared `load_confined_source` helper. This chunk owns `ImportDirectiveBase`
  (a thin `SongDirectiveBase` subclass reused by `.. import-abc::`).
- Granular typography (`doxtr_music_typography` + per-song directive options):
  independent `font`/`size`/`color` for the five song elements (`title`,
  `metadata`, `roman`, `chord`, `lyrics`), globally and per song, across HTML,
  LaTeX/PDF and EPUB. Global typography rides scoped element-class CSS
  (HTML/EPUB, injected once per page) / a LaTeX preamble indirection-macro
  contributor; per-song typography rides an inline `style` (HTML/EPUB) / a
  scoped `\begingroup...\def...\endgroup` group that redefines only the
  overridden attribute macros (LaTeX). Per-attribute merge
  (`core -> theme -> global -> per-song`) means `:chord-color:` overrides only
  chord color. Colors are resolved/validated in Python and emitted once
  (hex -> `\definecolor{...}{HTML}{...}`; invalid color warns + falls back).
  EPUB font-sizes are relative (reflow-safe; absolute units downgraded).
  Styling-only: DOM order, copy-safety, `aria-hidden` and the chord display
  string are unchanged. `doxtr_music/typography.py` is the resolution authority;
  it reuses `config.py`'s `three_tier_merge`/`deep_update` (no re-implemented
  merge). Singer color (4-2) wins over typography *color* within a singer span;
  typography font/size always apply.
- Chord-system i18n (`doxtr_music_chord_system`): localizes chord **letter**
  names at render into `german` (H/B swap, `-is`/`-es` with `Es`/`As`
  elisions + double-accidentals), `italian` (Do-Re-Mi, ASCII `#`/`b`), and
  `hungarian` (`-sz` spellings). Remap is keyed on the parsed chord root
  (no string-prefix bug); quality/extensions are verbatim. `chord_system="roman"`
  resolves at **parse time** (single `ChordNode.roman` source). `engine/i18n.py`
  is the localization authority and `resolve_chord_display` is the single shared
  render call site for the HTML/LaTeX/EPUB chord visitors.
- RTL lyrics: HTML is first-class (`dir="auto"` + logical-only CSS); LaTeX and
  EPUB use a documented, tested fallback (verbatim / reflow-safe `<pre>` with a
  best-effort warning, never a crash; bidi wiring deferred to the theme layer).
- Roman-numeral analysis (`:roman-numerals:`): `engine/roman.py` is the single
  `roman_for_chord` authority (quality-driven case, deterministic chromatic
  mapping). Numerals **replace** the chord label in all three formats (HTML
  span text, LaTeX `\dmchord`, EPUB `<pre>` chord row); `RomanNode` visitors
  registered for HTML/LaTeX/EPUB.
- Package bootstrap: `setup()`, `__version__`, and the HTML provenance
  `<meta name="doxtr-music">` tag.

### Bug Fixes

- LaTeX/PDF: fixed a swallowed interword space after a chord word (e.g.
  "Swing low" rendering as "Swinglow"). A chord word ends its color group with
  `\endgroup`, and TeX silently discards a space following a control word; the
  reconstructed interword gap is now shielded with an empty group `{}` so the
  space survives regardless of the preceding token.
- Dark mode: fixed double-inversion of `dd:` colors and incorrect global colors
  (the LaTeX preamble is now assembled after the theme resolves dark); the
  `dd:`/dark transform also applies to multi-singer colors.
- Lyrics/chords contrast against their own background (section labels,
  highlight markers) so highlighted text stays readable and reaches LaTeX
  output; a lyric fragment under a chord uses the lyric color, not the chord
  color.
