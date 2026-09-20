"""Shared base for song-family directives (``.. song::``/``.. chord-line::``/…).

The ``run`` sequence is factored here **once** so ``.. song::`` (CHUNK-1-4),
``.. chord-line::`` (this chunk) and ``.. song-include::`` (CHUNK-3-5) cannot
drift. The locked sequence is::

    run():
        text      = self._get_source_text()          # overridable
        tokens,   = parser_fn(text)                   # per-subclass parser
        song_meta
        drain_warnings(self, song_meta)               # single drain point
        tokens    = self._post_parse_transform(...)   # named ordered pipeline
        node      = build_nodes(tokens, clean_meta, options, warn=...)
        assign id / title_id
        self._node_parsed_hook(node)                  # reserved (CHUNK-5-4)
        self._register_song(node)                     # reserved (CHUNK-5-1)
        return [node]

Subclasses supply :attr:`parser_fn` and share the ``option_spec`` from
:mod:`doxtr_music.directives._options`.

**Named ordered pipeline (LOCKED).** :meth:`_post_parse_transform` composes
``chord_preprocess (CHUNK-5-4) → transpose (CHUNK-3-2) → roman (CHUNK-3-3)``.
Each sub-step is identity by default; later chunks **fill** their named step
(they never rewrite the method body). Order is locked so preprocessed chords
flow into transpose and roman analyzes the transposed pitch. Non-``ChordToken``
tokens pass by identity through every step.
"""

from __future__ import annotations

from docutils.parsers.rst import Directive

from doxtr_music.directives._options import (
    normalize_options,
    resolve_transpose_key,
    song_option_spec,
)
from doxtr_music.directives._warnings import drain_warnings

__all__ = ["SongDirectiveBase"]


