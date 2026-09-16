"""Agent-hold doctor checks: stale holds a normal read would silently prune."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sase.core.agent_hold_facade import list_current_agent_holds
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10
_AGENT_HOLD_STATE_FILENAME = "agent_holds.json"
_UNSET: Any = object()


class _MalformedHoldStore(Exception):
    """Raised when the raw hold-store file is unreadable or misshapen."""


def agent_hold_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return the ``agent_holds.*`` doctor check specs."""
    return (
        CheckSpec(
            id="agent_holds.stale",
            group="agent_holds",
            title="Stale agent holds",
            runner=lambda: _check_agent_holds_stale(context),
        ),
    )


def _check_agent_holds_stale(
    context: DoctorContext,
    *,
    raw_holds: dict[str, Any] | None | Any = _UNSET,
    pruned: list[dict[str, Any]] | Any = _UNSET,
    now: datetime | float | None = None,
) -> DiagnosticCheck:
    """Flag holds a routine read would prune: dead armers or past expiry.

    ``sase agent hold list``/the admission loop already prune dead-armer and
    past-expiry records on every read (fail-open, prune-on-read), so a hold
    only stays stale on disk when nothing has read the store since it went
    bad -- e.g. a short-TTL hold armed just before the host went idle. This
    check reads the raw store once (bypassing that self-heal) to see what
    was actually stale, then reconciles it the normal way.
    """
    if raw_holds is _UNSET:
        try:
            resolved_raw = _read_raw_holds(context.sase_home)
        except _MalformedHoldStore:
            return _check(
                "agent_holds.stale",
                "WARN",
                "agent-hold store is malformed; it will self-heal on next arm/list",
                data={"raw_readable": False},
            )
    else:
        resolved_raw = raw_holds
    if resolved_raw is None:
        return _check(
            "agent_holds.stale",
            "OK",
            "no agent-hold store present",
            data={"hold_count": 0},
        )
    if not resolved_raw:
        return _check(
            "agent_holds.stale",
            "OK",
            "no active agent holds",
            data={"hold_count": 0},
        )

    try:
        resolved_pruned = (
            list_current_agent_holds(now=now) if pruned is _UNSET else pruned
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a WARN, not a crash.
        return _check(
            "agent_holds.stale",
            "WARN",
            f"agent-hold store failed to reconcile: {exc}",
            data={"hold_count": len(resolved_raw)},
        )

    pruned_keys = {
        armer.get("key")
        for hold in resolved_pruned
        if isinstance((armer := hold.get("armer")), dict)
    }
    now_epoch = _epoch_seconds(now)
    stale: list[tuple[str, str, str]] = []
    for key, record in resolved_raw.items():
        if key in pruned_keys or not isinstance(record, dict):
            continue
        raw_armer = record.get("armer")
        armer = raw_armer if isinstance(raw_armer, dict) else {}
        display = armer.get("display") or armer.get("key") or key
        expires_at = record.get("expires_at")
        past_expiry = (
            isinstance(expires_at, (int, float))
            and not isinstance(expires_at, bool)
            and expires_at <= now_epoch
        )
        reason = "past expiry" if past_expiry else "dead armer"
        stale.append((str(key), str(display), reason))

    if not stale:
        return _check(
            "agent_holds.stale",
            "OK",
            f"{len(resolved_pruned)} active hold(s), none stale",
            data={"hold_count": len(resolved_pruned)},
        )

    details = tuple(
        f"{display} ({key}): {reason}, now pruned" for key, display, reason in stale
    )[:_MAX_DETAIL_ROWS]
    return _check(
        "agent_holds.stale",
        "WARN",
        f"{len(stale)} stale hold(s) found and pruned",
        details=details,
        data={
            "hold_count": len(resolved_pruned),
            "stale_count": len(stale),
            "stale": [
                {"armer_key": key, "display": display, "reason": reason}
                for key, display, reason in stale
            ],
        },
        next_steps=(
            "No action needed: reading the store (this check, `sase agent "
            "hold list`, or a launch's admission poll) already pruned these. "
            "If holds keep going stale, something armed them and stopped "
            "reading the store before they released -- check for a killed "
            "`sase agent hold run` or a host that went idle.",
        ),
    )


def _read_raw_holds(sase_home: Any) -> dict[str, Any] | None:
    """Return the store's raw ``holds`` map, or ``None`` when absent.

    Raises :class:`_MalformedHoldStore` for anything unreadable or
    misshapen -- distinct from "absent" so the doctor check can WARN
    instead of quietly reporting no holds.
    """
    path = sase_home / _AGENT_HOLD_STATE_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise _MalformedHoldStore(str(exc)) from exc
    if not isinstance(raw, dict):
        raise _MalformedHoldStore("agent hold store is not a JSON object")
    holds = raw.get("holds")
    if not isinstance(holds, dict):
        raise _MalformedHoldStore("agent hold store has no holds map")
    return holds


def _epoch_seconds(value: datetime | float | None) -> float:
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.timestamp()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return datetime.now(UTC).timestamp()


def _check(
    check_id: str,
    status: CheckStatus,
    summary: str,
    *,
    details: tuple[str, ...] = (),
    next_steps: tuple[str, ...] = (),
    data: dict[str, object] | None = None,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        id=check_id,
        group="agent_holds",
        status=status,
        title="Stale agent holds",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data=data or {},
    )


__all__ = [
    "agent_hold_check_specs",
]
