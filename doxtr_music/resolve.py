r"""Resolve-phase machinery for ``song-list`` / ``song-index`` (CHUNK-5-3).

Two responsibilities, both wired from :func:`doxtr_music.setup`:

1. **Replacement** — a ``doctree-resolved`` **event handler**
   ``(app, doctree, fromdocname)`` that finds every
   :class:`~doxtr_music.nodes.SongListNode` / :class:`~doxtr_music.nodes.SongIndexNode`
   placeholder, queries the merged registry via
   :func:`~doxtr_music.registry.iter_songs`, applies the ``:filter:`` (via
   :func:`~doxtr_music.safe_eval.safe_eval`), ``:group-by:`` and ``:sort:``
   (metadata-key lookups), and **replaces** each placeholder with **standard
   docutils nodes** — a ``bullet_list`` of ``reference`` nodes built with
   :func:`sphinx.util.nodes.make_refnode` (song-list), or a ``definition_list`` of
   group headings each holding such a ``bullet_list`` (song-index). Because the
   output is standard nodes, Sphinx's own HTML/LaTeX/EPUB writers render the links
   with correct escaping — no custom visitors, no ``builders/*`` edits.

2. **Incremental cross-doc invalidation** — an ``env-updated`` handler (fires
   **after** all reads + ``env-merge-info``, and its return value is exactly "extra
   docnames to re-resolve"). It computes a stable, order-independent signature over
   the sorted queryable registry fields, compares it to the signature persisted on
   ``env`` between builds, and — if it changed — returns the set of docnames that
   contain a ``song-list``/``song-index`` so they re-resolve **this** build. Using
   ``env-updated`` (not ``env-get-outdated``, which fires before merge) makes the
   update same-build correct.

LOCKED policy:

* Malformed ``:filter:`` → a Sphinx warning + the list is treated as **empty**
  (never a crash, never all songs). ``safe_eval`` coercion diagnostics are surfaced
  as warnings. A valid-but-zero-match filter → empty state with **no** warning.
* ``:group-by:`` / ``:sort:`` are **metadata key names**, never ``safe_eval``.
  Missing group key → single ``"Other"`` label.
* Cross-references use the ``(docname, id)`` identity (docutils ids are doc-local),
  never ``id`` alone.
"""

from __future__ import annotations

import hashlib
import json

from docutils import nodes as _dn
from sphinx.util import logging as _sphinx_logging
from sphinx.util.nodes import make_refnode

from doxtr_music import nodes as _nodes
from doxtr_music.directives.song_list import QUERY_DOCS_ATTR
from doxtr_music.registry import iter_songs
from doxtr_music.safe_eval import FilterError, safe_eval

__all__ = [
    "resolve_song_queries",
    "invalidate_query_docs",
    "connect_resolve_handlers",
    "OTHER_GROUP_LABEL",
    "SIGNATURE_ATTR",
]

logger = _sphinx_logging.getLogger(__name__)

#: Single label for entries missing the group-by key.
OTHER_GROUP_LABEL = "Other"

#: ``env`` attribute persisting the registry signature between builds.
SIGNATURE_ATTR = "doxtr_music_registry_signature"

#: CSS class stamped on the resolved list/index containers (marker + a11y hook).
_SONG_LIST_CLASS = "doxtr-song-list"
_SONG_INDEX_CLASS = "doxtr-song-index"


# ---------------------------------------------------------------------------
# Query helpers (filter / group / sort)
# ---------------------------------------------------------------------------

def _filtered_entries(expr, entries, node, docname):
    """Return the entries matching ``expr`` (or all entries when ``expr`` falsy).

    A :class:`~doxtr_music.safe_eval.FilterError` (parse error / disallowed
    element) → a Sphinx warning and an **empty** result. Per-entry coercion
    diagnostics are surfaced as warnings once (deduplicated). A valid filter that
    simply matches nothing returns an empty list with **no** warning.
    """
    if not expr:
        return list(entries)

    selected = []
    seen_diagnostics = set()
    try:
        for entry in entries:
            diagnostics = []
            if safe_eval(expr, entry, diagnostics):
                selected.append(entry)
            for note in diagnostics:
                if note not in seen_diagnostics:
                    seen_diagnostics.add(note)
                    logger.warning(
                        "song-list/index :filter: %r coercion note: %s"
                        % (expr, note),
                        location=docname,
                    )
    except FilterError as exc:
        logger.warning(
            "song-list/index :filter: %r is invalid (%s); rendering an empty list"
            % (expr, exc),
            location=docname,
        )
        return []
    return selected


