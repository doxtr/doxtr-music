"""Tests for CHUNK-5-3 (``.. song-list::`` / ``.. song-index::``, resolve phase).

Covers the exit criteria:

* ``:filter:`` selects the right songs via ``safe_eval`` and resolves cross-doc
  links (``make_refnode`` — ``(docname, id)`` identity) in HTML.
* Placeholder at read (``SongListNode``/``SongIndexNode`` with raw option attrs;
  no read-phase registry query); resolved + replaced by the ``doctree-resolved``
  event handler into **standard docutils nodes** (``bullet_list``/``reference``,
  ``definition_list``).
* ``:group-by:`` is a metadata-key lookup (``entry.get``), not ``safe_eval``;
  missing key → single ``"Other"`` group; stable order.
* Malformed ``:filter:`` → a warning + empty list (never a crash, never all
  songs); a valid-but-zero-match filter → empty + **no** warning; coercion
  diagnostics surfaced as warnings.
* Incremental (``env-updated`` + registry signature): rebuilding doc B (adding a
  song) updates doc A's list **this build** without editing doc A.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sphinx = pytest.importorskip("sphinx")
from sphinx.application import Sphinx  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "test_harness"))

from doxtr_music.directives.song_list import (  # noqa: E402
    QUERY_DOCS_ATTR,
    SongIndexDirective,
    SongListDirective,
)
from doxtr_music.resolve import (  # noqa: E402
    OTHER_GROUP_LABEL,
    _filtered_entries,
    _grouped_entries,
    _sorted_entries,
)


# ---------------------------------------------------------------------------
# Sphinx project helpers
# ---------------------------------------------------------------------------

_SONG = """{{title: {title}}}
{{artist: {artist}}}
{{meta: tags {tags}}}
{{meta: year {year}}}

