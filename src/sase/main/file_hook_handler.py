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
from sase.file_hooks.audit import (
    FileHookAuditAmbiguousError,
    FileHookAuditNotFoundError,
    FileHookDispatchResult,
    list_file_hook_audits,
    load_file_hook_audit,
)


FILE_HOOK_LIST_JSON_SCHEMA_VERSION = 4
FILE_HOOK_HISTORY_JSON_SCHEMA_VERSION = 1


def _filter_text(hook: FileHookConfig) -> Text:
    text = Text()
    filters = hook.filters
    rows = (
        ("projects", filters.projects),
        ("sidecars", filters.sidecars),
        ("path_globs", filters.path_globs),
        ("agent_name_globs", filters.agent_name_globs),
        ("ops", filters.ops),
        ("producers", filters.producers),
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


def _audit_path_label(result: FileHookDispatchResult) -> str:
    for event in result.events:
        rel_path = event.get("rel_path")
        if isinstance(rel_path, str) and rel_path:
            return rel_path
    return "-"


def _history_limit(args: argparse.Namespace) -> int | None:
    limit = getattr(args, "limit", 20)
    if not isinstance(limit, int) or limit <= 0:
        return None
    return limit


def _handle_file_hook_history_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
) -> int:
    """Render recent producer audits."""
    records = list_file_hook_audits(limit=_history_limit(args))
    if args.json:
        print(
            json.dumps(
                {
                    "schema_version": FILE_HOOK_HISTORY_JSON_SCHEMA_VERSION,
                    "count": len(records),
                    "audits": [
                        item.to_payload() | {"audit_path": item.audit_path}
                        for item in records
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    output = console or Console()
    if not records:
        output.print("[dim]No file-hook producer audits recorded.[/dim]")
        return 0

    table = Table(
        title="File-Hook Producer History",
        expand=True,
        header_style="bold",
        show_lines=False,
    )
    table.add_column("Time", min_width=19, no_wrap=True)
    table.add_column("Outcome", min_width=16, overflow="fold")
    table.add_column("Producer", min_width=10, no_wrap=True)
    table.add_column("File", ratio=2, overflow="fold")
    table.add_column("Hooks", ratio=1, overflow="fold")
    table.add_column("Audit", min_width=12, overflow="fold")
    for item in records:
        outcome_style = "red" if item.outcome == "producer_error" else "cyan"
        table.add_row(
            item.created_at[:19] if item.created_at else "-",
            Text(item.outcome, style=outcome_style),
            item.producer,
            _audit_path_label(item),
            ", ".join(item.matched_hook_names) or "-",
            item.audit_id,
        )
    output.print(table)
    return 0


def _handle_file_hook_show_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
) -> int:
    """Render one producer audit in full."""
    try:
        result = load_file_hook_audit(args.audit_id)
    except FileHookAuditNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except FileHookAuditAmbiguousError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    payload = result.to_payload()
    payload["audit_path"] = result.audit_path
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    output = console or Console()
    output.print(f"[bold cyan]{result.audit_id}[/bold cyan]  {result.outcome}")
    rows = (
        ("producer", result.producer),
        ("created_at", result.created_at or "-"),
        ("commit_sha", result.commit_sha or "-"),
        ("repository", result.repo_root or "-"),
        ("sidecar", result.sidecar_role or "-"),
        ("agent", result.agent_name or "-"),
        ("project", result.project or "-"),
        ("hooks", ", ".join(result.matched_hook_names) or "-"),
        ("configured_hooks", str(result.configured_hook_count)),
        ("batch", result.batch_id or "-"),
        ("batch_path", result.batch_path or "-"),
        ("error", result.error or "-"),
        ("audit_path", result.audit_path or "-"),
    )
    for label, value in rows:
        output.print(f"[dim]{label}:[/dim] {value}")
    if result.events:
        output.print("[dim]events:[/dim]")
        for event in result.events:
            rel_path = event.get("rel_path") or event.get("abs_path") or "-"
            op = event.get("op") or "-"
            output.print(f"  {op} {rel_path}")
    return 0


def handle_file_hook_command(args: argparse.Namespace) -> None:
    """Dispatch a ``sase file-hook`` subcommand."""
    subcommand = getattr(args, "file_hook_subcommand", None)
    if subcommand == "exec-batch":
        from sase.file_hooks.runner import execute_batch

        sys.exit(execute_batch(args.batch))
    if subcommand == "history":
        sys.exit(_handle_file_hook_history_command(args))
    if subcommand == "list":
        sys.exit(_handle_file_hook_list_command(args))
    if subcommand == "show":
        sys.exit(_handle_file_hook_show_command(args))

    print("Usage: sase file-hook {history,list,show}")
    sys.exit(1)


__all__ = [
    "FILE_HOOK_HISTORY_JSON_SCHEMA_VERSION",
    "FILE_HOOK_LIST_JSON_SCHEMA_VERSION",
    "handle_file_hook_command",
]
