"""Agent-session attach launch plan resolution."""

from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable
from typing import Any

from sase.agent import _agent_session_attach_candidates as _candidates
from sase.agent import _agent_session_attach_directives as _directives
from sase.agent import _agent_session_attach_types as _types
from sase.plan_chain import AGENT_SESSION_SEPARATOR, canonical_plan_chain_suffix

_AgentSessionSnapshot = Callable[[str], Any]
_DismissedIdentityDicts = Callable[[], list[dict[str, str | None]]]


def resolve_agent_session_attach_plan(
    directive: _types.AgentSessionAttachDirective,
    *,
    project_name: str,
    pending_agent_session_parents: list[_types.AgentSessionAttachSibling] | None = None,
    agent_session_snapshot: _AgentSessionSnapshot | None = None,
    dismissed_identity_dicts: _DismissedIdentityDicts | None = None,
) -> _types.AgentSessionAttachLaunchPlan:
    snapshot_factory = agent_session_snapshot or _candidates.agent_session_snapshot
    dismissed_factory = dismissed_identity_dicts or _candidates.dismissed_identity_dicts
    snapshot = snapshot_factory(project_name)
    pending_siblings = tuple(pending_agent_session_parents or ())
    sibling_candidates = [
        _candidates.candidate_from_sibling(sibling)
        for sibling in pending_siblings
        if sibling.can_attach_parent
    ]
    request = {
        "schema_version": 1,
        "parent_name": directive.parent,
        "project_name": project_name,
        "candidates": [
            *[_candidates.candidate_from_record(record) for record in snapshot.records],
            *sibling_candidates,
        ],
        "dismissed": dismissed_factory(),
    }

    binding = _candidates.resolve_binding()
    from sase.core.agent_identity_facade import (
        current_owner_agent_name_lookup_candidates,
    )

    result: dict[str, Any] = {"kind": "absent"}
    for parent_candidate in current_owner_agent_name_lookup_candidates(
        directive.parent
    ):
        result = dict(binding({**request, "parent_name": parent_candidate}))
        if result.get("kind") != "absent":
            break
    kind = result.get("kind")
    if kind not in {"resolved", "running"}:
        raise _types.AgentSessionAttachError(
            _candidates.resolution_error_message(directive, result, project_name)
        )

    parent = dict(result.get("parent") or {})
    if not parent:
        raise _types.AgentSessionAttachError(
            f"Cannot attach session member to '{directive.parent}': "
            "resolved parent metadata is no longer available."
        )
    sibling_by_artifact_dir = _candidates.sibling_by_artifact_dir(pending_siblings)
    parent_sibling = sibling_by_artifact_dir.get(str(parent["artifact_dir"]))
    parent_record = _candidates.record_by_artifact_dir(snapshot.records).get(
        parent["artifact_dir"]
    )
    if parent_record is None or parent_record.agent_meta is None:
        if parent_sibling is None:
            raise _types.AgentSessionAttachError(
                f"Cannot attach session member to '{directive.parent}': "
                "resolved parent metadata is no longer available."
            )

    parent_name = str(parent["name"])
    raw_parent_base = (
        parent_sibling.agent_session_base_name
        if parent_sibling is not None
        else _candidates.agent_session_base_from_record(parent_record, parent_name)
    )
    from sase.core.agent_identity_facade import normalize_owned_agent_name

    parent_base = normalize_owned_agent_name(raw_parent_base)
    role_suffix = _resolve_role_suffix(
        directive.suffix,
        parent_base,
        snapshot.records,
        pending_agent_session_parents=pending_agent_session_parents,
    )
    agent_name = f"{parent_base}{role_suffix}"
    _ensure_generated_agent_session_name(agent_name, directive, role_suffix)
    if parent_sibling is not None:
        parent_agent_session_role_suffix = parent_sibling.agent_session_root_role_suffix
    else:
        assert parent_record is not None and parent_record.agent_meta is not None
        from sase.agent._agent_session_promotion import agent_session_root_role_suffix

        parent_meta = parent_record.agent_meta
        parent_agent_session_role_suffix = agent_session_root_role_suffix(
            {
                "role_suffix": getattr(parent_meta, "role_suffix", None),
                "plan_chain_root": getattr(parent_meta, "plan_chain_root", False),
                "approve": getattr(parent_meta, "approve", False),
                "plan": getattr(parent_meta, "plan", False),
            }
        )
    parent_needs_rename = parent_name == raw_parent_base
    parent_agent_session_member_name = (
        f"{parent_base}{parent_agent_session_role_suffix}"
        if parent_needs_rename
        else parent_name
    )
    if parent_needs_rename:
        _ensure_generated_agent_session_name(
            parent_agent_session_member_name,
            directive,
            parent_agent_session_role_suffix,
        )
        _ensure_agent_session_name_available(
            parent_agent_session_member_name,
            directive,
            snapshot.records,
            pending_agent_session_parents=pending_agent_session_parents,
            member_kind="original session member",
        )
    if agent_name == parent_agent_session_member_name:
        raise _types.AgentSessionAttachError(
            f"Agent session member '{agent_name}' is reserved for the original "
            f"parent. Use %i(@, family={directive.parent}) to allocate the next "
            "free suffix."
        )
    _ensure_agent_session_name_available(
        agent_name,
        directive,
        snapshot.records,
        pending_agent_session_parents=pending_agent_session_parents,
    )
    role = _agent_session_role(role_suffix, directive.suffix)
    if parent_sibling is not None:
        parent_cl_name = parent_sibling.cl_name
        parent_workspace_dir = parent_sibling.workspace_dir
        parent_workspace_num = parent_sibling.workspace_num
        model_alias_overrides = dict(parent_sibling.model_alias_overrides)
        parent_agent_clan = parent_sibling.agent_clan
        parent_agent_clan_generation = parent_sibling.agent_clan_generation
    else:
        if parent_record is None or parent_record.agent_meta is None:
            raise _types.AgentSessionAttachError(
                f"Cannot attach session member to '{directive.parent}': "
                "resolved parent metadata is no longer available."
            )
        parent_cl_name = _candidates.record_cl_name(parent_record)
        parent_workspace_dir = parent_record.agent_meta.workspace_dir
        parent_workspace_num = parent_record.agent_meta.workspace_num
        model_alias_overrides = _read_parent_model_alias_overrides(
            str(parent["artifact_dir"])
        )
        parent_agent_clan = getattr(parent_record.agent_meta, "agent_clan", None)
        parent_agent_clan_generation = getattr(
            parent_record.agent_meta,
            "agent_clan_generation",
            None,
        )
        if parent_agent_clan and not parent_agent_clan_generation:
            parent_agent_clan_generation = (
                getattr(parent_record.agent_meta, "parent_timestamp", None)
                or parent_record.timestamp
            )
    if parent_agent_clan:
        parent_agent_clan = normalize_owned_agent_name(parent_agent_clan)

    return _types.AgentSessionAttachLaunchPlan(
        parent_arg=directive.parent,
        suffix_arg=directive.suffix,
        parent_name=parent_name,
        parent_base=parent_base,
        parent_timestamp=parent["timestamp"],
        parent_artifacts_dir=parent["artifact_dir"],
        role_suffix=role_suffix,
        agent_name=agent_name,
        agent_session_role=role,
        parent_agent_session_member_name=parent_agent_session_member_name,
        parent_agent_session_role_suffix=parent_agent_session_role_suffix,
        parent_needs_rename=parent_needs_rename,
        parent_project_name=project_name,
        parent_is_running=kind == "running",
        parent_cl_name=parent_cl_name,
        parent_agent_clan=parent_agent_clan,
        parent_agent_clan_generation=parent_agent_clan_generation,
        parent_workspace_dir=parent_workspace_dir,
        parent_workspace_num=parent_workspace_num,
        sase_plan=_candidates.agent_session_sase_plan(snapshot.records, parent_base)
        if role == "code"
        else None,
        model_alias_overrides=model_alias_overrides,
    )


