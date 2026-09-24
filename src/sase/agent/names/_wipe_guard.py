"""Fail-closed guard: a member wipe never deletes its agent-session root."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.agent.names._registry_scan_payloads import (
    agent_session_from_payload,
    owner_identity_names,
)
from sase.agent.names._wipe_payload import read_json_object
from sase.agent.names._wipe_plan import WipePlan
from sase.plan_chain import (
    PLAN_CHAIN_ROOT_FIELD,
    agent_session_base,
    agent_session_role_value,
)


def session_root_removal_refusal(
    target_name: str,
    plan: WipePlan,
    batch_names: set[str],
) -> str | None:
    """Return a refusal when *plan* would remove a session root nobody asked for.

    Forced reuse of one session member (``P--code``) must replace only that
    member and its own descendants. A closure that reaches the session root
    (``P--plan``) while the root's own names are not wipe targets means a
    shared name leaked into the plan, so the whole batch is refused rather
    than deleting the session out from under its agent-session-attach parent.
    """
    session = agent_session_base(target_name)
    if session is None:
        return None
    for path in sorted(plan.artifact_dirs):
        meta = read_json_object(path / "agent_meta.json")
        if not _is_session_root(meta, session):
            continue
        root_names = owner_identity_names(meta, read_json_object(path / "done.json"))
        if root_names & batch_names:
            continue
        root_label = ", ".join(sorted(root_names)) or "<unnamed>"
        return (
            f"forced reuse of '{target_name}' would remove agent-session "
            f"root '{root_label}' ({path}); refusing to wipe"
        )
    return None


def _is_session_root(meta: Mapping[str, Any] | None, session: str) -> bool:
    if meta is None or agent_session_from_payload(dict(meta)) != session:
        return False
    return (
        agent_session_role_value(meta) == "root"
        or meta.get(PLAN_CHAIN_ROOT_FIELD) is True
        or not meta.get("parent_timestamp")
    )
