"""
doxtr-music — Test Harness Base Sphinx Configuration

This is the BASE configuration for the test harness. Per-feature overrides in
``conf_overrides/`` are merged on top of this at build time by ``test_runner``.

To add a new feature test:
    1. Add a FeatureSubTest to features.py.
    2. Create the RST fixture in source/_test_cases/ (optional).
    3. Create a conf override in conf_overrides/<feature>.py (optional).

INVARIANTS (LOCKED):
    * ``html_theme = "basic"`` is load-bearing: the CHUNK-0-1 provenance meta
      tag is injected via ``context['metatags']`` on ``html-page-context``,
      which only reaches ``<head>`` when the theme's ``layout.html`` emits
      ``{{ metatags }}`` (the built-in ``basic`` theme does). Do NOT replace it
      with ``None``/minimal.
    * This base config sets NO ``doxtr_music_*`` values. Config registration is
      owned by CHUNK-0-3; per-feature ``conf_overrides`` set the values.
"""

# -- Project information -----------------------------------------------------
project = "doxtr-music Test Harness"
copyright = "2026, Doxtr"
author = "Doxtr"
version = "0.0.1"
release = "0.0.1"

# -- General configuration ---------------------------------------------------
extensions = [
    "doxtr_music",
    "auto_include_tests",
]

# The harness tests doxtr_music in ISOLATION. When doxtr-pdf-theme-core happens
# to be installed in the build environment, doxtr_music would auto-load it and
# its theme-tier palette would color chords/lyrics in every feature build,
# masking the config/per-song styling each feature asserts. Disable the
# auto-load so harness output depends only on doxtr_music + each feature's own
# conf override. (A feature that specifically exercises theme interop supplies
# its own stubbed ``doxtr_theme_defaults``.)
doxtr_music_autoload_theme = False

master_doc = "index"
exclude_patterns = [
    "_build",
    "_extensions",
    "conf_overrides",
    "features.py",
    "test_runner.py",
    "assertions.py",
    "*.md",
]

# -- HTML output (primary / load-bearing) ------------------------------------
html_theme = "basic"
html_static_path = ["_static"]

# -- Extension search path ---------------------------------------------------
import os
import sys

sys.path.insert(0, os.path.abspath("_extensions"))
