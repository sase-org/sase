"""Wrapper liveness observation and lost-run reconciliation."""

from __future__ import annotations

import os
import signal
from pathlib import Path
import time
from typing import Any

from sase.core.process_identity import (
    identity_from_previous_boot,
    process_identity_token,
)
from sase.core.tool_run import tool_run_list, tool_run_reconcile, tool_run_show
from sase.tool.owner import observe_owner_fact
from sase.tool.stage_protocol import ingest_event_file


_LOST_REASON = "runner exited without settling"
_LAUNCHER_EXIT_REASON = "launcher exit is not proof of launch failure"
_LAUNCHER_PROOF_OWNER_STATES = frozenset({"missing", "terminal"})
_UNSETTLED_STATES = ("created", "running")
_RECONCILE_LIMIT = 1000
_REAP_TERM_GRACE_SECONDS = 2.0
_REAP_POLL_SECONDS = 0.05


def current_boot_id() -> str:
    """Return the current kernel boot id, or ``""`` when unavailable."""

    try:
        return (
            Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        )
    except OSError:
        token = process_identity_token(os.getpid())
        return token.partition(":")[0]


def _is_created_handoff(run: dict[str, Any]) -> bool:
    return (
        str(run.get("state") or "") == "created"
        and str(run.get("launch_mode") or "") == "handoff"
    )


def _probe_process(
    pid_raw: object,
    recorded_boot: str,
    recorded_identity: object,
    *,
    label: str,
) -> tuple[str, str | None]:
    """Return ``(observation, reason)`` for one recorded process identity.

    The observation is ``alive``, ``dead``, or ``unknown``; *label* names the
    process (wrapper or launcher) in the reasons.
    """

    if pid_raw is None:
        return "unknown", f"{label} pid was not recorded"
    try:
        pid = int(pid_raw)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return "unknown", f"{label} pid is not an integer"

    if recorded_boot:
        boot = current_boot_id()
        if boot and recorded_boot != boot:
            return "dead", None
    if identity_from_previous_boot(recorded_identity):
        return "dead", None

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "dead", None
    except PermissionError:
        return "unknown", f"{label} liveness is permission-denied"
    except OSError:
        return "unknown", f"{label} liveness is unavailable"

    current = process_identity_token(pid)
    recorded = recorded_identity if isinstance(recorded_identity, str) else ""
    if recorded and current and current != recorded:
        return "dead", None
    if recorded and not current:
        return "unknown", f"{label} identity is unreadable"
    return "alive", None


def _observe_wrapper(run: dict[str, Any]) -> dict[str, Any]:
    """Return a core liveness fact for one unsettled wrapper."""

    fact: dict[str, Any] = {
        "run_id": str(run.get("run_id") or ""),
        "wrapper_pid": run.get("wrapper_pid"),
        "boot_id": run.get("boot_id"),
        "process_start_identity": run.get("process_start_identity"),
    }
    observation, reason = _probe_process(
        run.get("wrapper_pid"),
        str(run.get("boot_id") or ""),
        run.get("process_start_identity"),
        label="wrapper",
    )
    if observation == "dead":
        return _dead_or_launcher_unknown(run, fact)
    fact["observation"] = observation
    if reason is not None:
        fact["reason"] = reason
    return fact


def _observe_launcher(
    run: dict[str, Any], owner: dict[str, Any] | None
) -> dict[str, Any]:
    """Return a core liveness fact for a created hand-off's launcher.

    A dead launcher is reported as ``dead`` only when the owner is missing or
    terminal; otherwise it stays ``unknown``, because a launcher that exited
    after submitting its proc is normal and never proof of a failed launch.
    """

    launcher = run.get("launcher")
    if not isinstance(launcher, dict):
        return _observe_wrapper(run)
    fact: dict[str, Any] = {
        "run_id": str(run.get("run_id") or ""),
        "wrapper_pid": launcher.get("pid"),
        "boot_id": launcher.get("boot_id"),
        "process_start_identity": launcher.get("process_start_identity"),
    }
    observation, reason = _probe_process(
        launcher.get("pid"),
        str(launcher.get("boot_id") or ""),
        launcher.get("process_start_identity"),
        label="launcher",
    )
    owner_state = str(owner.get("state") or "") if owner is not None else ""
    if observation == "dead":
        if owner_state in _LAUNCHER_PROOF_OWNER_STATES:
            fact["observation"] = "dead"
            fact["reason"] = "launcher exited before the owner started the command"
        else:
            fact["observation"] = "unknown"
            fact["reason"] = _LAUNCHER_EXIT_REASON
        return fact
    fact["observation"] = observation
    if reason is not None:
        fact["reason"] = reason
    return fact


