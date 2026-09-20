"""Unit tests for doxtr_music.hooks (CHUNK-5-4) — no Sphinx build required.

Covers the LOCKED contracts:

* dotted-string + callable resolution for each hook; bad path -> warn + no hook;
* ``chord_preprocess`` chains as the FIRST pipeline step (before transpose/roman),
  rebuilding frozen tokens via ``dataclasses.replace``; exception -> keep original;
* ``node_parsed`` fires in the reserved slot; a ``song_meta`` mutation is reflected;
  a non-picklable mutation -> warn AND revert to the pre-hook snapshot;
* ``html_visit`` is invoked additively; exception -> skip; the pipeline never crashes;
* ``register_*`` helpers (parity); late registration warns + is ignored;
  config-value hook runs before registered hooks (documented order);
* ``_resolved`` attrs hold only picklable values (string/None), and directly
  provided callables live in the module registry (parallel-safety under -j);
* no ``eval`` anywhere (dotted-string resolution is importlib).
"""

from __future__ import annotations

import pickle
from types import SimpleNamespace

import pytest

from doxtr_music import hooks
from doxtr_music.directives._base import SongDirectiveBase
from doxtr_music.parsers.chordpro import parse_chordpro
from doxtr_music.tokens import ChordToken


# ---------------------------------------------------------------------------
# Module-level hook functions referenced by DOTTED-STRING tests.
# (Resolved via "tests.test_hooks.<name>" — importlib, never eval.)
# ---------------------------------------------------------------------------

def _dotted_chord_hook(chord, song_meta):
    return chord + "7"


def _dotted_node_hook(node):
    node["song_meta"]["_hooked"] = True


NOT_CALLABLE = 42  # a module attribute that is not callable (bad-target test)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_hook_registry():
    """Isolate the module-global hook registry between tests."""
    hooks.reset_hook_registry()
    yield
    hooks.reset_hook_registry()


def _config(**attrs):
    """A minimal config stand-in exposing the hook config + ``_resolved`` attrs."""
    base = {
        "doxtr_music_chord_preprocess_resolved": None,
        "doxtr_music_node_parsed_resolved": None,
        "doxtr_music_html_visit_resolved": None,
        "doxtr_music_chord_preprocess": None,
        "doxtr_music_node_parsed": None,
        "doxtr_music_html_visit": None,
        "doxtr_music_chord_system": "english",
    }
    base.update(attrs)
    return SimpleNamespace(**base)


class _BareDirective(SongDirectiveBase):
    """A SongDirectiveBase usable without a full Sphinx directive init."""

    parser_fn = staticmethod(parse_chordpro)


def _directive(config):
    """Build a pipeline-capable directive whose ``_config()`` returns ``config``."""
    d = object.__new__(_BareDirective)
    d._config = lambda: config  # type: ignore[method-assign]
    return d


# ===========================================================================
# resolve_hook_value — dotted string / callable / bad target
# ===========================================================================

def test_resolve_none_returns_none():
    assert hooks.resolve_hook_value(None, "doxtr_music_html_visit") is None


def test_resolve_direct_callable_returned_as_is():
    fn = lambda *a: None  # noqa: E731
    assert hooks.resolve_hook_value(fn, "doxtr_music_html_visit") is fn


def test_resolve_dotted_string_imports_callable():
    resolved = hooks.resolve_hook_value(
        "tests.test_hooks._dotted_chord_hook", "doxtr_music_chord_preprocess"
    )
    assert callable(resolved)
    assert resolved.__name__ == "_dotted_chord_hook"
    assert resolved("C", {}) == "C7"


def test_resolve_bad_dotted_path_warns_and_returns_none(caplog):
    with caplog.at_level("WARNING"):
        resolved = hooks.resolve_hook_value(
            "tests.test_hooks.does_not_exist", "doxtr_music_chord_preprocess"
        )
    assert resolved is None
    assert any("could not be imported" in r.message for r in caplog.records)


def test_resolve_non_dotted_string_warns(caplog):
    with caplog.at_level("WARNING"):
        resolved = hooks.resolve_hook_value("nodot", "doxtr_music_node_parsed")
    assert resolved is None
    assert any("dotted" in r.message for r in caplog.records)


def test_resolve_dotted_to_non_callable_warns(caplog):
    with caplog.at_level("WARNING"):
        resolved = hooks.resolve_hook_value(
            "tests.test_hooks.NOT_CALLABLE", "doxtr_music_html_visit"
        )
    assert resolved is None
    assert any("non-callable" in r.message for r in caplog.records)


