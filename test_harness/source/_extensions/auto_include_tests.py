"""
doxtr-music — Auto-Include Test Cases (Sphinx extension)

Reads ``features.py`` and auto-generates the harness toctree so new features
are included without manual ``index.rst`` edits. Mirrors the
doxtr-pdf-theme-core auto-include logic in shape (grouped by status; only
features with an RST fixture are linked).

Usage: add ``"auto_include_tests"`` to ``extensions`` in ``conf.py``. On
``builder-inited`` it writes ``source/_generated_toctree.rst``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure we can import features.py from the test_harness directory.
_harness_dir = Path(__file__).resolve().parent.parent
if str(_harness_dir) not in sys.path:
    sys.path.insert(0, str(_harness_dir))

from features import FEATURE_REGISTRY, FeatureStatus  # noqa: E402


def setup(app):
    """Register the extension with Sphinx."""
    app.connect("builder-inited", on_builder_inited)
    return {
        "version": "0.0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }


def on_builder_inited(app):
    """Generate the auto toctree from the feature registry at build time."""
    toctree_content = _generate_toctree()
    toctree_path = Path(app.srcdir) / "_generated_toctree.rst"
    toctree_path.write_text(toctree_content, encoding="utf-8")


def _generate_toctree() -> str:
    """Generate the toctree content, grouped by status, RST-features only."""
    lines = [
        ".. toctree::\n",
        "   :maxdepth: 1\n",
        "   :caption: Test Cases\n",
        "   :hidden:\n",
        "\n",
    ]

    for status in (FeatureStatus.COMPLETE, FeatureStatus.PARTIAL, FeatureStatus.PENDING):
        features_with_status = [
            name for name, feat in FEATURE_REGISTRY.items()
            if any(st.status == status for st in feat.sub_tests)
            and any(st.rst_file for st in feat.sub_tests)
        ]
        if not features_with_status:
            continue
        for name in sorted(features_with_status):
            lines.append(f"   _test_cases/{name}\n")

    return "".join(lines)
