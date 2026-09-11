"""Lazy wire validators for continuation capture records."""

from __future__ import annotations

from sase.core.continuation_wire import (
    AgentDeltaWire,
    ContinuationIntentWire,
    ContinuationNodeWire,
    MonitorResultWire,
)


def validate_agent_delta_capture(
    delta: AgentDeltaWire,
    *,
    allow_missing_validation: bool,
) -> dict[str, str]:
    try:
        from sase.core.continuation_facade import validate_agent_delta

        validate_agent_delta(delta)
        return {"status": "ok"}
    except (AttributeError, ModuleNotFoundError) as exc:
        if allow_missing_validation:
            return {"status": "unavailable", "message": str(exc)}
        raise


def validate_continuation_node_capture(
    node: ContinuationNodeWire,
    *,
    allow_missing_validation: bool,
) -> dict[str, str]:
    try:
        from sase.core.continuation_facade import validate_continuation_node

        validate_continuation_node(node)
        return {"status": "ok"}
    except (AttributeError, ModuleNotFoundError) as exc:
        if allow_missing_validation:
            return {"status": "unavailable", "message": str(exc)}
        raise


def validate_continuation_intent_capture(
    intent: ContinuationIntentWire,
    *,
    allow_missing_validation: bool,
) -> dict[str, str]:
    try:
        from sase.core.continuation_facade import validate_continuation_intent

        validate_continuation_intent(intent)
        return {"status": "ok"}
    except (AttributeError, ModuleNotFoundError) as exc:
        if allow_missing_validation:
            return {"status": "unavailable", "message": str(exc)}
        raise


def validate_monitor_result_capture(
    result: MonitorResultWire,
    *,
    allow_missing_validation: bool,
) -> dict[str, str]:
    try:
        from sase.core.continuation_facade import validate_monitor_result

        validate_monitor_result(result)
        return {"status": "ok"}
    except (AttributeError, ModuleNotFoundError) as exc:
        if allow_missing_validation:
            return {"status": "unavailable", "message": str(exc)}
        raise
