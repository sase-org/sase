"""Handler for the `sase comments` CLI command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import ValidationError, validate  # type: ignore[import-untyped]
from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text

from sase.ace.mentor_output import MENTOR_OUTPUT_JSON_SCHEMA
from sase.ace.tui.modals.mentor_review_models import lexer_for_path

_SEVERITY_STYLE: dict[str, str] = {
    "error": "bold red",
    "warning": "bold yellow",
    "suggestion": "bold #87D7FF",
}


def handle_comments_command(args: argparse.Namespace) -> None:
    """Entry point for ``sase comments``."""
    data = _load_comments_json(args)
    comments = data["comments"]
    if not comments:
        print("No comments.")
        sys.exit(0)

    missing = _render_comments(comments, args.context)
    sys.exit(2 if missing else 0)


def _load_comments_json(args: argparse.Namespace) -> dict:
    """Read and validate comments JSON from file or stdin."""
    if args.file:
        path = Path(args.file)
        if not path.is_file():
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        raw = path.read_text(encoding="utf-8")
    elif sys.stdin.isatty():
        print(
            "Error: no input. Pipe JSON via stdin or pass a file path.\n"
            "Usage: sase comments [file]  or  cat comments.json | sase comments",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        raw = sys.stdin.read()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        validate(instance=data, schema=MENTOR_OUTPUT_JSON_SCHEMA)
    except ValidationError as exc:
        print(f"Error: schema validation failed: {exc.message}", file=sys.stderr)
        sys.exit(1)

    return data


def _render_comments(comments: list[dict], context_lines: int) -> bool:
    """Render all comments. Returns True if any referenced files were missing."""
    console = Console()
    total = len(comments)
    any_missing = False

    for idx, comment in enumerate(comments):
        missing = _render_single_comment(console, comment, idx, total, context_lines)
        if missing:
            any_missing = True
        if idx < total - 1:
            console.print()

    return any_missing


def _render_single_comment(
    console: Console,
    comment: dict,
    index: int,
    total: int,
    context_lines: int,
) -> bool:
    """Render one comment mirroring the TUI layout. Returns True if file was missing."""
    text = Text()

    # Header
    text.append(f" Comment {index + 1}/{total}", style="bold white")
    text.append("\n")
    text.append(" " + "\u2500" * 40 + "\n", style="dim #87D7FF")

    # Focus and severity
    text.append("  Focus: ", style="dim")
    text.append(str(comment["focus_name"]), style="bold #87D7FF")
    text.append("    Severity: ", style="dim")
    severity = str(comment["severity"])
    text.append(severity, style=_SEVERITY_STYLE.get(severity, ""))
    text.append("\n")

    # File path
    text.append("  File: ", style="dim")
    text.append(
        f"{comment['file_path']}:{comment['line_number']}", style="bold #00D7AF"
    )
    text.append("\n\n")

    # Description
    for line in str(comment["description"]).split("\n"):
        text.append(f"  {line}\n")

    console.print(text, end="")

    # Code snippet
    snippet, missing = _build_code_snippet(
        comment["file_path"], comment["line_number"], context_lines
    )
    if snippet is not None:
        console.print(snippet)
    elif missing:
        console.print(
            f"  [dim yellow]Warning: file not found: {comment['file_path']}[/]"
        )

    return missing


def _build_code_snippet(
    file_path: str, line_number: int, context_lines: int
) -> tuple[Syntax | None, bool]:
    """Read a file and return a Rich Syntax object centered on line_number.

    Returns (Syntax, False) on success, (None, True) if the file is missing,
    or (None, False) if the file is empty.
    """
    path = Path(file_path)
    if not path.is_file():
        return None, True

    content = path.read_text(encoding="utf-8", errors="replace")
    if not content:
        return None, False

    total_lines = content.count("\n") + 1
    line_number = max(1, min(line_number, total_lines))

    lexer = lexer_for_path(file_path)

    max_lines = context_lines * 2 + 1
    half = max_lines // 2
    start = max(1, line_number - half)
    end = min(total_lines, start + max_lines - 1)
    start = max(1, end - max_lines + 1)

    return (
        Syntax(
            content,
            lexer,
            theme="monokai",
            line_numbers=True,
            line_range=(start, end),
            highlight_lines={line_number},
            word_wrap=True,
        ),
        False,
    )
