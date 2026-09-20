"""``env.song_data`` — the global song registry (CHUNK-5-1).

Per-song metadata is snapshotted into ``env.song_data`` during the **read**
phase so dynamic directives (``.. song-list::`` / ``.. song-index::``,
CHUNK-5-3) can query it during the **resolve** phase — parallel-safe and
incremental-build-correct.

Registry authority (LOCKED — single writer, single reader)
----------------------------------------------------------
``env.song_data`` is written **only** via :func:`register_song`, called from the
single :meth:`SongDirectiveBase._register_song` post-build step (every song
directive — ``.. song::`` / ``.. chord-line::`` / ``.. song-include::`` —
inherits it; there is **no** per-directive registration). It is read **only**
via :func:`iter_songs` during resolve. ``.. chord-progression::`` (CHUNK-4-4) is
not a song and never registers.

Data model (LOCKED)
-------------------
``env.song_data: dict[str, list[dict]]`` keyed by **docname** → per-song entries.
Each entry is **plain picklable data** snapshotted from ``node['song_meta']``
(already ``_``-key-free and post-``node_parsed``): ``{"id": <resolvable ids
anchor>, "docname": <docname>, "title":..., <promoted metadata>}``. There is no
lyric/token body and no live node reference, so entries pickle cleanly and merge
across parallel workers. ``(docname, id)`` is the cross-reference identity
(docutils ids are doc-local and can collide across docs); CHUNK-5-3 resolves
links via ``make_refnode(..., todocname=entry["docname"], targetid=entry["id"])``
— never by ``id`` alone.

Parallel-safety (re-justifies the CHUNK-0-1 ``parallel_*_safe = True`` flags)
-----------------------------------------------------------------------------
Every entry point lazy-inits the registry via the shared :func:`_ensure` helper,
so a doc with no songs never raises ``AttributeError``. Writes happen only during
read (into the per-worker ``env``, merged through the official ``env-merge-info``
hook); reads happen only during resolve (single process, after all workers are
merged). All stored values are picklable. This keeps both parallel flags ``True``.
"""

from __future__ import annotations

from typing import Iterable, List

#: The ``env`` attribute holding the set of query docnames (song-list/index).
#: Defined authoritatively in :mod:`doxtr_music.directives.song_list`; re-imported
#: here so the parallel-safe env handlers can merge/purge it. The import chain
#: ``registry -> song_list -> nodes`` is acyclic and Sphinx-free.
from doxtr_music.directives.song_list import QUERY_DOCS_ATTR

__all__ = [
    "register_song",
    "iter_songs",
    "purge_doc",
    "merge_info",
    "connect_env_handlers",
]


def _ensure(env) -> dict:
    """Return ``env.song_data``, lazy-initialising it to ``{}`` if absent.

    Called at every entry point (register / purge / merge / iter) so a build
    that never registered a song does not raise ``AttributeError``. Never
    mutates at import time.
    """
    data = getattr(env, "song_data", None)
    if data is None:
        data = {}
        env.song_data = data
    return data


def register_song(env, entry: dict) -> None:
    """Append a plain-data song ``entry`` to the registry.

    The docname is derived from ``entry["docname"]`` (single source of truth;
    there is no separate docname argument). Lazy-inits the registry. The entry
    must already be plain picklable data (no live node, no lyric/token body).
    """
    data = _ensure(env)
    docname = entry["docname"]
    data.setdefault(docname, []).append(entry)


def iter_songs(env) -> Iterable[dict]:
    """Yield every registered song entry, resolve-phase only.

    Entries are flattened across all docnames and returned **sorted by docname,
    then insertion order** so the sequence is deterministic even when parallel
    workers merge their registries out of order. MUST NOT be called during read
    (the main env has not merged worker registries yet → an incomplete view).
    """
    data = _ensure(env)
    ordered: List[dict] = []
    for docname in sorted(data):
        # Insertion order within a doc is preserved (list append order).
        ordered.extend(data[docname])
    return ordered


def purge_doc(app, env, docname) -> None:
    """``env-purge-doc`` handler — drop ``docname``'s entries on re-read.

    Canonical signature ``(app, env, docname)``. Removing entries before a doc
    is re-read prevents stale duplicates. Purging a song-less doc is a no-op
    (``pop(..., None)``), never a crash.

    Also drops ``docname`` from the ``doxtr_music_query_docs`` set (written by
    CHUNK-5-3's song-list/song-index read phase) so a doc that no longer
    contains a ``song-list``/``song-index`` does not leave a stale query-doc
    entry driving needless resolve-phase invalidation. Discarding an absent
    name is a no-op.
    """
    _ensure(env).pop(docname, None)

    query_docs = getattr(env, QUERY_DOCS_ATTR, None)
    if query_docs is not None:
        query_docs.discard(docname)


def merge_info(app, env, docnames, other) -> None:
    """``env-merge-info`` handler — merge a worker's registry into the main env.

    Canonical signature ``(app, env, docnames, other)``. Iterates the freshly
    read ``docnames`` and copies each doc's entries from the worker ``other``
    env into the main ``env``. Docname keying means there is no cross-doc
    collision, and copying (rather than extending) keeps a re-read idempotent.
    ``other`` is guarded so a worker that registered nothing is a no-op.
    """
    data = _ensure(env)
    other_data = getattr(other, "song_data", None) or {}
    for docname in docnames:
        entries = other_data.get(docname)
        if entries is not None:
            data[docname] = list(entries)

    # Merge the parallel worker's query-doc set (CHUNK-5-3). It is written into
    # the per-worker ``env`` during the read phase, so under ``-j`` the main env
    # never sees it unless folded in here. Plain set of ``str`` (picklable);
    # set-union keeps the merge idempotent across re-reads.
    other_query = getattr(other, QUERY_DOCS_ATTR, None)
    if other_query:
        main_query = getattr(env, QUERY_DOCS_ATTR, None)
        if main_query is None:
            main_query = set()
            setattr(env, QUERY_DOCS_ATTR, main_query)
        main_query.update(other_query)


def connect_env_handlers(app) -> None:
    """Wire the ``env-purge-doc`` + ``env-merge-info`` registry hooks.

    Called from :func:`doxtr_music.setup`. Keeps the registry parallel-safe:
    purge drops stale per-doc entries on re-read; merge folds each worker's
    registry into the main env after a parallel read.
    """
    app.connect("env-purge-doc", purge_doc)
    app.connect("env-merge-info", merge_info)