def _liveness_fact(run: dict[str, Any], owner: dict[str, Any] | None) -> dict[str, Any]:
    """Return the liveness fact for *run*, with its owner fact attached."""

    if _is_created_handoff(run):
        fact = _observe_launcher(run, owner)
    else:
        fact = _observe_wrapper(run)
    if owner is not None:
        fact["owner"] = owner
    return fact


def _dead_or_launcher_unknown(
    run: dict[str, Any], fact: dict[str, Any]
) -> dict[str, Any]:
    """Downgrade a dead launcher observation for a created hand-off."""

    if _is_created_handoff(run):
        fact["observation"] = "unknown"
        fact["reason"] = _LAUNCHER_EXIT_REASON
        return fact
    fact["observation"] = "dead"
    fact["reason"] = _LOST_REASON
    return fact


def _events_path(run: dict[str, Any]) -> Path | None:
    logs = run.get("logs")
    if not isinstance(logs, dict):
        return None
    raw = logs.get("events_path")
    if not raw:
        return None
    return Path(str(raw))


def reconcile_unsettled_tool_runs(*, reap_orphans: bool = False) -> dict[str, Any]:
    """Collect bounded liveness facts and persist lost transitions.

    Reconcile authorizes reap candidates (a recorded pgid plus the recorded
    child identity) for runs whose wrapper is definitively dead, but Rust
    never signals. Only the executor passes ``reap_orphans=True``: read-only
    store paths (``tool runs``, ``tool show``) reconcile without reaping and
    never signal a group.
    """

    facts: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    owned_run_ids: set[str] = set()
    for state in _UNSETTLED_STATES:
        try:
            listed = tool_run_list(
                {
                    "schema_version": 1,
                    "state": state,
                    "limit": _RECONCILE_LIMIT,
                }
            )
        except Exception as exc:  # noqa: BLE001 - queries must fail open.
            diagnostics.append(str(exc))
            continue
        diagnostics.extend(str(item) for item in listed.get("diagnostics") or ())
        for run in listed.get("runs") or ():
            if not isinstance(run, dict):
                continue
            events_path = _events_path(run)
            run_id = str(run.get("run_id") or "")
            if events_path is not None and run_id:
                diagnostics.extend(ingest_event_file(events_path, run_id))
            facts.append(_liveness_fact(run, observe_owner_fact(run)))
            if run_id and run.get("owner_kind"):
                owned_run_ids.add(run_id)
    if not facts and not diagnostics:
        try:
            result = tool_run_reconcile({"schema_version": 1, "facts": []})
        except Exception as exc:  # noqa: BLE001 - missing store is not fatal.
            return {
                "schema_version": 1,
                "marked_lost": [],
                "persisted": False,
                "diagnostics": [str(exc)],
            }
        return _maybe_reap(
            result, reap_orphans=reap_orphans, owned_run_ids=owned_run_ids
        )
    try:
        result = tool_run_reconcile({"schema_version": 1, "facts": facts})
    except Exception as exc:  # noqa: BLE001 - read-only/busy must not crash.
        return {
            "schema_version": 1,
            "marked_lost": [],
            "persisted": False,
            "diagnostics": [*diagnostics, str(exc)],
        }
    merged = list(result.get("diagnostics") or ())
    merged.extend(diagnostics)
    result["diagnostics"] = list(dict.fromkeys(str(item) for item in merged))
    _publish_settlements(result)
    return _maybe_reap(result, reap_orphans=reap_orphans, owned_run_ids=owned_run_ids)


def _is_unsettled_handoff(run: dict[str, Any]) -> bool:
    return (
        str(run.get("state") or "") in _UNSETTLED_STATES
        and str(run.get("launch_mode") or "") == "handoff"
    )


def reconcile_handoff_run(
    run_id: str, owner_fact: dict[str, Any] | None
) -> dict[str, Any]:
    """Reconcile one hand-off run against an owner fact the caller already holds.

    Proc settlement runs before the proc row is finished, so the row still
    reads ``settling``; the settlement hook passes the terminal fact it holds.
    This pass never reaps, never launches anything, and never raises: every
    failure is a diagnostics envelope.
    """

    envelope: dict[str, Any] = {
        "schema_version": 1,
        "marked_lost": [],
        "persisted": False,
        "settled": [],
        "diagnostics": [],
    }
    try:
        run = tool_run_show(run_id).get("run")
        if not isinstance(run, dict) or not _is_unsettled_handoff(run):
            return envelope
        diagnostics: list[str] = []
        events_path = _events_path(run)
        if events_path is not None:
            diagnostics.extend(ingest_event_file(events_path, run_id))
        fact = _liveness_fact(run, owner_fact)
        result = tool_run_reconcile({"schema_version": 1, "facts": [fact]})
        merged = [*(result.get("diagnostics") or ()), *diagnostics]
        result["diagnostics"] = list(dict.fromkeys(str(item) for item in merged))
        return result
    except Exception as exc:  # noqa: BLE001 - settlement hooks must never wedge.
        envelope["diagnostics"] = [str(exc)]
        return envelope


