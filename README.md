# doxtr-music

Sheet music (chords + lyrics) for Sphinx docs: **HTML**, **LaTeX/PDF**, **ePub**.
Layout and build pipeline mirror doxtr-pdf-theme-core.

## Status

0.1.0 — first release (see [CHANGELOG](CHANGELOG.md)). All features ship across
HTML, LaTeX/PDF and ePub, verified by the feature harness (`--fail-on-pending`)
and a unit suite (~93% coverage) inside `doxtr/reactor:0.1.5`.

## Three-format support

HTML, LaTeX/PDF and ePub are **first-class**. Every renderable construct emits a
copy-safe HTML rendering (real chord spans over lyrics), a LaTeX rendering via
backend-neutral `\dm` macros (`songs`/`songbook` backends, exchangeable), and a
reflow-safe ePub `<pre>` two-row rendering — or a documented, tested fallback.
A single format-neutral node model dispatches to per-format visitors via the
`_VISITORS` seam (resolved by builder name), so a downstream theme can swap in
its own renderers without forking core. The seam is exposed through **stable
public names** on the top-level package — a child theme imports these instead of
reaching into underscored internals:

```python
import doxtr_music

def setup(app):
    app.setup_extension("doxtr_music")   # ensure core runs first
    reg = doxtr_music.get_visitor_registry()          # the _VISITORS seam
    reg["html"][SomeNodeClass] = (my_visit, my_depart) # override HTML rendering
    # LaTeX preamble contributor registry:
    doxtr_music.register_preamble_contributor(750, my_preamble_fn)
```

`get_visitor_registry()`, `register_html_visitors()`/`register_latex_visitors()`/
`register_epub_visitors()` (re-install the built-ins, then override), and
`register_preamble_contributor()` / `assemble_latex_preamble()` are the public
rendering seams. A child theme's `setup()` must run **after** `doxtr_music`'s so
its overrides win.

## Accessibility

HTML and EPUB output is oriented to **WCAG 2.1 AA**: the song container carries
`role="group"`, chords are exposed as `role="img"` with an `aria-label`,
multi-singer spans get a **visible** non-color cue (WCAG 1.4.1, so meaning does
not rely on color alone), and a warn-not-fail contrast check (WCAG 1.4.3) runs
against a documented background heuristic. LaTeX/PDF accessibility (e.g. PDF/UA
tagging) is out of scope for v1.

## Installation

```bash
pip install doxtr-music
```

Optional extras (all **soft** — never runtime dependencies):

```bash
pip install doxtr-music[musicxml]    # .. import-musicxml:: (defusedxml, XXE-safe)
pip install doxtr-music[clipboard]   # doxtr-music-convert --clipboard (pyperclip)
pip install doxtr-music[all]         # both of the above
```

For development, from the repo root: `pip install -e .[dev]`.

Add `doxtr_music` to `extensions` in `source/conf.py`.

> The extension adds a provenance tag `<meta name="doxtr-music"
> content="<version>"/>` to the head of every HTML page (the harness smoke
> test asserts on it to detect a missing/broken extension).

> Optional theme interop: when `doxtr-pdf-theme-core` is the active theme, its
> fonts/palette are picked up automatically (config-attribute detection, never
> an import) — it is *not* a dependency of doxtr-music.

## Usage

Add the extension and write a song in ChordPro (inline `[chords]` over lyrics):

```python
# source/conf.py
extensions += ["doxtr_music"]
```

```rst
.. song::

   {title: Amazing Grace}
   {key: G}

   A[G]mazing [G7]grace, how [C]sweet the [G]sound
   That [G]saved a [Em]wretch like [D]me
```

The chords render as real, copy-safe spans positioned over the lyric they
precede (HTML), as `\dmchord` macros with page-break avoidance (LaTeX), and as a
reflow-safe two-row `<pre>` block (ePub). Transposition (`:transpose:`), roman
analysis (`:roman-numerals:`), chord-system i18n (`en`/`de`/`it`/`hu`/`roman`),
RTL, multi-singer (`{singer:X}`), and per-song typography options are all
supported — see the harness cases in `test_harness/source/_test_cases/`.

## Directives & roles

| Syntax | Purpose | Formats |
|--------|---------|---------|
| `.. song::` | Primary container (ChordPro, metadata, per-song options) | H/L/E |
| `.. chord-line::` | Legacy chords-over-lyrics (column-aligned) | H/L/E |
| `.. song-include::` | Pull a confined `.cho`/ChordPro file from the source tree | H/L/E |
| `.. chord-progression::` | Chord / roman-numeral grid (semantic table) | H/L/E |
| `.. song-list::` / `.. song-index::` | Filtered list / index (safe AST filter); `:style: index` = alphabetical index with page numbers | H/L/E |
| `.. import-musicxml::` / `.. import-abc::` | External score imports → tokens | H/L/E |
| `:chord:` `:key:` `:roman:` | Inline roles | H/L/E |
| `doxtr-music-convert` (CLI) | Convert monospaced chords-over-lyrics → inline ChordPro | — |

