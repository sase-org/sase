"""Primitives for launch-carried ``%hold`` arming, rebinding, and release.

Imports of the facade and the Rust bindings stay lazy throughout, matching
:mod:`sase.core.agent_hold_liveness`'s own precedent for avoiding a
``sase.agent`` package-init circular import.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.launch_admission_store import RECEIPT_FILENAME, UNITS_DIRNAME
from sase.core.atomic_json import write_json_marker_atomic
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchPlanWire,
    LaunchUnitWire,
    ProcUnitWire,
)
from sase.xprompt.hold_directive import HoldFields

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult
    from sase.core.agent_hold_types import AgentHoldArmResult

LOGGER = logging.getLogger(__name__)

LAUNCH_HOLD_KEY_ENV = "SASE_LAUNCH_HOLD_KEY"
LAUNCH_HOLD_RELEASE_REASON = "launch unit ended without dispatch"


class LaunchHoldError(RuntimeError):
    """Raised when a launch-carried ``%hold`` action fails.

    Every message is prefixed with ``%hold: `` so it reads as a directive
    failure wherever it surfaces (admission errors, bootstrap failures).
    """


def unit_hold_key(request_id: str, logical_id: str) -> str:
    """Return the durable-hold key for one typed-launch unit."""
    from sase.core.rust import require_rust_binding

    binding = require_rust_binding("launch_unit_hold_key")
    return str(binding(request_id, logical_id))


def _hold_fields_for(payload: Any) -> HoldFields | None:
    """Return the ``%hold`` fields carried by an agent/proc unit payload.

    ``payload`` is either an ``AgentUnitWire``/``ProcUnitWire`` dataclass
    (whose ``.hold`` is a ``HoldFieldsWire``) or a plain directive mapping
    (whose ``"hold"`` entry is already a mapping).
    """
    hold = (
        payload.get("hold")
        if isinstance(payload, Mapping)
        else getattr(payload, "hold", None)
    )
    if hold is None:
        return None
    if isinstance(hold, Mapping):
        return HoldFields.from_mapping(hold)
    from sase.core.agent_launch_wire_conversion import agent_launch_wire_to_json_dict

    data = agent_launch_wire_to_json_dict(hold)
    return HoldFields.from_mapping(data if isinstance(data, Mapping) else None)


def _arm_hold_for_fields(
    fields: HoldFields,
    *,
    armer: Mapping[str, Any],
    now: float | None = None,
) -> AgentHoldArmResult:
    """Arm a durable hold from parsed ``%hold`` fields for *armer*.

    Any failure -- selector expansion, TTL validation, kin rejection, a
    store error -- is re-raised as :class:`LaunchHoldError`.
    """
    try:
        from sase.core.agent_hold_facade import arm_agent_hold, resolve_hold_ttl_seconds
        from sase.xprompt.hold_directive import hold_fields_to_selectors

        selectors = hold_fields_to_selectors(fields)
        ttl_seconds = resolve_hold_ttl_seconds(fields.ttl_seconds)
        return arm_agent_hold(
            armer=armer,
            selectors=selectors,
            scope=fields.scope or "project",
            pending=fields.pending,
            ttl_seconds=ttl_seconds,
            now=now,
        )
    except Exception as exc:  # noqa: BLE001 - re-raised as a typed hold error.
        raise LaunchHoldError(f"%hold: {exc}") from exc


def rebind_hold(
    old_key: str,
    new_armer: Mapping[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Rebind a durable hold's armer, wrapping failures as ``LaunchHoldError``."""
    try:
        from sase.core.agent_hold_facade import rebind_agent_hold

        return rebind_agent_hold(old_key, new_armer, now=now)
    except Exception as exc:  # noqa: BLE001 - re-raised as a typed hold error.
        raise LaunchHoldError(f"%hold: {exc}") from exc


def release_hold_best_effort(
    key: str, *, reason: str, display: str | None = None
) -> bool:
    """Best-effort release: log and swallow failures instead of raising."""
    try:
        from sase.core.agent_hold_facade import release_agent_hold

        return release_agent_hold(key, reason=reason, display=display)
    except Exception as exc:  # noqa: BLE001 - release is cleanup, not settlement.
        LOGGER.warning("launch hold release failed for %s: %s", key, exc)
        return False


def _launch_unit_armer(
    unit: Any,
    *,
    request_id: str,
    project: str,
    pid: int,
    done_marker_path: str,
) -> dict[str, Any]:
    """Build a validated ``launch``-kind armer for one typed-launch unit."""
    from sase.core.agent_launch_wire_conversion import agent_launch_wire_to_json_dict
    from sase.core.rust import require_rust_binding

    binding = require_rust_binding("launch_unit_hold_armer")
    unit_payload = agent_launch_wire_to_json_dict(unit)
    return dict(binding(unit_payload, request_id, project, pid, done_marker_path))