def _read_parent_model_alias_overrides(artifacts_dir: str) -> dict[str, str]:
    """Read the additive launch-scoped override field from parent metadata."""
    try:
        data = json.loads(
            (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    value = data.get("model_alias_overrides") if isinstance(data, dict) else None
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str) and key and item
    }


def _resolve_role_suffix(
    suffix_arg: str,
    parent_base: str,
    records: list[Any],
    *,
    pending_agent_session_parents: list[_types.AgentSessionAttachSibling] | None = None,
) -> str:
    known_suffixes = [
        *_candidates.known_agent_session_suffixes(records, parent_base),
        *_candidates.known_agent_session_suffixes_from_siblings(
            pending_agent_session_parents or [],
            parent_base,
        ),
    ]
    if suffix_arg == "@":
        from sase.plan_chain import allocate_agent_session_child_suffix

        return allocate_agent_session_child_suffix(
            parent_base,
            f"{AGENT_SESSION_SEPARATOR}@",
            extra_reserved_suffixes=tuple(known_suffixes),
        )
    if suffix_arg.startswith(AGENT_SESSION_SEPARATOR) and suffix_arg.endswith("@"):
        from sase.plan_chain import allocate_agent_session_child_suffix

        return allocate_agent_session_child_suffix(
            parent_base,
            suffix_arg,
            extra_reserved_suffixes=tuple(known_suffixes),
        )
    canonical = canonical_plan_chain_suffix(suffix_arg)
    if canonical is not None:
        return canonical
    return _directives.normalize_agent_session_suffix_arg(suffix_arg)


