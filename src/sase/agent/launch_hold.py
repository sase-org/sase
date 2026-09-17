"""Primitives for launch-carried ``%hold`` arming, rebinding, and release.

No call sites yet: the typed-arm and bootstrap-arm phases of this epic wire
these primitives into dispatch. Imports of the facade and the Rust bindings
stay lazy throughout, matching :mod:`sase.core.agent_hold_liveness`'s own
precedent for avoiding a `sase.agent` package-init circular import.
"""

from __future__ import annotations

import logging
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


__all__ = [
    "LAUNCH_HOLD_KEY_ENV",
    "LAUNCH_HOLD_RELEASE_REASON",
    "LaunchHoldError",
    "arm_hold_for_fields",
    "hold_fields_for",
    "launch_unit_armer",
    "rebind_hold",
    "release_hold_best_effort",
    "runner_anchor_armer",
    "unit_hold_key",
]
