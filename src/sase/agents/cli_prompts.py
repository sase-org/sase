"""CLI handlers for the canonical agents-sidecar prompt archive."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys

from rich.table import Table

from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.validation import (
    PromptArchiveValidation,
    list_prompt_archive_files,
    resolve_prompt_archive_file,
    validate_prompt_archive,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.history.chat_prompt_sections import (
    extract_prompt_renderings,
    remove_prompt_sections,
)
from sase.output import console, error_console
from sase.repo_inventory import RepoRecord, collect_repo_inventory
from sase.sdd.plan_header_block import parse_plan_header_block
from sase.workspace_provider.marker import find_marker_from_cwd

# ``EX_UNAVAILABLE`` from sysexits.h, kept literal for cross-platform parity.
PROMPT_ARCHIVE_CONTEXT_UNAVAILABLE_EXIT_CODE = 69


@dataclass(frozen=True, slots=True)
class _PromptArchiveContext:
    target: ProjectTarget
    plans_repo: Path | None


def handle_agents_prompts(args: argparse.Namespace) -> int:
    """Dispatch ``sase agent prompts`` subcommands."""

    subcommand = getattr(args, "prompts_subcommand", None)
    try:
        context = _resolve_context(getattr(args, "project", None))
    except _PromptArchiveContextUnavailable as exc:
        if subcommand == "validate":
            _print_unavailable_context(args, str(exc))
            return PROMPT_ARCHIVE_CONTEXT_UNAVAILABLE_EXIT_CODE
        error_console.print(f"[red]Error:[/red] {exc}")
        return 1
    except ValueError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        return 1
    if subcommand == "migrate":
        return _handle_migrate(args, context)
    if subcommand == "list":
        return _handle_list(args, context)
    if subcommand == "show":
        return _handle_show(args, context)
    if subcommand == "validate":
        return _handle_validate(args, context)
    error_console.print("Usage: sase agent prompts {list,migrate,show,validate}")
    return 2


class _PromptArchiveContextUnavailable(ValueError):
    """The prompt archive cannot be reached from the current host context."""


def _print_unavailable_context(args: argparse.Namespace, reason: str) -> None:
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "ok": False,
                    "skipped": True,
                    "reason": reason,
                },
                indent=2,
            )
        )
        return
    console.print(
        "[yellow]Prompt archive validation skipped:[/yellow] "
        f"context unavailable: {reason}"
    )


def _handle_list(
    args: argparse.Namespace,
    context: _PromptArchiveContext,
) -> int:
    files = list_prompt_archive_files(
        context.target.sidecar_path,
        month=getattr(args, "month", None),
    )
    if getattr(args, "json", False):
        print(json.dumps([file.to_json_dict() for file in files], indent=2))
        return 0

    table = Table(
        title=f"Prompt archive · {context.target.project}",
        header_style="bold cyan",
        box=None,
    )
    table.add_column("PROMPT", style="bold")
    table.add_column("TITLE")
    table.add_column("PLAN")
    table.add_column("AGENT")
    table.add_column("ARTIFACTS", justify="right")
    for file in files:
        table.add_row(
            file.relpath,
            file.title,
            file.plan_label or "-",
            ", ".join(file.agent_labels) or "-",
            str(file.artifact_count),
        )
    console.print(table)
    return 0


def _handle_show(
    args: argparse.Namespace,
    context: _PromptArchiveContext,
) -> int:
    rendered = bool(getattr(args, "rendered", False))
    try:
        file = resolve_prompt_archive_file(context.target.sidecar_path, args.prompt)
        content = file.path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        return 1

    body = _document_body(content)
    xprompt_body = _normalize_printable_prompt(remove_prompt_sections(body))
    renderings = extract_prompt_renderings(body, xprompt_fallback=xprompt_body)
    selected = renderings.rendered_prompt if rendered else renderings.xprompt_prompt
    rendering = "rendered" if rendered else "xprompt"
    if selected is None:
        error_console.print(
            f"[red]Error:[/red] {file.relpath} has no stored {rendering} prompt"
        )
        return 1

    if getattr(args, "json", False):
        payload = file.to_json_dict()
        payload["rendering"] = rendering
        payload["content"] = selected
        print(json.dumps(payload, indent=2))
    else:
        _write_prompt_content(selected)
    return 0


def _handle_validate(
    args: argparse.Namespace,
    context: _PromptArchiveContext,
) -> int:
    validation = validate_prompt_archive(
        context.target.sidecar_path,
        month=getattr(args, "month", None),
        plans_repo=context.plans_repo,
        workspace_roots=context.target.primary_roots,
        project_key=context.target.project_key,
    )
    if getattr(args, "json", False):
        print(json.dumps(validation.to_json_dict(), indent=2))
    else:
        _print_validation(
            validation,
            show_warnings=bool(getattr(args, "show_warnings", False)),
        )
    return 0 if validation.ok else 1


def _handle_migrate(
    args: argparse.Namespace,
    context: _PromptArchiveContext,
) -> int:
    """Move historical plans-sidecar prompts into the canonical archive."""

    if context.plans_repo is None:
        error_console.print("[red]Error:[/red] plans sidecar checkout is unavailable")
        return 1
    from sase.agents_sync.prompt_archive.migration import migrate_prompt_archive

    return migrate_prompt_archive(
        args,
        target=context.target,
        plans_repo=context.plans_repo,
    )


def _document_body(content: str) -> str:
    try:
        return parse_plan_header_block(content).body
    except (RuntimeError, ValueError):
        return content


def _normalize_printable_prompt(content: str) -> str:
    return content.strip("\n")


def _write_prompt_content(content: str) -> None:
    sys.stdout.write(content)
    if not content.endswith("\n"):
        sys.stdout.write("\n")


def _resolve_context(project: str | None) -> _PromptArchiveContext:
    target = _resolve_target(project)
    return _PromptArchiveContext(target, _plans_repo(target))


def resolve_prompt_archive_root(project: str | None = None) -> Path:
    """Return the agents-sidecar root selected by ``sase agent prompts``."""

    return _resolve_target(project).sidecar_path


def _resolve_target(project: str | None) -> ProjectTarget:
    selector = project or _current_project()
    selection = (
        resolve_sync_targets((selector,)) if selector else resolve_sync_targets()
    )
    if len(selection.targets) > 1:
        raise ValueError("multiple projects matched; pass -p/--project")
    if not selection.targets:
        details = [
            outcome.error or outcome.skip_reason
            for outcome in selection.outcomes
            if outcome.error or outcome.skip_reason
        ]
        if details:
            raise _PromptArchiveContextUnavailable(details[0])
        raise _PromptArchiveContextUnavailable(
            "no project with an available agents sidecar was found"
        )
    target = selection.targets[0]
    if not target.sidecar_path.is_dir():
        raise _PromptArchiveContextUnavailable(
            f"agents sidecar checkout is unavailable: {target.sidecar_path}"
        )
    return target


def _current_project() -> str | None:
    try:
        from sase.workflows.utils import get_project_from_workspace

        return get_project_from_workspace()
    except Exception:
        return None


def _plans_repo(target: ProjectTarget) -> Path | None:
    try:
        inventory = collect_repo_inventory(project=target.project_key)
    except Exception:
        return None
    matches = [
        record
        for record in inventory.records
        if record.kind == "sidecar"
        and (record.name == "plans" or record.slug == "plans")
    ]
    if len(matches) != 1:
        return None
    workspace_num = _caller_workspace_num(target, inventory.records)
    match = matches[0]
    clone = match.clone_for_workspace(workspace_num)
    raw_path = clone.path if clone is not None else match.path
    path = Path(raw_path).expanduser().resolve(strict=False)
    return path if path.is_dir() else None


def _caller_workspace_num(
    target: ProjectTarget,
    records: tuple[RepoRecord, ...],
) -> int:
    """Return the registered workspace containing the command's caller."""

    cwd = Path.cwd().resolve(strict=False)
    marker_match = find_marker_from_cwd(str(cwd))
    if marker_match is not None:
        marker = marker_match[1]
        if marker.project_key == target.project_key and marker.workspace_num >= 0:
            return marker.workspace_num
    primary = next(
        (
            record
            for record in records
            if record.kind == "primary" and record.project_key == target.project_key
        ),
        None,
    )
    if primary is None:
        return 0
    for clone in primary.clones:
        clone_path = Path(clone.path).expanduser().resolve(strict=False)
        if cwd == clone_path or cwd.is_relative_to(clone_path):
            return clone.workspace_num
    return 0


def _print_validation(
    validation: PromptArchiveValidation,
    *,
    show_warnings: bool,
) -> None:
    warning_count = len(validation.warnings)
    hidden_hint = (
        " (use --show-warnings to display)"
        if warning_count and not show_warnings
        else ""
    )
    if validation.ok:
        console.print(
            "[green]Prompt archive validation passed:[/green] "
            f"{len(validation.files)} prompts, {warning_count} warnings"
            f"{hidden_hint}"
        )
    else:
        error_console.print(
            "[red]Prompt archive validation failed:[/red] "
            f"{len(validation.errors)} errors, {warning_count} warnings"
            f"{hidden_hint}"
        )
    for issue in validation.issues:
        if issue.severity == "warning" and not show_warnings:
            continue
        target = error_console if issue.severity == "error" else console
        style = "red" if issue.severity == "error" else "yellow"
        target.print(
            f"[{style}]{issue.severity}:[/{style}] {issue.path}: "
            f"{issue.message} [dim]({issue.code})[/dim]"
        )


__all__ = [
    "PROMPT_ARCHIVE_CONTEXT_UNAVAILABLE_EXIT_CODE",
    "handle_agents_prompts",
]