New directives/importers/formats extend documented seams — `ImportDirectiveBase`
(new importers), the `_lyrics`/`tokens_to_chordpro` pair (new text formats), the
`_VISITORS` bucket + preamble contributor registry (new output formats), and the
plugin hooks below — without touching core.

### Add your own importer

An importer is a pure `parse(text) -> (tokens, song_meta)` function plus a thin
`ImportDirectiveBase` subclass; it converges on the locked token vocabulary and
reuses the shared `.. song::` rendering across all three formats — no
format-specific code:

```python
from doxtr_music.directives._import_base import ImportDirectiveBase

def parse_myformat(text):
    tokens = []          # build ChordToken/LyricToken/SectionToken/... here
    song_meta = {}       # locked song_meta shape
    return tokens, song_meta

class ImportMyFormatDirective(ImportDirectiveBase):
    parser_fn = staticmethod(parse_myformat)   # (text) -> (tokens, song_meta)

def setup(app):
    app.setup_extension("doxtr_music")
    app.add_directive("import-myformat", ImportMyFormatDirective)
```

The base handles source-text loading (confined file reads via
`load_confined_source`), the `_post_parse_transform` pipeline (chord
preprocess → transpose → roman), and node building; you only supply the parser.

## Configuration

| Conf value | Default | Rebuild scope | Meaning |
|------------|---------|---------------|---------|
| `doxtr_music_chord_system` | `english` | `env` | Notation system (english/german/italian/hungarian/roman) |
| `doxtr_music_roman_display` | `off` | `env` | Roman-numeral display: `off` / `replace` (numeral instead of chord) / `alongside` (chord **and** numeral) |
| `doxtr_music_roman_format` | `{chord} ({roman})` | `env` | `alongside` template (`{chord}`/`{roman}` placeholders; `\n` stacks) |
| `doxtr_music_index_page_format` | `{page}` | `env` | Page-number format for `.. song-index:: :style: index` (LaTeX/PDF); single `{page}` placeholder, e.g. `page {page}`; the whole phrase links to the song |
| `doxtr_music_latex_package` | `songbook` | `env` | LaTeX bridge backend (`songs`/`songbook`) |
| `doxtr_music_latex_backend_path` | `None` | `env` | User override dir for LaTeX backend `*.tex_t` templates |
| `doxtr_music_typography` | `{}` | `env` | Granular per-element **font / size / color / background** (see *Styling & typography*) |
| `doxtr_music_singer_colors` | `{}` | `env` | Global singer-ID → color map (per-song override wins) |
| `doxtr_music_theme_interop` | `True` | `env` | Pull fonts/palette from `doxtr-pdf-theme-core` when it is the active theme |
| `doxtr_music_autoload_theme` | `True` | `env` | Auto-load `doxtr-pdf-theme-core` as an extension when it is installed (no need to list it before `doxtr_music`); set `False` to opt out |
| `doxtr_music_chord_preprocess` | `None` | `env` | Hook `(chord, song_meta) -> str` |
| `doxtr_music_node_parsed` | `None` | `env` | Hook `(SongNode) -> None` |
| `doxtr_music_html_visit` | `None` | `html` | Custom HTML injection hook |

## Styling & typography

`doxtr_music_typography` is a nested `{element: {attribute: value}}` dict giving
independent control over every song element in all three formats (HTML, LaTeX/
PDF, EPUB). Each element accepts up to four attributes:

| Attribute | Value |
|-----------|-------|
| `font` | a CSS font-family: a generic (`serif`/`sans-serif`/`monospace`) or a **named font** (`Lato`, `Anton`, …). Named fonts render in PDF under a fontspec engine (LuaLaTeX/XeLaTeX — provided by the theme) and must be installed on the build host; generics map to `\rmfamily`/`\sffamily`/`\ttfamily`. |
| `size` | a CSS size (EPUB requires a **relative** unit like `1.1em`; absolute is downgraded) |
| `color` | a text color (`#rgb`/`#rrggbb`, an xcolor name, or a `dd:` expression — see below) |
| `background` | a background color (HTML/EPUB `background-color`; LaTeX `\colorbox` on block elements) |

### Elements

**Base elements** — `title`, `metadata`, `roman`, `chord`, `lyrics`.

**Section elements** (flexible — any section kind a songwriter introduces):

- `section-title` / `section-body` — defaults for **every** section.
- `section-<kind>-title` / `section-<kind>-body` — a specific kind
  (`verse`/`chorus`/`bridge`/… or any custom kind), overriding the generic
  section styling for that kind only. The per-kind cell falls back to the
  generic `section-title`/`section-body` for any attribute it does not set.

