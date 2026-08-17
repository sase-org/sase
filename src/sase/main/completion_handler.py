"""Handler implementation for the ``sase completion`` CLI subcommand."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text


@dataclass(frozen=True, slots=True)
class _ShellRow:
    """One row of ``sase completion list``. Extra columns land in install."""

    shell: str
    generator: bool
    status: str


# Install later extends these rows with path, `.zwc` freshness, and stamp.
_SHELL_ROWS: tuple[_ShellRow, ...] = (
    _ShellRow("bash", False, "pending"),
    _ShellRow("fish", False, "pending"),
    _ShellRow("zsh", True, "not installed"),
)


def handle_completion_command(args: argparse.Namespace) -> int:
    """Dispatch a parsed ``sase completion ...`` command."""
    sub = getattr(args, "completion_subcommand", None) or "list"
    if sub == "list":
        return _handle_completion_list(args)
    if sub == "spec":
        return _handle_completion_spec(args)
    if sub == "zsh":
        return _handle_completion_zsh(args)
    print("Usage: sase completion {list,spec,zsh}", file=sys.stderr)
    return 2


def _handle_completion_list(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    rows: Sequence[_ShellRow] | None = None,
) -> int:
    """Run ``sase completion list``."""
    resolved = _SHELL_ROWS if rows is None else tuple(rows)
    if bool(getattr(args, "json", False)):
        print(json.dumps(_list_json(resolved), indent=2, sort_keys=True))
        return 0
    _render_list(resolved, console=console or Console(highlight=False))
    return 0


def _handle_completion_spec(args: argparse.Namespace) -> int:
    """Run ``sase completion spec``."""
    from sase.completion.snapshot import current_structural_view

    text = json.dumps(current_structural_view(), indent=2, sort_keys=True)
    return _write_output(getattr(args, "output", None), text)


def _handle_completion_zsh(args: argparse.Namespace) -> int:
    """Run ``sase completion zsh``."""
    from sase.completion.build import build_spec
    from sase.completion.emit_zsh import emit_zsh

    return _write_output(getattr(args, "output", None), emit_zsh(build_spec()))


def _list_json(rows: Sequence[_ShellRow]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "shells": [
            {
                "generator": row.generator,
                "shell": row.shell,
                "status": row.status,
            }
            for row in rows
        ],
    }


def _render_list(rows: Sequence[_ShellRow], *, console: Console) -> None:
    table = Table(
        box=None,
        expand=False,
        pad_edge=False,
        show_edge=False,
        header_style="bold",
    )
    table.add_column("SHELL", no_wrap=True)
    table.add_column("GENERATOR", no_wrap=True)
    table.add_column("STATUS", no_wrap=True)
    for row in rows:
        table.add_row(
            Text(row.shell, style="bold"),
            Text("yes", style="green") if row.generator else Text("no", style="dim"),
            Text(row.status, style="green" if row.generator else "dim"),
        )
    console.print(table)


def _write_output(path: str | None, text: str) -> int:
    payload = text if text.endswith("\n") else f"{text}\n"
    if not path:
        sys.stdout.write(payload)
        return 0
    try:
        Path(path).write_text(payload, encoding="utf-8")
    except OSError as exc:
        print(f"sase completion: cannot write {path}: {exc}", file=sys.stderr)
        return 1
    return 0


__all__ = ["handle_completion_command"]