def test_resolve_wrong_type_warns(caplog):
    with caplog.at_level("WARNING"):
        resolved = hooks.resolve_hook_value(123, "doxtr_music_html_visit")
    assert resolved is None
    assert any("dotted import string or a callable" in r.message for r in caplog.records)


# ===========================================================================
# on_config_inited_hooks — _resolved attrs picklable + callable in registry
# ===========================================================================

def test_config_inited_dotted_string_stored_as_string():
    config = _config(
        doxtr_music_chord_preprocess="tests.test_hooks._dotted_chord_hook"
    )
    hooks.on_config_inited_hooks(None, config)
    # The RESOLVED attr holds the STRING (picklable), not the callable.
    assert config.doxtr_music_chord_preprocess_resolved == (
        "tests.test_hooks._dotted_chord_hook"
    )
    # Config stays picklable under -j.
    pickle.dumps(config.doxtr_music_chord_preprocess_resolved)


def test_config_inited_bad_dotted_string_resolved_none(caplog):
    config = _config(doxtr_music_node_parsed="tests.test_hooks.missing")
    with caplog.at_level("WARNING"):
        hooks.on_config_inited_hooks(None, config)
    assert config.doxtr_music_node_parsed_resolved is None


def test_config_inited_direct_callable_lives_in_registry_not_config():
    fn = lambda chord, meta: chord  # noqa: E731 - an unpicklable lambda
    config = _config(doxtr_music_chord_preprocess=fn)
    hooks.on_config_inited_hooks(None, config)
    # The RESOLVED attr is None (callable NOT on the pickled config).
    assert config.doxtr_music_chord_preprocess_resolved is None
    # The callable lives in the module registry so workers inherit it.
    assert fn in hooks._chord_preprocess_hooks
    # And the config remains picklable (no callable stored on it).
    pickle.dumps(config.doxtr_music_chord_preprocess_resolved)


# ===========================================================================
# Multi-build in a shared process: reopen registration + no accumulation
# (reviewer SHOULD-FIX — extensibility)
# ===========================================================================

def test_config_inited_reopens_registration_after_prior_build_closed():
    """A second build re-opens the pre-spawn registration window.

    ``on_builder_inited_hooks`` closes registration for a build. In a shared
    process (e.g. a test session or an app rebuilt twice) the next build's
    ``config-inited`` must reopen it, or no hook could ever be registered again.
    """
    hooks.on_builder_inited_hooks(None)  # build #1 closes registration
    assert hooks._registration_closed is True

    hooks.on_config_inited_hooks(None, _config())  # build #2 config-inited
    assert hooks._registration_closed is False

    # Registration works again on the second build.
    fn = lambda n, t: None  # noqa: E731
    hooks.register_html_visit(fn)
    assert fn in hooks._html_visit_hooks


def test_config_inited_does_not_accumulate_direct_callables_across_builds():
    """A directly-provided config callable is not duplicated across builds.

    Re-running ``config-inited`` (a second build in the same process) must not
    re-append the same config callable, or the store would grow every build and
    the hook would run N times.
    """
    fn = lambda chord, meta: chord + "!"  # noqa: E731
    config = _config(doxtr_music_chord_preprocess=fn)

    hooks.on_config_inited_hooks(None, config)
    count_after_first = len(hooks._chord_preprocess_hooks)

    # Simulate a second build cycle in the same process. The raw config value
    # was nulled by the first cycle (parallel-safety), so restore it as Sphinx
    # would from the user's conf.py on a fresh Config load.
    config.doxtr_music_chord_preprocess = fn
    hooks.on_config_inited_hooks(None, config)
    count_after_second = len(hooks._chord_preprocess_hooks)

    assert count_after_first == 1
    assert count_after_second == 1  # no accumulation
    assert hooks._chord_preprocess_hooks.count(fn) == 1


def test_config_inited_preserves_registered_hooks_when_clearing_config_callables():
    """Clearing config callables at config-inited must not drop register_* hooks."""
    registered = lambda c, m: c  # noqa: E731
    hooks.register_chord_preprocess(registered)  # untagged, must survive

    fn = lambda c, m: c  # noqa: E731 - a config callable
    config = _config(doxtr_music_chord_preprocess=fn)
    hooks.on_config_inited_hooks(None, config)

    assert registered in hooks._chord_preprocess_hooks
    assert fn in hooks._chord_preprocess_hooks

    # A second config-inited clears the config callable but keeps the registered one.
    config.doxtr_music_chord_preprocess = None
    hooks.on_config_inited_hooks(None, config)
    assert registered in hooks._chord_preprocess_hooks
    assert fn not in hooks._chord_preprocess_hooks


# ===========================================================================
# register_* API + late-registration guard + run order
# ===========================================================================

