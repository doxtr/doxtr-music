"""Unit tests for doxtr_music.registry (CHUNK-5-1) — no Sphinx build required.

Covers the locked contracts: single-writer/single-reader API, plain picklable
entries keyed by ``(docname, id)``, parallel-safe env hooks (``env-purge-doc`` +
``env-merge-info``) with their canonical signatures, deterministic ``iter_songs``
ordering under out-of-order merge, lazy-init at every entry point, and that a
post-``_node_parsed_hook`` metadata mutation is reflected in the snapshot.
"""

from __future__ import annotations

import pickle
from types import SimpleNamespace

import pytest

from doxtr_music import registry


def _env(docname="docA"):
    """A minimal env stand-in: only ``docname`` is read by the registry."""
    return SimpleNamespace(docname=docname)


# --- register_song / iter_songs --------------------------------------------

def test_register_and_iter_yields_all_entries_plain_dicts():
    env = _env()
    registry.register_song(env, {"id": "song-a", "docname": "docA", "title": "A"})
    registry.register_song(env, {"id": "song-b", "docname": "docA", "title": "B"})
    registry.register_song(env, {"id": "song-c", "docname": "docB", "title": "C"})

    songs = list(registry.iter_songs(env))

    assert len(songs) == 3
    assert all(isinstance(s, dict) for s in songs)
    # id + docname are the cross-reference identity on every entry.
    assert {(s["docname"], s["id"]) for s in songs} == {
        ("docA", "song-a"),
        ("docA", "song-b"),
        ("docB", "song-c"),
    }


def test_entries_are_picklable_round_trip():
    env = _env()
    registry.register_song(
        env,
        {
            "id": "song-a",
            "docname": "docA",
            "title": "Title",
            "artist": "Artist",
            "tags": ["rock", "live"],
            "year": 1971,
        },
    )
    entry = list(registry.iter_songs(env))[0]
    # No live node / no body: pickles cleanly (parallel-merge safety).
    assert pickle.loads(pickle.dumps(entry)) == entry


def test_iter_songs_deterministic_docname_then_insertion_order():
    env = _env()
    # Insert docB first, then docA, interleaved — output must be sorted by
    # docname then insertion order regardless of registration order.
    registry.register_song(env, {"id": "b1", "docname": "docB"})
    registry.register_song(env, {"id": "a1", "docname": "docA"})
    registry.register_song(env, {"id": "b2", "docname": "docB"})
    registry.register_song(env, {"id": "a2", "docname": "docA"})

    order = [s["id"] for s in registry.iter_songs(env)]
    assert order == ["a1", "a2", "b1", "b2"]


# --- env-purge-doc ----------------------------------------------------------

def test_purge_doc_drops_only_that_docs_entries():
    env = _env()
    registry.register_song(env, {"id": "a1", "docname": "docA"})
    registry.register_song(env, {"id": "b1", "docname": "docB"})

    registry.purge_doc(None, env, "docA")

    remaining = [s["id"] for s in registry.iter_songs(env)]
    assert remaining == ["b1"]


def test_purge_songless_doc_is_noop_not_error():
    env = _env()
    # No songs registered at all → lazy-init + pop(None) must not raise.
    registry.purge_doc(None, env, "never-seen")
    assert list(registry.iter_songs(env)) == []


# --- env-merge-info ---------------------------------------------------------

def test_merge_info_canonical_signature_and_union():
    main = _env()
    registry.register_song(main, {"id": "a1", "docname": "docA"})

    worker = SimpleNamespace(
        song_data={"docB": [{"id": "b1", "docname": "docB"}]}
    )
    # Canonical (app, env, docnames, other) signature.
    registry.merge_info(None, main, ["docB"], worker)

    ids = {s["id"] for s in registry.iter_songs(main)}
    assert ids == {"a1", "b1"}


