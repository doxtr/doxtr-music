"""Plugin hooks for doxtr-music (CHUNK-5-4).

Three extensibility hooks let advanced users modify music data during the
build without forking the extension:

``chord_preprocess(chord: str, song_meta: dict) -> str``
    Transform a chord string *before* engine processing (transpose/roman). It
    fills the first step of the :class:`~doxtr_music.directives._base.SongDirectiveBase`
    ``_post_parse_transform`` ordered pipeline
    (``chord_preprocess -> transpose -> roman``), rebuilding each frozen
    ``ChordToken`` via :func:`dataclasses.replace`. Multiple hooks **chain**
    (each receives the prior hook's output string).

``node_parsed(song: SongNode) -> None``
    Mutate the parsed AST before render. Fills the reserved
    ``_node_parsed_hook`` slot, running after id assignment and before the
    registry snapshot so a ``song_meta`` mutation is reflected in both the
    rendered song and ``env.song_data``. Compose additively.

``html_visit(node, translator) -> None``
    Inject custom HTML during translation (may append to ``translator.body``).
    HTML-only; invoked inside a copy-neutral wrapper so it cannot pollute the
    lyric stream (COPY_SAFE_ORDER_HTML). Compose additively.

Resolution model (LOCKED)
-------------------------

Each ``doxtr_music_*`` hook config value is resolved once at ``config-inited``
(a *separate* handler at the default ~500 priority, alongside — not folded into
— CHUNK-0-3's validation-only one):

* a **dotted string** (``"mypkg.mymod.myfn"``) is imported + resolved to a
  callable with :mod:`importlib` (never ``eval`` — invariant 5), and the
  *string* is stored on the ``_resolved``-suffixed config attr so it survives
  pickling under ``-j`` and is re-resolved per worker;
* a **callable** provided directly (may be a lambda/closure → unpicklable) is
  NOT stored on the pickled config; it lives in the module registry, populated
  during ``setup``/import/``config-inited`` *before* parallel workers spawn, so
  every worker inherits it;
* ``None`` → no config-value hook.

A bad path / non-callable → a Sphinx **warning** and no hook (never a crash).

Parallel-safety (LOCKED)
------------------------

Because directly-provided callables live in the setup-populated module registry
(not the pickled config) and dotted strings are stored as strings + re-resolved
per worker, the pickled ``config`` stays picklable and
``parallel_read_safe``/``parallel_write_safe`` stay ``True``. User hooks should
be pure / thread-safe under ``-j`` (documented author responsibility).

Run order (LOCKED)
------------------

For every hook the **config-value hook runs first**, then the ``register_*``
hooks in registration order. ``chord_preprocess`` **chains** (each hook receives
the prior hook's output); ``node_parsed`` / ``html_visit`` compose additively.
"""

from __future__ import annotations

import importlib
from typing import Callable, List, Optional

from sphinx.util import logging

logger = logging.getLogger(__name__)

__all__ = [
    "HOOK_INIT_PRIORITY",
    "register_chord_preprocess",
    "register_node_parsed",
    "register_html_visit",
    "on_config_inited_hooks",
    "on_builder_inited_hooks",
    "resolve_hook_value",
    "run_chord_preprocess",
    "run_node_parsed",
    "run_html_visit",
    "reset_hook_registry",
]

#: ``config-inited`` priority for hook resolution. The default ~500, matching
#: CHUNK-0-3's validation-only handler (LOCKED: a *separate* handler, not folded
#: into 0-3's). Runs before builder-inited (when workers spawn).
HOOK_INIT_PRIORITY = 500

# --- Module registry (populated before workers spawn) -----------------------
# Directly-provided callables (lambdas/closures, unpicklable) live here — NOT on
# the pickled config — so the config stays picklable and every parallel worker
# inherits these via the imported module. Config-value hooks are re-resolved
# per worker from the stored dotted string on the ``_resolved`` attr.
_chord_preprocess_hooks: List[Callable] = []
_node_parsed_hooks: List[Callable] = []
_html_visit_hooks: List[Callable] = []

#: Flipped ``True`` on ``builder-inited`` (workers spawn shortly after). Late
#: ``register_*`` calls after this point warn + are ignored — the pre-spawn
#: population window is the parallel-safety mechanism.
_registration_closed = False

#: Resolved-config-attr suffix (CHUNK-0-3 convention; excluded from the typo
#: guard). Each hook's resolved dotted-string value is stored on
#: ``<config-name>_resolved``.
_RESOLVED_SUFFIX = "_resolved"


