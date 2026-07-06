"""User-facing ``%n(parent, suffix)`` family attach support."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import re
from typing import Any

from sase.plan_chain import AGENT_FAMILY_SEPARATOR

FAMILY_ATTACH_ENV = "SASE_AGENT_FAMILY_ATTACH"


@dataclass(frozen=True)
class _ParsedNameDirective:
    plain_name: str | None = None
    family_parent: str | None = None
    family_suffix: str | None = None


@dataclass(frozen=True)
class _FamilyAttachDirective:
    parent: str
    suffix: str


@dataclass(frozen=True)
class _FamilyAttachLaunchPlan:
    parent_arg: str
    suffix_arg: str
    parent_name: str
    parent_base: str
    parent_timestamp: str
    parent_artifacts_dir: str
    role_suffix: str
    agent_name: str
    agent_family_role: str
    parent_cl_name: str | None = None
    parent_workspace_dir: str | None = None
    parent_workspace_num: int | None = None
    sase_plan: str | None = None


class _FamilyAttachError(RuntimeError):
    """Raised when a ``%n(parent, suffix)`` launch cannot be prepared."""


_SUFFIX_TOKEN_RE = re.compile(r"^[A-Za-z0-9]+$")


def parse_name_directive_args(
    positional_args: list[str],
    named_args: dict[str, str],
    *,
    source: str,
) -> _ParsedNameDirective:
    """Classify ``%name`` / ``%n`` arguments as plain naming or family attach."""

    if named_args:
        keys = ", ".join(f"{key}=" for key in sorted(named_args))
        raise ValueError(
            f"Unsupported keyword on {source}: {keys}. "
            "Use %n(parent, suffix) for family attach; keyword arguments "
            "are not supported."
        )
    if len(positional_args) > 2:
        raise ValueError(
            f"{source} accepts at most two positional arguments. "
            "Use %n(parent, suffix) for family attach."
        )
    if len(positional_args) == 2:
        parent, suffix = (arg.strip() for arg in positional_args)
        if not parent or not suffix:
            raise ValueError("%n(parent, suffix) requires both parent and suffix.")
        _normalize_family_suffix_arg(suffix)
        return _ParsedNameDirective(family_parent=parent, family_suffix=suffix)
    return _ParsedNameDirective(
        plain_name=positional_args[0] if positional_args else ""
    )


def _extract_family_attach_directive(prompt: str) -> _FamilyAttachDirective | None:
    """Return the first top-level family attach directive in *prompt*."""

    if "%" not in prompt:
        return None

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks
    from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "name":
            continue
        if match.group(2) is None:
            continue
        paren_start = match.end() - 1
        paren_end = find_matching_paren_for_args(protected, paren_start)
        if paren_end is None:
            continue
        positional_args, named_args = parse_args(protected[paren_start + 1 : paren_end])
        parsed = parse_name_directive_args(
            positional_args,
            named_args,
            source=f"%{raw_name}",
        )
        if parsed.family_parent is not None and parsed.family_suffix is not None:
            return _FamilyAttachDirective(parsed.family_parent, parsed.family_suffix)
    return None


def prepare_family_attach_launch(
    prompt: str,
    context: Any,
    extra_env: dict[str, str] | None,
) -> tuple[Any, dict[str, str] | None]:
    """Resolve family attach metadata and return adjusted launch context/env."""

    directive = _extract_family_attach_directive(prompt)
    if directive is None:
        return context, extra_env

    plan = _resolve_family_attach_plan(directive, project_name=context.project_name)
    env = dict(extra_env or {})

    from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV

    env[INTERNAL_AGENT_NAME_BYPASS_ENV] = "1"
    env[FAMILY_ATTACH_ENV] = json.dumps(asdict(plan), sort_keys=True)
    if plan.sase_plan:
        env["SASE_PLAN"] = plan.sase_plan

    context_updates: dict[str, Any] = {}
    if plan.parent_cl_name:
        context_updates["cl_name"] = plan.parent_cl_name
        context_updates["history_sort_key"] = plan.parent_cl_name
    if (
        plan.parent_workspace_dir
        and plan.parent_workspace_num is not None
        and plan.parent_workspace_num > 0
        and not context.is_home_mode
    ):
        context_updates.update(
            workspace_dir=plan.parent_workspace_dir,
            workspace_num=plan.parent_workspace_num,
            use_preallocated_workspace=True,
            deferred_workspace=False,
        )
    if context_updates:
        context = replace(context, **context_updates)
    return context, env


def load_family_attach_plan_from_env(
    env: dict[str, str] | None = None,
) -> _FamilyAttachLaunchPlan | None:
    import os

    raw = (env or os.environ).get(FAMILY_ATTACH_ENV)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _FamilyAttachError("Invalid SASE_AGENT_FAMILY_ATTACH payload") from exc
    if not isinstance(data, dict):
        raise _FamilyAttachError("Invalid SASE_AGENT_FAMILY_ATTACH payload")
    return _FamilyAttachLaunchPlan(
        parent_arg=str(data["parent_arg"]),
        suffix_arg=str(data["suffix_arg"]),
        parent_name=str(data["parent_name"]),
        parent_base=str(data["parent_base"]),
        parent_timestamp=str(data["parent_timestamp"]),
        parent_artifacts_dir=str(data["parent_artifacts_dir"]),
        role_suffix=str(data["role_suffix"]),
        agent_name=str(data["agent_name"]),
        agent_family_role=str(data["agent_family_role"]),
        parent_cl_name=_str_or_none(data.get("parent_cl_name")),
        parent_workspace_dir=_str_or_none(data.get("parent_workspace_dir")),
        parent_workspace_num=_int_or_none(data.get("parent_workspace_num")),
        sase_plan=_str_or_none(data.get("sase_plan")),
    )


def _resolve_family_attach_plan(
    directive: _FamilyAttachDirective,
    *,
    project_name: str,
) -> _FamilyAttachLaunchPlan:
    snapshot = _agent_family_snapshot(project_name)
    request = {
        "schema_version": 1,
        "parent_name": directive.parent,
        "project_name": project_name,
        "candidates": [_candidate_from_record(record) for record in snapshot.records],
        "dismissed": _dismissed_identity_dicts(),
    }

    binding = _resolve_binding()
    result = dict(binding(request))
    kind = result.get("kind")
    if kind != "resolved":
        raise _FamilyAttachError(
            _resolution_error_message(directive, result, project_name)
        )

    parent = dict(result["parent"])
    parent_record = _record_by_artifact_dir(snapshot.records).get(
        parent["artifact_dir"]
    )
    if parent_record is None or parent_record.agent_meta is None:
        raise _FamilyAttachError(
            f"Cannot attach family member to '{directive.parent}': "
            "resolved parent metadata is no longer available."
        )

    parent_name = parent["name"]
    parent_base = _family_base(parent_record, parent_name)
    role_suffix = _resolve_role_suffix(directive.suffix, parent_base, snapshot.records)
    agent_name = f"{parent_base}{role_suffix}"
    _ensure_family_name_available(agent_name, directive, snapshot.records)
    role = _family_role(role_suffix, directive.suffix)
    parent_meta = parent_record.agent_meta

    return _FamilyAttachLaunchPlan(
        parent_arg=directive.parent,
        suffix_arg=directive.suffix,
        parent_name=parent_name,
        parent_base=parent_base,
        parent_timestamp=parent["timestamp"],
        parent_artifacts_dir=parent["artifact_dir"],
        role_suffix=role_suffix,
        agent_name=agent_name,
        agent_family_role=role,
        parent_cl_name=_record_cl_name(parent_record),
        parent_workspace_dir=parent_meta.workspace_dir,
        parent_workspace_num=parent_meta.workspace_num,
        sase_plan=_family_sase_plan(snapshot.records, parent_base)
        if role == "code"
        else None,
    )


def _normalize_family_suffix_arg(suffix: str) -> str:
    if suffix == "@":
        return f"{AGENT_FAMILY_SEPARATOR}@"
    if suffix.startswith((".", "-")) or AGENT_FAMILY_SEPARATOR in suffix:
        raise ValueError(
            f"Invalid %n family suffix '{suffix}'. Pass the bare suffix "
            "without a family separator, e.g. %n(parent, reviewer)."
        )
    if not _SUFFIX_TOKEN_RE.fullmatch(suffix):
        raise ValueError(
            f"Invalid %n family suffix '{suffix}'. Use letters and numbers only, "
            "or @ to allocate the next free suffix."
        )
    return f"{AGENT_FAMILY_SEPARATOR}{suffix}"


def _resolve_role_suffix(
    suffix_arg: str,
    parent_base: str,
    records: list[Any],
) -> str:
    if suffix_arg == "@":
        from sase.plan_chain import allocate_agent_family_child_suffix

        return allocate_agent_family_child_suffix(
            parent_base,
            f"{AGENT_FAMILY_SEPARATOR}@",
            extra_reserved_suffixes=tuple(_known_family_suffixes(records, parent_base)),
        )
    return _normalize_family_suffix_arg(suffix_arg)


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
    directive: _FamilyAttachDirective,
    records: list[Any] | None = None,
) -> None:
    from sase.agent.names import get_reserved_agent_names

    known_names = set(get_reserved_agent_names())
    if records is not None:
        known_names.update(_known_agent_names(records))
    if agent_name in known_names:
        raise _FamilyAttachError(
            f"Agent family member '{agent_name}' already exists. "
            f"Use %n({directive.parent}, @) to allocate the next free suffix."
        )


def _agent_family_snapshot(project_name: str) -> Any:
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


def _candidate_from_record(record: Any) -> dict[str, Any]:
    meta = record.agent_meta
    name = ""
    if meta is not None:
        name = meta.name or meta.workflow_name or ""
    return {
        "name": name,
        "workflow_name": None if meta is None else meta.workflow_name,
        "project_name": record.project_name,
        "artifact_dir": record.artifact_dir,
        "timestamp": record.timestamp,
        "cl_name": _record_cl_name(record) or record.project_name,
        "raw_suffix": record.timestamp,
        "parent_timestamp": None if meta is None else meta.parent_timestamp,
        "is_terminal": bool(record.has_done_marker),
    }


def _record_cl_name(record: Any) -> str | None:
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


def _dismissed_identity_dicts() -> list[dict[str, str | None]]:
    from sase.ace.dismissed_agents import load_dismissed_agents

    return [
        {
            "agent_type": getattr(agent_type, "value", str(agent_type)),
            "cl_name": cl_name,
            "raw_suffix": raw_suffix,
        }
        for agent_type, cl_name, raw_suffix in load_dismissed_agents()
    ]


def _record_by_artifact_dir(records: list[Any]) -> dict[str, Any]:
    return {record.artifact_dir: record for record in records}


def _family_base(record: Any, parent_name: str) -> str:
    meta = record.agent_meta
    if meta is not None and meta.agent_family:
        return meta.agent_family
    from sase.plan_chain import agent_family_base

    return agent_family_base(parent_name) or parent_name


def _known_family_suffixes(records: list[Any], parent_base: str) -> list[str]:
    suffixes: list[str] = []
    prefix = f"{parent_base}{AGENT_FAMILY_SEPARATOR}"
    for record in records:
        meta = record.agent_meta
        if meta is None:
            continue
        if meta.agent_family and meta.agent_family != parent_base:
            continue
        if meta.role_suffix:
            suffixes.append(meta.role_suffix)
            continue
        if meta.name and meta.name.startswith(prefix):
            suffixes.append(meta.name[len(parent_base) :])
    return suffixes


def _known_agent_names(records: list[Any]) -> list[str]:
    names: list[str] = []
    for record in records:
        meta = record.agent_meta
        if meta is None:
            continue
        for value in (meta.name, meta.workflow_name):
            if value:
                names.append(value)
    return names


def _family_sase_plan(records: list[Any], parent_base: str) -> str | None:
    family_records = [
        record
        for record in records
        if record.agent_meta is not None
        and (
            record.agent_meta.agent_family == parent_base
            or record.agent_meta.workflow_name == parent_base
            or record.agent_meta.name == parent_base
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


def _resolution_error_message(
    directive: _FamilyAttachDirective,
    result: dict[str, Any],
    project_name: str,
) -> str:
    kind = result.get("kind")
    candidates = [dict(candidate) for candidate in result.get("candidates", [])]
    if kind == "absent":
        return (
            f"Cannot attach family member with %n({directive.parent}, "
            f"{directive.suffix}): parent agent '{directive.parent}' was not "
            f"found in project '{project_name}'."
        )
    if kind == "dismissed":
        return (
            f"Cannot attach family member to dismissed parent '{directive.parent}'. "
            "Revive the parent from the Agents tab before using %n(parent, suffix)."
        )
    if kind == "running":
        return (
            f"Cannot attach family member to '{directive.parent}' yet: the parent "
            "is still running. Wait for it to finish and rerun the launch; queued "
            "attach for running parents is handled by the next phase."
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


def _resolve_binding() -> Any:
    from sase.core.rust import require_rust_binding

    return require_rust_binding("resolve_agent_family_parent")


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value:
        try:
            return int(value)
        except ValueError:
            return None
    return None
