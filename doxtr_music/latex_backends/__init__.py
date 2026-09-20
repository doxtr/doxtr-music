"""Packaged LaTeX backend templates (``*.tex_t``) for doxtr-music.

This package ships the ``preamble.tex_t`` skeleton plus one ``.tex_t`` fragment
per supported backend package (``songs``/``songbook``). The fragments are
rendered via Sphinx's :class:`sphinx.util.template.LaTeXRenderer` (JSP-style
``<%= %>`` delimiters that don't clash with LaTeX braces) — see
:mod:`doxtr_music.builders.latex`.

The directory is data, not importable code; this ``__init__`` exists so
``importlib.resources`` / package-data discovery treat it as a package and so
``pyproject.toml`` can ship ``latex_backends/*.tex_t`` in the wheel.
"""

__all__ = []
