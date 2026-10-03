"""Shared SIGTERM kill-source classification for agent runners.

A SIGTERM with no user-kill intent and no handoff marker used to be reported
as a user kill. This module gives every kill path one shared classifier so
``run_agent_exec`` (the killed-iteration handler), ``run_agent_exec_retry``
(the retry-wait interruption), and ``run_agent_runner`` (the ``SystemExit``
path) all report the same provenance:

- ``user``: an explicit user-kill intent marker exists.
- ``handoff``: a plan, questions, monitor, gate, or pipe marker predates the
  kill, so the runner's own handoff SIGTERM caused the failure.
- ``external``: everything else (an OOM teardown of the launcher's scope, a
  manual ``kill``, a host stop, ...), with OOM evidence when the runner's
  cgroup recorded OOM kills during the run.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.user_kill import has_user_kill_intent

HANDOFF_MARKERS = (
    ".sase_plan_pending",
    ".sase_questions_pending",
    ".sase_monitor_pending",
    ".sase_gate_pending",
    ".sase_pipe_pending",
)

_OOM_BASELINE: dict[str, Any] | None = None


@dataclass(frozen=True)
class KillProvenance:
    """Kill-source classification plus optional OOM evidence."""

    source: str
    evidence: dict[str, Any] | None = None


def classify_runner_kill(
    artifacts_dir: str,
    *,
    kill_time: float | None = None,
    proc_root: Path = Path("/proc"),
    sysfs_root: Path = Path("/sys/fs/cgroup"),
) -> KillProvenance:
    """Classify a runner SIGTERM without consuming any marker files."""

    if has_user_kill_intent(artifacts_dir):
        return KillProvenance(source="user")
    if _handoff_marker_predates_kill(artifacts_dir, kill_time):
        return KillProvenance(source="handoff")
    return KillProvenance(
        source="external",
        evidence=oom_kill_evidence(proc_root=proc_root, sysfs_root=sysfs_root),
    )


def snapshot_oom_baseline(
    *,
    proc_root: Path = Path("/proc"),
    sysfs_root: Path = Path("/sys/fs/cgroup"),
) -> None:
    """Snapshot this runner's cgroup OOM counter for later kill evidence.

    Best effort: a missing cgroup mount, permission error, or parse failure
    simply leaves no baseline, in which case kills carry no OOM evidence.
    Call this where the runner installs its SIGTERM handler.
    """

    global _OOM_BASELINE
    try:
        baseline = _read_oom_state(proc_root=proc_root, sysfs_root=sysfs_root)
    except Exception:
        baseline = None
    _OOM_BASELINE = baseline


def reset_oom_baseline() -> None:
    """Clear the snapshot (tests and loop-iteration boundaries)."""

    global _OOM_BASELINE
    _OOM_BASELINE = None


def oom_kill_evidence(
    *,
    proc_root: Path = Path("/proc"),
    sysfs_root: Path = Path("/sys/fs/cgroup"),
) -> dict[str, Any] | None:
    """Return OOM evidence for an external kill, or ``None`` when unavailable."""

    baseline = _OOM_BASELINE
    if not isinstance(baseline, dict):
        return None
    try:
        current = _read_oom_state(proc_root=proc_root, sysfs_root=sysfs_root)
    except Exception:
        return None
    if current is None:
        return None
    if current.get("cgroup_path") != baseline.get("cgroup_path"):
        return None
    try:
        delta = int(current.get("oom_kill", 0)) - int(baseline.get("oom_kill", 0))
    except (TypeError, ValueError):
        return None
    if delta <= 0:
        return None
    unit = _unit_from_cgroup_path(str(baseline.get("cgroup_path") or ""))
    evidence: dict[str, Any] = {"oom_kill_delta": delta}
    if unit is not None:
        evidence["cgroup_unit"] = unit
    return evidence


def record_kill_provenance(
    artifacts_dir: str,
    state: Any | None = None,
    *,
    kill_time: float | None = None,
    proc_root: Path = Path("/proc"),
    sysfs_root: Path = Path("/sys/fs/cgroup"),
) -> KillProvenance:
    """Classify a runner SIGTERM, count it, and stash it on *state*.

    Handoff kills keep their existing outcome handling: no metric and no
    ``kill_source``. ``user`` and ``external`` kills increment
    ``AGENT_KILLS{reason=...}`` and set ``kill_source``/``kill_evidence`` on
    *state* when it accepts those attributes. External kills also print the
    one-line classification after the signal handler's ``Received SIGTERM``
    line. Never raises: classification is best effort.
    """

    import sys as _sys

    try:
        provenance = classify_runner_kill(
            artifacts_dir,
            kill_time=kill_time,
            proc_root=proc_root,
            sysfs_root=sysfs_root,
        )
    except Exception:
        return KillProvenance(source="external")
    if provenance.source == "handoff":
        return provenance
    try:
        from sase.telemetry.metrics import AGENT_KILLS

        AGENT_KILLS.labels(reason=provenance.source).inc()
    except Exception:
        pass
    if state is not None:
        try:
            state.kill_source = provenance.source
            state.kill_evidence = provenance.evidence
        except Exception:
            pass
    if provenance.source == "external":
        try:
            print(format_kill_classification(provenance), file=_sys.stderr)
        except Exception:
            pass
    return provenance


def format_kill_classification(provenance: KillProvenance) -> str:
    """Render the one-line kill-source classification for the runner log."""

    if provenance.source != "external":
        return (
            f"Kill source: {provenance.source} "
            f"({'user-kill intent marker present' if provenance.source == 'user' else 'handoff marker predates the kill'})"
        )
    line = "Kill source: external (no user-kill intent or handoff marker)"
    evidence = provenance.evidence or {}
    delta = evidence.get("oom_kill_delta")
    unit = evidence.get("cgroup_unit")
    if isinstance(delta, int) and delta > 0:
        line += f"; cgroup {unit or 'unknown'} recorded {delta} OOM kill(s) since start"
    return line


def _handoff_marker_predates_kill(
    artifacts_dir: str,
    kill_time: float | None,
) -> bool:
    for marker in HANDOFF_MARKERS:
        data = _read_marker(artifacts_dir, marker)
        if data is not None and _marker_predates_kill(data, kill_time):
            return True
    return False


def _read_marker(artifacts_dir: str, marker: str) -> dict[str, Any] | None:
    try:
        with open(Path(artifacts_dir) / marker, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _marker_predates_kill(
    marker_data: dict[str, Any],
    kill_time: float | None,
) -> bool:
    if kill_time is None:
        return True
    marker_time = marker_data.get("timestamp")
    if not isinstance(marker_time, int | float):
        return True
    return float(marker_time) <= kill_time + 0.001


def _read_oom_state(
    *,
    proc_root: Path,
    sysfs_root: Path,
) -> dict[str, Any] | None:
    cgroup_path = _own_cgroup_path(proc_root=proc_root)
    if not cgroup_path:
        return None
    events_path = sysfs_root / cgroup_path.relative_to("/") / "memory.events"
    try:
        events = events_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    oom_kill = 0
    for line in events.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] == "oom_kill":
            try:
                oom_kill = int(fields[1])
            except ValueError:
                return None
            break
    else:
        return None
    return {"cgroup_path": str(cgroup_path), "oom_kill": oom_kill}


def _own_cgroup_path(*, proc_root: Path) -> Path | None:
    try:
        cgroup = (proc_root / str(os.getpid()) / "cgroup").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    for line in cgroup.splitlines():
        fields = line.split(":", 2)
        path = fields[2] if len(fields) == 3 else line
        if path.startswith("/"):
            return Path(path)
    return None


def _unit_from_cgroup_path(path: str) -> str | None:
    for component in reversed([part for part in path.split("/") if part]):
        if component.endswith((".scope", ".service")):
            return component
    return None


__all__ = [
    "HANDOFF_MARKERS",
    "KillProvenance",
    "classify_runner_kill",
    "format_kill_classification",
    "oom_kill_evidence",
    "reset_oom_baseline",
    "snapshot_oom_baseline",
]