def _publish_settlements(result: dict[str, Any]) -> None:
    """Deliver the once-only settlement notification for reconciled hand-offs."""

    settled = result.get("settled") or ()
    if not settled:
        return
    try:
        from sase.tool.notify import deliver_handoff_settlement
    except Exception as exc:  # noqa: BLE001 - delivery never fails reconcile.
        result["diagnostics"] = [*(result.get("diagnostics") or ()), str(exc)]
        return
    diagnostics = list(result.get("diagnostics") or ())
    for entry in settled:
        run_id = str(entry.get("run_id") or "") if isinstance(entry, dict) else ""
        if not run_id:
            continue
        try:
            status = deliver_handoff_settlement(run_id)
        except Exception as exc:  # noqa: BLE001 - delivery never fails reconcile.
            diagnostics.append(f"run {run_id}: settlement notification error ({exc})")
        else:
            if status == "failed":
                diagnostics.append(f"run {run_id}: settlement notification failed")
    result["diagnostics"] = list(dict.fromkeys(str(item) for item in diagnostics))


def _maybe_reap(
    result: dict[str, Any], *, reap_orphans: bool, owned_run_ids: set[str]
) -> dict[str, Any]:
    """Signal authorized reap candidates when the caller owns the lifecycle.

    Core only authorizes candidates for runs without an owner; as defense in
    depth, a candidate whose run has an owner is refused here too, so this
    module never signals a group an owner is responsible for.
    """

    if not reap_orphans:
        return result
    candidates = result.get("reap_candidates") or ()
    reaped: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        run_id = str(candidate.get("run_id") or "")
        if run_id in owned_run_ids:
            reaped.append(
                f"run {run_id}: run has an owner; not signaling its process group"
            )
            continue
        reaped.append(_reap_authorized_candidate(candidate))
    if reaped:
        diagnostics = list(result.get("diagnostics") or ())
        diagnostics.extend(reaped)
        result["diagnostics"] = list(dict.fromkeys(str(item) for item in diagnostics))
    return result


def _reap_authorized_candidate(candidate: dict[str, Any]) -> str:
    """TERM-then-KILL one authorized group, or explain why it was spared.

    Only a candidate reconcile authorized is ever considered, and even then a
    PID-reuse mismatch, an unreadable identity, a permission error, a missing
    process, or our own process group is a diagnostic — never a signal.
    """

    run_id = str(candidate.get("run_id") or "")
    label = f"run {run_id}" if run_id else "run with no id"
    try:
        pgid = int(candidate.get("pgid"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return f"{label}: reap candidate pgid is not an integer; not signaling"
    if pgid <= 0:
        return f"{label}: reap candidate pgid {pgid} is invalid; not signaling"
    if pgid == os.getpgrp():
        return f"{label}: reap candidate is our own process group; not signaling"
    recorded = candidate.get("child_process_start_identity")
    if not isinstance(recorded, str) or not recorded:
        return f"{label}: child identity was not recorded; not signaling pgid {pgid}"
    try:
        current = process_identity_token(pgid)
    except Exception:  # noqa: BLE001 - identity reads are best effort.
        current = ""
    if not current:
        return (
            f"{label}: identity of pgid {pgid} is unreadable; not signaling "
            "(PID reuse is never proof)"
        )
    if current != recorded:
        return (
            f"{label}: identity of pgid {pgid} no longer matches the recorded "
            "child; not signaling (stale pgid, PID reuse?)"
        )
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return f"{label}: pgid {pgid} is already gone; nothing to reap"
    except PermissionError:
        return f"{label}: permission denied signaling pgid {pgid}; not signaling"
    except OSError as exc:
        return f"{label}: cannot signal pgid {pgid} ({exc}); not signaling"
    deadline = time.monotonic() + _REAP_TERM_GRACE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except (ProcessLookupError, PermissionError):
            return f"{label}: reaped pgid {pgid} with SIGTERM"
        except OSError:
            return f"{label}: pgid {pgid} liveness is unavailable; not escalating"
        time.sleep(_REAP_POLL_SECONDS)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return f"{label}: reaped pgid {pgid} with SIGTERM"
    except OSError as exc:
        return f"{label}: cannot escalate pgid {pgid} ({exc}); not signaling"
    return f"{label}: reaped pgid {pgid} with SIGTERM then SIGKILL"


__all__ = [
    "current_boot_id",
    "reconcile_handoff_run",
    "reconcile_unsettled_tool_runs",
]