def _runner_anchor_armer(
    armer: Mapping[str, Any], *, pid: int, artifacts_dir: str
) -> dict[str, Any]:
    """Return a copy of a ``launch`` armer re-anchored to a spawned runner."""
    from pathlib import Path

    anchored = dict(armer)
    anchored["pid"] = pid
    anchored["done_marker_path"] = str(Path(artifacts_dir) / "done.json")
    return anchored


def _wrap_hold_error(exc: Exception) -> LaunchHoldError:
    if isinstance(exc, LaunchHoldError):
        return exc
    return LaunchHoldError(f"%hold: {exc}")


def arm_bootstrap_hold(
    state: Any,
    info: Any,
    retry_handoff: Any,
    launch_hold_key: str | None,
) -> None:
    """Arm or rebind a launch-carried hold during runner bootstrap."""
    from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV
    from sase.xprompt.hold_directive import agent_holds_enabled

    if (
        RUNNER_CODE_REFRESHED_ENV in os.environ
        or retry_handoff is not None
        or not agent_holds_enabled()
    ):
        return

    hold = getattr(info, "hold", None)
    if hold is None:
        if launch_hold_key:
            release_hold_best_effort(
                launch_hold_key,
                reason="launch hold key had no hold directive",
                display=launch_hold_key,
            )
        return

    try:
        from sase.core.agent_hold_facade import agent_armer_wire_for_artifacts

        armer = agent_armer_wire_for_artifacts(
            state.artifacts_dir,
            pid_fallback=os.getpid(),
        )
        if launch_hold_key:
            rebound = rebind_hold(launch_hold_key, armer)
            if rebound is None:
                print(
                    (
                        "Warning: launch hold already ended before runner "
                        f"bootstrap could bind it: {launch_hold_key}"
                    ),
                    file=sys.stderr,
                )
            return
        _arm_hold_for_fields(hold, armer=armer)
    except LaunchHoldError as exc:
        if launch_hold_key:
            release_hold_best_effort(
                launch_hold_key,
                reason="launch hold rebind failed",
                display=launch_hold_key,
            )
        raise exc
    except Exception as exc:  # noqa: BLE001 - surfaced as a directive failure.
        hold_error = _wrap_hold_error(exc)
        if launch_hold_key:
            release_hold_best_effort(
                launch_hold_key,
                reason="launch hold rebind failed",
                display=launch_hold_key,
            )
        raise hold_error from exc


def launch_hold_dispatch_env(
    unit: LaunchUnitWire,
    request_id: str | None,
) -> dict[str, str]:
    """Return the environment that carries a pre-armed hold to a runner."""
    if not request_id or _hold_fields_for(unit.payload) is None:
        return {}
    from sase.xprompt.hold_directive import agent_holds_enabled

    if not agent_holds_enabled():
        return {}
    return {LAUNCH_HOLD_KEY_ENV: unit_hold_key(request_id, unit.logical_id)}


def pre_arm_typed_plan_holds(
    root: Path,
    plan: LaunchPlanWire,
    request_id: str,
) -> None:
    """Pre-arm hold-carrying typed units before admission can dispatch them."""
    from sase.xprompt.hold_directive import agent_holds_enabled

    units = [
        unit
        for unit in sorted(plan.units, key=lambda item: item.source_order)
        if _hold_fields_for(unit.payload) is not None
    ]
    if not units or not agent_holds_enabled():
        return
    if not request_id:
        raise LaunchHoldError("%hold: typed launch hold arming requires request_id")

    units_dir = root / UNITS_DIRNAME
    units_dir.mkdir(parents=True, exist_ok=True)
    armed: list[tuple[str, Path]] = []
    try:
        for unit in units:
            marker_path = _unit_hold_marker_path(root, unit.logical_id)
            if marker_path.is_file():
                continue
            fields = _hold_fields_for(unit.payload)
            if fields is None:
                continue
            armer = _launch_unit_armer(
                unit,
                request_id=request_id,
                project=_unit_project(plan, unit),
                pid=os.getpid(),
                done_marker_path=str(root / RECEIPT_FILENAME),
            )
            result = _arm_hold_for_fields(fields, armer=armer)
            record = result.record
            key = str((record.get("armer") or {}).get("key") or armer["key"])
            armed.append((key, marker_path))
            write_json_marker_atomic(
                marker_path,
                {
                    "logical_id": unit.logical_id,
                    "key": key,
                    "armed_at_unix": time.time(),
                    "expires_at": record.get("expires_at"),
                },
            )
    except Exception as exc:  # noqa: BLE001 - rollback before surfacing as hold error.
        for key, marker_path in armed:
            release_hold_best_effort(
                key,
                reason="launch hold pre-arm rollback",
                display=marker_path.stem,
            )
            try:
                marker_path.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("failed to remove launch hold marker %s", marker_path)
        if isinstance(exc, LaunchHoldError):
            raise
        raise LaunchHoldError(f"%hold: {exc}") from exc