class SongDirectiveBase(Directive):
    """Common ``run`` pipeline for every ChordPro-family directive.

    Subclasses set :attr:`parser_fn` to a pure ``text -> (tokens, song_meta)``
    parser. The default source text is the directive body; ``.. song-include::``
    overrides :meth:`_get_source_text` to read an external file instead.
    """

    required_arguments = 0
    optional_arguments = 0
    has_content = True
    option_spec = song_option_spec()

    #: Pure parser ``(text) -> (tokens, song_meta)``. Subclasses MUST set this
    #: (as a ``staticmethod`` so it is not bound to ``self``).
    parser_fn = None

    # -- overridable seams ---------------------------------------------------

    def _get_source_text(self):
        """Return the raw source text to parse.

        Default is the directive body. ``.. song-include::`` (CHUNK-3-5)
        overrides this to load an external file through the confined loader.
        """
        return "\n".join(self.content)

    def _post_parse_transform(self, tokens, song_meta, options):
        """Named ordered token pipeline (LOCKED composition).

        ``chord_preprocess → transpose → roman``. Each sub-step is identity by
        default; CHUNK-5-4/3-2/3-3 fill their named step without rewriting this
        method. Non-``ChordToken`` tokens pass through unchanged.
        """
        tokens = self._transform_chord_preprocess(tokens, song_meta, options)
        tokens = self._transform_transpose(tokens, song_meta, options)
        tokens = self._transform_roman(tokens, song_meta, options)
        return tokens

    def _transform_chord_preprocess(self, tokens, song_meta, options):
        """Plugin chord-preprocess step (CHUNK-5-4).

        Rebuilds each frozen :class:`~doxtr_music.tokens.ChordToken` via
        :func:`dataclasses.replace`, chaining the ``chord_preprocess`` hooks
        over ``tok.text`` (config-value hook first, then ``register_*`` hooks).
        Runs FIRST in the ordered pipeline so preprocessed chords flow through
        transpose + roman. Non-``ChordToken`` tokens pass by identity. A hook
        exception is warned + the original chord kept (owned by
        :func:`doxtr_music.hooks.run_chord_preprocess`), so this step never
        crashes a build.

        Degrades to identity when there is no Sphinx config (bare docutils unit
        test) or no hook is configured/registered.
        """
        import dataclasses

        from doxtr_music.hooks import (
            _chord_preprocess_hooks,
            run_chord_preprocess,
        )
        from doxtr_music.tokens import ChordToken

        config = self._config()
        # Fast path: nothing configured and nothing registered -> identity.
        has_config_hook = False
        if config is not None:
            has_config_hook = (
                getattr(config, "doxtr_music_chord_preprocess_resolved", None)
                is not None
            )
        if not has_config_hook and not _chord_preprocess_hooks:
            return tokens

        new_tokens = []
        changed = False
        for tok in tokens:
            if isinstance(tok, ChordToken):
                new_text = run_chord_preprocess(tok.text, song_meta, config)
                if new_text != tok.text:
                    tok = dataclasses.replace(tok, text=new_text)
                    changed = True
            new_tokens.append(tok)
        return new_tokens if changed else tokens

    def _transform_transpose(self, tokens, song_meta, options):
        """Transposition step (CHUNK-3-2 fills).

        Resolves the single effective shift + spelling key from the resolved
        options + source ``song_meta`` (never sums ``:transpose:`` and ``:key:``;
        ``:transpose:`` wins on both-given). When a non-zero shift or an explicit
        target key applies, returns a NEW token list with each ``ChordToken``
        annotated ``transposed`` (others pass by identity). Transpose is silent
        on unrecognized chords (they annotate their own unchanged text),
        preserving the base's single warning-drain; option-level effective-shift
        notes (both-given / missing-source-key) route through the reporter here.
        """
        from doxtr_music.engine.transpose import (
            compute_effective_shift,
            transpose_tokens,
        )

        def _warn(message):
            reporter = getattr(
                getattr(self, "state_machine", None), "reporter", None
            )
            if reporter is None:
                return
            try:
                reporter.warning("doxtr-music: %s" % message, line=self.lineno)
            except Exception:  # pragma: no cover - reporter must never be fatal
                pass

        shift, spell_key = compute_effective_shift(options, song_meta, warn=_warn)
        # Resolve the single effective key ONCE here (LOCKED — CHUNK-3-3 consumes
        # it and MUST NOT re-derive): the transpose target key if one was
        # produced, else the song's source key. Stashed on options so the roman
        # step reads one resolved field.
        meta = song_meta or {}
        source_key = meta.get("key") if isinstance(meta.get("key"), str) else None
        options["_effective_key"] = spell_key or source_key
        if shift == 0 and not spell_key:
            return tokens
        return transpose_tokens(tokens, shift, spell_key)

    def _transform_roman(self, tokens, song_meta, options):
        """Roman-numeral annotation step (CHUNK-3-3, entry points closed in 3-4).

        Annotate every ``ChordToken`` with its harmonic numeral via
        :func:`~doxtr_music.engine.roman.roman_tokens` when **either**
        ``:roman-numerals:`` is set **or** ``doxtr_music_chord_system == "roman"``
        (LOCKED, CHUNK-3-4: ``chord_system="roman"`` resolves at *parse* time,
        identically to the option, so ``ChordNode.roman`` is the single source of
        truth and the render path never calls ``roman_for_chord`` or needs an
        effective key). ``chord_system`` is ``env``-scoped, so a parse-time read
        is correct (a change triggers a reparse).

        Analysis runs AFTER transpose (roman analyzes the transposed pitch)
        against the single ``_effective_key`` resolved by the transpose step.
        Silent on ``None`` (chords render as-is); absent/unparseable effective
        key (the no-key case for ``chord_system="roman"``) → roman is ``None`` for
        every chord, so chords fall back to English letter display silently.
        """
        want_roman = bool(options.get("roman_numerals"))
        # Resolve the effective roman-display mode (per-song option over global
        # config). replace/alongside both need the numeral annotated at parse
        # time; chord_system="roman" also forces replace (LOCKED).
        mode = self._effective_roman_display(options)
        if mode in ("replace", "alongside"):
            want_roman = True
        if not want_roman:
            config = self._config()
            if config is not None and getattr(
                config, "doxtr_music_chord_system", "english"
            ) == "roman":
                want_roman = True
        if not want_roman:
            return tokens
        from doxtr_music.engine.roman import roman_tokens

        effective_key = options.get("_effective_key")
        return roman_tokens(tokens, effective_key)

    def _effective_roman_display(self, options):
        """Resolve the effective roman-display mode: per-song over global.

        Returns one of ``off``/``replace``/``alongside``. A per-song
        ``:roman-display:`` (or the legacy ``:roman-numerals:`` -> ``replace``)
        wins over the global ``doxtr_music_roman_display``. An explicit
        ``roman_display`` also takes precedence over ``chord_system="roman"``
        (which otherwise forces ``replace``). Invalid values fall back to the
        global/``off``.
        """
        from doxtr_music.config import VALID_ROMAN_DISPLAYS

        per_song = options.get("roman_display")
        if per_song in VALID_ROMAN_DISPLAYS:
            return per_song
        config = self._config()
        if config is not None:
            g = getattr(config, "doxtr_music_roman_display", "off")
            if g in VALID_ROMAN_DISPLAYS and g != "off":
                return g
            if getattr(config, "doxtr_music_chord_system", "english") == "roman":
                return "replace"
        # Legacy flag with no explicit mode anywhere -> replace.
        if options.get("roman_numerals"):
            return "replace"
        return "off"

    def _stamp_typography(self, node):
        """Stamp resolved per-song typography onto ``node``'s child nodes.

        Uses the config-cached resolved global
        (``doxtr_music_typography_resolved``) when present; otherwise resolves
        it on the fly (so the directive still stamps under a bare env). Silent /
        best-effort: typography is styling-only and must never break a build.
        """
        from doxtr_music.typography import (
            RESOLVED_CONFIG_ATTR,
            resolve_global_typography,
            stamp_typography,
        )

        config = self._config()
        if config is not None:
            resolved_global = getattr(config, RESOLVED_CONFIG_ATTR, None)
            if resolved_global is None:
                resolved_global = resolve_global_typography(config)
        else:
            resolved_global = None
        stamp_typography(node, resolved_global, config=config)

    def _stamp_roman_display(self, node):
        """Stamp the resolved roman-display mode + format onto each ChordNode.

        The mode (off/replace/alongside) is resolved per-song over global; the
        ``alongside`` format template comes from the per-song ``:roman-format:``
        over the global ``doxtr_music_roman_format`` (validated). Both are stored
        as plain-data node attrs (``roman_display`` / ``roman_format``) so
        :func:`~doxtr_music.engine.i18n.resolve_chord_display` is node-local.
        Only stamped when the mode is not ``off`` (keeps the common case clean).
        """
        from doxtr_music import nodes as _nodes
        from doxtr_music.config import (
            DEFAULT_ROMAN_FORMAT,
            validate_roman_format,
        )

        options = node.get("options") or {}
        mode = self._effective_roman_display(options)
        if mode == "off":
            return
        fmt = options.get("roman_format")
        if not fmt:
            config = self._config()
            fmt = getattr(config, "doxtr_music_roman_format", DEFAULT_ROMAN_FORMAT) \
                if config is not None else DEFAULT_ROMAN_FORMAT
        fmt = validate_roman_format(fmt)
        # The numeral part (alongside mode) is styled with the ``roman``
        # typography element; stash its resolved cell on each chord so the
        # visitors can style the numeral independently of the chord.
        roman_cell = None
        if mode == "alongside":
            resolved_typo = node.get("typography") or {}
            cell = resolved_typo.get("roman") or {}
            roman_cell = {k: v for k, v in cell.items() if v is not None} or None
        for chord in node.findall(_nodes.ChordNode):
            # Inline-role chords (:chord:) are prose, not analyzed song chords.
            if chord.get("inline_role"):
                continue
            chord["roman_display"] = mode
            if mode == "alongside":
                chord["roman_format"] = fmt
                if roman_cell:
                    chord["roman_typography"] = dict(roman_cell)

    def _stamp_singer_colors(self, node):
        """Stamp the resolved winning singer color onto each singer run (4-2).

        Resolves the effective ``{singer: color}`` map (global
        ``doxtr_music_singer_colors`` + per-song ``:singer-colors:``) and stamps
        the winner onto each :class:`SingerSpanNode` + its chord/lyric children
        (the reserved CHUNK-1-2 ``singer_color`` slots), applying the
        singer-over-typography-color precedence in Python so the emitted color
        is already the winner. Runs AFTER :meth:`_stamp_typography` so the
        typography color is present to be overridden. Silent / best-effort:
        singer color is styling-only and must never break a build; an unmapped
        id stamps nothing (typography color survives).
        """
        from doxtr_music.singer import stamp_singer_colors

        config = self._config()
        stamp_singer_colors(node, config)

    def _check_contrast(self, node):
        """Warn (not fail) on sub-AA resolved colors (CHUNK-4-3, WCAG 1.4.3).

        Validates the single resolved emitted color per element (post-singer
        precedence) against a documented ``#ffffff`` heuristic background
        (CHUNK-7-1 will feed a resolved effective background). Runs AFTER
        typography + singer stamping so it sees the emitted winner. Warn-not-fail
        and best-effort: contrast is advisory and must never break a build.
        Skipped for LaTeX (background even less knowable) — the check reads only
        resolved node data, so it is format-neutral, but the *policy* scopes
        warnings to HTML/EPUB output; a single build-time warning per song is
        acceptable and documented.
        """
        from doxtr_music.a11y import check_song_contrast

        def _warn(message):
            reporter = getattr(
                getattr(self, "state_machine", None), "reporter", None
            )
            if reporter is None:
                from sphinx.util import logging as _logging

                _logging.getLogger("doxtr_music.a11y").warning(message)
                return
            try:
                reporter.warning(message, line=self.lineno)
            except Exception:  # pragma: no cover - defensive
                pass

        try:
            # CHUNK-7-1: feed the theme-resolved effective background (HTML+EPUB)
            # into the contrast check; falls back to the a11y #ffffff default
            # when no theme background resolved (config-attr read, never import).
            from doxtr_music.a11y import DEFAULT_BACKGROUND

            config = self._config()
            background = DEFAULT_BACKGROUND
            if config is not None:
                resolved_bg = getattr(
                    config, "doxtr_music_theme_background_resolved", None
                )
                if resolved_bg:
                    background = resolved_bg
            check_song_contrast(node, warn=_warn, background=background)
        except Exception:  # pragma: no cover - advisory, never break a build
            pass

    def _config(self):
        """Best-effort access to the Sphinx ``config`` from the directive.

        Returns ``None`` when unavailable (e.g. a bare docutils unit-test run
        without a Sphinx env), so the roman step degrades to option-only.
        """
        try:
            return self.state.document.settings.env.config
        except Exception:  # pragma: no cover - defensive (no env in unit tests)
            return None

    def _node_parsed_hook(self, node):
        """Dispatch ``node_parsed`` hooks, then enforce the picklable guard (5-4).

        Runs after id assignment and before :meth:`_register_song` so a hook's
        ``song_meta`` mutation is reflected in both the rendered song and the
        registry snapshot (CHUNK-5-1 contract). Hooks compose additively; a hook
        exception is warned + skipped (owned by
        :func:`doxtr_music.hooks.run_node_parsed`).

        **Non-picklable guard (LOCKED):** a hook may make ``node['song_meta']``
        non-picklable, which would crash Sphinx's doctree/env pickling under
        ``-j`` AND the 5-1 registry round-trip. After dispatch, probe
        ``pickle.dumps(node['song_meta'])``; on failure warn AND **revert** to
        the pre-hook ``song_meta`` snapshot (warn-only is insufficient). The
        pre-hook snapshot is a deep copy so a hook mutating a nested container
        in place is also recoverable.

        Degrades to a no-op when there is no Sphinx config and no hook is
        registered.
        """
        import copy
        import pickle

        from doxtr_music.hooks import _node_parsed_hooks, run_node_parsed

        config = self._config()
        has_config_hook = False
        if config is not None:
            has_config_hook = (
                getattr(config, "doxtr_music_node_parsed_resolved", None)
                is not None
            )
        if not has_config_hook and not _node_parsed_hooks:
            return node

        pre_hook_meta = copy.deepcopy(node.get("song_meta") or {})
        run_node_parsed(node, config)

        # Non-picklable guard: the post-hook song_meta must round-trip pickle.
        meta = node.get("song_meta")
        try:
            pickle.dumps(meta)
        except Exception as exc:  # noqa: BLE001 - any pickle failure reverts
            from sphinx.util import logging as _logging

            _logging.getLogger("doxtr_music.hooks").warning(
                "[doxtr-music] a node_parsed hook made song_meta "
                "non-picklable (%s); reverting to the pre-hook snapshot to "
                "keep the doctree and registry picklable under -j.",
                exc,
            )
            node["song_meta"] = pre_hook_meta
        return node

    def _register_song(self, node):
        """Snapshot this song's metadata into ``env.song_data`` (CHUNK-5-1).

        Runs AFTER :meth:`_node_parsed_hook` so the snapshot reflects post-hook
        metadata. The entry is **plain picklable data**: the resolvable output
        anchor (``node['ids'][0]``, NOT ``title_id``), the docname, and the
        queryable ``song_meta`` (defensively ``_``-key-filtered — the body is
        never stored). This is the *single* registry write point for every song
        directive; ``iter_songs`` is the single read point.

        Best-effort: registration is a query-index convenience and must never
        break a build. Without a Sphinx env (bare docutils unit test) or without
        a resolvable id it is a silent no-op.
        """
        from doxtr_music.registry import register_song

        try:
            env = self.state.document.settings.env
        except Exception:  # pragma: no cover - no env in bare unit tests
            return None
        if env is None:
            return None
        ids = node.get("ids") or []
        if not ids:  # pragma: no cover - run() always assigns an id first
            return None

        meta = node.get("song_meta") or {}
        entry = {
            k: v for k, v in meta.items() if not k.startswith("_")
        }
        # id / docname are authoritative and always overwrite any meta key of
        # the same name so the cross-ref identity is never shadowed by content.
        entry["id"] = ids[0]
        entry["docname"] = env.docname
        register_song(env, entry)
        return None

    # -- fixed pipeline ------------------------------------------------------

    def run(self):
        # Local imports keep this module importable without a full Sphinx app in
        # unit tests, and honor the "defer Sphinx-coupled imports" contract.
        from doxtr_music.nodes import build_nodes

        parser_fn = type(self).parser_fn
        if parser_fn is None:  # pragma: no cover - subclass contract
            raise NotImplementedError("SongDirectiveBase subclass must set parser_fn")

        text = self._get_source_text()
        tokens, song_meta = parser_fn(text)

        # 1. Normalize options, then resolve transpose/key precedence into single
        #    fields (directive is the sole home for that precedence).
        options = normalize_options(self.options)
        resolve_transpose_key(options, song_meta)

        # 2. Single warning-drain point (before transforms — transforms are
        #    silent on unrecognized input, so no post-transform warnings).
        drain_warnings(self, song_meta)

        # 3. Named ordered transform pipeline (identity until later chunks fill).
        tokens = self._post_parse_transform(tokens, song_meta, options)

        # 4. Strip internal ``_``-prefixed machinery keys before meta lands on
        #    the node (CHUNK-1-3 lifecycle contract).
        clean_meta = {k: v for k, v in song_meta.items() if not k.startswith("_")}

        # 5. Assemble the single node tree. Route build_nodes warnings through
        #    the reporter too (unknown chord annotations, etc.).
        def _warn(message):
            reporter = getattr(
                getattr(self, "state_machine", None), "reporter", None
            )
            if reporter is None:
                return
            try:
                reporter.warning(message, line=self.lineno)
            except Exception:  # pragma: no cover - defensive
                pass

        node = build_nodes(tokens, clean_meta, options, warn=_warn)

        # 5b. Resolve + stamp per-song typography (CHUNK-4-1) onto the styleable
        #     child nodes so each visitor is node-local (no ancestor walk). The
        #     resolved global is cached on config at config-inited (~600); when
        #     unavailable (pure unit test, no env) fall back to a fresh resolve.
        self._stamp_typography(node)

        # 5b'. Stamp the resolved roman-display mode + alongside format onto each
        #      chord so resolve_chord_display can render chord-only / numeral /
        #      chord+numeral node-locally (per-song over global).
        self._stamp_roman_display(node)

        # 5c. Resolve + stamp the winning singer color (CHUNK-4-2) onto each
        #     singer run. Runs AFTER typography so singer wins on the color
        #     channel while typography font/size are preserved. Emitted once per
        #     element by the visitors (no cascade/lexical reliance).
        self._stamp_singer_colors(node)

        # 5d. Validate the resolved emitted colors for WCAG AA contrast
        #     (CHUNK-4-3). Warn-not-fail vs a #ffffff heuristic background
        #     (CHUNK-7-1 feeds a resolved effective background later).
        self._check_contrast(node)

        # 6. Assign a stable id + title_id target (CHUNK-4-3 aria-labelledby /
        #    CHUNK-5-3 cross-refs target these). Prefer a title-derived name.
        document = self.state.document
        title = clean_meta.get("title")
        if isinstance(title, str) and title.strip():
            self.options["name"] = title.strip()
            self.add_name(node)
        if not node["ids"]:
            document.set_id(node)
        song_id = node["ids"][0]
        node["title_id"] = "%s-title" % song_id

        # 7. Reserved hook slots (identity/no-op until CHUNK-5-4 / CHUNK-5-1).
        self._node_parsed_hook(node)
        self._register_song(node)

        return [node]