def _ensure_generated_agent_session_name(
    agent_name: str,
    directive: _types.AgentSessionAttachDirective,
    role_suffix: str,
) -> None:
    """Reject a composed member name whose role suffix is not terminal.

    Attaching to a parent whose own name already carries a legacy session-member
    marker (such as ``fi--code.f0``) would compose a name the strict
    identity rules cannot classify, which is how names like
    ``fi--code.f0--code`` reached the artifact store. Fail loudly instead of
    silently renaming an agent the user explicitly asked for.
    """
    from sase.agent.names import generated_agent_name_is_valid

    if generated_agent_name_is_valid(agent_name):
        return
    role = role_suffix.removeprefix(AGENT_SESSION_SEPARATOR)
    raise _types.AgentSessionAttachError(
        f"Cannot attach session member '{role}' to '{directive.parent}': the "
        f"generated name '{agent_name}' would place its "
        f"'{AGENT_SESSION_SEPARATOR}{role}' suffix outside the final name "
        "segment. Relaunch the parent under a name without "
        f"'{AGENT_SESSION_SEPARATOR}' and attach the member to it."
    )


def _agent_session_role(role_suffix: str, suffix_arg: str) -> str:
    from sase.plan_chain import agent_session_role_for_suffix

    if suffix_arg == "@":
        return "agent"
    role = agent_session_role_for_suffix(role_suffix)
    if role is not None:
        return role
    token = role_suffix.removeprefix(AGENT_SESSION_SEPARATOR)
    if token.isdigit():
        return "agent"
    return token


def _ensure_agent_session_name_available(
    agent_name: str,
    directive: _types.AgentSessionAttachDirective,
    records: list[Any] | None = None,
    *,
    pending_agent_session_parents: list[_types.AgentSessionAttachSibling] | None = None,
    member_kind: str = "session member",
) -> None:
    from sase.agent.names import get_reserved_agent_names

    known_names = set(get_reserved_agent_names())
    if records is not None:
        known_names.update(_candidates.known_agent_names(records))
    known_names.update(
        _candidates.known_agent_names_from_siblings(pending_agent_session_parents or [])
    )
    from sase.core.agent_identity_facade import current_owner_agent_name_key

    known_keys = {current_owner_agent_name_key(name) for name in known_names}
    if current_owner_agent_name_key(agent_name) in known_keys:
        raise _types.AgentSessionAttachError(
            f"Agent {member_kind} '{agent_name}' already exists. "
            f"Use %i(@, family={directive.parent}) to allocate the next free suffix."
        )


__all__ = [
    "resolve_agent_session_attach_plan",
]
