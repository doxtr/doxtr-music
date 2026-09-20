"""Shared base for file-backed importer directives (owned by CHUNK-6-1).

``ImportDirectiveBase`` is a thin subclass of
:class:`~doxtr_music.directives._base.SongDirectiveBase` for directives that
import an **external notation file** (MusicXML, ABC, ...) rather than a ChordPro
body. It overrides exactly one seam — :meth:`_get_source_text` — to read the
directive's single path argument through the shared confined loader
(:func:`doxtr_music.directives._fileload.load_confined_source`); everything else
(the ``chord_preprocess → transpose → roman`` pipeline, warning drain, node
build, id assignment, typography/singer stamping, contrast check, reserved
hooks, registry write) is inherited unchanged, so an imported song is a
**first-class** song identical in intent to ``.. song::``.

Front-end convergence invariant (LOCKED — CHUNK-3-1 / CHUNK-6-1):

* An importer is a **pure** ``parse_*(text) -> (tokens, song_meta)`` parser
  (no Sphinx import, CLI-reusable) that converges on the *existing* locked
  token vocabulary (:mod:`doxtr_music.tokens`) — it never introduces a new node
  or token type and never emits format-specific code.
* All author-file reads go through the single confined loader; no importer
  inlines path confinement.

**CHUNK-6-1 owns this base; CHUNK-6-2 (``.. import-abc::``) subclasses it** by
setting :attr:`parser_fn` to its own pure parser.
"""

from __future__ import annotations

from doxtr_music.directives._base import SongDirectiveBase

__all__ = ["ImportDirectiveBase"]


class ImportDirectiveBase(SongDirectiveBase):
    """Common ``run`` pipeline for file-backed importer directives.

    Takes exactly one argument (the document-relative path to the notation
    file) and no body. Subclasses set :attr:`parser_fn` to a pure
    ``text -> (tokens, song_meta)`` parser; the rest of the behavior is the
    inherited :class:`~doxtr_music.directives._base.SongDirectiveBase` pipeline,
    so imported songs render identically to ``.. song::`` in all three formats.
    """

    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = True
    has_content = False

    def _get_source_text(self):
        """Read the external notation file via the shared confined loader.

        Resolves + confines the single path argument to the source root and
        registers a build dependency (see
        :func:`doxtr_music.directives._fileload.load_confined_source`). A
        confinement/read failure raises the directive's ``DirectiveError`` so
        the directive renders nothing and Sphinx reports it with source-line
        provenance — never a traceback.
        """
        from doxtr_music.directives._fileload import load_confined_source

        env = self.state.document.settings.env
        arg = self.arguments[0]
        _real, text = load_confined_source(env, self, arg)
        return text
