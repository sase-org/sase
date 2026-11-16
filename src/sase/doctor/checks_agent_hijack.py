"""Doctor check for running agents whose meta lacks hijack support."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.hijack import HIJACK_RUNNER_CAPABILITY
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.gate_turn.state import GATE_AGENT_SESSION_ROLE
from sase.plan_chain import agent_session_role_for_suffix

if TYPE_CHECKING:
    from sase.agent.running_listing import RunningAgentInfo
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10
_UNSET: Any = object()


def agent_hijack_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return the ``agent_hijack.*`` doctor check specs."""
    return (
        CheckSpec(
            id="agent_hijack.capability",
            group="agent_hijack",
            title="Hijack capability on running agents",
            runner=lambda: _check_hijack_capability(context),
        ),
    )


def _check_hijack_capability(
    context: DoctorContext,  # noqa: ARG001
    *,
    agents: Iterable[Any] | Any = _UNSET,
    load_meta: Callable[[Any], Mapping[str, Any] | None] | Any = _UNSET,
) -> DiagnosticCheck:
    """Warn when a live LLM runner did not stamp hijack support."""
    rows = _running_agents() if agents is _UNSET else list(agents)
    reader = _load_agent_meta if load_meta is _UNSET else load_meta
    missing: list[str] = []
    scanned = 0
    for row in rows:
        if _skip_row(row):
            continue
        scanned += 1
        meta = reader(row)
        if _has_hijack_capability(meta):
            continue
        name = _row_name(row)
        if name:
            missing.append(name)

    if not missing:
        summary = (
            f"{scanned} running agent turn(s) recorded hijack support"
            if scanned
            else "no running agent turns to check"
        )
        return _check("OK", summary, data={"scanned": scanned, "missing": []})

    details = tuple(
        f"{name}: runner did not record hijack support" for name in missing
    )[:_MAX_DETAIL_ROWS]
    return _check(
        "WARN",
        f"{len(missing)} running agent(s) lack hijack support",
        details=details,
        data={"scanned": scanned, "missing": missing},
        next_steps=(
            "Stop the runner with x, or wait for its next turn so the "
            "bootstrap restamps hijack support.",
        ),
    )


def _running_agents() -> list[RunningAgentInfo]:
    from sase.agent.running_listing import list_running_agents

    return list(list_running_agents())


def _skip_row(row: Any) -> bool:
    if bool(getattr(row, "is_monitor", False)):
        return True
    role = getattr(row, "agent_session_role", None)
    suffix = getattr(row, "role_suffix", None)
    if isinstance(role, str) and role.strip() == GATE_AGENT_SESSION_ROLE:
        return True
    return agent_session_role_for_suffix(suffix) == GATE_AGENT_SESSION_ROLE


def _has_hijack_capability(meta: Mapping[str, Any] | None) -> bool:
    if not isinstance(meta, Mapping):
        return False
    value = meta.get("runner_capabilities")
    return isinstance(value, list) and HIJACK_RUNNER_CAPABILITY in value


def _load_agent_meta(row: Any) -> Mapping[str, Any] | None:
    artifacts_dir = getattr(row, "artifacts_dir", None)
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return None
    try:
        from sase.history.chat_fork.common import load_json_object
    except Exception:
        return None
    try:
        payload = load_json_object(Path(artifacts_dir) / "agent_meta.json")
    except Exception:
        return None
    return payload if isinstance(payload, Mapping) else None


def _row_name(row: Any) -> str:
    name = getattr(row, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""


def _check(
    status: CheckStatus,
    summary: str,
    *,
    details: tuple[str, ...] = (),
    next_steps: tuple[str, ...] = (),
    data: dict[str, object] | None = None,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        id="agent_hijack.capability",
        group="agent_hijack",
        status=status,
        title="Hijack capability on running agents",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data=data or {},
    )


__all__ = [
    "agent_hijack_check_specs",
]
