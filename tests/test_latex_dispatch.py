"""Tests for CHUNK-2-1 — LaTeX/PDF foundation + bridge dispatcher + preamble seam.

Covers the exit criteria:

* Backend selection (``songs``/``songbook``/unknown → fallback) + ``.tex_t``
  rendered via Sphinx's ``LaTeXRenderer``.
* LaTeX escaping (parametrized specials incl. ``#``, ``\\`` first, ``~``/``^``).
* ``\\dmneedspace`` emission + ``\\usepackage{needspace}`` present.
* Preamble seam idempotency (double ``config-inited`` doesn't double-inject).
* Backend-neutral macro emission (no ``\\beginverse`` in visitor output).
* Write-only ``-b latex`` integration build (marked).
* Real ``pdflatex`` compile of the emitted ``.tex`` (marked ``latex``).
* package-data wheel check (marked ``slow``, gateable).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

from doxtr_music import latex_escape
from doxtr_music.builders import latex as dm_latex

sphinx = pytest.importorskip("sphinx")
from sphinx.application import Sphinx  # noqa: E402


# ---------------------------------------------------------------------------
# LaTeX escaping (own escaper, no core import)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("F#m7b5", r"F\#m7b5"),
        ("C&", r"C\&"),
        ("A_b", r"A\_b"),
        ("50%", r"50\%"),
        ("$C", r"\$C"),
        ("{C}", r"\{C\}"),
        ("a~b", r"a\textasciitilde{}b"),
        ("a^b", r"a\textasciicircum{}b"),
        # Backslash escaped first: the introduced backslashes are not re-escaped.
        ("a\\b", r"a\textbackslash{}b"),
    ],
)
def test_esc_latex_specials(raw, expected):
    assert latex_escape.esc_latex(raw) == expected


def test_esc_latex_empty_and_none():
    assert latex_escape.esc_latex("") == ""
    assert latex_escape.esc_latex(None) == ""


def test_esc_latex_no_core_import():
    """The escaper must not import doxtr_pdf_theme_core (soft dependency)."""
    src = Path(latex_escape.__file__).read_text(encoding="utf-8")
    assert "doxtr_pdf_theme_core" not in src


def test_latex_builder_no_core_import():
    src = Path(dm_latex.__file__).read_text(encoding="utf-8")
    assert "import doxtr_pdf_theme_core" not in src
    assert "from doxtr_pdf_theme_core" not in src


# ---------------------------------------------------------------------------
# Backend selection + .tex_t resolution
# ---------------------------------------------------------------------------

class _Cfg:
    """Minimal config stand-in for the resolver/seam unit tests."""

    def __init__(self, package="songbook", path=None):
        self.doxtr_music_latex_package = package
        self.doxtr_music_latex_backend_path = path
        self.latex_elements = {}


def test_resolve_ships_all_backends():
    assert dm_latex.resolve_backend_template("songbook") is not None
    assert dm_latex.resolve_backend_template("songs") is not None
    assert dm_latex.resolve_backend_template("preamble") is not None


def test_resolve_unknown_returns_none():
    assert dm_latex.resolve_backend_template("does-not-exist") is None


def test_select_backend_songs():
    assert dm_latex._select_backend(_Cfg(package="songs")) == "songs"


def test_select_backend_songbook():
    assert dm_latex._select_backend(_Cfg(package="songbook")) == "songbook"


def test_select_backend_unknown_falls_back(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        chosen = dm_latex._select_backend(_Cfg(package="totally-bogus"))
    assert chosen == dm_latex.DEFAULT_BACKEND
    assert "Unknown LaTeX backend" in caplog.text


def test_override_dir_takes_precedence(tmp_path):
    """A user override dir supplies a .tex_t ahead of the packaged one."""
    (tmp_path / "songs.tex_t").write_text("% override songs\n", encoding="utf-8")
    resolved = dm_latex.resolve_backend_template(
        "songs", _Cfg(package="songs", path=str(tmp_path))
    )
    assert resolved == str((tmp_path / "songs.tex_t").resolve())


def test_tex_t_rendered_via_latexrenderer():
    """The backend fragment is produced through the LaTeXRenderer path."""
    fragment = dm_latex.render_backend_fragment("songbook", _Cfg(package="songbook"))
    assert "\\usepackage" in fragment
    assert "songbook" in fragment
    # Backend-neutral section macros are defined by the fragment.
    assert "\\dmsectionbegin" in fragment


# ---------------------------------------------------------------------------
# Preamble-injection seam
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_preamble_registry():
    """Isolate the module-level contributor registry per test."""
    saved = list(dm_latex._LATEX_PREAMBLE_CONTRIBUTORS)
    dm_latex._LATEX_PREAMBLE_CONTRIBUTORS.clear()
    yield
    dm_latex._LATEX_PREAMBLE_CONTRIBUTORS[:] = saved


def test_assemble_orders_by_priority():
    dm_latex.register_preamble_contributor(300, lambda cfg: "THIRD")
    dm_latex.register_preamble_contributor(100, lambda cfg: "FIRST")
    dm_latex.register_preamble_contributor(200, lambda cfg: "SECOND")
    out = dm_latex.assemble_latex_preamble(_Cfg())
    assert out.index("FIRST") < out.index("SECOND") < out.index("THIRD")


def test_assemble_skips_empty_contributions():
    dm_latex.register_preamble_contributor(100, lambda cfg: "")
    dm_latex.register_preamble_contributor(200, lambda cfg: "REAL")
    out = dm_latex.assemble_latex_preamble(_Cfg())
    assert out.strip() == "REAL"


def test_backend_contributor_has_needspace_and_macros():
    dm_latex.register_preamble_contributor(
        200, dm_latex._backend_preamble_contributor
    )
    out = dm_latex.assemble_latex_preamble(_Cfg(package="songbook"))
    assert "\\usepackage{needspace}" in out
    assert "\\dmneedspace" in out
    assert "\\dmchord" in out
    assert "\\dmsinger" in out
    assert dm_latex.PREAMBLE_SENTINEL in out


def test_preamble_injection_is_idempotent():
    dm_latex.register_preamble_contributor(
        200, dm_latex._backend_preamble_contributor
    )
    cfg = _Cfg(package="songbook")
    dm_latex._on_config_inited_preamble(None, cfg)
    first = cfg.latex_elements["preamble"]
    dm_latex._on_config_inited_preamble(None, cfg)
    second = cfg.latex_elements["preamble"]
    assert first == second
    assert first.count(dm_latex.PREAMBLE_SENTINEL) == 1


def test_preamble_injection_uses_setdefault_no_keyerror():
    """An unset latex_elements['preamble'] must not KeyError."""
    dm_latex.register_preamble_contributor(
        200, dm_latex._backend_preamble_contributor
    )
    cfg = _Cfg(package="songbook")
    assert "preamble" not in cfg.latex_elements
    dm_latex._on_config_inited_preamble(None, cfg)  # must not raise
    assert "preamble" in cfg.latex_elements


# ---------------------------------------------------------------------------
# Write-only -b latex integration build
# ---------------------------------------------------------------------------

_SONG_RST = textwrap.dedent(
    """
    Title
    =====

    .. song::

       {title: My Song}
       {start_of_verse}
       [Am]Hello [C]world
       {end_of_verse}
       [F#m7b5]Weird [C&]stuff
    """
)


def test_render_line_flow_space_survives_after_chord_word():
    r"""A chord word followed by a plain lyric word keeps an interword space.

    Regression: a chord word renders with a trailing color-group ``\endgroup``,
    and TeX silently swallows a space that immediately follows a control word
    — gluing "Swing low" into "Swinglow". The interword gap must be protected
    (prefixed with an empty group ``{}``) so the space is never eaten.
    """
    # "Swing" (col 0) sits over a chord; "low" (col 6) is a plain lyric word.
    buf = {
        "chords": [(0, "C", "#112233", None)],
        "lyrics": [(0, "Swing", None, None), (6, "low", None, None)],
    }
    out = dm_latex._render_line_flow(buf)
    # The chord word ends its color group with \endgroup; the interword gap is
    # shielded by an empty group {} so the following space is not swallowed.
    assert "\\endgroup {} \\dmlyric{low}" in out
    # And the two words never appear glued together.
    assert "Swinglow" not in out


def _build_latex(root: Path, package="songbook") -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music"]\n'
        # Compile our backend standalone under pdflatex: do NOT auto-load
        # doxtr-pdf-theme-core (it targets lualatex via fontspec/polyglossia).
        'doxtr_music_autoload_theme = False\n'
        'doxtr_music_latex_package = "%s"\n'
        'latex_documents = [("index", "s.tex", "S Doc", "A", "manual")]\n'
        % package,
        encoding="utf-8",
    )
    (src / "index.rst").write_text(_SONG_RST, encoding="utf-8")
    out = root / "out"
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(root / "dt"),
        buildername="latex",
        freshenv=True,
    )
    app.build(force_all=True)
    return out / "s.tex"


def test_latex_build_emits_backend_and_needspace(tmp_path):
    tex = _build_latex(tmp_path).read_text(encoding="utf-8")
    # Exit #1: backend package + needspace usepackage + \dmchord macros.
    assert "\\usepackage[chordbk]{songbook}" in tex
    assert "\\usepackage{needspace}" in tex
    assert "\\dmchord{Am}{Hello}" in tex
    # Exit #3: \dmneedspace guard emitted before each song/section block.
    assert "\\dmneedspace" in tex
    # Exit #9: backend-neutral macros only — never package-native \beginverse.
    assert "\\beginverse" not in tex
    assert "\\dmsectionbegin{verse}{Verse}" in tex
    # kind="none" top-level content handled via \dmsectionbegin{none}.
    assert "\\dmsectionbegin{none}" in tex
    # Exit #4: chord specials escaped in content args.
    assert "\\dmchord{F\\#m7b5}" in tex
    assert "\\dmchord{C\\&}" in tex
    # Provenance meta is HTML-only: absent here (not a parity gap).
    assert "doxtr-music" not in tex or "% doxtr-music" in tex


def test_latex_build_routes_songs_backend(tmp_path):
    tex = _build_latex(tmp_path, package="songs").read_text(encoding="utf-8")
    assert "\\usepackage{songs}" in tex
    assert "\\usepackage[chordbk]{songbook}" not in tex


def test_latex_build_unknown_backend_falls_back(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        'project = "s"\nauthor = "s"\n'
        'extensions = ["doxtr_music"]\n'
        'doxtr_music_latex_package = "nope"\n'
        'latex_documents = [("index", "s.tex", "S", "A", "manual")]\n',
        encoding="utf-8",
    )
    (src / "index.rst").write_text(_SONG_RST, encoding="utf-8")
    out = tmp_path / "out"
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(tmp_path / "dt"),
        buildername="latex",
        freshenv=True,
    )
    app.build(force_all=True)
    tex = (out / "s.tex").read_text(encoding="utf-8")
    assert "\\usepackage[chordbk]{songbook}" in tex  # fell back to default


# ---------------------------------------------------------------------------
# Real pdflatex compile (marked; needs a TeX toolchain)
# ---------------------------------------------------------------------------

@pytest.mark.latex
@pytest.mark.skipif(
    shutil.which("pdflatex") is None, reason="pdflatex not available"
)
@pytest.mark.parametrize("package", ["songbook", "songs"])
def test_latex_tex_compiles_to_pdf(tmp_path, package):
    tex_path = _build_latex(tmp_path, package=package)
    out = tex_path.parent
    result = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "s.tex"],
        cwd=str(out),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-3000:]
    assert (out / "s.pdf").exists()


# ---------------------------------------------------------------------------
# package-data wheel check (slow, gateable)
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.skipif(
    importlib.util.find_spec("build") is None,
    reason="`build` not installed",
)
def test_wheel_ships_latex_backends(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    wheels = list(tmp_path.glob("*.whl"))
    assert wheels, "no wheel built"
    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
    assert any(n.endswith("latex_backends/preamble.tex_t") for n in names)
    assert any(n.endswith("latex_backends/songbook.tex_t") for n in names)
    assert any(n.endswith("latex_backends/songs.tex_t") for n in names)