def _sorted_entries(sort_key, entries):
    """Stably sort ``entries`` by the metadata key ``sort_key`` (missing → last).

    ``:sort:`` is a **key name**, never an expression. When ``sort_key`` is falsy
    the ``iter_songs`` order (deterministic per CHUNK-5-1) is preserved.
    """
    if not sort_key:
        return list(entries)

    def key(entry):
        value = entry.get(sort_key)
        # Missing/None sorts last; otherwise sort by a string projection so
        # mixed str/number metadata never raises a TypeError.
        return (value is None, "" if value is None else str(value))

    return sorted(entries, key=key)


def _grouped_entries(group_key, entries):
    """Group ``entries`` by the metadata key ``group_key`` (missing → "Other").

    ``:group-by:`` is a **key name** (``entry.get(key)``), never ``safe_eval``.
    Returns a list of ``(label, [entries])`` pairs sorted stably by label; the
    ``"Other"`` bucket (missing/``None`` key) sorts last.
    """
    buckets = {}
    order = []
    for entry in entries:
        value = entry.get(group_key)
        label = OTHER_GROUP_LABEL if value is None else str(value)
        if label not in buckets:
            buckets[label] = []
            order.append(label)
        buckets[label].append(entry)

    def group_sort_key(label):
        # "Other" always last; the rest alphabetically for stable output.
        return (label == OTHER_GROUP_LABEL, label)

    return [(label, buckets[label]) for label in sorted(order, key=group_sort_key)]


# ---------------------------------------------------------------------------
# Standard-node construction
# ---------------------------------------------------------------------------

def _entry_title(entry):
    """The display text for a song reference: its ``title`` else its id."""
    return entry.get("title") or entry.get("id") or "(untitled)"


def _reference_item(app, fromdocname, entry):
    """Build a ``list_item`` holding a resolved cross-``reference`` to ``entry``.

    Uses :func:`make_refnode` with the ``(docname, id)`` identity so the link
    resolves correctly across documents in every writer (HTML ``<a>`` / LaTeX
    ``\\hyperref`` / EPUB ``<a>``). If the target cannot be resolved (a missing
    id, or a cross-document target the writer cannot link in the assembled tree
    — e.g. the LaTeX single-file assembly), degrade gracefully to plain title
    text so the list/index still renders every song and the build never crashes.
    """
    title = _entry_title(entry)
    inner = _dn.Text(title)
    docname = entry.get("docname")
    target_id = entry.get("id")
    refnode = None
    if docname and target_id:
        try:
            refnode = make_refnode(
                app.builder, fromdocname, docname, target_id, inner, title
            )
        except Exception:
            # make_refnode can raise when the target is not resolvable in the
            # current writer's assembled tree; fall back to plain text.
            refnode = None
    para = _dn.inline("", "", refnode if refnode is not None else _dn.Text(title))
    item = _dn.list_item("", para)
    return item


def _empty_note(message):
    """A standard ``paragraph`` used as the empty-state body."""
    para = _dn.paragraph("", message)
    return para


def _build_song_list(app, fromdocname, entries):
    """Return the replacement node(s) for a ``song-list`` placeholder.

    A ``bullet_list`` of resolved references (or an empty-state paragraph),
    wrapped in a ``container`` carrying the ``doxtr-song-list`` class so the
    marker + a11y hook survive in every format.
    """
    container = _dn.container(classes=[_SONG_LIST_CLASS])
    if not entries:
        container += _empty_note("No matching songs.")
        return container
    blist = _dn.bullet_list()
    for entry in entries:
        blist += _reference_item(app, fromdocname, entry)
    container += blist
    return container