def test_register_appends_and_runs():
    calls = []
    hooks.register_chord_preprocess(lambda c, m: calls.append(c) or c)
    hooks.run_chord_preprocess("C", {}, _config())
    assert calls == ["C"]


def test_register_non_callable_warns_and_ignored(caplog):
    with caplog.at_level("WARNING"):
        hooks.register_node_parsed(42)
    assert hooks._node_parsed_hooks == []
    assert any("not callable" in r.message for r in caplog.records)


def test_late_registration_after_builder_inited_warns_and_ignored(caplog):
    hooks.on_builder_inited_hooks(None)  # closes registration
    with caplog.at_level("WARNING"):
        hooks.register_html_visit(lambda n, t: None)
    assert hooks._html_visit_hooks == []
    assert any("after builder-inited" in r.message for r in caplog.records)


def test_run_order_config_value_first_then_registered():
    """The config-value hook runs before register_* hooks (LOCKED order)."""
    order = []

    def registered(chord, meta):
        order.append("registered")
        return chord

    def config_hook(chord, meta):
        order.append("config")
        return chord

    config = _config(doxtr_music_chord_preprocess=config_hook)
    hooks.on_config_inited_hooks(None, config)  # config callable -> front of store
    hooks.register_chord_preprocess(registered)  # appended after
    hooks.run_chord_preprocess("C", {}, config)
    assert order == ["config", "registered"]


# ===========================================================================
# chord_preprocess chaining + exception handling
# ===========================================================================

def test_chord_preprocess_chains_outputs():
    hooks.register_chord_preprocess(lambda c, m: c + "7")
    hooks.register_chord_preprocess(lambda c, m: c + "sus4")
    assert hooks.run_chord_preprocess("C", {}, _config()) == "C7sus4"


def test_chord_preprocess_exception_keeps_prior_value(caplog):
    def boom(chord, meta):
        raise ValueError("nope")

    hooks.register_chord_preprocess(boom)
    hooks.register_chord_preprocess(lambda c, m: c + "m")
    with caplog.at_level("WARNING"):
        result = hooks.run_chord_preprocess("C", {}, _config())
    # First hook raised (kept "C"); second appended "m".
    assert result == "Cm"
    assert any("chord_preprocess hook" in r.message for r in caplog.records)


def test_chord_preprocess_none_return_keeps_prior():
    hooks.register_chord_preprocess(lambda c, m: None)
    assert hooks.run_chord_preprocess("Am", {}, _config()) == "Am"


# ===========================================================================
# chord_preprocess integrated into the _post_parse_transform pipeline (FIRST)
# ===========================================================================

def test_chord_preprocess_is_first_pipeline_step_frozen_replace():
    """chord_preprocess rebuilds frozen tokens and runs before transpose/roman."""
    hooks.register_chord_preprocess(lambda c, m: "G" if c == "C" else c)
    config = _config()
    d = _directive(config)

    tokens, song_meta = parse_chordpro("[C]Hello [Am]world")
    options = {}
    out = d._post_parse_transform(tokens, song_meta, options)

    chords = [t.text for t in out if isinstance(t, ChordToken)]
    assert chords == ["G", "Am"]  # C -> G by the preprocess hook
    # Frozen tokens are replaced, not mutated: originals unchanged.
    orig = [t.text for t in tokens if isinstance(t, ChordToken)]
    assert orig == ["C", "Am"]


def test_chord_preprocess_feeds_transpose():
    """A preprocessed chord flows into transpose (proves ordering)."""
    # Preprocess turns C into D; then transpose +2 turns D into E.
    hooks.register_chord_preprocess(lambda c, m: "D" if c == "C" else c)
    config = _config()
    d = _directive(config)
    tokens, song_meta = parse_chordpro("[C]Hi")
    options = {"transpose": 2}
    out = d._post_parse_transform(tokens, song_meta, options)
    chord = next(t for t in out if isinstance(t, ChordToken))
    # transpose annotates ``transposed`` on the (preprocessed) D -> E.
    ann = dict(chord.annotations)
    assert ann.get("transposed") == "E"


def test_chord_preprocess_identity_when_no_hook():
    d = _directive(_config())
    tokens, song_meta = parse_chordpro("[C]Hi")
    out = d._transform_chord_preprocess(tokens, song_meta, {})
    assert out is tokens  # identity fast-path (no new list)


# ===========================================================================
# node_parsed — reserved slot, mutation reflected, non-picklable revert
# ===========================================================================

class _FakeSongNode(dict):
    """A dict-like stand-in for SongNode carrying a ``song_meta`` attr."""


