"""Primitives for launch-carried ``%hold`` arming, rebinding, and release.

No call sites yet: the typed-arm and bootstrap-arm phases of this epic wire
these primitives into dispatch. Imports of the facade and the Rust bindings
stay lazy throughout, matching :mod:`sase.core.agent_hold_liveness`'s own
precedent for avoiding a `sase.agent` package-init circular import.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sase.xprompt.hold_directive import HoldFields

if TYPE_CHECKING:
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


def hold_fields_for(payload: Any) -> HoldFields | None:
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


def arm_hold_for_fields(
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


def launch_unit_armer(
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


def runner_anchor_armer(
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
        arm_hold_for_fields(hold, armer=armer)
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


__all__ = [
    "LAUNCH_HOLD_KEY_ENV",
    "LAUNCH_HOLD_RELEASE_REASON",
    "LaunchHoldError",
    "arm_bootstrap_hold",
    "arm_hold_for_fields",
    "hold_fields_for",
    "launch_unit_armer",
    "rebind_hold",
    "release_hold_best_effort",
    "runner_anchor_armer",
    "unit_hold_key",
]