def _build_song_index(app, fromdocname, groups):
    """Return the replacement node(s) for a ``song-index`` placeholder.

    A ``definition_list`` whose terms are the group labels and whose definitions
    hold a ``bullet_list`` of resolved references, wrapped in a ``container``
    carrying the ``doxtr-song-index`` class. Empty → an empty-state paragraph.
    """
    container = _dn.container(classes=[_SONG_INDEX_CLASS])
    if not groups:
        container += _empty_note("No matching songs.")
        return container
    dlist = _dn.definition_list()
    for label, entries in groups:
        term = _dn.term("", label)
        blist = _dn.bullet_list()
        for entry in entries:
            blist += _reference_item(app, fromdocname, entry)
        definition = _dn.definition("", blist)
        dlist += _dn.definition_list_item("", term, definition)
    container += dlist
    return container


# ---------------------------------------------------------------------------
# Alphabetical, LaTeX-index-style rendering (letter heading + title + page)
# ---------------------------------------------------------------------------

#: CSS class on the alphabetical-index container / its parts.
_SONG_INDEX_ALPHA_CLASS = "doxtr-song-index-alpha"


def _title_sorted(entries):
    """Sort entries case-insensitively by display title (for the letter index)."""
    return sorted(entries, key=lambda e: _entry_title(e).casefold())


def _index_letter(entry):
    """Return the uppercase first-letter bucket for an entry's title.

    A title starting with a non-letter (digit/symbol) buckets under ``"#"`` — the
    common LaTeX-index convention for the leading non-alphabetic group.
    """
    title = _entry_title(entry).strip()
    if not title:
        return "#"
    ch = title[0].upper()
    return ch if ch.isalpha() else "#"


def _target_label(fromdocname, entry):
    """Return the LaTeX ``\\pageref`` label for a song target: ``docname:id``.

    Mirrors how Sphinx's LaTeX writer labels a cross-document reference target
    (``\\label{\\detokenize{<docname>:<id>}}``), so ``\\pageref`` resolves to the
    page the song is on. Returns ``None`` when the target is incomplete.
    """
    docname = entry.get("docname")
    target_id = entry.get("id")
    if not (docname and target_id):
        return None
    return "%s:%s" % (docname, target_id)


def _is_latex_builder(app):
    """True when the active builder produces LaTeX/PDF (page numbers exist)."""
    name = getattr(getattr(app, "builder", None), "name", "") or ""
    return name.startswith("latex") or name == "latexpdf"


def _index_page_format(app):
    """Return the validated ``{page}`` format string for page references.

    Reads ``doxtr_music_index_page_format`` from config (already validated on
    ``config-inited``) and defends against a missing/invalid value so a bare
    unit-test app without the config still renders. The single ``{page}``
    placeholder is substituted with the LaTeX page-number macro by the caller.
    """
    config = getattr(app, "config", None)
    value = getattr(config, "doxtr_music_index_page_format", None)
    if not isinstance(value, str) or "{page}" not in value:
        return "{page}"
    return value


def _latex_text_escape(text):
    r"""Escape the LaTeX-special characters in literal page-format text.

    Only the characters that would break out of a text run are escaped; the
    format string is short author-supplied boilerplate (e.g. ``"page "``), so a
    compact, dependency-free escape is sufficient. Keeps an author-provided
    format inert LaTeX text (matches the roman-format safety policy).
    """
    if not text:
        return ""
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def _latex_page_reference(app, label):
    r"""Return raw LaTeX for a formatted, hyperlinked page reference to ``label``.

    The configured ``doxtr_music_index_page_format`` (e.g. ``"page {page}"``)
    wraps the page number; the **entire** formatted string is wrapped in a single
    ``\hyperref[label]{...}`` so the whole phrase links to the song's page, not
    just the digits. ``{page}`` becomes ``\pageref*{\detokenize{label}}`` (the
    starred form suppresses the nested hyperlink so only the outer ``\hyperref``
    links, avoiding a nested-link warning). Literal text around ``{page}`` is
    LaTeX-escaped so an author-provided format cannot inject control sequences.
    """
    detok = _latex_idescape(label)
    page_macro = r"\pageref*{%s}" % detok
    fmt = _index_page_format(app)
    # Split on the single {page} placeholder and escape the literal segments
    # (unescaping standard {{ }} brace escapes first).
    before, _sep, after = fmt.partition("{page}")
    before = _latex_text_escape(before.replace("{{", "{").replace("}}", "}"))
    after = _latex_text_escape(after.replace("{{", "{").replace("}}", "}"))
    inner = "%s%s%s" % (before, page_macro, after)
    return r"\hyperref[%s]{%s}" % (detok, inner)


