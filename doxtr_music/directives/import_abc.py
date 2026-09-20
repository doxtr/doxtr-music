"""The ``.. import-abc::`` directive — render an external ABC notation tune.

``.. import-abc:: <path.abc>`` converts an ABC file into the locked token
vocabulary via the pure :func:`parse_abc` parser and renders it **identically**
to ``.. song::`` in all three formats — by reusing
:class:`~doxtr_music.directives._import_base.ImportDirectiveBase` (which itself
extends :class:`~doxtr_music.directives._base.SongDirectiveBase`). It introduces
no new node/token type and no format-specific code (front-end convergence,
CHUNK-3-1 / CHUNK-6-1 / CHUNK-6-2). Sibling of ``.. import-musicxml::``.

Because it inherits the full ``SongDirectiveBase`` pipeline, an imported tune is
first-class: ``:transpose:``/``:key:``/``:roman-numerals:``/typography/singer/
registry all apply, and the tune's ``K:`` field feeds roman analysis.

Security (LOCKED): the file path is confined to the source tree and registered
as a build dependency via the shared
:func:`doxtr_music.directives._fileload.load_confined_source` (owned by
CHUNK-6-1). ABC is plain text — no XML-bomb surface — and the parser scans
linearly and degrades gracefully on malformed input.
"""

from __future__ import annotations

from doxtr_music.directives._import_base import ImportDirectiveBase
from doxtr_music.parsers.abc import parse_abc

__all__ = ["ImportABCDirective"]


class ImportABCDirective(ImportDirectiveBase):
    """``.. import-abc:: <path>`` — render an external ABC notation tune.

    Takes exactly one argument (the document-relative path to a ``.abc`` file)
    and no body. Everything else (confined file read, transpose/roman pipeline,
    warning drain, node build, id assignment, typography/singer stamping,
    contrast check, reserved hooks, registry write) is inherited from
    :class:`ImportDirectiveBase`, so the rendering is identical to ``.. song::``.
    """

    #: Front-end convergence: a pure ``text -> (tokens, song_meta)`` parser that
    #: converges on the existing token vocabulary (never a new node/token type).
    parser_fn = staticmethod(parse_abc)
