"""The ``.. import-musicxml::`` directive — render an external MusicXML score.

``.. import-musicxml:: <path.musicxml>`` converts an uncompressed MusicXML file
into the locked token vocabulary via the pure :func:`parse_musicxml` parser and
renders it **identically** to ``.. song::`` in all three formats — by reusing
:class:`~doxtr_music.directives._import_base.ImportDirectiveBase` (which itself
extends :class:`~doxtr_music.directives._base.SongDirectiveBase`). It introduces
no new node/token type and no format-specific code (front-end convergence,
CHUNK-3-1 / CHUNK-6-1).

Because it inherits the full ``SongDirectiveBase`` pipeline, an imported song is
first-class: ``:transpose:``/``:key:``/``:roman-numerals:``/typography/singer/
registry all apply, and the score's ``<key>`` feeds roman analysis.

Security (LOCKED): the file path is confined to the source tree and registered
as a build dependency via the shared
:func:`doxtr_music.directives._fileload.load_confined_source`; the MusicXML
itself is parsed with ``defusedxml`` (XXE / entity-bomb safe), a hard
requirement of the import feature (optional-dep ``doxtr-music[musicxml]``).
"""

from __future__ import annotations

from doxtr_music.directives._import_base import ImportDirectiveBase
from doxtr_music.parsers.musicxml import parse_musicxml

__all__ = ["ImportMusicXMLDirective"]


class ImportMusicXMLDirective(ImportDirectiveBase):
    """``.. import-musicxml:: <path>`` — render an external MusicXML score.

    Takes exactly one argument (the document-relative path to an uncompressed
    ``.xml``/``.musicxml`` file) and no body. Everything else (confined file
    read, transpose/roman pipeline, warning drain, node build, id assignment,
    typography/singer stamping, contrast check, reserved hooks, registry write)
    is inherited, so the rendering is identical to ``.. song::``.
    """

    #: Front-end convergence: a pure ``text -> (tokens, song_meta)`` parser that
    #: converges on the existing token vocabulary (never a new node/token type).
    parser_fn = staticmethod(parse_musicxml)