def test_merge_info_out_of_order_docnames_still_sorted():
    main = _env()
    worker = SimpleNamespace(
        song_data={
            "docB": [{"id": "b1", "docname": "docB"}],
            "docA": [{"id": "a1", "docname": "docA"}],
        }
    )
    # Merge docB before docA (out of order) — iter_songs must still be sorted.
    registry.merge_info(None, main, ["docB", "docA"], worker)
    order = [s["id"] for s in registry.iter_songs(main)]
    assert order == ["a1", "b1"]


def test_merge_info_guards_worker_without_registry():
    main = _env()
    registry.register_song(main, {"id": "a1", "docname": "docA"})
    worker = SimpleNamespace()  # no song_data attr at all
    registry.merge_info(None, main, ["docA"], worker)
    # No crash; main untouched.
    assert [s["id"] for s in registry.iter_songs(main)] == ["a1"]


def test_parallel_total_equals_serial_total():
    # Two workers each read one doc; merged main == sum of both.
    w1 = SimpleNamespace(song_data={"docA": [{"id": "a1", "docname": "docA"}]})
    w2 = SimpleNamespace(song_data={"docB": [{"id": "b1", "docname": "docB"}]})
    main = _env()
    registry.merge_info(None, main, ["docA"], w1)
    registry.merge_info(None, main, ["docB"], w2)
    assert len(list(registry.iter_songs(main))) == 2


# --- query-doc set: parallel merge + purge (CHUNK-5-3 incremental) ----------

def test_merge_info_folds_worker_query_docs_set():
    """A query doc recorded in a parallel worker survives the merge.

    ``env.doxtr_music_query_docs`` is written into the per-worker env during the
    read phase; without merging it in ``env-merge-info`` the main env would
    never see it under ``-j``, silently defeating the resolve-phase
    invalidation signature.
    """
    from doxtr_music.registry import QUERY_DOCS_ATTR

    main = _env()
    worker = SimpleNamespace(
        song_data={},
        doxtr_music_query_docs={"queries"},
    )
    registry.merge_info(None, main, ["queries"], worker)
    assert getattr(main, QUERY_DOCS_ATTR) == {"queries"}


def test_merge_info_query_docs_set_union_across_workers():
    from doxtr_music.registry import QUERY_DOCS_ATTR

    main = _env()
    w1 = SimpleNamespace(song_data={}, doxtr_music_query_docs={"docA"})
    w2 = SimpleNamespace(song_data={}, doxtr_music_query_docs={"docB"})
    registry.merge_info(None, main, ["docA"], w1)
    registry.merge_info(None, main, ["docB"], w2)
    assert getattr(main, QUERY_DOCS_ATTR) == {"docA", "docB"}


def test_merge_info_no_query_docs_attr_when_worker_has_none():
    from doxtr_music.registry import QUERY_DOCS_ATTR

    main = _env()
    worker = SimpleNamespace(song_data={"docA": [{"id": "a1", "docname": "docA"}]})
    registry.merge_info(None, main, ["docA"], worker)
    # Worker had no query docs → main env is not given a spurious set.
    assert getattr(main, QUERY_DOCS_ATTR, None) is None


def test_purge_doc_drops_stale_query_doc_entry():
    """Re-reading a doc that no longer has a song-list purges its query entry.

    Without purging, a doc whose last ``song-list``/``song-index`` was removed
    would keep a stale ``doxtr_music_query_docs`` entry and keep driving
    resolve-phase invalidation forever.
    """
    from doxtr_music.registry import QUERY_DOCS_ATTR

    env = _env()
    setattr(env, QUERY_DOCS_ATTR, {"docA", "docB"})
    registry.purge_doc(None, env, "docA")
    assert getattr(env, QUERY_DOCS_ATTR) == {"docB"}


def test_purge_doc_query_docs_absent_is_noop():
    env = _env()  # no query-docs set at all
    registry.purge_doc(None, env, "docA")  # must not raise
    from doxtr_music.registry import QUERY_DOCS_ATTR
    assert getattr(env, QUERY_DOCS_ATTR, None) is None


