"""``sase prompt doctor``/``delete``/``prune`` — safe history maintenance.

``doctor`` is read-only. ``delete`` and ``prune`` mutate the live prompt-history
store, so they reuse the storage layer's sidecar lock and atomic replace, refuse
to rewrite a corrupt store, and confirm before removing anything unless ``--yes``
(or, for ``prune``, ``--dry-run``) is supplied. In a non-interactive shell a
destructive command without ``--yes``/``--dry-run`` fails with instructions
rather than silently deleting.
"""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.history.prompt import (
    PromptDateError,
    PromptHistoryDoctor,
    PromptLargest,
    PromptSelectorError,
    PromptStoreCorruptError,
    PromptStoreWriteError,
    PrunePlan,
    compute_prompt_doctor,
    delete_prompt,
    parse_prune_date,
    prune_prompts,
    resolve_prompt_selector,
)
from sase.prompt.render import format_size, format_timestamp


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _confirm(message: str) -> bool:
    """Prompt for a yes/no answer; treat EOF and anything but yes as no."""
    try:
        answer = input(message)
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def handle_prompt_delete(args: argparse.Namespace) -> None:
    """Delete exactly one stored prompt by selector, with confirmation."""
    selector: str = getattr(args, "id", "")
    assume_yes = bool(getattr(args, "yes", False))

    # Resolve up front so the confirmation can name what will be removed. The
    # authoritative re-resolution happens under the lock inside delete_prompt.
    try:
        record = resolve_prompt_selector(selector)
    except PromptSelectorError as exc:
        print(f"sase prompt delete: {exc}", file=sys.stderr)
        sys.exit(2)

    if not assume_yes:
        if not _stdin_is_tty():
            print(
                "sase prompt delete: refusing to delete without confirmation in a"
                " non-interactive shell. Re-run with --yes.",
                file=sys.stderr,
            )
            sys.exit(1)
        question = (
            f"Delete {record.id} ({record.text_chars} chars, last used "
            f"{format_timestamp(record.last_used)})? [y/N] "
        )
        if not _confirm(question):
            print("Aborted.", file=sys.stderr)
            sys.exit(1)

    try:
        deleted = delete_prompt(selector)
    except PromptSelectorError as exc:
        print(f"sase prompt delete: {exc}", file=sys.stderr)
        sys.exit(2)
    except (PromptStoreCorruptError, PromptStoreWriteError) as exc:
        print(f"sase prompt delete: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Deleted {deleted.id} ({deleted.text_chars} chars).")


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


def handle_prompt_prune(args: argparse.Namespace) -> None:
    """Remove prompts by objective criteria, with dry-run and confirmation."""
    keep: int | None = getattr(args, "keep", None)
    before_raw: str | None = getattr(args, "before", None)
    cancelled_only = bool(getattr(args, "cancelled", False))
    dry_run = bool(getattr(args, "dry_run", False))
    assume_yes = bool(getattr(args, "yes", False))

    if keep is None and before_raw is None and not cancelled_only:
        print(
            "sase prompt prune: specify at least one of --keep, --before, or"
            " --cancelled.",
            file=sys.stderr,
        )
        sys.exit(2)

    before: str | None = None
    if before_raw is not None:
        try:
            before = parse_prune_date(before_raw)
        except PromptDateError as exc:
            print(f"sase prompt prune: {exc}", file=sys.stderr)
            sys.exit(2)

    # Dry-run: compute and show the plan, never mutate, never confirm.
    if dry_run:
        plan = _compute_plan_or_exit(
            keep=keep, before=before, cancelled_only=cancelled_only, dry_run=True
        )
        _print_prune_plan(plan, applied=False)
        return

    if not assume_yes:
        preview = _compute_plan_or_exit(
            keep=keep, before=before, cancelled_only=cancelled_only, dry_run=True
        )
        if not preview.removed:
            _print_prune_plan(preview, applied=False)
            return
        if not _stdin_is_tty():
            print(
                "sase prompt prune: refusing to prune without confirmation in a"
                " non-interactive shell. Re-run with --yes or --dry-run.",
                file=sys.stderr,
            )
            sys.exit(1)
        _print_prune_plan(preview, applied=False)
        if not _confirm(
            f"Remove {len(preview.removed)} of {preview.total} prompts? [y/N] "
        ):
            print("Aborted.", file=sys.stderr)
            sys.exit(1)

    plan = _compute_plan_or_exit(
        keep=keep, before=before, cancelled_only=cancelled_only, dry_run=False
    )
    _print_prune_plan(plan, applied=True)


def _compute_plan_or_exit(
    *,
    keep: int | None,
    before: str | None,
    cancelled_only: bool,
    dry_run: bool,
) -> PrunePlan:
    try:
        return prune_prompts(
            keep=keep,
            before=before,
            cancelled_only=cancelled_only,
            dry_run=dry_run,
        )
    except (PromptStoreCorruptError, PromptStoreWriteError) as exc:
        print(f"sase prompt prune: {exc}", file=sys.stderr)
        sys.exit(1)


