"""``sase agent auto-restart scan`` — read-only classifier replay.

The witness-scan phase ships ``scan`` only: it enumerates failed
``done.json`` rows and dismissed bundles, assembles each failure's
facts/context/W1-W3 witnesses, classifies through ``sase_core_rs``,
and prints one row per failure. It never writes the restart ledger,
claims lineages, or relaunches anything. The healer phase adds the
mutating commands (``list``, ``resume``, ``run``, ``show``).
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
    """Dispatch ``sase agent auto-restart {scan}``."""
    sub = getattr(args, "auto_restart_subcommand", None)
    if sub == "scan":
        return _handle_scan(args)

    print(
        "Usage: sase agent auto-restart {scan}",
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