def reanchor_pending_unit_holds(
    root: Path,
    plan: LaunchPlanWire,
    request_id: str,
    *,
    pid: int,
) -> None:
    """Re-anchor bundle-held launch records to the live coordinator process."""
    del request_id
    for unit in plan.units:
        if _hold_fields_for(unit.payload) is None:
            continue
        key = _marker_key(root, unit.logical_id)
        if key is None:
            continue
        record = _hold_record_without_liveness(key)
        if record is None:
            continue
        armer = _bundle_launch_armer(record, root)
        if armer is None:
            continue
        new_armer = dict(armer)
        new_armer["pid"] = pid
        try:
            rebind_hold(key, new_armer)
        except LaunchHoldError as exc:
            LOGGER.warning(
                "launch hold coordinator re-anchor failed for %s: %s", key, exc
            )


def reanchor_dispatched_agent_hold(
    root: Path,
    unit: LaunchUnitWire,
    request_id: str,
    spawned: list[AgentLaunchResult],
) -> None:
    """Re-anchor a dispatched agent unit's launch record to its spawned runner."""
    if not request_id or _hold_fields_for(unit.payload) is None or not spawned:
        return
    first = spawned[0]
    pid = int(getattr(first, "pid", 0) or 0)
    artifacts_dir = str(getattr(first, "artifacts_dir", "") or "")
    if pid <= 0 or not artifacts_dir:
        return
    key = _marker_key(root, unit.logical_id)
    if key is None:
        return
    record = _hold_record_without_liveness(key)
    if record is None:
        return
    armer = _bundle_launch_armer(record, root)
    if armer is None:
        return
    try:
        rebind_hold(
            key, _runner_anchor_armer(armer, pid=pid, artifacts_dir=artifacts_dir)
        )
    except LaunchHoldError as exc:
        LOGGER.warning("launch hold runner re-anchor failed for %s: %s", key, exc)


def release_unit_hold_if_terminal(
    unit: LaunchUnitWire,
    request_id: str,
    *,
    reason: str = LAUNCH_HOLD_RELEASE_REASON,
) -> None:
    """Release a pre-dispatch launch key for a unit that will not dispatch."""
    if not request_id or _hold_fields_for(unit.payload) is None:
        return
    try:
        key = unit_hold_key(request_id, unit.logical_id)
    except Exception as exc:  # noqa: BLE001 - cleanup must not mask admission outcome.
        LOGGER.warning(
            "launch hold key resolution failed for %s: %s", unit.logical_id, exc
        )
        return
    release_hold_best_effort(key, reason=reason, display=unit.logical_id)


def _unit_hold_marker_path(root: Path, logical_id: str) -> Path:
    return root / UNITS_DIRNAME / f"{logical_id}.hold.json"


def _marker_key(root: Path, logical_id: str) -> str | None:
    try:
        import json

        data = json.loads(
            _unit_hold_marker_path(root, logical_id).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    if not isinstance(data, Mapping):
        return None
    key = data.get("key")
    return key if isinstance(key, str) and key else None


def _hold_record_without_liveness(key: str) -> dict[str, Any] | None:
    from sase.core.agent_hold_facade import list_agent_holds_without_liveness

    for record in list_agent_holds_without_liveness():
        armer = record.get("armer")
        if isinstance(armer, Mapping) and armer.get("key") == key:
            return record
    return None


def _bundle_launch_armer(
    record: Mapping[str, Any],
    root: Path,
) -> dict[str, Any] | None:
    armer = record.get("armer")
    if not isinstance(armer, Mapping):
        return None
    if armer.get("kind") != "launch":
        return None
    if armer.get("done_marker_path") != str(root / RECEIPT_FILENAME):
        return None
    return dict(armer)


def _unit_project(plan: LaunchPlanWire, unit: LaunchUnitWire) -> str:
    payload = unit.payload
    if isinstance(payload, ProcUnitWire):
        return _proc_unit_project(payload, plan.selected_project)
    if isinstance(payload, AgentUnitWire):
        from sase.agent.launch_admission_runtime import resolve_agent_unit_project

        project = resolve_agent_unit_project(payload, plan.selected_project)
        if project:
            return project
    if plan.selected_project:
        return plan.selected_project
    return _infer_project_from_cwd()


def _proc_unit_project(payload: ProcUnitWire, selected_project: str | None) -> str:
    if payload.selected_project:
        return payload.selected_project
    if selected_project:
        return selected_project
    return _infer_project_from_cwd()


def _infer_project_from_cwd() -> str:
    try:
        from sase.bead.project_name import infer_project_name_from_cwd

        project = infer_project_name_from_cwd()
        if project:
            return project
    except Exception:  # noqa: BLE001 - host-scoped holds can still match.
        pass
    return "unknown"


__all__ = [
    "LAUNCH_HOLD_KEY_ENV",
    "LAUNCH_HOLD_RELEASE_REASON",
    "LaunchHoldError",
    "arm_bootstrap_hold",
    "launch_hold_dispatch_env",
    "pre_arm_typed_plan_holds",
    "reanchor_dispatched_agent_hold",
    "reanchor_pending_unit_holds",
    "rebind_hold",
    "release_unit_hold_if_terminal",
    "release_hold_best_effort",
    "unit_hold_key",
]
