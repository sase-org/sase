"""Handler implementation for the ``sase file-hook`` command group."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import asdict
import json
import sys

from rich.console import Console
from rich.table import Table
from rich.text import Text

from sase.config.file_hooks import FileHookConfig, get_all_file_hooks


FILE_HOOK_LIST_JSON_SCHEMA_VERSION = 1


def _filter_text(hook: FileHookConfig) -> Text:
    text = Text()
    rows = (
        ("projects", hook.projects),
        ("sidecars", hook.sidecars),
        ("globs", hook.globs),
        ("ops", hook.ops),
    )
    for index, (label, values) in enumerate(rows):
        if index:
            text.append("\n")
        text.append(f"{label}: ", style="dim")
        text.append(", ".join(values) if values else "*")
    return text


def _format_timeout(seconds: float) -> str:
    if seconds < 1 and seconds:
        return f"{seconds * 1000:g}ms"
    return f"{seconds:g}s"


def _json_payload(hooks: Sequence[FileHookConfig]) -> dict[str, object]:
    return {
        "schema_version": FILE_HOOK_LIST_JSON_SCHEMA_VERSION,
        "count": len(hooks),
        "file_hooks": [asdict(hook) for hook in hooks],
    }


def _handle_file_hook_list_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    hooks_fn: Callable[[], list[FileHookConfig]] = get_all_file_hooks,
) -> int:
    """Render the effective file-hook inventory."""
    hooks = hooks_fn()
    if args.json:
        print(json.dumps(_json_payload(hooks), indent=2, sort_keys=True))
        return 0

    output = console or Console()
    if not hooks:
        output.print("[dim]No file hooks configured.[/dim]")
        return 0

    table = Table(
        title="File Hooks",
        expand=True,
        header_style="bold",
        show_lines=True,
    )
    table.add_column("Name", min_width=14, overflow="fold")
    table.add_column("Source", min_width=10, overflow="fold")
    table.add_column("Command", ratio=2, overflow="fold")
    table.add_column("Filters", ratio=2, overflow="fold")
    table.add_column("Timeout", justify="right", no_wrap=True)
    table.add_column("Description", ratio=2, overflow="fold")

    for hook in hooks:
        table.add_row(
            Text(hook.name, style="bold cyan"),
            Text(hook.source_layer, style="magenta"),
            hook.command,
            _filter_text(hook),
            _format_timeout(hook.timeout_seconds),
            hook.description or "-",
        )
    output.print(table)
    return 0


def handle_file_hook_command(args: argparse.Namespace) -> None:
    """Dispatch a ``sase file-hook`` subcommand."""
    if getattr(args, "file_hook_subcommand", None) == "exec-batch":
        from sase.file_hooks.runner import execute_batch

        sys.exit(execute_batch(args.batch))
    if getattr(args, "file_hook_subcommand", None) == "list":
        sys.exit(_handle_file_hook_list_command(args))

    print("Usage: sase file-hook {list}")
    sys.exit(1)


__all__ = [
    "FILE_HOOK_LIST_JSON_SCHEMA_VERSION",
    "handle_file_hook_command",
]
