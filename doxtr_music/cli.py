"""``doxtr-music-convert`` — chords-over-lyrics → inline ChordPro CLI.

A standalone terminal utility (no Sphinx import) that converts monospaced
"chords-over-lyrics" text (Ultimate-Guitar style) into inline ChordPro suitable
for pasting into a ``.. song::`` directive. Conversion is exactly

    parse_chord_line(text) -> tokens_to_chordpro(tokens, song_meta)

— it re-implements no line classification, chord↔lyric pairing, tab handling or
column math (all inherited from CHUNK-3-1's pure ``parse_chord_line``) and
hand-rolls no ChordPro emission (owned by the ``tokens_to_chordpro`` authority,
CHUNK-6-3).

Standalone guarantee (LOCKED — cross-chunk with CHUNK-0-1): importing
``doxtr_music.cli`` (and the pure ``parsers/`` layer) must not transitively
import Sphinx via the package ``__init__``, which defers all Sphinx imports into
``setup()``. A runtime subprocess import test (Sphinx un-importable) enforces
this.

Exit codes (LOCKED): ``0`` success; ``1`` runtime failure (unreadable/malformed
input); ``2`` usage/bad args (argparse convention); ``3`` no clipboard backend.
All errors surface as a friendly ``stderr`` message, never a stack trace.
"""

from __future__ import annotations

import argparse
import sys

from doxtr_music import __version__

__all__ = ["main"]

_PROG = "doxtr-music-convert"

# Exit-code taxonomy (LOCKED).
EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2  # argparse also uses 2 for its own usage errors
EXIT_NO_CLIPBOARD = 3


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser with a mutually-exclusive input group."""
    parser = argparse.ArgumentParser(
        prog=_PROG,
        description=(
            "Convert monospaced chords-over-lyrics text into inline ChordPro "
            "for pasting into a Sphinx .. song:: directive."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%s %s" % (_PROG, __version__),
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "file",
        nargs="?",
        help="input file to read (UTF-8); omit to read stdin",
    )
    group.add_argument(
        "--stdin",
        action="store_true",
        help="read input from standard input",
    )
    group.add_argument(
        "--clipboard",
        action="store_true",
        help="read input from the system clipboard (requires the 'clipboard' extra)",
    )

    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="write ChordPro to FILE (UTF-8); default is stdout",
    )
    return parser


def main(argv=None) -> int:
    """Entry point: ``argv=None`` uses ``sys.argv[1:]``. Returns an exit code.

    Reads the source text (file / stdin / clipboard), converts it via
    ``parse_chord_line -> tokens_to_chordpro``, drains any parser warnings to
    stderr, and writes the ChordPro output. Never raises past this boundary — a
    failure returns a non-zero code with a friendly stderr message.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --- read input --------------------------------------------------------
    try:
        text = _read_input(args)
    except _CLIError as exc:
        print("%s: error: %s" % (_PROG, exc), file=sys.stderr)
        return exc.code

    # --- convert (pure parser + pure serializer) ---------------------------
    try:
        from doxtr_music.parsers.chordline import parse_chord_line
        from doxtr_music.parsers.chordpro_serialize import (
            has_literal_brackets,
            tokens_to_chordpro,
        )

        tokens, song_meta = parse_chord_line(text)
        chordpro = tokens_to_chordpro(tokens, song_meta)
        literal_bracket_warn = has_literal_brackets(tokens)
    except Exception as exc:  # noqa: BLE001 - convert must never dump a traceback
        print("%s: error: could not convert input: %s" % (_PROG, exc),
              file=sys.stderr)
        return EXIT_RUNTIME

    # --- drain parser warnings to stderr (analog of drain_warnings) --------
    for line_no, message in song_meta.get("_warnings", []):
        print("%s: warning: line %s: %s" % (_PROG, line_no, message),
              file=sys.stderr)

    # Literal-bracket faithfulness note (CHUNK-6-3 Option B): the forward
    # ChordPro parser has no backslash de-escape, so a literal '[' / '{' in a
    # lyric may be misread as a chord/directive when pasted into .. song::.
    if literal_bracket_warn:
        print(
            "%s: warning: literal brackets/braces in lyric text may be "
            "misinterpreted as chords/directives; review the output" % _PROG,
            file=sys.stderr,
        )

    # --- write output ------------------------------------------------------
    try:
        _write_output(args, chordpro)
    except _CLIError as exc:
        print("%s: error: %s" % (_PROG, exc), file=sys.stderr)
        return exc.code

    return EXIT_OK


class _CLIError(Exception):
    """A friendly CLI failure carrying an exit ``code``."""

    def __init__(self, message: str, code: int = EXIT_RUNTIME):
        super().__init__(message)
        self.code = code


def _read_input(args) -> str:
    """Read the source text from the selected input (file / stdin / clipboard).

    Precedence (inputs are a mutually-exclusive argparse group, so at most one is
    set): ``--clipboard`` → clipboard; a positional ``file`` → that file;
    ``--stdin`` or nothing → standard input (UTF-8).
    """
    if args.clipboard:
        return _read_clipboard()
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            raise _CLIError("cannot read file %r: %s" % (args.file, exc.strerror),
                            EXIT_RUNTIME)
    # stdin (explicit --stdin or default).
    data = sys.stdin.read()
    return data


def _read_clipboard() -> str:
    """Read text from the system clipboard via the optional ``pyperclip`` backend.

    ``pyperclip`` is an optional extra (``doxtr-music[clipboard]``), never a hard
    dependency. Missing backend → :class:`_CLIError` with exit code ``3``.
    """
    try:
        import pyperclip  # type: ignore
    except ImportError:
        raise _CLIError(
            "clipboard input requires the 'clipboard' extra; install it with "
            "`pip install doxtr-music[clipboard]`",
            EXIT_NO_CLIPBOARD,
        )
    try:
        return pyperclip.paste() or ""
    except Exception as exc:  # noqa: BLE001 - backend errors → friendly message
        raise _CLIError("could not read clipboard: %s" % exc, EXIT_NO_CLIPBOARD)


def _write_output(args, chordpro: str) -> None:
    """Write ``chordpro`` to ``-o FILE`` (UTF-8) or stdout."""
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(chordpro)
        except OSError as exc:
            raise _CLIError("cannot write file %r: %s" % (args.output, exc.strerror),
                            EXIT_RUNTIME)
    else:
        sys.stdout.write(chordpro)


if __name__ == "__main__":  # pragma: no cover - module CLI entry
    sys.exit(main())