def _song_node(meta=None):
    node = _FakeSongNode()
    node["ids"] = ["song-1"]
    node["song_meta"] = dict(meta or {})
    return node


def test_node_parsed_fires_and_mutation_reflected():
    hooks.register_node_parsed(lambda n: n["song_meta"].update({"artist": "X"}))
    d = _directive(_config())
    node = _song_node({"title": "T"})
    d._node_parsed_hook(node)
    assert node["song_meta"]["artist"] == "X"


def test_node_parsed_no_hook_is_noop():
    d = _directive(_config())
    node = _song_node({"title": "T"})
    result = d._node_parsed_hook(node)
    assert result is node
    assert node["song_meta"] == {"title": "T"}


def test_node_parsed_exception_warns_and_continues(caplog):
    def boom(node):
        raise RuntimeError("bad hook")

    hooks.register_node_parsed(boom)
    hooks.register_node_parsed(lambda n: n["song_meta"].update({"ok": True}))
    d = _directive(_config())
    node = _song_node({"title": "T"})
    with caplog.at_level("WARNING"):
        d._node_parsed_hook(node)
    # First hook raised; second still ran.
    assert node["song_meta"]["ok"] is True
    assert any("node_parsed hook" in r.message for r in caplog.records)


def test_node_parsed_non_picklable_reverts_to_snapshot(caplog):
    """A hook making song_meta non-picklable -> warn AND revert (LOCKED)."""
    unpicklable = lambda: None  # noqa: E731 - a local lambda is unpicklable

    def bad(node):
        node["song_meta"]["fn"] = unpicklable

    hooks.register_node_parsed(bad)
    d = _directive(_config())
    node = _song_node({"title": "T"})
    with caplog.at_level("WARNING"):
        d._node_parsed_hook(node)
    # Reverted to the pre-hook snapshot: no non-picklable value survives.
    assert "fn" not in node["song_meta"]
    assert node["song_meta"] == {"title": "T"}
    pickle.dumps(node["song_meta"])  # now picklable
    assert any("non-picklable" in r.message for r in caplog.records)


def test_node_parsed_dotted_string_hook_runs():
    config = _config(doxtr_music_node_parsed="tests.test_hooks._dotted_node_hook")
    hooks.on_config_inited_hooks(None, config)
    d = _directive(config)
    node = _song_node({"title": "T"})
    d._node_parsed_hook(node)
    assert node["song_meta"]["_hooked"] is True


# ===========================================================================
# html_visit — additive, exception-safe, run order
# ===========================================================================

class _FakeTranslator:
    def __init__(self, config):
        self.body = []
        self.config = config


def test_html_visit_additive_and_order():
    order = []

    def h1(node, tr):
        order.append("a")
        tr.body.append("<a>")

    def h2(node, tr):
        order.append("b")
        tr.body.append("<b>")

    config = _config(doxtr_music_html_visit=h1)
    hooks.on_config_inited_hooks(None, config)  # config callable leads
    hooks.register_html_visit(h2)
    tr = _FakeTranslator(config)
    hooks.run_html_visit(object(), tr, config)
    assert order == ["a", "b"]
    assert tr.body == ["<a>", "<b>"]


def test_html_visit_exception_skips(caplog):
    def boom(node, tr):
        raise ValueError("x")

    hooks.register_html_visit(boom)
    hooks.register_html_visit(lambda n, t: t.body.append("<ok>"))
    tr = _FakeTranslator(_config())
    with caplog.at_level("WARNING"):
        hooks.run_html_visit(object(), tr, _config())
    assert tr.body == ["<ok>"]
    assert any("html_visit hook" in r.message for r in caplog.records)


def test_html_visit_no_hook_no_output():
    tr = _FakeTranslator(_config())
    hooks.run_html_visit(object(), tr, _config())
    assert tr.body == []


# ===========================================================================
# Parallel-safety: no callable is stored on the pickled config
# ===========================================================================

def test_parallel_safety_config_stays_picklable_with_all_hook_kinds():
    fn = lambda *a: None  # noqa: E731 - unpicklable direct callable
    config = _config(
        doxtr_music_chord_preprocess="tests.test_hooks._dotted_chord_hook",
        doxtr_music_node_parsed=fn,
        doxtr_music_html_visit=None,
    )
    hooks.on_config_inited_hooks(None, config)
    # Only strings / None land on the _resolved attrs -> picklable.
    for name in (
        "doxtr_music_chord_preprocess_resolved",
        "doxtr_music_node_parsed_resolved",
        "doxtr_music_html_visit_resolved",
    ):
        pickle.dumps(getattr(config, name))
    # The direct callable is in the registry (workers inherit it), NOT on config.
    assert fn in hooks._node_parsed_hooks