def reset_hook_registry() -> None:
    """Clear the module registries + reopen registration (test-only helper).

    Production code never calls this; unit tests use it to isolate hook state
    between cases (the registries are module-global by design).
    """
    global _registration_closed
    _chord_preprocess_hooks.clear()
    _node_parsed_hooks.clear()
    _html_visit_hooks.clear()
    _registration_closed = False


# --- register_* API (parity with core register_* helpers) -------------------
def _register(store: List[Callable], fn: Callable, name: str) -> None:
    """Validate + append ``fn`` to ``store``; warn (not raise) on misuse.

    Parity with ``doxtr_pdf_theme_core.register_preamble_hook`` /
    ``register_ast_processor`` (validate-callable + append). Diverges only in
    the failure mode: this extension **warns and ignores** (never raises) so a
    misconfigured hook never breaks a build. Late registration (after
    ``builder-inited``) also warns + is ignored — that window is the
    parallel-safety guarantee (workers spawn after builder-inited).
    """
    if _registration_closed:
        logger.warning(
            "[doxtr-music] %s called after builder-inited; ignoring. "
            "Register hooks during setup()/config-inited (before parallel "
            "workers spawn).",
            name,
        )
        return
    if not callable(fn):
        logger.warning(
            "[doxtr-music] %s: argument is not callable (%r); ignoring.",
            name,
            type(fn).__name__,
        )
        return
    store.append(fn)


def register_chord_preprocess(fn: Callable) -> None:
    """Register a ``chord_preprocess(chord, song_meta) -> str`` hook.

    Appends to the module registry (populated before workers spawn). Runs after
    the config-value hook, in registration order, chaining each hook's output.
    Late registration (after ``builder-inited``) warns + is ignored.
    """
    _register(_chord_preprocess_hooks, fn, "register_chord_preprocess")


def register_node_parsed(fn: Callable) -> None:
    """Register a ``node_parsed(song) -> None`` hook (additive composition)."""
    _register(_node_parsed_hooks, fn, "register_node_parsed")


def register_html_visit(fn: Callable) -> None:
    """Register an ``html_visit(node, translator) -> None`` hook (additive)."""
    _register(_html_visit_hooks, fn, "register_html_visit")


# --- Config-value resolution -------------------------------------------------
def resolve_hook_value(value, name: str) -> Optional[Callable]:
    """Resolve a config hook ``value`` to a callable, or ``None``.

    ``value`` is a dotted import string, a callable, or ``None``. A dotted
    string is imported via :mod:`importlib` (NOT ``eval`` — invariant 5); a
    callable is returned as-is; ``None`` yields ``None``. A bad path /
    non-callable target → a Sphinx warning + ``None`` (never raises).
    """
    if value is None:
        return None
    if callable(value):
        return value
    if isinstance(value, str):
        return _import_dotted(value, name)
    logger.warning(
        "[doxtr-music] %s must be a dotted import string or a callable; "
        "got %r. Ignoring.",
        name,
        type(value).__name__,
    )
    return None


def _import_dotted(path: str, name: str) -> Optional[Callable]:
    """Import ``path`` (``"pkg.mod.attr"``) to a callable; warn + ``None`` on error."""
    dotted = path.strip()
    if "." not in dotted:
        logger.warning(
            "[doxtr-music] %s=%r is not a dotted 'module.attr' path; ignoring.",
            name,
            path,
        )
        return None
    module_path, _, attr = dotted.rpartition(".")
    try:
        module = importlib.import_module(module_path)
        target = getattr(module, attr)
    except (ImportError, AttributeError) as exc:
        logger.warning(
            "[doxtr-music] %s=%r could not be imported (%s); ignoring.",
            name,
            path,
            exc,
        )
        return None
    if not callable(target):
        logger.warning(
            "[doxtr-music] %s=%r resolved to a non-callable (%s); ignoring.",
            name,
            path,
            type(target).__name__,
        )
        return None
    return target