def _alpha_entry_nodes(app, fromdocname, entry):
    """Build the inline nodes for one index entry: title link + (LaTeX) page no.

    * The title is a resolved cross-``reference`` to the song (all formats).
    * In LaTeX, a raw ``\\dotfill`` + a formatted, hyperlinked page reference is
      appended, so the entry reads ``Title .... page 12`` with the whole page
      phrase linked to the song (the format comes from
      ``doxtr_music_index_page_format``). HTML/EPUB have no pages, so only the
      linked title is emitted.
    """
    title = _entry_title(entry)
    nodes_out = []
    docname = entry.get("docname")
    target_id = entry.get("id")
    ref = None
    if docname and target_id:
        try:
            ref = make_refnode(
                app.builder, fromdocname, docname, target_id, _dn.Text(title), title
            )
        except Exception:
            ref = None
    nodes_out.append(ref if ref is not None else _dn.Text(title))

    label = _target_label(fromdocname, entry)
    if label and _is_latex_builder(app):
        # Dotted leader + a formatted, hyperlinked page reference to the song's
        # label. The configured page format wraps the number and the whole
        # phrase links to the song (see :func:`_latex_page_reference`).
        tex = r"\nobreak\dotfill\nobreak %s" % _latex_page_reference(app, label)
        nodes_out.append(_dn.raw("", tex, format="latex"))
    return nodes_out


def _latex_idescape(label):
    r"""Return ``\detokenize{<label>}`` matching Sphinx's LaTeX label escaping.

    Sphinx labels a target as ``\label{\detokenize{<docname>:<id>}}`` and refs
    it via ``\detokenize{...}`` with backslashes replaced by ``_`` and
    non-ASCII backslash-escaped. Mirror that so ``\autopageref*`` resolves to
    the song's page. (doxtr-music ids are ASCII slugs, so this is normally an
    identity apart from the ``\detokenize`` wrapper.)
    """
    ascii_label = str(label).encode("ascii", "backslashreplace").decode("ascii")
    return r"\detokenize{%s}" % ascii_label.replace("\\", "_")


def _build_song_index_alpha(app, fromdocname, entries):
    """Return a LaTeX-index-style alphabetical index of songs.

    Groups entries by the first letter of their title (a ``#`` bucket for
    non-alphabetic leads), emitting a **letter heading** (``rubric``) followed by
    a ``bullet_list`` of entries; each entry is the song title linked to the
    song, and — in LaTeX/PDF — a hyperlinked **page number**. HTML/EPUB show the
    linked titles under each letter (no page numbers, which do not exist there).
    Wrapped in a ``container`` carrying the ``doxtr-song-index-alpha`` class.
    Empty → an empty-state paragraph.
    """
    container = _dn.container(classes=[_SONG_INDEX_ALPHA_CLASS])
    if not entries:
        container += _empty_note("No matching songs.")
        return container
    current_letter = None
    blist = None
    for entry in entries:
        letter = _index_letter(entry)
        if letter != current_letter:
            current_letter = letter
            # A letter heading (rubric renders as a bold run in all formats;
            # LaTeX gets a \sphinxstyletheadfamily-ish heading).
            heading = _dn.rubric("", letter, classes=["doxtr-song-index-letter"])
            container += heading
            blist = _dn.bullet_list(classes=["doxtr-song-index-letter-list"])
            container += blist
        item = _dn.list_item()
        para = _dn.inline("", "", *_alpha_entry_nodes(app, fromdocname, entry))
        item += para
        blist += item
    return container


