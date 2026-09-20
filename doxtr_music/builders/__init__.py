"""Builders package for doxtr-music — per-format visitor bodies.

Each module here fills exactly one bucket of the ``_VISITORS`` seam defined in
:mod:`doxtr_music.nodes` by plain dict assignment (never ``add_node`` /
``override=True``, never editing ``nodes.py``):

* :mod:`doxtr_music.builders.html`  → ``_VISITORS["html"]`` (CHUNK-1-4)
* ``doxtr_music.builders.latex``    → ``_VISITORS["latex"]`` (CHUNK-2-1)
* ``doxtr_music.builders.epub``     → ``_VISITORS["epub"]`` (CHUNK-2-2)

This keeps the three output formats independently swappable and lets a child
theme replace a whole format's rendering without forking core.
"""

from __future__ import annotations

__all__ = []
