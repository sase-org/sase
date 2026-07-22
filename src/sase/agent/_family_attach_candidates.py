"""Family attach artifact candidates and resolution support."""

from __future__ import annotations

import re
from typing import Any

from sase.agent import _family_attach_types as _types
from sase.plan_chain import AGENT_FAMILY_SEPARATOR


def agent_family_snapshot(project_name: str) -> Any:
    from sase.core.agent_scan_facade import (
        default_agent_artifact_index_path,
        query_agent_artifact_index,
        scan_agent_artifacts,
    )
    from sase.core.agent_scan_wire import (
        AgentArtifactIndexQueryWire,
        AgentArtifactScanOptionsWire,
    )
    from sase.core.paths import sase_projects_dir

    projects_root = sase_projects_dir()
    options = AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        only_projects=(project_name,),
    )
    index_path = default_agent_artifact_index_path()
    if index_path.is_file():
        try:
            return query_agent_artifact_index(
                index_path,
                projects_root,
                AgentArtifactIndexQueryWire(
                    include_active=True,
                    include_recent_completed=False,
                    include_full_history=True,
                    active_limit=None,
                    recent_completed_limit=None,
                    include_hidden=True,
                ),
                options,
            )
        except (OSError, RuntimeError, ValueError, ImportError, AttributeError):
            pass
    return scan_agent_artifacts(projects_root, options)


def candidate_from_record(record: Any) -> dict[str, Any]:
    meta = record.agent_meta
    name = ""
    if meta is not None:
        name = meta.name or meta.workflow_name or ""
    return {
        "name": name,
        "workflow_name": None if meta is None else meta.workflow_name,
        "project_name": record.project_name,
        "artifact_dir": str(record.artifact_dir),
        "timestamp": record.timestamp,
        "cl_name": record_cl_name(record) or record.project_name,
        "raw_suffix": record.timestamp,
        "parent_timestamp": None if meta is None else meta.parent_timestamp,
        "is_terminal": bool(record.has_done_marker),
    }


def candidate_from_sibling(sibling: _types.FamilyAttachSibling) -> dict[str, Any]:
    return {
        "name": sibling.name,
        "workflow_name": sibling.family_base,
        "project_name": sibling.project_name,
        "artifact_dir": sibling.artifact_dir,
        "timestamp": sibling.timestamp,
        "cl_name": sibling.cl_name or sibling.project_name,
        "raw_suffix": sibling.timestamp,
        "parent_timestamp": None,
        "is_terminal": False,
    }


def record_cl_name(record: Any) -> str | None:
    meta = record.agent_meta
    if meta is not None:
        for value in (meta.cl_name, meta.changespec_name):
            if value:
                return value
    if record.done is not None and record.done.cl_name:
        return record.done.cl_name
    if record.workflow_state is not None and record.workflow_state.cl_name:
        return record.workflow_state.cl_name
    if record.running is not None and record.running.cl_name:
        return record.running.cl_name
    return None


def dismissed_identity_dicts() -> list[dict[str, str | None]]:
    from sase.ace.dismissed_agents import load_dismissed_agents

    return [
        {
            "agent_type": getattr(agent_type, "value", str(agent_type)),
            "cl_name": cl_name,
            "raw_suffix": raw_suffix,
        }
        for agent_type, cl_name, raw_suffix in load_dismissed_agents()
    ]


def record_by_artifact_dir(records: list[Any]) -> dict[str, Any]:
    return {str(record.artifact_dir): record for record in records}


def sibling_by_artifact_dir(
    siblings: tuple[_types.FamilyAttachSibling, ...],
) -> dict[str, _types.FamilyAttachSibling]:
    return {sibling.artifact_dir: sibling for sibling in siblings}


def artifacts_timestamp_from_launch_timestamp(timestamp: str) -> str:
    if re.fullmatch(r"\d{14}", timestamp):
        return timestamp

    from sase.artifacts import convert_timestamp_to_artifacts_format

    return convert_timestamp_to_artifacts_format(timestamp)


