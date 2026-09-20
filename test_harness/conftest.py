"""Pytest configuration for the test_harness directory.

The harness machinery modules match the repo's ``python_files = ["test_*.py"]``
glob (notably ``test_runner.py``) but are NOT test modules — they are the
harness itself, imported and driven by ``test_runner.py``'s CLI. Ignore them
during collection so pytest stays clean (EC9: runner pytest-collection-inert).

Actual harness unit tests, if any are added later, must be named distinctly
(e.g. ``harness_test_*.py`` is avoided; use ``test_*`` files placed here only
when they are genuine tests) — for now all unit tests live in ``../tests/``.
"""

collect_ignore = ["test_runner.py"]