# --- config-inited / builder-inited handlers --------------------------------
def on_config_inited_hooks(app, config) -> None:
    """Resolve the three hook config values once at ``config-inited`` (~500).

    Reopens registration for this app (a fresh build re-opens the pre-spawn
    registration window even in a shared process where a prior build closed it
    on ``builder-inited``) and clears any config-sourced callables from a prior
    build before re-resolving, so directly-provided config callables do not
    accumulate duplicates across consecutive builds in the same process.

    Each value is validated (a bad path/non-callable → warn + no hook) and the
    ORIGINAL config value is normalised on the ``_resolved`` attr so it survives
    pickling under ``-j`` and is re-resolvable per worker:

    * a dotted string is validated now and the *string* is stored on the
      ``_resolved`` attr (re-resolved lazily at invocation, per worker);
    * a directly-provided callable is validated now and stored on the
      ``_resolved`` attr as-is *only when picklable is not required* — but to
      guarantee a picklable config under ``-j`` the callable is instead kept in
      the module registry via :func:`register_*`, and the ``_resolved`` attr is
      set to ``None`` (the registry already holds it).

    This keeps the pickled config picklable (only strings/``None`` on the
    ``_resolved`` attrs) while still honouring a directly-provided callable.
    """
    global _registration_closed
    # Per-app: reopen the registration window (a prior build in the same
    # process may have closed it on ``builder-inited``).
    _registration_closed = False
    # Drop config-sourced callables from a prior build so they do not
    # accumulate; registered (``register_*``) hooks are untagged and kept.
    _clear_config_callables()
    _resolve_one(
        config,
        "doxtr_music_chord_preprocess",
        register_chord_preprocess,
    )
    _resolve_one(
        config,
        "doxtr_music_node_parsed",
        register_node_parsed,
    )
    _resolve_one(
        config,
        "doxtr_music_html_visit",
        register_html_visit,
    )


def _resolve_one(config, name: str, register_fn: Callable) -> None:
    """Resolve one hook config value; set its ``_resolved`` attr picklable-safely.

    * dotted string → validate; store the *string* on ``<name>_resolved`` (a
      picklable value, re-resolved per worker at invocation time).
    * callable → validate; move it into the module registry (so the pickled
      config carries no callable), null the raw config value, and set
      ``<name>_resolved`` to ``None``.
    * ``None`` / invalid → ``<name>_resolved`` is ``None``.

    The config value is READ once here; the config-value hook always runs
    *before* any ``register_*`` hooks at invocation, so ordering is preserved
    even though a direct callable is physically stored in the registry (it is
    prepended-conceptually via the invocation order, see ``_iter_*``).
    """
    resolved_attr = name + _RESOLVED_SUFFIX
    value = getattr(config, name, None)
    if value is None:
        setattr(config, resolved_attr, None)
        return
    if isinstance(value, str):
        # Validate now (warn early), but store the *string* for per-worker
        # re-resolution — strings pickle cleanly.
        resolved = resolve_hook_value(value, name)
        setattr(config, resolved_attr, value if resolved is not None else None)
        return
    if callable(value):
        # Move a directly-provided callable into the module registry so the
        # pickled config holds no callable. It is registered as the *config
        # value* conceptually — invocation runs config-value hook first, which
        # for a direct callable means it must lead the registry ordering, so we
        # insert it at the front of the store.
        _prepend_config_callable(name, value)
        setattr(config, resolved_attr, None)
        # Null the RAW config value too: a callable left on the registered
        # config attr trips Sphinx's own config-cache pickling under ``-j``
        # (a benign warning, but avoidable). The hook now lives in the module
        # registry, so the raw value is no longer needed.
        try:
            setattr(config, name, None)
        except Exception:  # pragma: no cover - config attr always assignable
            pass
        return
    # Non-string, non-callable, non-None → warn via resolve_hook_value.
    resolve_hook_value(value, name)
    setattr(config, resolved_attr, None)


def _clear_config_callables() -> None:
    """Remove config-sourced callables (tagged ``_dm_config_hook``) from stores.

    Called at the start of every ``config-inited`` so a directly-provided config
    callable resolved on a prior build does not accumulate a duplicate on the
    next build in a shared process. Registered (``register_*``) hooks are
    untagged and preserved.
    """
    for store in (
        _chord_preprocess_hooks,
        _node_parsed_hooks,
        _html_visit_hooks,
    ):
        store[:] = [
            h for h in store if not getattr(h, "_dm_config_hook", False)
        ]


def _prepend_config_callable(name: str, fn: Callable) -> None:
    """Insert a directly-provided config-value callable at the FRONT of its store.

    The config-value hook must run before ``register_*`` hooks (LOCKED order).
    Registered hooks are appended by ``register_*``; a direct config callable is
    inserted at index 0 so it leads. Tagged so ``_iter_*`` can keep config
    callables ahead of registered ones even if resolution runs after some
    ``register_*`` calls.
    """
    store = {
        "doxtr_music_chord_preprocess": _chord_preprocess_hooks,
        "doxtr_music_node_parsed": _node_parsed_hooks,
        "doxtr_music_html_visit": _html_visit_hooks,
    }[name]
    setattr(fn, "_dm_config_hook", True)
    # Insert after any existing config-value callables, before registered ones.
    insert_at = sum(1 for h in store if getattr(h, "_dm_config_hook", False))
    store.insert(insert_at, fn)


