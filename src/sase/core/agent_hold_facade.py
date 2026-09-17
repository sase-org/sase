"""Python runtime adapter for durable agent holds.

Admission-path readers (:func:`active_agent_hold_records` and friends) stay
fail-open by design: a broken hold store must never strand a waiter. The
CLI/directive-facing service functions below it -- :func:`arm_agent_hold`,
:func:`release_agent_hold`, :func:`list_current_agent_holds` -- are the
opposite: they are direct user actions, so Rust validation and lock-timeout
errors propagate instead of being swallowed.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.agent_hold_liveness import (
    FamilyIndexCache,
    agent_family_settled,
    liveness_facts_for_holds,
    proc_identity_and_terminal,
)
from sase.core.agent_hold_notifications import (
    notify_liveness_dropped_holds,
    upsert_hold_armed_notification,
    upsert_hold_released_notification,
)
from sase.core.agent_hold_pending import (
    capture_pending_targets as _capture_pending_targets,
    format_pending_capture,
    preview_pending_capture,
)
from sase.core.agent_hold_store import (
    epoch_seconds,
    list_holds,
    mapping_payload,
    read_json_mapping,
    release_agent_hold_key,
    validated_holds,
)
from sase.core.agent_hold_types import (
    AgentHoldArmResult,
    AgentHoldServiceError as _AgentHoldServiceError,
    PendingCapture as _PendingCapture,
)
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.procs.models import Proc

LOGGER = logging.getLogger(__name__)


def active_agent_hold_records(
    records: Sequence[AgentArtifactRecordWire] | None = None,
    *,
    now: datetime | float | None = None,
) -> list[dict[str, Any]]:
    """Return validated active holds, or an empty list on hold-store failures."""
    try:
        before, after = _list_and_reconcile_holds(
            records or (), allow_index_scan=records is None, now=now
        )
    except Exception as exc:  # noqa: BLE001 - holds fail open by design.
        LOGGER.warning("agent hold snapshot failed open: %s", exc)
        return []
    notify_liveness_dropped_holds(before, after, now=now)
    return after


def list_current_agent_holds(
    records: Sequence[AgentArtifactRecordWire] | None = None,
    *,
    now: datetime | float | None = None,
) -> list[dict[str, Any]]:
    """Return validated active holds for CLI/directive-facing callers.

    Unlike :func:`active_agent_hold_records`, failures propagate: a CLI
    command should report a broken hold store clearly instead of silently
    showing an empty list.
    """
    before, after = _list_and_reconcile_holds(
        records or (), allow_index_scan=records is None, now=now
    )
    notify_liveness_dropped_holds(before, after, now=now)
    return after


def list_agent_holds_without_liveness(
    *,
    now: datetime | float | None = None,
) -> list[dict[str, Any]]:
    """Return validated holds without applying per-armer liveness facts."""
    return validated_holds(list_holds({}, now=now))


def find_agent_hold(
    armer_key: str,
    *,
    now: datetime | float | None = None,
) -> dict[str, Any] | None:
    """Return the one active hold armed by *armer_key*, if any."""
    for hold in list_current_agent_holds(now=now):
        if mapping_payload(hold.get("armer")).get("key") == armer_key:
            return hold
    return None


def agent_hold_blocks_candidate(
    record: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Evaluate the pure Rust hold predicate for one candidate."""
    blocks = require_rust_binding("agent_hold_blocks_candidate")
    value = blocks(dict(record), dict(candidate))
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise RuntimeError("agent_hold_blocks_candidate returned a non-object block")
    return dict(value)


