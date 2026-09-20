"""Tests for the ``doxtr-music-convert`` CLI (CHUNK-6-3).

Invoke ``main(argv=[...])`` directly (stdin/file/-o/clipboard/version/exit-codes)
plus a runtime subprocess import test proving ``doxtr_music.cli`` imports without
Sphinx, and a ``[project.scripts]`` metadata check.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import doxtr_music
from doxtr_music import cli


# ---------------------------------------------------------------------------
# Conversion via stdin / file / -o
# ---------------------------------------------------------------------------

def test_stdin_conversion(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", _FakeStdin("C\nHello"))
    rc = cli.main(["--stdin"])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "[C]" in out and "Hello" in out


def test_default_reads_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", _FakeStdin("C\nHello"))
    rc = cli.main([])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "[C]Hello" in out


def test_file_conversion(tmp_path, capsys):
    src = tmp_path / "in.txt"
    src.write_text("C     G\nHello world", encoding="utf-8")
    rc = cli.main([str(src)])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "[C]" in out and "[G]" in out


def test_output_file(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin", _FakeStdin("C\nHello"))
    dst = tmp_path / "out.cho"
    rc = cli.main(["--stdin", "-o", str(dst)])
    assert rc == cli.EXIT_OK
    assert "[C]Hello" in dst.read_text(encoding="utf-8")


def test_unreadable_file_exit_1(capsys):
    rc = cli.main(["/no/such/file/here.txt"])
    err = capsys.readouterr().err
    assert rc == cli.EXIT_RUNTIME
    assert "error" in err and "cannot read file" in err


def test_utf8_roundtrip(tmp_path, capsys):
    src = tmp_path / "in.txt"
    src.write_text("C\nHëllo wörld", encoding="utf-8")
    rc = cli.main([str(src)])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "Hëllo" in out


# ---------------------------------------------------------------------------
# Clipboard (present via mock; absent → exit 3)
# ---------------------------------------------------------------------------

def test_clipboard_present(monkeypatch, capsys):
    fake = _FakePyperclip("C\nHello")
    monkeypatch.setitem(sys.modules, "pyperclip", fake)
    rc = cli.main(["--clipboard"])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "[C]Hello" in out


def test_clipboard_absent_exit_3(monkeypatch, capsys):
    # Simulate no pyperclip backend importable.
    monkeypatch.setitem(sys.modules, "pyperclip", None)
    rc = cli.main(["--clipboard"])
    err = capsys.readouterr().err
    assert rc == cli.EXIT_NO_CLIPBOARD
    assert "clipboard" in err


# ---------------------------------------------------------------------------
# Argument handling / exit codes / version
# ---------------------------------------------------------------------------

def test_mutually_exclusive_inputs_exit_2(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--stdin", "--clipboard"])
    assert exc.value.code == cli.EXIT_USAGE


def test_file_and_stdin_mutually_exclusive_exit_2():
    with pytest.raises(SystemExit) as exc:
        cli.main(["somefile.txt", "--stdin"])
    assert exc.value.code == cli.EXIT_USAGE


def test_version_prints_package_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert doxtr_music.__version__ in out


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "ChordPro" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Warnings drained to stderr
# ---------------------------------------------------------------------------

def test_parser_warnings_to_stderr(monkeypatch, capsys):
    # A chord past the end of a short lyric triggers a parser warning.
    monkeypatch.setattr("sys.stdin", _FakeStdin("            C\nHi"))
    rc = cli.main(["--stdin"])
    err = capsys.readouterr().err
    assert rc == cli.EXIT_OK
    assert "warning" in err


def test_literal_bracket_warning_to_stderr(monkeypatch, capsys):
    # A literal '[' in a lyric triggers the CLI's faithfulness note.
    monkeypatch.setattr("sys.stdin", _FakeStdin("see [later]"))
    rc = cli.main(["--stdin"])
    err = capsys.readouterr().err
    assert rc == cli.EXIT_OK
    assert "misinterpreted" in err


# ---------------------------------------------------------------------------
# No-Sphinx standalone import (runtime subprocess, authoritative)
# ---------------------------------------------------------------------------

def test_cli_imports_without_sphinx():
    """Importing doxtr_music.cli must not transitively import Sphinx."""
    code = (
        "import sys;"
        "sys.modules['sphinx'] = None;"  # any Sphinx import now raises
        "import doxtr_music.cli as c;"
        "print(c.main(['--stdin']) == 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        input="C\nHello",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("True")


def test_parsers_import_without_sphinx():
    code = (
        "import sys;"
        "sys.modules['sphinx'] = None;"
        "from doxtr_music.parsers.chordpro_serialize import tokens_to_chordpro;"
        "from doxtr_music.parsers.chordline import parse_chord_line;"
        "print(tokens_to_chordpro(*parse_chord_line('C\\nHello')).strip())"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "[C]Hello" in result.stdout


# ---------------------------------------------------------------------------
# Packaging: [project.scripts] entry present
# ---------------------------------------------------------------------------

def test_project_scripts_entry_present():
    import pathlib
    import tomllib

    root = pathlib.Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})
    assert scripts.get("doxtr-music-convert") == "doxtr_music.cli:main"


def test_clipboard_extra_declared():
    import pathlib
    import tomllib

    root = pathlib.Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data.get("project", {}).get("optional-dependencies", {})
    assert "clipboard" in extras
    assert any("pyperclip" in dep for dep in extras["clipboard"])
    # Must NOT be a hard dependency.
    assert not any("pyperclip" in dep for dep in data["project"].get("dependencies", []))


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeStdin:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text


class _FakePyperclip:
    def __init__(self, text):
        self._text = text

    def paste(self):
        return self._text
