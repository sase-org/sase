"""Standing publication alerts as ``state.agent_publication_outbox`` issues.

The publisher keeps one live standing alert per ``(project, signature)``
failure cause. Doctor folds an alert into the matching outbox row group when
one exists; an alert with no stuck rows (target unavailable, drain timeout,
lock busy, heartbeat write, ...) becomes its own issue so a failing project
never reports OK. Reads are strictly read-only and fail open.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.agents_sync.publication_standing import (
    STANDING_ALERTS_FILENAME,
    STANDING_ALERTS_SCHEMA_VERSION,
)
from sase.doctor._agent_publication import format_duration

_MAX_SAMPLE_CHARS = 240


def read_standing_alerts(
    sase_home: Path,
) -> tuple[tuple[dict[str, Any], ...], dict[tuple[str, str], dict[str, Any]]]:
    """Read live publication standing alerts without touching the store.

    Best-effort and strictly read-only: a missing, corrupt, or
    wrong-version store degrades to no alerts rather than failing doctor or
    quarantining another subsystem's state aside.
    """

    path = sase_home / "agent_publication" / STANDING_ALERTS_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - doctor isolates store trouble.
        return (), {}
    if not isinstance(payload, dict):
        return (), {}
    if payload.get("schema_version") != STANDING_ALERTS_SCHEMA_VERSION:
        return (), {}
    raw_alerts = payload.get("alerts")
    if not isinstance(raw_alerts, dict):
        return (), {}
    alerts: list[dict[str, Any]] = []
    by_group: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in raw_alerts.values():
        if not isinstance(raw, dict):
            continue
        project = raw.get("project")
        signature = raw.get("signature")
        if not isinstance(project, str) or not isinstance(signature, str):
            continue
        row = {
            "project": project,
            "signature": signature,
            "failure_kind": raw.get("failure_kind"),
            "error_class": raw.get("error_class"),
            "detail": raw.get("detail"),
            "attempts": raw.get("attempts"),
            "first_seen": raw.get("first_seen"),
            "last_seen": raw.get("last_seen"),
            "last_reported": raw.get("last_reported"),
            "escalated": raw.get("escalated"),
            "next_attempt_at": raw.get("next_attempt_at"),
            "project_scoped": raw.get("project_scoped"),
        }
        alerts.append(row)
        by_group[(project, signature)] = row
    ordered = tuple(sorted(alerts, key=lambda row: (row["project"], row["signature"])))
    return ordered, by_group


@dataclass(frozen=True, slots=True)
class _StandingIssue:
    """One live standing alert that matches no outbox row group."""

    alert: Mapping[str, Any]
    project: str

    def backing_off(self, now: float) -> bool:
        next_attempt_at = _number(self.alert.get("next_attempt_at"))
        return next_attempt_at is not None and next_attempt_at > now

    def detail(self, now: float) -> str:
        kind = self.alert.get("failure_kind") or "unknown"
        error_class = self.alert.get("error_class")
        class_text = f" ({error_class})" if error_class else ""
        attempts = _number(self.alert.get("attempts"))
        attempts_text = f"{int(attempts)}" if attempts is not None else "unknown"
        escalated = "; escalated" if self.alert.get("escalated") is True else ""
        next_attempt_at = _number(self.alert.get("next_attempt_at"))
        if next_attempt_at is not None and next_attempt_at > now:
            backoff = (
                f"; backing off until {_utc(next_attempt_at)} "
                f"(in {format_duration(next_attempt_at - now)})"
            )
        else:
            backoff = "; not backing off"
        sample = self.alert.get("detail")
        sample_text = (
            f"; last error: {_truncate(sample)}"
            if isinstance(sample, str) and sample.strip()
            else ""
        )
        return (
            f"{self.project}: standing {kind} alert{class_text} with no stuck "
            f"rows, {attempts_text} attempt(s), first seen "
            f"{_seen(self.alert.get('first_seen'), now)}, last seen "
            f"{_seen(self.alert.get('last_seen'), now)}"
            f"{backoff}{escalated}{sample_text}"
        )

    def to_data(self, now: float) -> dict[str, Any]:
        return {
            **self.alert,
            "display_project": self.project,
            "backing_off": self.backing_off(now),
            "detail_line": self.detail(now),
        }


def unmatched_standing_issues(
    alerts: Iterable[Mapping[str, Any]],
    group_keys: Iterable[tuple[str, str]],
    *,
    project_names: Mapping[str, str],
) -> tuple[_StandingIssue, ...]:
    """Return one issue per live alert that folds into no row group.

    *alerts* arrive sorted by ``(project, signature)``, so unchanged state
    yields the same issues in the same order on every read; attempt bumps
    change only the detail text, never the count.
    """

    matched = set(group_keys)
    return tuple(
        _StandingIssue(
            alert=alert,
            project=project_names.get(alert["project"], alert["project"]),
        )
        for alert in alerts
        if (alert["project"], alert["signature"]) not in matched
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _utc(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return "unknown"


def _seen(value: object, now: float) -> str:
    timestamp = _number(value)
    if timestamp is None:
        return "unknown"
    return f"{_utc(timestamp)} ({format_duration(now - timestamp)} ago)"


def _truncate(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _MAX_SAMPLE_CHARS:
        return collapsed
    return collapsed[: _MAX_SAMPLE_CHARS - 1] + "…"
