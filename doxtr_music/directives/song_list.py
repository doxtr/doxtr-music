r"""``.. song-list::`` and ``.. song-index::`` — dynamic song directories (CHUNK-5-3).

Both directives are **read-phase placeholders**: their ``run()`` emits a reserved
:class:`~doxtr_music.nodes.SongListNode` / :class:`~doxtr_music.nodes.SongIndexNode`
carrying the raw ``:filter:`` / ``:group-by:`` / ``:sort:`` option strings as plain
node attributes, and registers the containing docname on
``env.doxtr_music_query_docs`` so CHUNK-5-3's incremental machinery
(:mod:`doxtr_music.resolve`) can re-resolve the doc when the registry changes.

They do **not** query ``env.song_data`` during read (LOCKED): parallel-read workers
have not merged their registries yet and :func:`~doxtr_music.registry.iter_songs`
is resolve-only. The actual query + node replacement happens at the
``doctree-resolved`` event (see :mod:`doxtr_music.resolve`), which turns each
placeholder into **standard docutils nodes** (``bullet_list``/``reference`` and
``definition_list``/``rubric``) rendered by Sphinx's own HTML/LaTeX/EPUB writers.

Option semantics (LOCKED):

* ``:filter:`` — a safe boolean expression evaluated per song entry via
  :func:`doxtr_music.safe_eval.safe_eval` (the sole expression authority). No
  ``eval``. A malformed filter yields an empty list + a warning (never a crash,
  never all songs).
* ``:group-by:`` (song-index) — a **metadata key name** (``entry.get(key)``), not
  an expression. ``safe_eval`` returns a bool and cannot produce a group value.
  A missing/``None`` key groups under the single ``"Other"`` label.
* ``:sort:`` — a **metadata key name**; a stable sort by that key (missing → last).

This module imports only Docutils + the pure node layer at top level (no Sphinx
import), honoring the deferred-import contract.
"""

from __future__ import annotations

from docutils.parsers.rst import Directive, directives

from doxtr_music import nodes as _nodes

__all__ = [
    "SongListDirective",
    "SongIndexDirective",
    "QUERY_DOCS_ATTR",
    "register_query_doc",
]

#: The ``env`` attribute holding the set of docnames that contain a
#: ``song-list``/``song-index`` (registered at read; read by the incremental
#: signature machinery in :mod:`doxtr_music.resolve`).
QUERY_DOCS_ATTR = "doxtr_music_query_docs"


def register_query_doc(env, docname):
    """Record ``docname`` as containing a song-list/index query (read phase).

    Lazily initialises ``env.doxtr_music_query_docs`` to a ``set``. Idempotent:
    a doc that re-reads simply re-adds its own name. The set is plain picklable
    data (of ``str``) so it survives ``env-purge-doc`` / parallel merge.
    """
    docs = getattr(env, QUERY_DOCS_ATTR, None)
    if docs is None:
        docs = set()
        setattr(env, QUERY_DOCS_ATTR, docs)
    docs.add(docname)


class _QueryDirectiveBase(Directive):
    """Shared read-phase placeholder emitter for song-list / song-index.

    Subclasses set :attr:`node_class`. Both take no argument and no body; all
    behaviour is carried by the raw option strings stored on the placeholder.
    """

    #: The reserved placeholder node class (set by subclasses).
    node_class = None

    required_arguments = 0
    optional_arguments = 0
    has_content = False
    option_spec = {
        "filter": directives.unchanged,
        "group-by": directives.unchanged,
        "sort": directives.unchanged,
        "style": directives.unchanged,   # song-index: "list" (default) | "index"
    }

    def run(self):
        """Emit the reserved placeholder node and register the docname.

        No registry query happens here (LOCKED read/resolve split). The raw
        option strings are stored verbatim as node attrs (``filter``/``group_by``/
        ``sort``/``style``) for :mod:`doxtr_music.resolve` to consume at
        ``doctree-resolved``.
        """
        node = self.node_class()
        node["filter"] = self.options.get("filter")
        node["group_by"] = self.options.get("group-by")
        node["sort"] = self.options.get("sort")
        node["style"] = self.options.get("style")
        node["docname"] = None  # set below when an env is available

        try:
            env = self.state.document.settings.env
        except Exception:  # pragma: no cover - no env in bare unit tests
            env = None
        if env is not None:
            node["docname"] = env.docname
            register_query_doc(env, env.docname)
        return [node]


class SongListDirective(_QueryDirectiveBase):
    """``.. song-list::`` — a filtered, cross-referenced list of songs.

    Emits a :class:`~doxtr_music.nodes.SongListNode` placeholder at read; the
    ``doctree-resolved`` handler replaces it with a ``bullet_list`` of
    ``reference`` nodes to the matching songs (all three formats).
    """

    node_class = _nodes.SongListNode


class SongIndexDirective(_QueryDirectiveBase):
    """``.. song-index::`` — a glossary-style index grouped by a metadata key.

    Emits a :class:`~doxtr_music.nodes.SongIndexNode` placeholder at read; the
    ``doctree-resolved`` handler replaces it with a ``definition_list`` of group
    headings, each holding a ``bullet_list`` of ``reference`` nodes (all three
    formats). ``:group-by:`` is a metadata key (``entry.get(key)``), never a
    ``safe_eval`` expression.
    """

    node_class = _nodes.SongIndexNode