# ---------------------------------------------------------------------------
# doctree-resolved event handler
# ---------------------------------------------------------------------------

def resolve_song_queries(app, doctree, fromdocname):
    """``doctree-resolved`` handler — replace query placeholders with real nodes.

    Signature ``(app, doctree, fromdocname)`` (an event handler, not a docutils
    Transform: it needs the event's ``fromdocname`` for :func:`make_refnode`).
    Connected after Sphinx's own xref resolution.
    """
    env = app.env
    entries = list(iter_songs(env))

    for placeholder in list(doctree.findall(_nodes.SongListNode)):
        selected = _filtered_entries(
            placeholder.get("filter"), entries, placeholder, fromdocname
        )
        selected = _sorted_entries(placeholder.get("sort"), selected)
        replacement = _build_song_list(app, fromdocname, selected)
        placeholder.replace_self(replacement)

    for placeholder in list(doctree.findall(_nodes.SongIndexNode)):
        selected = _filtered_entries(
            placeholder.get("filter"), entries, placeholder, fromdocname
        )
        style = (placeholder.get("style") or "list").strip().lower()
        sort_key = placeholder.get("sort")
        if style == "index":
            # LaTeX-style alphabetical index: letter headings + title + page.
            # Sort by title (the letter grouping is by title first letter),
            # unless an explicit :sort: key overrides the ordering.
            if sort_key:
                selected = _sorted_entries(sort_key, selected)
            else:
                selected = _title_sorted(selected)
            replacement = _build_song_index_alpha(app, fromdocname, selected)
            placeholder.replace_self(replacement)
            continue
        group_key = placeholder.get("group_by")
        if sort_key:
            selected = _sorted_entries(sort_key, selected)
        if group_key:
            groups = _grouped_entries(group_key, selected)
        else:
            # No group-by → a single unlabelled group is meaningless; fall back
            # to one "Other" bucket so the index still renders every song.
            groups = [(OTHER_GROUP_LABEL, selected)] if selected else []
        replacement = _build_song_index(app, fromdocname, groups)
        placeholder.replace_self(replacement)


# ---------------------------------------------------------------------------
# Incremental invalidation (env-updated + registry signature)
# ---------------------------------------------------------------------------

def _registry_signature(env):
    """A stable, order-independent hash over the sorted queryable registry fields.

    ``iter_songs`` is already deterministically ordered (CHUNK-5-1), so a plain
    JSON dump of the full entry list is stable across builds. The signature
    covers only the stored plain-data fields (queryable metadata + ``id``/
    ``docname``) — a song's *body* is never stored, so a body-only edit cannot
    spuriously invalidate a list.
    """
    entries = list(iter_songs(env))
    payload = json.dumps(entries, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def invalidate_query_docs(app, env):
    """``env-updated`` handler — re-resolve query docs when the registry changed.

    Fires after all reads + ``env-merge-info``. Computes the current registry
    signature, compares to the one persisted on ``env`` from the previous build,
    and — when it differs — returns the docnames that contain a
    ``song-list``/``song-index`` so Sphinx re-resolves them **this** build
    (same-build correct). Persists the new signature for the next build.
    """
    current = _registry_signature(env)
    previous = getattr(env, SIGNATURE_ATTR, None)
    setattr(env, SIGNATURE_ATTR, current)

    if previous == current:
        return []
    query_docs = getattr(env, QUERY_DOCS_ATTR, None) or set()
    # Only return docs Sphinx still knows about (a removed query doc is dropped).
    known = set(env.found_docs) if hasattr(env, "found_docs") else set(query_docs)
    return sorted(d for d in query_docs if d in known)


def connect_resolve_handlers(app):
    """Wire the ``doctree-resolved`` replacement + ``env-updated`` invalidation.

    Called from :func:`doxtr_music.setup`. ``doctree-resolved`` is connected at a
    priority after Sphinx's own xref resolution so ``make_refnode`` targets exist.
    """
    app.connect("doctree-resolved", resolve_song_queries)
    app.connect("env-updated", invalidate_query_docs)
