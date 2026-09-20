"""The ``.. song-include::`` directive — render an external ChordPro file.

``.. song-include:: <path.cho>`` pulls a raw external ChordPro file and renders
it **identically** to ``.. song::`` by reusing the same
:class:`~doxtr_music.directives._base.SongDirectiveBase` pipeline and the same
``parse_chordpro`` front end (front-end convergence — no second parser). It only
overrides :meth:`~doxtr_music.directives._base.SongDirectiveBase._get_source_text`
to read the file through the confined loader instead of the directive body.

Security (LOCKED — via the shared confined loader): path resolution +
confinement (reject absolute args, ``..``/symlink escapes) and the build
``note_dependency`` registration live once in
:func:`doxtr_music.directives._fileload.load_confined_source`; this directive
calls it rather than inlining the checks.

Inherited options: because it shares ``_options.py``'s ``option_spec`` via the
base class, ``:transpose:`` / ``:key:`` / ``:roman-numerals:`` / typography all
work exactly as on ``.. song::``.
"""

from __future__ import annotations

from doxtr_music.directives._base import SongDirectiveBase
from doxtr_music.parsers.chordpro import parse_chordpro

__all__ = ["SongIncludeDirective"]


class SongIncludeDirective(SongDirectiveBase):
    """``.. song-include:: <path>`` — render an external ChordPro file.

    Takes exactly one argument (the document-relative file path) and no body.
    Everything else (transpose/roman pipeline, warning drain, node build, id
    assignment, reserved hooks) is inherited from
    :class:`~doxtr_music.directives._base.SongDirectiveBase`, so the rendering is
    identical to ``.. song::``.
    """

    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = True
    has_content = False

    #: Front-end convergence: the SAME ChordPro parser as ``.. song::`` — never
    #: a second parser (LOCKED, CHUNK-3-1).
    parser_fn = staticmethod(parse_chordpro)

    def _get_source_text(self):
        """Read the external ChordPro file via the confined loader.

        Resolves + confines the argument path to the source root and registers a
        build dependency (see
        :func:`doxtr_music.directives._fileload.load_confined_source`). A
        confinement/read failure raises the directive's ``DirectiveError`` so the
        directive renders nothing and Sphinx reports it with source-line
        provenance.
        """
        from doxtr_music.directives._fileload import load_confined_source

        env = self.state.document.settings.env
        arg = self.arguments[0]
        _real, text = load_confined_source(env, self, arg)
        return text
