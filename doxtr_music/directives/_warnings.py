"""Standalone warning-drain helper for song-family directives.

The exact content-relative line math (``self.content_offset + 1 + body_line``)
that turns parser ``_warnings`` entries into Sphinx reporter warnings is factored
here so **every** directive that runs a parser reuses one authority instead of
copying the math:

* :class:`~doxtr_music.directives._base.SongDirectiveBase` (``.. song::``,
  ``.. chord-line::``, ``.. song-include::``) drains through this helper.
* Plain :class:`docutils.parsers.rst.Directive` subclasses without a
  ``build_nodes``/``title_id`` path — e.g. ``.. chord-progression::``
  (CHUNK-4-4) — reuse the same drain rather than duplicating the offset math.

This module imports only from Docutils (no Sphinx top-level import) so it stays
usable inside a directive ``run`` without violating the deferred-import contract.
"""

from __future__ import annotations

__all__ = ["drain_warnings"]


def drain_warnings(directive, song_meta):
    """Drain a parser's ``song_meta["_warnings"]`` through the directive reporter.

    Each ``_warnings`` entry is a ``(body_line, message)`` pair where
    ``body_line`` is the 0-based logical line index within the directive body.
    The directive marker sits at ``directive.lineno``; the first content line is
    therefore ``directive.content_offset + 1``, and a body warning maps to
    ``directive.content_offset + 1 + body_line``.

    Best-effort and never fatal: a malformed entry or a broken reporter must not
    crash the build. Non-tuple entries fall back to line
    ``content_offset + 1`` with the entry stringified.
    """
    meta = song_meta or {}
    reporter = getattr(getattr(directive, "state_machine", None), "reporter", None)
    base = getattr(directive, "content_offset", 0) + 1

    for warning in meta.get("_warnings", []):
        try:
            body_line, message = warning
        except (TypeError, ValueError):
            body_line, message = 0, str(warning)
        try:
            line = base + int(body_line)
        except (TypeError, ValueError):
            line = base
        if reporter is None:
            continue
        try:
            reporter.warning("doxtr-music: %s" % message, line=line)
        except Exception:  # pragma: no cover - reporter must never be fatal
            pass