def _print_prune_plan(plan: PrunePlan, *, applied: bool) -> None:
    """Print the prune funnel and outcome in plain, pipe-friendly text."""
    if applied:
        print(
            f"Pruned {len(plan.removed)} of {plan.total} prompts, {plan.kept} remaining."
        )
        return

    if not plan.removed:
        print(f"Nothing to prune ({plan.total} prompts, none match the criteria).")
        return

    print(f"Prune plan (dry run) over {plan.total} prompts:")
    if plan.cancelled_only:
        print(f"  cancelled-only candidates: {plan.candidate_count}")
    if plan.keep is not None:
        print(f"  beyond newest {plan.keep}: {plan.beyond_keep_count}")
    if plan.before is not None:
        print(f"  older than {plan.before}: {plan.older_than_count}")
    print(f"  -> would remove {len(plan.removed)}, keeping {plan.kept}")


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def handle_prompt_doctor(args: argparse.Namespace) -> None:
    """Render a read-only health report for the prompt-history store."""
    report = compute_prompt_doctor()
    if bool(getattr(args, "json", False)):
        _print_doctor_json(report)
        return
    _print_doctor_pretty(report)


def _largest_to_json(item: PromptLargest) -> dict[str, object]:
    return {"id": item.id, "text_chars": item.text_chars, "preview": item.preview}


def _doctor_to_json(report: PromptHistoryDoctor) -> dict[str, object]:
    return {
        "path": report.path,
        "exists": report.exists,
        "size_bytes": report.size_bytes,
        "parseable": report.parseable,
        "total": report.total,
        "cancelled": report.cancelled,
        "invalid_entries": report.invalid_entries,
        "duplicate_ids": [[pid, count] for pid, count in report.duplicate_ids],
        "legacy_field_entries": report.legacy_field_entries,
        "oversized": [_largest_to_json(item) for item in report.oversized],
        "short_recovery": [_largest_to_json(item) for item in report.short_recovery],
        "fzf_available": report.fzf_available,
        "clipboard_available": report.clipboard_available,
    }


def _print_doctor_json(report: PromptHistoryDoctor) -> None:
    json.dump(_doctor_to_json(report), sys.stdout, indent=2)
    sys.stdout.write("\n")


def _ok_bad(value: bool, *, ok: str, bad: str) -> Text:
    return Text(ok, style="green") if value else Text(bad, style="red")


def _print_doctor_pretty(report: PromptHistoryDoctor) -> None:
    console = Console()

    summary = Table(show_header=False, box=None, pad_edge=False)
    summary.add_column("k", style="bold cyan", no_wrap=True)
    summary.add_column("v")
    summary.add_row("path", report.path)
    if not report.exists:
        summary.add_row("status", Text("no history file yet", style="yellow"))
    summary.add_row("size", format_size(report.size_bytes))
    summary.add_row(
        "parseable", _ok_bad(report.parseable, ok="yes", bad="NO — corrupt store")
    )
    summary.add_row("total", str(report.total))
    summary.add_row("cancelled", f"[magenta]{report.cancelled}[/magenta]")
    summary.add_row(
        "invalid entries",
        Text(
            str(report.invalid_entries),
            style="red" if report.invalid_entries else "dim",
        ),
    )
    summary.add_row(
        "duplicate ids",
        Text(
            str(len(report.duplicate_ids)),
            style="red" if report.duplicate_ids else "dim",
        ),
    )
    summary.add_row("legacy-field entries", str(report.legacy_field_entries))
    summary.add_row("fzf", _ok_bad(report.fzf_available, ok="available", bad="missing"))
    summary.add_row(
        "clipboard",
        _ok_bad(report.clipboard_available, ok="available", bad="missing"),
    )

    console.print(Panel(summary, title="Prompt History Doctor", border_style="cyan"))

    _print_doctor_largest(console, "Oversized Prompts", report.oversized)
    _print_doctor_largest(console, "Short Recovery-Path Prompts", report.short_recovery)

    if report.duplicate_ids:
        dup = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        dup.add_column("ID", style="cyan", no_wrap=True)
        dup.add_column("COPIES", justify="right", style="red", no_wrap=True)
        for pid, count in report.duplicate_ids:
            dup.add_row(pid, str(count))
        console.print(Panel(dup, title="Duplicate IDs", border_style="cyan"))


def _print_doctor_largest(
    console: Console, title: str, items: list[PromptLargest]
) -> None:
    if not items:
        return
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("CHARS", justify="right", style="dim", no_wrap=True)
    table.add_column("PREVIEW")
    for item in items:
        table.add_row(item.id, str(item.text_chars), item.preview)
    console.print(Panel(table, title=title, border_style="cyan"))