def test_query_docs_set_is_picklable():
    # The query-doc set is plain ``str`` data → survives -j pickling.
    import pickle as _pickle

    from doxtr_music.registry import QUERY_DOCS_ATTR

    env = _env()
    setattr(env, QUERY_DOCS_ATTR, {"docA", "docB"})
    restored = _pickle.loads(_pickle.dumps(getattr(env, QUERY_DOCS_ATTR)))
    assert restored == {"docA", "docB"}


# --- lazy-init at every entry point -----------------------------------------

def test_lazy_init_no_attribute_error_on_fresh_env():
    # A fresh env has no song_data attr; every entry point must lazy-init it.
    assert list(registry.iter_songs(_env())) == []
    registry.purge_doc(None, _env(), "docA")  # no raise
    registry.merge_info(None, _env(), [], SimpleNamespace())  # no raise


def test_no_import_time_env_mutation():
    env = _env()
    assert not hasattr(env, "song_data")  # untouched until an entry point runs
    registry.register_song(env, {"id": "a", "docname": "docA"})
    assert hasattr(env, "song_data")


# --- post-node_parsed-hook snapshot (via SongDirectiveBase._register_song) ---

def test_register_song_snapshots_after_node_parsed_hook():
    """A stub node_parsed hook that mutates song_meta is reflected in the snapshot.

    Exercises the reserved-slot ordering: _register_song reads node['song_meta']
    which _node_parsed_hook may have mutated first.
    """
    from docutils import nodes as du

    from doxtr_music.directives._base import SongDirectiveBase

    # Build a real SongNode-like element carrying song_meta + an id.
    node = du.Element()
    node["ids"] = ["song-x"]
    node["song_meta"] = {"title": "Original", "_internal": "drop-me"}

    env = _env("docZ")

    class _Stub(SongDirectiveBase):
        pass

    inst = _Stub.__new__(_Stub)
    # Wire the minimal state chain _register_song reads.
    inst.state = SimpleNamespace(
        document=SimpleNamespace(settings=SimpleNamespace(env=env))
    )

    # Simulate the node_parsed hook mutating metadata before registration.
    node["song_meta"]["title"] = "Mutated By Hook"

    inst._register_song(node)

    songs = list(registry.iter_songs(env))
    assert len(songs) == 1
    entry = songs[0]
    assert entry["title"] == "Mutated By Hook"  # post-hook value captured
    assert entry["id"] == "song-x"              # resolvable anchor, not title_id
    assert entry["docname"] == "docZ"
    assert "_internal" not in entry            # _-keys defensively excluded


def test_register_song_without_env_is_silent_noop():
    from doxtr_music.directives._base import SongDirectiveBase
    from docutils import nodes as du

    node = du.Element()
    node["ids"] = ["song-x"]
    node["song_meta"] = {"title": "T"}

    class _Stub(SongDirectiveBase):
        pass

    inst = _Stub.__new__(_Stub)
    # No state/env at all → best-effort no-op (must not raise).
    inst.state = SimpleNamespace(
        document=SimpleNamespace(settings=SimpleNamespace(env=None))
    )
    assert inst._register_song(node) is None


def test_register_song_id_overrides_meta_key_collision():
    """A song_meta 'id'/'docname' must not shadow the authoritative anchor."""
    from doxtr_music.directives._base import SongDirectiveBase
    from docutils import nodes as du

    node = du.Element()
    node["ids"] = ["real-anchor"]
    node["song_meta"] = {"title": "T", "id": "bogus", "docname": "bogus-doc"}

    env = _env("realdoc")

    class _Stub(SongDirectiveBase):
        pass

    inst = _Stub.__new__(_Stub)
    inst.state = SimpleNamespace(
        document=SimpleNamespace(settings=SimpleNamespace(env=env))
    )
    inst._register_song(node)

    entry = list(registry.iter_songs(env))[0]
    assert entry["id"] == "real-anchor"
    assert entry["docname"] == "realdoc"