Custom section kinds come from ChordPro `{start_of_<kind>}` / `{end_of_<kind>}`
directives (e.g. `{start_of_highlight}`), so you can introduce any kind and
style it. A `section-<kind>-body` **background** cascades onto that section's
lyric words — a marker-pen highlight (e.g. a yellow `#fff59d` background on one
section) that renders in all three formats (HTML/EPUB `background-color`, LaTeX
per-word `\colorbox`).

**Metadata elements** (song-metadata rows are rendered as a `Label: value`
block):

- `metadata` — the default style for **all** metadata rows.
- `meta-<key>` — a specific metadata key (`tempo`, `key`, or any key you use),
  overriding `metadata` for that row only (falls back to `metadata`).

```python
doxtr_music_typography = {
    # Title: navy on a pale panel.
    "title":               {"color": "#1a3d7a", "background": "#eef"},
    # Chords: bold red; lyrics slightly larger.
    "chord":               {"color": "#b00020"},
    "lyrics":              {"size": "1.05em"},
    # Every section label italic-gray by default…
    "section-title":       {"color": "#555"},
    # …but the chorus stands out with a tinted background.
    "section-chorus-title": {"color": "#0a6", "background": "#eaffea"},
    # Verse body in a slightly smaller size.
    "section-verse-body":  {"size": "0.98em"},
    # Metadata rows small; the Tempo row monospace + blue.
    "metadata":            {"size": "0.9em"},
    "meta-tempo":          {"color": "#00a", "font": "monospace"},
    "meta-key":            {"color": "#0a0"},
}
```

Per-song directive options override the global config for one song, e.g.
`:chord-color:`, `:lyrics-size:`, `:title-color:` (the base-element grid).

### Theme integration

#### `dd:` color expressions

Any `color`/`background` value may be a **`dd:` expression** that
`doxtr-pdf-theme-core` resolves against its **semantic palette**, so song colors
track the active theme (swap the theme → songs re-color automatically):

```python
doxtr_music_typography = {
    "title": {"color": "dd:primary"},
    "chord": {"color": "dd:secondary:contrast:fg:page"},  # WCAG-safe
    "section-verse-title": {"background": "dd:primary:lighten:85"},
}
```

Common forms: `dd:primary` (a palette color), `dd:page` (page background),
`dd:primary:lighten:80` / `dd:primary:darken:30` (tints),
`dd:secondary:contrast:fg:page` (auto WCAG-contrast against the page). `dd:`
expressions **require the theme** — using one without `doxtr-pdf-theme-core`
installed fails with an actionable error asking you to install the theme or use
a static color (e.g. `#1a3d7a`). Static colors work with or without the theme.

#### Automatic palette pickup

When `doxtr-pdf-theme-core` is the active theme its **semantic palette** is
picked up conservatively (theme tier, below your config + per-song overrides):
the body font/text color style the lyrics, the accent color styles chords, a
distinct heading color styles the title, and a panel/surface color tints the
section titles. If the theme is installed it is **auto-loaded** — you do not
have to list it before `doxtr_music` in `extensions` (disable with
`doxtr_music_autoload_theme = False`).

#### Default lyric color & dark mode

When the theme is active, lyrics with no explicit color use the **document's
body text color** (so they match the surrounding prose). In **dark-mode** builds
all doxtr-music colors transform with the rest of the document via the theme's
own helpers: `dd:` expressions resolve against the theme's **dark** palette,
static hex colors are soft-inverted, and the default lyric color becomes the
dark body text color. The same `conf.py` produces correct light and dark builds.

## CLI: `doxtr-music-convert`

Converts monospaced chords-over-lyrics text into inline ChordPro suitable for
pasting into a `.. song::` directive. The CLI imports **without Sphinx** (the
pure parser layer is standalone):

```bash
doxtr-music-convert input.txt          # -> ChordPro on stdout
doxtr-music-convert --stdin < in.txt   # read stdin
doxtr-music-convert --clipboard        # read the clipboard (needs [clipboard])
doxtr-music-convert input.txt -o out.cho
```

## Test Harness

`test_harness/` is the end-to-end feature pipeline (mirrors doxtr-pdf-theme-core,
HTML-first): every feature is registered in `test_harness/features.py`, built
per-feature by `test_harness/test_runner.py`, and validated against expected
markers + assertions (`test_harness/assertions.py`).

```bash
cd test_harness
python test_runner.py --fail-on-pending   # CI mode (exit 1 on fail/pending)
python test_runner.py --feature smoke     # single feature
python features.py                        # registry summary
make ci                                   # same as CI mode
```

Add a case: register a `FeatureSubTest` in `features.py` → RST in
`source/_test_cases/` → optional conf override in `conf_overrides/` → set
`status=COMPLETE` when green. Full docs: `test_harness/README.md`.

## Development

- Unit tests: `python -m pytest tests/ test_harness/ -v`
- Feature harness: `cd test_harness && python test_runner.py --fail-on-pending`
- RST style: `cd test_harness && make doc8`

## License

MIT.
