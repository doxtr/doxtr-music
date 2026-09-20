# doxtr-music — Test Harness

The **single source of truth** for feature coverage. Every renderable feature
is declared once in `features.py`; the harness auto-discovers what to build,
what to render, and how to validate it.

## Quick start

```bash
cd test_harness

python test_runner.py                     # build + validate every feature
python test_runner.py --feature smoke     # only the "smoke" feature
python test_runner.py --fail-on-pending   # CI mode: non-zero if any pending
python features.py                        # print the registry summary
make ci                                   # == --fail-on-pending
```

## Architecture

```
test_harness/
├── features.py          # SSOT: FEATURE_REGISTRY (features + sub-tests)
├── assertions.py        # AssertType + check_assertions() (HTML-first)
├── test_runner.py       # builds each feature, resolves output, validates
├── conf.py              # base Sphinx config (html_theme="basic")
├── conf_overrides/      # per-feature config overrides: <feature>.py
├── Makefile             # convenience targets
├── .doc8.ini            # doc8 config (max-line-length = 100)
└── source/
    ├── index.rst        # includes the auto-generated toctree
    ├── _extensions/
    │   └── auto_include_tests.py   # writes _generated_toctree.rst
    ├── _static/
    └── _test_cases/     # one .rst fixture per feature
```

`test_runner.py`, `features.py`, `assertions.py`, and `auto_include_tests.py`
are intentionally NOT named `test_*.py`, so pytest (which collects `test_*.py`)
does not import them as tests; they also have no import-time side effects.

## Multi-format model (LOCKED)

Each `FeatureSubTest` declares:

- `formats: list[str]` — the output lanes it exercises (`"html"`, `"latex"`,
  `"epub"`). Defaults to `["html"]`.
- `expected_markers: dict[str, list[str]]` — regex (literal fallback) markers,
  **keyed by format**. A marker can be HTML-only (e.g. the provenance `<meta>`
  tag has no LaTeX/EPUB analog).
- `assertions: dict[str, list[str]]` — `AssertType` names, **keyed by format**.

The runner builds each needed format once via the `BUILDER_MAP`
(`builder -> (sphinx_target, resolver)`) and validates each format's keyed
markers/assertions against that format's resolved output. Only the `html`
resolver is implemented in this chunk; `latex`/`epub` resolvers raise
`NotImplementedError("CHUNK-2-3")` and are filled there — **without editing the
runner loop or the dataclasses**.

## How to add a feature

1. Add a `Feature` (with one or more `FeatureSubTest`s) to `FEATURE_REGISTRY`
   in `features.py`. Populate `expected_markers["html"]` / `assertions["html"]`
   and set `formats` accordingly. Set `status=FeatureStatus.COMPLETE` when it
   passes.
2. Create the RST fixture at `source/_test_cases/<feature>.rst` (doc8-clean,
   ≤ 100 columns).
3. If the feature needs config, create `conf_overrides/<feature>.py` (the
   `conf_overrides/<feature>.py` naming convention). **Do not reference a
   `doxtr_music_*` config key before the chunk that registers it is DONE** —
   otherwise Sphinx warns.
4. Run `python test_runner.py --feature <feature>` and confirm PASSED.