def _list_and_reconcile_holds(
    records: Sequence[AgentArtifactRecordWire],
    *,
    allow_index_scan: bool,
    now: datetime | float | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(before, after)`` validated holds across a liveness pass.

    ``before`` has expired/malformed rows pruned but no per-armer liveness
    facts applied; ``after`` additionally prunes armers the current
    liveness facts say are dead. Both raise on genuine store failures --
    callers decide whether to fail open.
    """
    snapshot = list_holds({}, now=now)
    before = validated_holds(snapshot)
    if not before:
        return [], []
    liveness = liveness_facts_for_holds(
        before, records, allow_index_scan=allow_index_scan, now=now
    )
    snapshot = list_holds(liveness, now=now)
    return before, validated_holds(snapshot)


def release_proc_agent_holds(
    proc: Proc | Mapping[str, Any] | str,
    *,
    now: datetime | float | None = None,
) -> int:
    """Release every hold armed by a terminal proc identity."""
    proc_id, terminal = proc_identity_and_terminal(proc)
    if not proc_id or not terminal:
        return 0
    released = 0
    try:
        for hold in validated_holds(list_holds({}, now=now)):
            armer = mapping_payload(hold.get("armer"))
            if armer.get("kind") == "proc" and armer.get("proc_id") == proc_id:
                released += int(release_agent_hold_key(str(armer.get("key")), now=now))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("proc agent-hold reconciliation failed for %s: %s", proc_id, exc)
    return released


def reconcile_agent_holds_for_artifact(
    artifacts_dir: str | Path,
    *,
    records: Sequence[AgentArtifactRecordWire] | None = None,
    now: datetime | float | None = None,
) -> int:
    """Release agent-authored holds whose recorded family generation settled."""
    target_dir = str(Path(artifacts_dir))
    released = 0
    try:
        holds = validated_holds(list_holds({}, now=now))
        index_cache = FamilyIndexCache(records or (), allow_scans=records is None)
        for hold in holds:
            armer = mapping_payload(hold.get("armer"))
            if armer.get("kind") != "agent":
                continue
            marker_path = armer.get("done_marker_path")
            if not isinstance(marker_path, str) or not marker_path:
                continue
            root_dir = str(Path(marker_path).parent)
            if root_dir != target_dir:
                continue
            project = armer.get("project")
            if isinstance(project, str) and agent_family_settled(
                root_dir,
                project,
                index_cache,
            ):
                released += int(release_agent_hold_key(str(armer.get("key")), now=now))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "agent hold reconciliation failed for %s: %s",
            target_dir,
            exc,
        )
    return released


def current_armer_wire(
    *,
    pid_override: int | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the armer wire payload for the process invoking a hold action.

    Uses the current agent's metadata when ``SASE_ARTIFACTS_DIR`` is set,
    and a standalone ``cli``-kind armer otherwise.
    """
    current_env = env if env is not None else os.environ
    artifacts_dir = (current_env.get("SASE_ARTIFACTS_DIR") or "").strip()
    if artifacts_dir:
        return agent_armer_wire_for_artifacts(artifacts_dir)
    return _cli_armer_wire(pid_override=pid_override)


def agent_armer_wire_for_artifacts(
    artifacts_dir: str, *, pid_fallback: int | None = None
) -> dict[str, Any]:
    """Build an ``agent``-kind armer wire from one artifacts directory.

    ``pid_fallback`` is used when ``agent_meta.json`` has no integer pid yet,
    for example when a launch-carried hold rebinds to an agent whose runner
    has not finished writing its metadata.
    """
    meta = read_json_mapping(Path(artifacts_dir) / "agent_meta.json")
    name = meta.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _AgentHoldServiceError(
            f"cannot determine agent identity from {artifacts_dir}/agent_meta.json"
        )
    name = name.strip()
    pid = meta.get("pid")
    if not isinstance(pid, int):
        pid = pid_fallback
    family = meta.get("agent_family")
    clan = meta.get("agent_clan")
    return {
        "kind": "agent",
        "key": f"agent:{name}",
        "display": name,
        "project": _project_for_artifacts_dir(artifacts_dir),
        "agent_name": name,
        "family": family if isinstance(family, str) and family else None,
        "clan": clan if isinstance(clan, str) and clan else None,
        "pid": pid,
        "done_marker_path": str(Path(artifacts_dir) / "done.json"),
    }


def _cli_armer_wire(*, pid_override: int | None) -> dict[str, Any]:
    import getpass
    import socket

    # A bare CLI invocation exits the moment `create` returns, so anchoring
    # liveness to its own pid would prune the hold before the caller's next
    # command runs. `run` passes the wrapped command's pid explicitly; a
    # bare `create`/`release` pair anchors to the parent shell instead, so
    # the hold survives for the invoking terminal session (and self-cleans
    # once that session ends), matching the durable-until-TTL-or-release
    # contract manual arm/release scripting depends on.
    pid = pid_override if pid_override is not None else os.getppid()
    from sase.config.core import get_machine_name

    host = get_machine_name() or socket.gethostname() or "local"
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = "unknown"
    return {
        "kind": "cli",
        "key": f"cli:{host}:{pid}",
        "display": f"{user}@{host} (pid {pid})",
        "project": _project_for_cwd(),
        "pid": pid,
    }


def _project_for_artifacts_dir(artifacts_dir: str) -> str:
    from sase.core.agent_artifact_paths import parse_agent_artifact_path

    try:
        parsed = parse_agent_artifact_path(artifacts_dir)
    except (OSError, RuntimeError, ValueError):
        parsed = None
    if parsed is not None and parsed.project_name:
        return parsed.project_name
    return _project_for_cwd()


def _project_for_cwd() -> str:
    from sase.bead.project_name import infer_project_name_from_cwd

    project = infer_project_name_from_cwd()
    if not project:
        raise _AgentHoldServiceError(
            "cannot determine the current project; run from inside a SASE "
            "project checkout, or from an agent shell with SASE_ARTIFACTS_DIR set"
        )
    return project


def _hold_scope_wire(scope: str, *, project: str) -> dict[str, Any]:
    """Build the scope wire payload for ``--scope project|host``."""
    if scope == "host":
        return {"kind": "host"}
    return {"kind": "project", "project": project}


def _hold_selectors_wire(
    *,
    names: Sequence[str] = (),
    tribes: Sequence[str] = (),
    hoods: Sequence[str] = (),
    future: bool = False,
    artifact_dirs: Sequence[str] = (),
) -> dict[str, Any]:
    """Build the selectors wire payload from CLI-facing selector inputs."""
    return {
        "artifact_dirs": list(artifact_dirs),
        "names": list(names),
        "hoods": list(hoods),
        "tribes": [_normalize_tribe(tribe) for tribe in tribes],
        "future": bool(future),
    }


def _normalize_tribe(value: str) -> str:
    stripped = value.strip()
    return stripped[1:] if stripped.startswith("@") else stripped


def arm_agent_hold(
    *,
    names: Sequence[str] = (),
    tribes: Sequence[str] = (),
    hoods: Sequence[str] = (),
    future: bool = False,
    pending: bool = False,
    scope: str = "project",
    ttl_seconds: float,
    pid_override: int | None = None,
    armer: Mapping[str, Any] | None = None,
    selectors: Mapping[str, Any] | None = None,
    now: datetime | float | None = None,
) -> AgentHoldArmResult:
    """Arm a durable hold and upsert its "armed" lifecycle notification.

    Errors propagate: this is a direct CLI/directive action, not an
    admission-path read, so Rust validation and lock-timeout failures must
    reach the caller instead of being swallowed.

    ``armer`` defaults to :func:`current_armer_wire`. ``selectors``, when
    given, is the base selectors payload; ``names``, ``tribes``, ``hoods``,
    and ``future`` are ignored in that case.
    """
    armer_wire = (
        dict(armer)
        if armer is not None
        else current_armer_wire(pid_override=pid_override)
    )
    scope_wire = _hold_scope_wire(scope, project=armer_wire["project"])
    capture: _PendingCapture | None = None
    artifact_dirs: tuple[str, ...] = ()
    if pending:
        capture = _capture_pending_targets(
            project=armer_wire["project"] if scope == "project" else None
        )
        artifact_dirs = capture.artifact_dirs
    if selectors is not None:
        selectors_wire = dict(selectors)
        if pending:
            merged = {*selectors_wire.get("artifact_dirs", ()), *artifact_dirs}
            merged.discard(_own_agent_artifacts_dir(armer_wire))
            selectors_wire["artifact_dirs"] = sorted(merged)
    else:
        selectors_wire = _hold_selectors_wire(
            names=names,
            tribes=tribes,
            hoods=hoods,
            future=future,
            artifact_dirs=artifact_dirs,
        )
    arm = require_rust_binding("agent_hold_arm_relative")
    record = dict(
        arm(
            str(sase_home()),
            armer_wire,
            scope_wire,
            selectors_wire,
            float(ttl_seconds),
            {},
            epoch_seconds(now),
        )
    )
    upsert_hold_armed_notification(record, capture, now=now)
    return AgentHoldArmResult(record=record, capture=capture)


def _own_agent_artifacts_dir(armer: Mapping[str, Any]) -> str | None:
    if armer.get("kind") != "agent":
        return None
    marker_path = armer.get("done_marker_path")
    if not isinstance(marker_path, str) or not marker_path:
        return None
    return str(Path(marker_path).parent)


def release_agent_hold(
    armer_key: str,
    *,
    now: datetime | float | None = None,
    display: str | None = None,
    reason: str = "Released explicitly",
) -> bool:
    """Release one hold by armer key, surfacing failures to the caller.

    This is the CLI/service counterpart to the fail-open
    ``release_agent_hold_key`` used by background reconciliation.
    """
    release = require_rust_binding("agent_hold_release")
    removed = bool(release(str(sase_home()), armer_key, {}, epoch_seconds(now)))
    if removed:
        upsert_hold_released_notification(
            {"key": armer_key, "display": display or armer_key},
            reason=reason,
            now=now,
        )
    return removed


def rebind_agent_hold(
    old_key: str,
    new_armer: Mapping[str, Any],
    *,
    now: datetime | float | None = None,
) -> dict[str, Any] | None:
    """Rebind one hold's armer in place, keeping its scope/selectors/timing.

    Returns ``None`` without writing anything when *old_key* has no active
    hold. Errors propagate like :func:`arm_agent_hold`, and this sends no
    lifecycle notification.
    """
    rebind = require_rust_binding("agent_hold_rebind")
    record = rebind(
        str(sase_home()), old_key, dict(new_armer), None, epoch_seconds(now)
    )
    return dict(record) if record is not None else None


def resolve_hold_ttl_seconds(requested: float | None) -> float:
    """Return *requested* seconds, or the configured default when ``None``.

    Raises:
        ValueError: naming the configured maximum, when *requested* exceeds
            ``get_agent_hold_max_ttl_seconds()``.
    """
    from sase.config.core import (
        get_agent_hold_default_ttl_seconds,
        get_agent_hold_max_ttl_seconds,
    )

    if requested is None:
        return get_agent_hold_default_ttl_seconds()
    max_seconds = get_agent_hold_max_ttl_seconds()
    if requested > max_seconds:
        raise ValueError(
            f"--ttl exceeds the configured maximum ({_format_ttl_seconds(max_seconds)})"
        )
    return requested


def _format_ttl_seconds(value: float) -> str:
    if value == int(value):
        return f"{int(value)}s"
    return f"{value}s"


def candidate_created_at_from_timestamp(timestamp: str | None) -> float | None:
    """Return a configured-timezone epoch for a 14-digit artifact timestamp."""
    if not timestamp or len(timestamp) != 14 or not timestamp.isdigit():
        return None
    try:
        from sase.core.time import get_timezone

        parsed = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
        return parsed.replace(tzinfo=get_timezone()).timestamp()
    except (OSError, OverflowError, ValueError):
        return None


__all__ = [
    "AgentHoldArmResult",
    "active_agent_hold_records",
    "agent_armer_wire_for_artifacts",
    "agent_hold_blocks_candidate",
    "arm_agent_hold",
    "candidate_created_at_from_timestamp",
    "current_armer_wire",
    "find_agent_hold",
    "format_pending_capture",
    "list_agent_holds_without_liveness",
    "list_current_agent_holds",
    "preview_pending_capture",
    "reconcile_agent_holds_for_artifact",
    "rebind_agent_hold",
    "release_agent_hold",
    "release_proc_agent_holds",
    "resolve_hold_ttl_seconds",
]