def family_base(record: Any, parent_name: str) -> str:
    meta = record.agent_meta
    if meta is not None and meta.agent_family:
        return meta.agent_family
    from sase.plan_chain import agent_family_base

    return agent_family_base(parent_name) or parent_name


def known_family_suffixes(records: list[Any], parent_base: str) -> list[str]:
    from sase.core.machine_hood_facade import canonical_local_agent_name_key

    suffixes: list[str] = []
    parent_key = canonical_local_agent_name_key(parent_base)
    for record in records:
        meta = record.agent_meta
        if meta is None:
            continue
        if (
            meta.agent_family
            and canonical_local_agent_name_key(meta.agent_family) != parent_key
        ):
            continue
        if meta.role_suffix:
            suffixes.append(meta.role_suffix)
            continue
        if meta.name:
            local_name = canonical_local_agent_name_key(meta.name)
            prefix = f"{parent_key}{AGENT_FAMILY_SEPARATOR}"
            if local_name.startswith(prefix):
                suffixes.append(local_name[len(parent_key) :])
    return suffixes


def known_family_suffixes_from_siblings(
    siblings: list[_types.FamilyAttachSibling],
    parent_base: str,
) -> list[str]:
    from sase.core.machine_hood_facade import canonical_local_agent_name_key

    suffixes: list[str] = []
    parent_key = canonical_local_agent_name_key(parent_base)
    prefix = f"{parent_key}{AGENT_FAMILY_SEPARATOR}"
    for sibling in siblings:
        if (
            sibling.family_base
            and canonical_local_agent_name_key(sibling.family_base) != parent_key
        ):
            continue
        local_name = canonical_local_agent_name_key(sibling.name)
        if local_name.startswith(prefix):
            suffixes.append(local_name[len(parent_key) :])
    return suffixes


def known_agent_names(records: list[Any]) -> list[str]:
    names: list[str] = []
    for record in records:
        meta = record.agent_meta
        if meta is None:
            continue
        for value in (meta.name, meta.workflow_name):
            if value:
                names.append(value)
    return names


def known_agent_names_from_siblings(
    siblings: list[_types.FamilyAttachSibling],
) -> list[str]:
    return [sibling.name for sibling in siblings if sibling.name]


def family_sase_plan(records: list[Any], parent_base: str) -> str | None:
    from sase.core.machine_hood_facade import canonical_local_agent_name_key

    parent_key = canonical_local_agent_name_key(parent_base)
    family_records = [
        record
        for record in records
        if record.agent_meta is not None
        and (
            canonical_local_agent_name_key(record.agent_meta.agent_family or "")
            == parent_key
            or canonical_local_agent_name_key(record.agent_meta.workflow_name or "")
            == parent_key
            or canonical_local_agent_name_key(record.agent_meta.name or "")
            == parent_key
        )
    ]
    family_records.sort(key=lambda record: record.timestamp, reverse=True)
    for record in family_records:
        meta = record.agent_meta
        if meta is None:
            continue
        for value in (meta.sdd_plan_path, meta.plan_path):
            if value:
                return value
        if record.plan_path is not None and record.plan_path.plan_path:
            return record.plan_path.plan_path
        if record.done is not None and record.done.plan_path:
            return record.done.plan_path
    return None


def resolution_error_message(
    directive: _types.FamilyAttachDirective,
    result: dict[str, Any],
    project_name: str,
) -> str:
    kind = result.get("kind")
    candidates = [dict(candidate) for candidate in result.get("candidates", [])]
    if kind == "absent":
        return (
            f"Cannot attach family member with %i({directive.suffix}, "
            f"family={directive.parent}): parent agent '{directive.parent}' was not "
            f"found in project '{project_name}'."
        )
    if kind == "dismissed":
        return (
            f"Cannot attach family member to dismissed parent '{directive.parent}'. "
            "Revive the parent from the Agents tab before using "
            "%i(suffix, family=parent)."
        )
    if kind == "ambiguous":
        labels = ", ".join(_candidate_label(candidate) for candidate in candidates[:5])
        return (
            f"Cannot attach family member to '{directive.parent}': multiple newest "
            f"parent candidates matched ({labels}). Use the exact parent after "
            "dismissing or reviving duplicates."
        )
    return f"Cannot attach family member to '{directive.parent}': {kind or 'unknown'}."