[C]a [G]song
"""


def _song_block(title, artist, tags, year):
    return ".. song::\n\n" + "\n".join(
        "   " + line
        for line in _SONG.format(title=title, artist=artist, tags=tags, year=year).splitlines()
    ) + "\n"


def _make_project(root: Path, docs: dict) -> Path:
    """Write a multi-doc project. ``docs`` maps docname -> rst body."""
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music"]\n'
        'html_theme = "basic"\n',
        encoding="utf-8",
    )
    for docname, body in docs.items():
        (src / f"{docname}.rst").write_text(body, encoding="utf-8")
    return src


def _build_html(root: Path, docs: dict, warning=None, freshenv=True, force_all=True):
    src = _make_project(root, docs)
    out = root / "out"
    doctrees = root / "doctrees"
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(doctrees),
        buildername="html",
        freshenv=freshenv,
        warning=warning,
    )
    app.build(force_all=force_all)
    return app, out, src


def _read(out: Path, docname: str) -> str:
    return (out / f"{docname}.html").read_text(encoding="utf-8")


def _container_region(html: str, cls: str = "doxtr-song") -> str:
    """Return the HTML of the resolved song-list/index container ``<div>``.

    Scopes marker/link checks to the container itself (excludes theme chrome
    like the sidebar nav / "Show Source" list items). Matches the container
    ``<div>`` by its class and returns text up to its balanced ``</div>``.
    """
    idx = html.find(cls)
    if idx == -1:
        return ""
    # Back up to the opening <div ...
    start = html.rfind("<div", 0, idx)
    if start == -1:
        start = idx
    # Walk forward balancing <div>/</div> from the opening tag.
    depth = 0
    pos = start
    while pos < len(html):
        nxt_open = html.find("<div", pos)
        nxt_close = html.find("</div>", pos)
        if nxt_close == -1:
            return html[start:]
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            pos = nxt_open + 4
        else:
            depth -= 1
            pos = nxt_close + 6
            if depth <= 0:
                return html[start:pos]
    return html[start:]


# ---------------------------------------------------------------------------
# Pure filter / group / sort helpers (no Sphinx)
# ---------------------------------------------------------------------------

_ENTRIES = [
    {"id": "s1", "docname": "a", "title": "Rock 95", "tags": ["rock", "pop"], "year": "1995"},
    {"id": "s2", "docname": "a", "title": "Ballad 75", "tags": ["ballad"], "year": "1975"},
    {"id": "s3", "docname": "b", "title": "Rock 05", "tags": ["rock"], "year": "2005"},
]


def test_filter_selects_matching_songs():
    got = _filtered_entries('"rock" in tags and year > 1990', _ENTRIES, None, "a")
    assert [e["id"] for e in got] == ["s1", "s3"]


def test_valid_but_empty_filter_returns_empty():
    got = _filtered_entries('"jazz" in tags', _ENTRIES, None, "a")
    assert got == []


def test_no_filter_returns_all():
    got = _filtered_entries(None, _ENTRIES, None, "a")
    assert len(got) == len(_ENTRIES)


def test_group_by_missing_key_goes_to_other():
    entries = [
        {"id": "x", "docname": "a", "artist": "The Nines"},
        {"id": "y", "docname": "a", "artist": "The Nines"},
        {"id": "z", "docname": "a"},  # no artist
    ]
    groups = _grouped_entries("artist", entries)
    labels = [label for label, _ in groups]
    assert "The Nines" in labels
    assert OTHER_GROUP_LABEL in labels
    # "Other" sorts last.
    assert labels[-1] == OTHER_GROUP_LABEL
    other = dict(groups)[OTHER_GROUP_LABEL]
    assert [e["id"] for e in other] == ["z"]


def test_sort_by_key_missing_last():
    entries = [
        {"id": "b", "docname": "a", "year": "2000"},
        {"id": "a", "docname": "a", "year": "1990"},
        {"id": "c", "docname": "a"},  # missing year -> last
    ]
    got = _sorted_entries("year", entries)
    assert [e["id"] for e in got] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Read phase: placeholder emitted, no registry query
# ---------------------------------------------------------------------------

def test_directive_option_spec_uses_key_names_not_eval():
    # group-by / sort are plain unchanged key strings, filter too; style is the
    # song-index render mode (list/index).
    for cls in (SongListDirective, SongIndexDirective):
        assert set(cls.option_spec) == {"filter", "group-by", "sort", "style"}


def test_song_list_placeholder_at_read(tmp_path):
    docs = {
        "index": ".. toctree::\n\n   songs\n   listing\n",
        "songs": _song_block("Rock 95", "Nines", "rock, pop", "1995"),
        "listing": (
            "Listing\n=======\n\n"
            ".. song-list::\n   :filter: \"rock\" in tags\n"
        ),
    }
    app, out, _ = _build_html(tmp_path, docs)
    # After a full build the placeholder is replaced (resolve ran), so the
    # rendered listing page has the resolved container, not a raw placeholder.
    html = _read(out, "listing")
    assert "doxtr-song-list" in html


# ---------------------------------------------------------------------------
# Resolve phase: cross-doc links, standard nodes
# ---------------------------------------------------------------------------

def test_cross_doc_links_resolve(tmp_path):
    docs = {
        "index": ".. toctree::\n\n   songs\n   listing\n",
        "songs": (
            _song_block("Rock 95", "Nines", "rock, pop", "1995")
            + "\n"
            + _song_block("Rock 05", "New", "rock", "2005")
        ),
        "listing": (
            "Listing\n=======\n\n"
            ".. song-list::\n   :filter: \"rock\" in tags and year > 1990\n"
        ),
    }
    app, out, _ = _build_html(tmp_path, docs)
    html = _read(out, "listing")
    assert "doxtr-song-list" in html
    region = _container_region(html)
    # Two matching songs -> two <li> links inside the container.
    assert region.count("<li") >= 2
    # Cross-doc links point at the songs page.
    assert 'href="songs.html#' in region


def test_resolved_output_is_standard_nodes(tmp_path):
    docs = {
        "index": ".. toctree::\n\n   songs\n   listing\n",
        "songs": _song_block("Rock 95", "Nines", "rock", "1995"),
        "listing": (
            "Listing\n=======\n\n"
            ".. song-list::\n"
        ),
    }
    app, out, _ = _build_html(tmp_path, docs)
    html = _read(out, "listing")
    region = _container_region(html)
    # Standard-node output: the resolved container renders a native <ul>/<li>
    # list of <a> references (bullet_list + reference), not a custom element.
    assert "<ul" in region
    assert "<li" in region
    assert "<a" in region and "href=" in region
    # The reserved placeholder node emits no custom tag/class of its own.
    assert "SongListNode" not in html


def test_song_index_group_by_renders_groups(tmp_path):
    docs = {
        "index": ".. toctree::\n\n   songs\n   idx\n",
        "songs": (
            _song_block("A", "The Nines", "rock", "1990")
            + "\n"
            + ".. song::\n\n   {title: NoArtist}\n\n   [C]x\n"
        ),
        "idx": (
            "Index\n=====\n\n"
            ".. song-index::\n   :group-by: artist\n"
        ),
    }
    app, out, _ = _build_html(tmp_path, docs)
    html = _read(out, "idx")
    assert "doxtr-song-index" in html
    region = _container_region(html, "doxtr-song-index")
    assert "The Nines" in region
    assert OTHER_GROUP_LABEL in region
    # Standard-node output: a definition list (<dl>) of group headings.
    assert "<dl" in region


# ---------------------------------------------------------------------------
# Malformed vs valid-empty filter (warning behaviour)
# ---------------------------------------------------------------------------

def _warning_text(root: Path, docs: dict):
    import io

    buf = io.StringIO()
    _build_html(root, docs, warning=buf)
    return buf.getvalue()


def test_malformed_filter_warns_and_empty(tmp_path):
    docs = {
        "index": ".. toctree::\n\n   songs\n   listing\n",
        "songs": _song_block("Rock 95", "Nines", "rock", "1995"),
        "listing": (
            "Listing\n=======\n\n"
            # Arithmetic is rejected by safe_eval -> FilterError -> warn + empty.
            ".. song-list::\n   :filter: year + 1\n"
        ),
    }
    warnings = _warning_text(tmp_path, docs)
    assert "song-list/index :filter:" in warnings and "invalid" in warnings.lower()
    html = _read(tmp_path / "out", "listing")
    assert "doxtr-song-list" in html
    # Empty: no <li> link items despite a song existing.
    region = _container_region(html)
    assert "<li" not in region


def test_valid_empty_filter_no_warning(tmp_path):
    docs = {
        "index": ".. toctree::\n\n   songs\n   listing\n",
        "songs": _song_block("Rock 95", "Nines", "rock", "1995"),
        "listing": (
            "Listing\n=======\n\n"
            ".. song-list::\n   :filter: \"jazz\" in tags\n"
        ),
    }
    warnings = _warning_text(tmp_path, docs)
    # A valid filter that matches nothing must NOT emit a song-list/index
    # filter warning (distinct from the malformed case).
    assert "song-list/index :filter:" not in warnings
    html = _read(tmp_path / "out", "listing")
    region = _container_region(html)
    assert "<li" not in region


# ---------------------------------------------------------------------------
# Incremental cross-doc invalidation (env-updated + signature)
# ---------------------------------------------------------------------------

def test_incremental_rebuild_updates_list_same_build(tmp_path):
    # Build 1: doc "songs" has one rock song; "listing" filters rock.
    docs = {
        "index": ".. toctree::\n\n   songs\n   listing\n",
        "songs": _song_block("Rock 95", "Nines", "rock", "1995"),
        "listing": (
            "Listing\n=======\n\n"
            ".. song-list::\n   :filter: \"rock\" in tags\n"
        ),
    }
    src = _make_project(tmp_path, docs)
    out = tmp_path / "out"
    doctrees = tmp_path / "doctrees"

    def build():
        app = Sphinx(
            srcdir=str(src),
            confdir=str(src),
            outdir=str(out),
            doctreedir=str(doctrees),
            buildername="html",
            freshenv=False,
        )
        app.build()
        return app

    build()
    html1 = _read(out, "listing")
    assert _container_region(html1).count("<li") == 1

    # Edit ONLY the songs doc (add a second rock song). Do NOT touch listing.
    (src / "songs.rst").write_text(
        _song_block("Rock 95", "Nines", "rock", "1995")
        + "\n"
        + _song_block("Rock 05", "New", "rock", "2005"),
        encoding="utf-8",
    )
    build()  # incremental build reuses the doctree cache
    html2 = _read(out, "listing")
    # listing was re-resolved THIS build (env-updated returned it) and now shows
    # both songs, even though listing's source never changed.
    assert _container_region(html2).count("<li") == 2


def test_coercion_diagnostic_surfaced_as_warning(tmp_path):
    # `year > tags` compares a numeric year against a list -> safe_eval records
    # a coercion diagnostic that CHUNK-5-3 surfaces as a warning (the "silently
    # matched nothing" guard).
    docs = {
        "index": ".. toctree::\n\n   songs\n   listing\n",
        "songs": _song_block("Rock 95", "Nines", "rock, pop", "1995"),
        "listing": (
            "Listing\n=======\n\n"
            ".. song-list::\n   :filter: year > tags\n"
        ),
    }
    warnings = _warning_text(tmp_path, docs)
    assert "coercion note" in warnings


def test_query_docs_registered_on_env(tmp_path):
    docs = {
        "index": ".. toctree::\n\n   listing\n",
        "listing": "Listing\n=======\n\n.. song-list::\n",
    }
    app, out, _ = _build_html(tmp_path, docs)
    query_docs = getattr(app.env, QUERY_DOCS_ATTR, None)
    assert query_docs is not None
    assert "listing" in query_docs


# ---------------------------------------------------------------------------
# Alphabetical index (:style: index) — letter headings + page numbers (LaTeX)
# ---------------------------------------------------------------------------

def _build_latex(root: Path, docs: dict, extra_conf: str = ""):
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music"]\n'
        "doxtr_music_autoload_theme = False\n"
        + extra_conf
        + 'latex_documents = [("index", "s.tex", "S", "A", "manual")]\n',
        encoding="utf-8",
    )
    for docname, body in docs.items():
        (src / f"{docname}.rst").write_text(body, encoding="utf-8")
    out = root / "latex"
    app = Sphinx(
        srcdir=str(src), confdir=str(src), outdir=str(out),
        doctreedir=str(root / "dt"), buildername="latex",
        status=None, warning=None, freshenv=True,
    )
    app.build(force_all=True)
    return next(out.glob("*.tex")).read_text(encoding="utf-8")


_INDEX_DOCS = {
    "index": ".. toctree::\n\n   songs\n   idx\n",
    "songs": (
        _song_block("Apple Song", "X", "", "2001")
        + _song_block("Banana Tune", "Y", "", "2002")
    ),
    "idx": "Index\n=====\n\n.. song-index::\n   :style: index\n",
}


def test_latex_alpha_index_has_letters_and_pagerefs(tmp_path):
    tex = _build_latex(tmp_path, _INDEX_DOCS)
    # Letter headings for A and B (rubric -> a bold heading run).
    assert "Apple Song" in tex and "Banana Tune" in tex
    # Each entry: a hyperref title + a dotted leader + a hyperlinked page ref.
    assert "\\dotfill" in tex
    # Default format is the bare {page}: a \hyperref wrapping a \pageref* of
    # the song's label (the whole phrase links to the song's page).
    assert (
        "\\hyperref[\\detokenize{songs:apple-song}]"
        "{\\pageref*{\\detokenize{songs:apple-song}}}" in tex
    )
    assert (
        "\\hyperref[\\detokenize{songs:banana-tune}]"
        "{\\pageref*{\\detokenize{songs:banana-tune}}}" in tex
    )
    # And the song target labels exist so the page refs resolve.
    assert "\\label{\\detokenize{songs:apple-song}}" in tex
    assert "\\label{\\detokenize{songs:banana-tune}}" in tex


def test_latex_alpha_index_page_format_wraps_the_whole_link(tmp_path):
    # A custom "page {page}" format: the literal "page " text sits INSIDE the
    # single \hyperref, so the whole "page N" phrase links to the song page.
    tex = _build_latex(
        tmp_path,
        _INDEX_DOCS,
        extra_conf='doxtr_music_index_page_format = "page {page}"\n',
    )
    assert (
        "\\hyperref[\\detokenize{songs:apple-song}]"
        "{page \\pageref*{\\detokenize{songs:apple-song}}}" in tex
    )


def test_index_page_format_validation():
    from doxtr_music.config import (
        DEFAULT_INDEX_PAGE_FORMAT,
        validate_index_page_format,
    )

    warnings = []
    warn = lambda msg, *a: warnings.append(msg % a if a else msg)

    # Valid: exactly one {page}.
    assert validate_index_page_format("page {page}") == "page {page}"
    assert validate_index_page_format("{page}") == "{page}"
    # Invalid: missing {page}, an extra placeholder, or a non-string all fall
    # back to the default (with a warning for the malformed string cases).
    assert validate_index_page_format("no placeholder", warn) == DEFAULT_INDEX_PAGE_FORMAT
    assert validate_index_page_format("{page} {bogus}", warn) == DEFAULT_INDEX_PAGE_FORMAT
    assert validate_index_page_format("{page} {page}", warn) == DEFAULT_INDEX_PAGE_FORMAT
    assert validate_index_page_format(123, warn) == DEFAULT_INDEX_PAGE_FORMAT
    assert len(warnings) == 3  # the three malformed strings warned; 123 is silent


def test_index_page_format_and_escape_helpers():
    from doxtr_music.resolve import (
        _index_page_format,
        _latex_page_reference,
        _latex_text_escape,
    )

    class _Cfg:
        def __init__(self, val):
            self.doxtr_music_index_page_format = val

    class _App:
        def __init__(self, val):
            self.config = _Cfg(val)

    # Valid config value is returned; missing/invalid falls back to "{page}".
    assert _index_page_format(_App("page {page}")) == "page {page}"
    assert _index_page_format(_App(None)) == "{page}"
    assert _index_page_format(_App("no placeholder")) == "{page}"

    # Literal LaTeX specials in the format text are escaped (never injected).
    assert _latex_text_escape("p & #_%") == r"p \& \#\_\%"
    assert _latex_text_escape("") == ""

    # The whole formatted phrase is one \hyperref wrapping a \pageref* of the
    # detokenized label; the literal "page " prefix sits INSIDE the link.
    ref = _latex_page_reference(_App("page {page}"), "docs:my-song")
    assert ref == (
        r"\hyperref[\detokenize{docs:my-song}]"
        r"{page \pageref*{\detokenize{docs:my-song}}}"
    )


def test_html_alpha_index_groups_by_letter_no_pages(tmp_path):
    app, out, _ = _build_html(tmp_path, _INDEX_DOCS)
    html = _read(out, "idx")
    region = _container_region(html, "doxtr-song-index-alpha")
    assert region, "no alpha-index container"
    # Letter headings present (rubric class); titles linked; no "page" leader.
    assert "doxtr-song-index-letter" in region
    assert "Apple Song" in region and "Banana Tune" in region
    assert "autopageref" not in region  # LaTeX-only page refs never leak to HTML


def test_alpha_index_letter_bucketing():
    from doxtr_music.resolve import _index_letter

    assert _index_letter({"title": "Apple"}) == "A"
    assert _index_letter({"title": "banana"}) == "B"
    assert _index_letter({"title": "99 Luftballons"}) == "#"
    assert _index_letter({"title": ""}) == "#"
