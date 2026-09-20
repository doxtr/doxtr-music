"""Confined external-file loading for author-file directives (created here for
CHUNK-3-5, reused by CHUNK-6-1/6-2).

A single security-critical helper, :func:`load_confined_source`, is the sole
place a doxtr-music directive reads an author-supplied file path. The file-read
**confinement invariant is stated once here** and reused by ``.. song-include::``
(CHUNK-3-5) and the importer directives ``.. import-musicxml::`` /
``.. import-abc::`` (CHUNK-6-1/6-2), so the check is never copy-pasted across
three directives (where it could silently drift).

Confinement (LOCKED)
--------------------

Given a directive argument, the loader:

* rejects an **absolute-path** argument outright (Sphinx error, render nothing);
* resolves the argument relative to the current document via
  ``env.relfn2path(arg)`` → ``(rel, abs)``;
* resolves symlinks with :func:`os.path.realpath` on BOTH the candidate and the
  source root, then requires
  ``os.path.commonpath([real, root]) == root`` — this catches ``..`` traversal
  **and** symlink escapes (a literal ``".."`` string check is insufficient);
* reads the file as UTF-8 (a leading BOM is tolerated);
* registers the resolved **absolute** path with ``env.note_dependency`` so
  editing the external file triggers a rebuild.

On any confinement/read failure the loader raises the directive's own
``self.error(...)`` (a ``docutils`` ``DirectiveError``) so the directive renders
nothing and Sphinx reports the problem with source-line provenance — never a
traceback/crash.
"""

from __future__ import annotations

import os

__all__ = ["load_confined_source", "ConfinementError"]


class ConfinementError(Exception):
    """Raised internally when a path escapes the source root or cannot be read.

    Callers catch this and re-raise via ``self.error(...)`` so the failure is
    reported with directive source-line provenance rather than as a traceback.
    """


def _resolve_confined_path(env, arg):
    """Resolve ``arg`` to a confined absolute path, or raise ConfinementError.

    Pure of Docutils/Sphinx reporter concerns: returns the real absolute path
    string on success; raises :class:`ConfinementError` with a human message on
    an absolute argument, a traversal/symlink escape, or an unresolvable path.
    """
    if not arg or not str(arg).strip():
        raise ConfinementError("empty file path")
    raw = str(arg).strip()

    # Reject absolute-path arguments outright (both POSIX ``/`` and Windows
    # drive/UNC forms) — external files must be addressed relative to the doc.
    if os.path.isabs(raw) or (os.name == "nt" and raw[:2] in ("\\\\",)):
        raise ConfinementError("absolute file paths are not allowed: %r" % raw)

    # Resolve relative to the current document (env.relfn2path → (rel, abs)).
    try:
        _rel, abs_path = env.relfn2path(raw)
    except Exception as exc:  # pragma: no cover - defensive
        raise ConfinementError("cannot resolve path %r: %s" % (raw, exc))

    # realpath BOTH sides so symlink escapes are caught, then require the source
    # root to be the common ancestor. commonpath raises ValueError on mixed
    # drives / empty input — treat that as an escape.
    real = os.path.realpath(abs_path)
    root = os.path.realpath(str(env.srcdir))
    try:
        common = os.path.commonpath([real, root])
    except ValueError:
        raise ConfinementError("path %r escapes the source directory" % raw)
    if common != root:
        raise ConfinementError("path %r escapes the source directory" % raw)

    return real


def _read_utf8(path):
    """Read ``path`` as UTF-8 text (tolerating a leading BOM); raise on error."""
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return handle.read()
    except OSError as exc:
        raise ConfinementError("cannot read file: %s" % exc)


def load_confined_source(env, directive, arg):
    """Load an author file confined to the source root.

    Args:
        env: the Sphinx build environment (provides ``relfn2path`` / ``srcdir``
            / ``note_dependency``).
        directive: the calling ``Directive`` instance (for ``self.error`` on
            failure — reported with source-line provenance).
        arg: the raw directive argument (a document-relative file path).

    Returns:
        ``(real_abs_path, text)`` — the resolved absolute path (also registered
        as a build dependency) and the file's UTF-8 text.

    Raises:
        The directive's ``DirectiveError`` (via ``directive.error(...)``) on an
        absolute path, a traversal/symlink escape, or an unreadable file, so the
        directive renders nothing and Sphinx reports the failure.
    """
    try:
        real = _resolve_confined_path(env, arg)
        text = _read_utf8(real)
    except ConfinementError as exc:
        raise directive.error("doxtr-music: %s" % exc)

    # Register the resolved absolute path so editing it triggers a rebuild.
    env.note_dependency(real)
    return real, text
