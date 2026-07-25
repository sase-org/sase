"""Family attach launch plan resolution."""

from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable
from typing import Any

from sase.agent import _family_attach_candidates as _candidates
from sase.agent import _family_attach_directives as _directives
from sase.agent import _family_attach_types as _types
from sase.plan_chain import AGENT_FAMILY_SEPARATOR

_AgentFamilySnapshot = Callable[[str], Any]
_DismissedIdentityDicts = Callable[[], list[dict[str, str | None]]]


def resolve_family_attach_plan(
    directive: _types.FamilyAttachDirective,
    *,
    project_name: str,
    pending_family_parents: list[_types.FamilyAttachSibling] | None = None,
    agent_family_snapshot: _AgentFamilySnapshot | None = None,
    dismissed_identity_dicts: _DismissedIdentityDicts | None = None,
) -> _types.FamilyAttachLaunchPlan:
    snapshot_factory = agent_family_snapshot or _candidates.agent_family_snapshot
    dismissed_factory = dismissed_identity_dicts or _candidates.dismissed_identity_dicts
    snapshot = snapshot_factory(project_name)
    pending_siblings = tuple(pending_family_parents or ())
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
        raise _types.FamilyAttachError(
            _candidates.resolution_error_message(directive, result, project_name)
        )

    parent = dict(result.get("parent") or {})
    if not parent:
        raise _types.FamilyAttachError(
            f"Cannot attach family member to '{directive.parent}': "
            "resolved parent metadata is no longer available."
        )
    sibling_by_artifact_dir = _candidates.sibling_by_artifact_dir(pending_siblings)
    parent_sibling = sibling_by_artifact_dir.get(str(parent["artifact_dir"]))
    parent_record = _candidates.record_by_artifact_dir(snapshot.records).get(
        parent["artifact_dir"]
    )
    if parent_record is None or parent_record.agent_meta is None:
        if parent_sibling is None:
            raise _types.FamilyAttachError(
                f"Cannot attach family member to '{directive.parent}': "
                "resolved parent metadata is no longer available."
            )

    parent_name = str(parent["name"])
    raw_parent_base = (
        parent_sibling.family_base
        if parent_sibling is not None
        else _candidates.family_base(parent_record, parent_name)
    )
    from sase.core.agent_identity_facade import normalize_owned_agent_name

    parent_base = normalize_owned_agent_name(raw_parent_base)
    role_suffix = _resolve_role_suffix(
        directive.suffix,
        parent_base,
        snapshot.records,
        pending_family_parents=pending_family_parents,
    )
    agent_name = f"{parent_base}{role_suffix}"
    _ensure_generated_family_name(agent_name, directive, role_suffix)
    if parent_sibling is not None:
        parent_family_role_suffix = parent_sibling.family_root_role_suffix
    else:
        assert parent_record is not None and parent_record.agent_meta is not None
        from sase.agent._family_promotion import family_root_role_suffix

        parent_meta = parent_record.agent_meta
        parent_family_role_suffix = family_root_role_suffix(
            {
                "role_suffix": getattr(parent_meta, "role_suffix", None),
                "plan_chain_root": getattr(parent_meta, "plan_chain_root", False),
                "approve": getattr(parent_meta, "approve", False),
                "plan": getattr(parent_meta, "plan", False),
            }
        )
    parent_needs_rename = parent_name == raw_parent_base
    parent_family_member_name = (
        f"{parent_base}{parent_family_role_suffix}"
        if parent_needs_rename
        else parent_name
    )
    if parent_needs_rename:
        _ensure_generated_family_name(
            parent_family_member_name,
            directive,
            parent_family_role_suffix,
        )
        _ensure_family_name_available(
            parent_family_member_name,
            directive,
            snapshot.records,
            pending_family_parents=pending_family_parents,
            member_kind="original family member",
        )
    if agent_name == parent_family_member_name:
        raise _types.FamilyAttachError(
            f"Agent family member '{agent_name}' is reserved for the original "
            f"parent. Use %i(@, family={directive.parent}) to allocate the next "
            "free suffix."
        )
    _ensure_family_name_available(
        agent_name,
        directive,
        snapshot.records,
        pending_family_parents=pending_family_parents,
    )
    role = _family_role(role_suffix, directive.suffix)
    if parent_sibling is not None:
        parent_cl_name = parent_sibling.cl_name
        parent_workspace_dir = parent_sibling.workspace_dir
        parent_workspace_num = parent_sibling.workspace_num
        model_alias_overrides = dict(parent_sibling.model_alias_overrides)
        parent_agent_clan = parent_sibling.agent_clan
        parent_agent_clan_generation = parent_sibling.agent_clan_generation
    else:
        if parent_record is None or parent_record.agent_meta is None:
            raise _types.FamilyAttachError(
                f"Cannot attach family member to '{directive.parent}': "
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

    return _types.FamilyAttachLaunchPlan(
        parent_arg=directive.parent,
        suffix_arg=directive.suffix,
        parent_name=parent_name,
        parent_base=parent_base,
        parent_timestamp=parent["timestamp"],
        parent_artifacts_dir=parent["artifact_dir"],
        role_suffix=role_suffix,
        agent_name=agent_name,
        agent_family_role=role,
        parent_family_member_name=parent_family_member_name,
        parent_family_role_suffix=parent_family_role_suffix,
        parent_needs_rename=parent_needs_rename,
        parent_project_name=project_name,
        parent_is_running=kind == "running",
        parent_cl_name=parent_cl_name,
        parent_agent_clan=parent_agent_clan,
        parent_agent_clan_generation=parent_agent_clan_generation,
        parent_workspace_dir=parent_workspace_dir,
        parent_workspace_num=parent_workspace_num,
        sase_plan=_candidates.family_sase_plan(snapshot.records, parent_base)
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
    pending_family_parents: list[_types.FamilyAttachSibling] | None = None,
) -> str:
    if suffix_arg == "@":
        from sase.plan_chain import allocate_agent_family_child_suffix

        known_suffixes = [
            *_candidates.known_family_suffixes(records, parent_base),
            *_candidates.known_family_suffixes_from_siblings(
                pending_family_parents or [],
                parent_base,
            ),
        ]
        return allocate_agent_family_child_suffix(
            parent_base,
            f"{AGENT_FAMILY_SEPARATOR}@",
            extra_reserved_suffixes=tuple(known_suffixes),
        )
    return _directives.normalize_family_suffix_arg(suffix_arg)


def _ensure_generated_family_name(
    agent_name: str,
    directive: _types.FamilyAttachDirective,
    role_suffix: str,
) -> None:
    """Reject a composed member name whose role suffix is not terminal.

    Attaching to a parent whose own name already carries a family marker (a
    legacy spelling such as ``fi--code.f0``) would compose a name the strict
    identity rules cannot classify, which is how names like
    ``fi--code.f0--code`` reached the artifact store. Fail loudly instead of
    silently renaming an agent the user explicitly asked for.
    """
    from sase.agent.names import generated_agent_name_is_valid

    if generated_agent_name_is_valid(agent_name):
        return
    role = role_suffix.removeprefix(AGENT_FAMILY_SEPARATOR)
    raise _types.FamilyAttachError(
        f"Cannot attach family member '{role}' to '{directive.parent}': the "
        f"generated name '{agent_name}' would place its "
        f"'{AGENT_FAMILY_SEPARATOR}{role}' suffix outside the final name "
        "segment. Relaunch the parent under a name without "
        f"'{AGENT_FAMILY_SEPARATOR}' and attach the member to it."
    )


def _family_role(role_suffix: str, suffix_arg: str) -> str:
    from sase.plan_chain import agent_family_role_for_suffix

    role = agent_family_role_for_suffix(role_suffix)
    if role is not None:
        return role
    token = role_suffix.removeprefix(AGENT_FAMILY_SEPARATOR)
    if suffix_arg == "@" or token.isdigit():
        return "feedback"
    return token


def _ensure_family_name_available(
    agent_name: str,
    directive: _types.FamilyAttachDirective,
    records: list[Any] | None = None,
    *,
    pending_family_parents: list[_types.FamilyAttachSibling] | None = None,
    member_kind: str = "family member",
) -> None:
    from sase.agent.names import get_reserved_agent_names

    known_names = set(get_reserved_agent_names())
    if records is not None:
        known_names.update(_candidates.known_agent_names(records))
    known_names.update(
        _candidates.known_agent_names_from_siblings(pending_family_parents or [])
    )
    from sase.core.agent_identity_facade import current_owner_agent_name_key

    known_keys = {current_owner_agent_name_key(name) for name in known_names}
    if current_owner_agent_name_key(agent_name) in known_keys:
        raise _types.FamilyAttachError(
            f"Agent {member_kind} '{agent_name}' already exists. "
            f"Use %i(@, family={directive.parent}) to allocate the next free suffix."
        )


__all__ = [
    "resolve_family_attach_plan",
]
