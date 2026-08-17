"""Handler implementation for the ``sase completion`` CLI subcommand."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from sase.completion.install import (
    RECOMMENDED_ZSTYLE,
    CompletionInstallError,
    InstallResult,
    InstallStep,
    ShellInstallStatus,
    install_completion,
    list_shell_statuses,
)
from sase.completion.install_targets import CannotDetectShell
from sase.completion.model import CompletionSpec


def handle_completion_command(args: argparse.Namespace) -> int:
    """Dispatch a parsed ``sase completion ...`` command."""
    sub = getattr(args, "completion_subcommand", None) or "list"
    if sub == "bash":
        return _handle_completion_bash(args)
    if sub == "candidates":
        return _handle_completion_candidates(args)
    if sub == "fish":
        return _handle_completion_fish(args)
    if sub == "install":
        return _handle_completion_install(args)
    if sub == "list":
        return _handle_completion_list(args)
    if sub == "spec":
        return _handle_completion_spec(args)
    if sub == "zsh":
        return _handle_completion_zsh(args)
    print(
        "Usage: sase completion {bash,candidates,fish,install,list,spec,zsh}",
        file=sys.stderr,
    )
    return 2


def _handle_completion_candidates(args: argparse.Namespace) -> int:
    """Run ``sase completion candidates`` through the normal argparse path.

    The pre-argparse fast path in ``completion_fast_path.py`` handles every
    normal invocation before argparse ever runs. Reaching this handler means
    the fast path deferred -- ``--help`` or an argv shape its hand-rolled
    parser does not recognize -- so this stays a thin, correct fallback
    rather than a second latency-critical path.
    """
    from sase.completion.candidates.protocol import render_candidates
    from sase.completion.candidates.providers import candidates_for

    candidates = candidates_for(
        str(args.kind),
        str(getattr(args, "prefix", "") or ""),
        project=getattr(args, "project", None),
        limit=int(args.limit),
    )
    output = render_candidates(candidates)
    if output:
        print(output)
    return 0


def _handle_completion_list(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    rows: Sequence[ShellInstallStatus] | None = None,
) -> int:
    """Run ``sase completion list``."""
    resolved = list_shell_statuses() if rows is None else tuple(rows)
    if bool(getattr(args, "json", False)):
        print(json.dumps(_list_json(resolved), indent=2, sort_keys=True))
        return 0
    _render_list(resolved, console=console or Console(highlight=False))
    return 0


def _handle_completion_install(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    install_fn: Callable[..., InstallResult] | None = None,
) -> int:
    """Run ``sase completion install``."""
    out = console or Console(highlight=False)
    try:
        result = (install_fn or install_completion)(
            requested=getattr(args, "shell", None),
            dry_run=bool(getattr(args, "dry_run", False)),
            force=bool(getattr(args, "force", False)),
            target=getattr(args, "target", None),
        )
    except CannotDetectShell as exc:
        print(f"sase completion install: {exc}", file=sys.stderr)
        return 1
    except CompletionInstallError as exc:
        print(f"sase completion install: {exc}", file=sys.stderr)
        return 1
    _render_install(result, console=out)
    return result.exit_code


def _handle_completion_spec(args: argparse.Namespace) -> int:
    """Run ``sase completion spec``."""
    from sase.completion.snapshot import current_structural_view

    text = json.dumps(current_structural_view(), indent=2, sort_keys=True)
    return _write_output(getattr(args, "output", None), text)


def _handle_completion_bash(args: argparse.Namespace) -> int:
    """Run ``sase completion bash``."""
    from sase.completion.emit_bash import emit_bash

    return _handle_completion_script(args, emit_bash)


def _handle_completion_fish(args: argparse.Namespace) -> int:
    """Run ``sase completion fish``."""
    from sase.completion.emit_fish import emit_fish

    return _handle_completion_script(args, emit_fish)


def _handle_completion_zsh(args: argparse.Namespace) -> int:
    """Run ``sase completion zsh``."""
    from sase.completion.emit_zsh import emit_zsh

    return _handle_completion_script(args, emit_zsh)


def _handle_completion_script(
    args: argparse.Namespace, emit: Callable[[CompletionSpec], str]
) -> int:
    from sase.completion.build import build_spec

    return _write_output(getattr(args, "output", None), emit(build_spec()))


def _list_json(rows: Sequence[ShellInstallStatus]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "shells": [
            {
                "generator": row.generator,
                "path": row.path,
                "shell": row.shell,
                "stamp_version": row.stamp_version,
                "status": row.status,
                "zwc": row.zwc,
            }
            for row in rows
        ],
    }


def _render_list(rows: Sequence[ShellInstallStatus], *, console: Console) -> None:
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
    table.add_column("PATH", overflow="fold")
    table.add_column("ZWC", no_wrap=True)
    table.add_column("STAMP", no_wrap=True)
    for row in rows:
        table.add_row(
            Text(row.shell, style="bold"),
            Text("yes", style="green") if row.generator else Text("no", style="dim"),
            Text(row.status, style=_status_style(row.status)),
            Text(row.path or "—", style="dim" if row.path is None else ""),
            Text(row.zwc, style=_zwc_style(row.zwc)),
            Text(
                row.stamp_version or "—",
                style="dim" if row.stamp_version is None else "",
            ),
        )
    console.print(table)


def _render_install(result: InstallResult, *, console: Console) -> None:
    detected = result.shell
    console.print(
        Text.assemble(
            ("Detected shell: ", "bold"),
            (detected.name, "cyan bold"),
            (f" ({detected.source})", "dim"),
        )
    )
    table = Table(
        box=None,
        expand=False,
        pad_edge=False,
        show_edge=False,
        header_style="bold",
    )
    table.add_column("STEP", no_wrap=True)
    table.add_column("STATUS", no_wrap=True)
    table.add_column("DETAIL", overflow="fold")
    for step in result.steps:
        table.add_row(
            Text(step.name, style="bold"),
            Text(step.status, style=_step_style(step)),
            Text(step.detail),
        )
    console.print(table)
    if result.fpath_hint and result.registered is False:
        console.print(
            Text(
                "Add this line before compinit (do not let sase edit your rc):",
                style="yellow",
            ),
        )
        console.print(Text(result.fpath_hint, style="bold"))
    console.print()
    console.print(Text(RECOMMENDED_ZSTYLE.rstrip(), style="dim"))


def _status_style(status: str) -> str:
    if status == "installed":
        return "green"
    if status == "not installed":
        return "dim"
    return "yellow"


def _zwc_style(zwc: str) -> str:
    if zwc == "fresh":
        return "green"
    if zwc in {"n/a", "—"}:
        return "dim"
    return "yellow"


def _step_style(step: InstallStep) -> str:
    if step.status == "ok":
        return "green"
    if step.status == "fail":
        return "red"
    if step.status == "planned":
        return "cyan"
    return "dim"


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