def _candidate_label(candidate: dict[str, Any]) -> str:
    timestamp = candidate.get("timestamp") or "unknown"
    name = candidate.get("name") or candidate.get("workflow_name") or "unnamed"
    return f"{name}@{timestamp}"


def resolve_binding() -> Any:
    from sase.core.rust import require_rust_binding

    try:
        return require_rust_binding("resolve_agent_family_parent")
    except AttributeError:
        return _resolve_agent_family_parent_fallback


def _resolve_agent_family_parent_fallback(request: dict[str, Any]) -> dict[str, Any]:
    """Compatibility path for dev checkouts with a stale core binding."""

    parent_name = str(request.get("parent_name") or "")
    project_name = str(request.get("project_name") or "")
    candidates = [
        dict(candidate)
        for candidate in request.get("candidates", [])
        if isinstance(candidate, dict)
        and candidate.get("project_name") == project_name
        and _candidate_matches_parent(candidate, parent_name)
    ]
    if not candidates:
        return {"kind": "absent", "candidates": []}

    candidates.sort(key=lambda candidate: str(candidate.get("timestamp") or ""))
    newest_timestamp = str(candidates[-1].get("timestamp") or "")
    newest = [
        candidate
        for candidate in candidates
        if str(candidate.get("timestamp") or "") == newest_timestamp
    ]
    dismissed = request.get("dismissed")
    dismissed_identities = dismissed if isinstance(dismissed, list) else []
    active = [
        candidate
        for candidate in newest
        if not _candidate_is_dismissed(candidate, dismissed_identities)
    ]
    if not active:
        return {"kind": "dismissed", "candidates": newest}
    if len(active) > 1:
        return {"kind": "ambiguous", "candidates": active}
    parent = active[0]
    kind = "resolved" if parent.get("is_terminal") else "running"
    return {
        "kind": kind,
        "parent": {
            "name": parent.get("name") or parent.get("workflow_name") or parent_name,
            "artifact_dir": parent.get("artifact_dir"),
            "timestamp": parent.get("timestamp"),
        },
    }


def _candidate_matches_parent(candidate: dict[str, Any], parent_name: str) -> bool:
    for key in ("name", "workflow_name"):
        value = candidate.get(key)
        if value == parent_name:
            return True
    name = candidate.get("name")
    return isinstance(name, str) and name.startswith(
        f"{parent_name}{AGENT_FAMILY_SEPARATOR}"
    )


def _candidate_is_dismissed(
    candidate: dict[str, Any],
    dismissed_identities: list[Any],
) -> bool:
    cl_name = candidate.get("cl_name")
    raw_suffix = candidate.get("raw_suffix")
    for identity in dismissed_identities:
        if not isinstance(identity, dict):
            continue
        if (
            identity.get("cl_name") == cl_name
            and identity.get("raw_suffix") == raw_suffix
        ):
            return True
    return False


__all__ = [
    "agent_family_snapshot",
    "artifacts_timestamp_from_launch_timestamp",
    "candidate_from_record",
    "candidate_from_sibling",
    "dismissed_identity_dicts",
    "family_base",
    "family_sase_plan",
    "known_agent_names",
    "known_agent_names_from_siblings",
    "known_family_suffixes",
    "known_family_suffixes_from_siblings",
    "record_by_artifact_dir",
    "record_cl_name",
    "resolution_error_message",
    "resolve_binding",
    "sibling_by_artifact_dir",
]
