"""``sase agent auto-restart`` — healer CLI for update-skew restarts.

``scan`` enumerates failed ``done.json`` rows and dismissed bundles,
assembles each failure's facts/context/W1-W3 witnesses, classifies through
``sase_core_rs``, and prints one row per failure. It never writes the
restart ledger, claims lineages, or relaunches anything. ``run`` is the
healer: it claims the at-most-once ledger and relaunches once per
lineage. ``list`` and ``show`` read the ledger; ``resume`` re-arms the
storm breaker.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.agent.auto_restart.history import (
    FailedCandidate,
    candidate_log_tail,
    collect_failed_candidates,
)
from sase.agent.auto_restart.inputs import (
    AssembledInput,
    assemble_bundle_input,
    assemble_done_row_input,
)
from sase.agent.auto_restart.managed_roots import (
    ManagedRoot,
    collect_managed_roots,
)
from sase.core.agent_auto_restart_wire import (
    RecoveryVerdictWire,
    agent_failure_facts_to_dict,
    auto_restart_context_to_dict,
    auto_restart_witnesses_to_dict,
    recovery_verdict_to_dict,
)

#: Default table rows shown; the summary always covers the full set.
DEFAULT_SCAN_LIMIT = 50

_SINCE_RE = re.compile(r"^(\d+(?:\.\d+)?)([smhdw]?)$")
_SINCE_UNIT_SECONDS = {
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
    "d": 86400.0,
    "w": 604800.0,
}

_MODE_STYLE = {
    "relaunch": "green",
    "defer": "yellow",
    "notify_post_provider": "cyan",
    "ask": "cyan",
    "decline": "dim",
}


@dataclass(frozen=True)
class _ScannedRow:
    """One classified failure plus everything needed to render it."""

    candidate: FailedCandidate
    assembled: AssembledInput | None
    verdict: RecoveryVerdictWire | None
    error: str | None


def handle_agents_auto_restart(args: argparse.Namespace) -> int:
    """Dispatch ``sase agent auto-restart {list,resume,run,scan,show}``."""
    sub = getattr(args, "auto_restart_subcommand", None)
    if sub == "scan":
        return _handle_scan(args)
    if sub == "list":
        return _handle_list(args)
    if sub == "resume":
        return _handle_resume(args)
    if sub == "run":
        return _handle_run(args)
    if sub == "show":
        return _handle_show(args)

    print(
        "Usage: sase agent auto-restart {list,resume,run,scan,show}",
        file=sys.stderr,
    )
    return 2


def _parse_since_seconds(raw: Any) -> float:
    """Parse a --since duration; raises ``ValueError`` with CLI copy."""
    text = str(raw or "").strip()
    match = _SINCE_RE.match(text)
    if match is None:
        raise ValueError(
            f"invalid --since value {raw!r}; use e.g. 90, 90s, 45m, 2h, 7d, 2w"
        )
    seconds = float(match.group(1)) * _SINCE_UNIT_SECONDS[match.group(2) or "s"]
    if seconds <= 0:
        raise ValueError("--since must be greater than zero")
    return seconds


def _parse_limit(raw: Any) -> int:
    """Parse a --limit row count; raises ``ValueError`` with CLI copy."""
    if raw is None:
        return DEFAULT_SCAN_LIMIT
    try:
        limit = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError(
            f"invalid --limit value {raw!r}; use a positive integer"
        ) from None
    if limit <= 0:
        raise ValueError("--limit must be greater than zero")
    return limit


def _handle_scan(args: argparse.Namespace) -> int:
    err = Console(stderr=True)
    try:
        since_seconds = _parse_since_seconds(getattr(args, "since", "7d"))
    except ValueError as exc:
        err.print(f"sase agent auto-restart scan: {exc}", style="red")
        return 2
    try:
        limit = _parse_limit(getattr(args, "limit", None))
    except ValueError as exc:
        err.print(f"sase agent auto-restart scan: {exc}", style="red")
        return 2

    try:
        from sase.core.agent_auto_restart_facade import (
            auto_restart_wire_schema_version,
        )

        auto_restart_wire_schema_version()
    except Exception as exc:  # noqa: BLE001 - surfaced to the CLI, not swallowed.
        err.print(
            "sase agent auto-restart scan: the update-skew classifier is "
            f"unavailable ({exc}); rebuild the extension with "
            "`just rust-install` and retry",
            style="red",
            soft_wrap=True,
        )
        return 1

    try:
        managed_roots = collect_managed_roots()
    except Exception as exc:  # noqa: BLE001 - surfaced to the CLI, not swallowed.
        err.print(
            f"sase agent auto-restart scan: cannot read managed roots: {exc}",
            style="red",
            soft_wrap=True,
        )
        return 1

    candidates = collect_failed_candidates(since_seconds=since_seconds)
    rows = [_classify_candidate(candidate, managed_roots) for candidate in candidates]

    if getattr(args, "json", False):
        _print_scan_json(rows, since_seconds)
        return 0
    _print_scan_table(rows, since_seconds, limit)
    return 0


_LEDGER_STATE_STYLE = {
    "claimed": "cyan",
    "deferred": "yellow",
    "declined": "dim",
    "launching": "yellow",
    "launched": "green",
    "settled_ok": "green",
    "settled_failed": "red",
}

_IN_FLIGHT_STATES = frozenset({"claimed", "deferred", "launching"})


def _handle_list(args: argparse.Namespace) -> int:
    from sase.agent.auto_restart.ledger import iter_ledger_records

    err = Console(stderr=True)
    try:
        records = iter_ledger_records()
    except Exception as exc:  # noqa: BLE001 - surfaced to the CLI, not swallowed.
        err.print(
            f"sase agent auto-restart list: cannot read ledger: {exc}", style="red"
        )
        return 1
    if not getattr(args, "all", False):
        records = [r for r in records if r.record.state in _IN_FLIGHT_STATES]
    if getattr(args, "json", False):
        from sase.core.agent_auto_restart_wire import ledger_record_to_dict

        json.dump(
            {
                "schema_version": 1,
                "count": len(records),
                "records": [
                    {**ledger_record_to_dict(r.record), "extra": r.extra}
                    for r in records
                ],
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0
    console = Console()
    if not records:
        console.print("No auto-restart ledger records.", style="dim")
        return 0
    by_episode: dict[str, list] = {}
    for stored in records:
        by_episode.setdefault(stored.record.episode_id or "no episode", []).append(
            stored
        )
    for episode, group in by_episode.items():
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("Agent")
        table.add_column("Lineage")
        table.add_column("State")
        table.add_column("Verdict")
        for stored in group:
            record = stored.record
            verdict = stored.extra.get("python_verdict") or {}
            table.add_row(
                _truncate(record.agent_name or "-", 28),
                _truncate(record.lineage_root, 24),
                Text(record.state, style=_LEDGER_STATE_STYLE.get(record.state, "")),
                _truncate(
                    verdict.get("signature") or verdict.get("reason") or "-",
                    44,
                ),
            )
        console.print(
            Panel(table, title=f"↻ {episode} ({len(group)})", border_style="yellow")
        )
    return 0


def _handle_resume(args: argparse.Namespace) -> int:
    from sase.agent.auto_restart.storm import clear_pause, is_paused

    _ = args
    console = Console()
    paused, state = is_paused()
    clear_pause()
    if paused:
        console.print(
            "Auto-restart re-armed"
            + (f" (was paused: {state.get('paused_reason') or 'storm breaker'})")
            + ".",
            style="green",
        )
    else:
        console.print("Auto-restart was not paused; nothing to re-arm.", style="dim")
    return 0


def _handle_run(args: argparse.Namespace) -> int:
    from sase.agent.auto_restart.gate import auto_restart_automatic_enabled
    from sase.agent.auto_restart.healer import heal_one, resolve_targets

    err = Console(stderr=True)
    if not auto_restart_automatic_enabled():
        err.print(
            "sase agent auto-restart run: automatic restarts are disabled "
            "(agent_auto_restart.enabled is false); "
            "nothing was claimed or relaunched",
            style="yellow",
            soft_wrap=True,
        )
        return 3
    try:
        targets = resolve_targets(
            name=getattr(args, "name", None),
            artifacts_dir=getattr(args, "artifacts_dir", None),
            pending=bool(getattr(args, "pending", False)),
        )
    except LookupError as exc:
        err.print(f"sase agent auto-restart run: {exc}", style="red")
        return 1
    except ValueError as exc:
        err.print(f"sase agent auto-restart run: {exc}", style="red")
        return 2
    if not targets:
        Console().print("No pending failures to heal.", style="dim")
        return 0
    dry_run = bool(getattr(args, "dry_run", False))
    from sase.agent.auto_restart.healer import HealerOutcome

    outcomes: list[HealerOutcome] = []
    for target in targets:
        try:
            outcomes.append(heal_one(target, dry_run=dry_run))
        except Exception as exc:  # noqa: BLE001 - one bad row must not hide the rest.
            outcomes.append(
                HealerOutcome(
                    action="error",
                    reason="healer_error",
                    reason_text=str(exc)[:300],
                    ledger_key=None,
                )
            )
    if getattr(args, "json", False):
        json.dump(
            {
                "schema_version": 1,
                "dry_run": dry_run,
                "count": len(outcomes),
                "outcomes": [
                    {
                        "action": o.action,
                        "reason": o.reason,
                        "reason_text": o.reason_text,
                        "ledger_key": o.ledger_key,
                        "launched_artifacts_dir": o.launched_artifacts_dir,
                        "evidence_dir": o.evidence_dir,
                    }
                    for o in outcomes
                ],
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0
    console = Console()
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Agent")
    table.add_column("Action")
    table.add_column("Reason")
    failed = False
    for target, outcome in zip(targets, outcomes, strict=True):
        style = (
            "green"
            if outcome.action == "relaunched"
            else "yellow"
            if outcome.action in ("deferred", "dry_run")
            else "red"
            if outcome.action == "error"
            else "dim"
        )
        if outcome.action == "error":
            failed = True
        table.add_row(
            _truncate(target.agent_name, 28),
            Text(outcome.action, style=style),
            _truncate(outcome.reason_text, 60),
        )
    console.print(
        Panel(
            table,
            title=f"Healer ({len(outcomes)} target{'s' if len(outcomes) != 1 else ''}"
            + ("; dry run" if dry_run else "")
            + ")",
            border_style="yellow",
        )
    )
    return 1 if failed else 0


def _handle_show(args: argparse.Namespace) -> int:
    from sase.agent.auto_restart.ledger import iter_ledger_records
    from sase.core.agent_auto_restart_wire import ledger_record_to_dict

    err = Console(stderr=True)
    wanted = str(getattr(args, "target", "") or "")
    matches = [
        r
        for r in iter_ledger_records()
        if wanted
        in (
            r.record.key,
            r.record.lineage_root,
            r.record.agent_name or "",
            r.record.episode_id or "",
        )
    ]
    if not matches:
        err.print(
            f"sase agent auto-restart show: no ledger record matches {wanted!r}",
            style="red",
        )
        return 1
    stored = matches[0]
    if getattr(args, "json", False):
        json.dump(
            {**ledger_record_to_dict(stored.record), "extra": stored.extra},
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0
    _print_record_card(stored)
    return 0


def _print_record_card(stored: Any) -> None:
    console = Console()
    record = stored.record
    verdict = stored.extra.get("python_verdict") or {}
    witnesses = stored.extra.get("python_witnesses") or {}
    lines = [
        f"[bold]{record.agent_name or record.key}[/bold]  "
        f"[{_LEDGER_STATE_STYLE.get(record.state, '')}]{record.state}[/]",
        f"Lineage: {record.lineage_root}",
        f"Episode: {record.episode_id or '-'}",
        f"Failed row: {record.failed_artifacts_dir or '-'}",
        f"Verdict: {verdict.get('tier', '-')}/{verdict.get('family', '-') or '-'} — "
        f"{verdict.get('signature') or verdict.get('reason') or '-'} "
        f"({verdict.get('mode', '-')})",
    ]
    fired = set(verdict.get("witnesses_fired") or [])
    checklist: list[str] = []
    for witness in ("W1", "W2", "W3", "W4"):
        mark = "✓" if witness in fired else "✗"
        detail = ""
        if witness == "W3" and isinstance(witnesses.get("file_proof"), dict):
            detail = f" {witnesses['file_proof'].get('culprit_commit', '')}"
        checklist.append(f"{mark} {witness}{detail}")
    lines.append("Witnesses: " + "  ".join(checklist))
    timeline = "; ".join(f"{entry.state}@{entry.at or '?'}" for entry in record.history)
    lines.append(f"Timeline: {timeline or '-'}")
    if stored.extra.get("python_last_note"):
        lines.append(f"Last note: {stored.extra['python_last_note']}")
    lines.append(f"Evidence: {record.evidence_dir or '-'}")
    console.print(
        Panel(
            "\n".join(lines),
            title=f"↻ {record.key}",
            border_style="yellow",
        )
    )


def _classify_candidate(
    candidate: FailedCandidate, managed_roots: tuple[ManagedRoot, ...]
) -> _ScannedRow:
    """Assemble one candidate's inputs and classify them.

    A per-row failure never aborts the scan: the row is kept with an
    error marker so one corrupt marker cannot hide the corpus.
    """
    from sase.core.agent_auto_restart_facade import classify_agent_failure

    try:
        log_tail = candidate_log_tail(candidate)
        assembled: AssembledInput | None = None
        if candidate.source == "done" and candidate.done is not None:
            if candidate.artifacts_dir is None:
                return _ScannedRow(
                    candidate=candidate,
                    assembled=None,
                    verdict=None,
                    error="missing artifact directory",
                )
            assembled = assemble_done_row_input(
                artifacts_dir=candidate.artifacts_dir,
                done=candidate.done,
                meta=candidate.meta or {},
                managed_roots=managed_roots,
                project=candidate.project,
                died_at=candidate.died_at,
                log_tail=log_tail,
                done_mtime=candidate.mtime,
            )
        elif candidate.bundle is not None:
            assembled = assemble_bundle_input(
                bundle=candidate.bundle,
                managed_roots=managed_roots,
                project=candidate.project,
                died_at=candidate.died_at,
                log_tail=log_tail,
                done_mtime=candidate.mtime,
            )
        else:
            return _ScannedRow(
                candidate=candidate,
                assembled=None,
                verdict=None,
                error="missing failure payload",
            )
        verdict = classify_agent_failure(
            assembled.context, assembled.witnesses, assembled.facts
        )
        return _ScannedRow(
            candidate=candidate,
            assembled=assembled,
            verdict=verdict,
            error=None,
        )
    except Exception as exc:  # noqa: BLE001 - one bad row must not hide the corpus.
        return _ScannedRow(
            candidate=candidate,
            assembled=None,
            verdict=None,
            error=str(exc)[:160],
        )


def _format_died(died_at: float | None) -> str:
    if died_at is None:
        return "unknown"
    from sase.core.time import get_timezone

    return datetime.fromtimestamp(died_at, tz=get_timezone()).strftime("%Y-%m-%d %H:%M")


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def _print_scan_table(
    rows: list[_ScannedRow],
    since_seconds: float,
    limit: int,
) -> None:
    console = Console()
    counts: dict[str, int] = {}
    for row in rows:
        mode = row.verdict.mode if row.verdict is not None else "error"
        counts[mode] = counts.get(mode, 0) + 1

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Agent")
    table.add_column("Project")
    table.add_column("Died")
    table.add_column("Phase")
    table.add_column("Signature")
    table.add_column("Witnesses")
    table.add_column("Verdict")

    for row in rows[:limit]:
        candidate = row.candidate
        if row.verdict is None:
            table.add_row(
                _truncate(candidate.name, 28),
                _truncate(candidate.project, 22),
                _format_died(candidate.died_at),
                "-",
                _truncate(row.error or "unclassifiable", 44),
                "-",
                Text("error", style="red"),
            )
            continue
        verdict = row.verdict
        witnesses = ",".join(verdict.witnesses_fired) or "-"
        table.add_row(
            _truncate(candidate.name, 28),
            _truncate(candidate.project, 22),
            _format_died(candidate.died_at),
            verdict.phase_class or "-",
            _truncate(verdict.signature or verdict.reason, 44),
            witnesses,
            Text(verdict.mode, style=_MODE_STYLE.get(verdict.mode, "dim")),
        )

    shown = min(limit, len(rows))
    title = f"Auto-Restart Scan ({len(rows)} failures, showing {shown}; read-only)"
    console.print(Panel(table, title=title, border_style="cyan"))
    ordered = ("relaunch", "defer", "notify_post_provider", "ask", "decline")
    parts = [f"{counts.get(mode, 0)} {mode}" for mode in ordered]
    errors = counts.get("error", 0)
    if errors:
        parts.append(f"{errors} error")
    console.print(
        f"Scanned {len(rows)} failures within the last "
        f"{_format_duration(since_seconds)}: "
        + " · ".join(parts)
        + ". Scan only: nothing was restarted and the ledger was not written."
    )


def _format_duration(seconds: float) -> str:
    if seconds % 604800 == 0:
        return f"{int(seconds // 604800)}w"
    if seconds % 86400 == 0:
        return f"{int(seconds // 86400)}d"
    if seconds % 3600 == 0:
        return f"{int(seconds // 3600)}h"
    if seconds % 60 == 0:
        return f"{int(seconds // 60)}m"
    return f"{seconds:g}s"


def _print_scan_json(rows: list[_ScannedRow], since_seconds: float) -> None:
    """Write classifier verdict wires plus row identity as JSON."""
    payload_results: list[dict[str, Any]] = []
    for row in rows:
        candidate = row.candidate
        assembled = row.assembled
        entry: dict[str, Any] = {
            "source": candidate.source,
            "name": candidate.name,
            "project": candidate.project,
            "died_at": candidate.died_at,
            "artifacts_dir": (
                str(candidate.artifacts_dir)
                if candidate.artifacts_dir is not None
                else None
            ),
            "lifecycle_phase": (
                assembled.lifecycle_phase if assembled is not None else None
            ),
            "facts": (
                agent_failure_facts_to_dict(assembled.facts)
                if assembled is not None and assembled.facts is not None
                else None
            ),
            "context": (
                auto_restart_context_to_dict(assembled.context)
                if assembled is not None
                else None
            ),
            "witnesses": (
                auto_restart_witnesses_to_dict(assembled.witnesses)
                if assembled is not None
                else None
            ),
            "verdict": (
                recovery_verdict_to_dict(row.verdict)
                if row.verdict is not None
                else None
            ),
            "error": row.error,
        }
        payload_results.append(entry)
    json.dump(
        {
            "schema_version": 1,
            "since_seconds": since_seconds,
            "count": len(payload_results),
            "results": payload_results,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")


__all__ = [
    "DEFAULT_SCAN_LIMIT",
    "handle_agents_auto_restart",
]