def on_builder_inited_hooks(app) -> None:
    """Close hook registration on ``builder-inited`` (workers spawn after this)."""
    global _registration_closed
    _registration_closed = True


# --- Invocation --------------------------------------------------------------
def _iter_chord_preprocess(config):
    """Yield chord_preprocess hooks in run order: config-value then registered.

    A dotted-string config value is re-resolved here (per worker under ``-j``).
    A direct config callable already leads the module registry (see
    ``_prepend_config_callable``); registered hooks follow. To avoid yielding a
    direct config callable twice, config-value dotted strings are yielded first
    and the module store (which already contains any direct config callable at
    its front) is yielded after — direct config callables are tagged so they are
    not re-yielded from the dotted-string path.
    """
    resolved = _resolved_config_hook(config, "doxtr_music_chord_preprocess")
    if resolved is not None:
        yield resolved
    yield from _chord_preprocess_hooks


def _iter_node_parsed(config):
    resolved = _resolved_config_hook(config, "doxtr_music_node_parsed")
    if resolved is not None:
        yield resolved
    yield from _node_parsed_hooks


def _iter_html_visit(config):
    resolved = _resolved_config_hook(config, "doxtr_music_html_visit")
    if resolved is not None:
        yield resolved
    yield from _html_visit_hooks


def _resolved_config_hook(config, name: str) -> Optional[Callable]:
    """Re-resolve the dotted-string config hook for ``name`` (per worker).

    Returns the callable for a stored dotted string, or ``None`` when the
    config value was a direct callable (already in the module registry) / None /
    invalid. Reads the ``_resolved`` attr (a string or ``None``).
    """
    if config is None:
        return None
    resolved_attr = name + _RESOLVED_SUFFIX
    stored = getattr(config, resolved_attr, None)
    if isinstance(stored, str):
        return resolve_hook_value(stored, name)
    return None


def run_chord_preprocess(chord: str, song_meta: dict, config) -> str:
    """Chain every chord_preprocess hook over ``chord``; return the final string.

    Config-value hook first, then registered hooks (registration order), each
    receiving the prior hook's output. A hook exception → warn + keep the prior
    value (never crash, never abort the chain). Non-str returns are coerced to
    ``str``.
    """
    result = chord
    for hook in _iter_chord_preprocess(config):
        try:
            out = hook(result, song_meta)
        except Exception as exc:  # noqa: BLE001 - hooks must never crash builds
            logger.warning(
                "[doxtr-music] chord_preprocess hook %r raised (%s); "
                "keeping %r.",
                _hook_name(hook),
                exc,
                result,
            )
            continue
        if out is None:
            continue
        result = out if isinstance(out, str) else str(out)
    return result


def run_node_parsed(node, config) -> None:
    """Dispatch every node_parsed hook over ``node`` (additive).

    Config-value hook first, then registered hooks. A hook exception → warn +
    skip that hook (never crash). The non-picklable ``song_meta`` guard is
    applied by the caller (``SongDirectiveBase._node_parsed_hook``) after all
    hooks run, per the LOCKED probe-and-revert contract.
    """
    for hook in _iter_node_parsed(config):
        try:
            hook(node)
        except Exception as exc:  # noqa: BLE001 - hooks must never crash builds
            logger.warning(
                "[doxtr-music] node_parsed hook %r raised (%s); skipping.",
                _hook_name(hook),
                exc,
            )


def run_html_visit(node, translator, config) -> None:
    """Dispatch every html_visit hook over ``(node, translator)`` (additive).

    Config-value hook first, then registered hooks. A hook exception → warn +
    skip (never crash). Injection lands inside a copy-neutral wrapper (the
    caller in ``builders/html.py`` owns that), so appended markup cannot pollute
    the copy-safe lyric stream.
    """
    for hook in _iter_html_visit(config):
        try:
            hook(node, translator)
        except Exception as exc:  # noqa: BLE001 - hooks must never crash builds
            logger.warning(
                "[doxtr-music] html_visit hook %r raised (%s); skipping.",
                _hook_name(hook),
                exc,
            )


def _hook_name(hook) -> str:
    """Best-effort readable name for a hook (for warning messages)."""
    return getattr(hook, "__qualname__", None) or getattr(
        hook, "__name__", repr(hook)
    )
