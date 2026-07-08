"""User-facing ``%n(parent, suffix)`` family attach support."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import re
from typing import Any, TYPE_CHECKING

from sase.plan_chain import AGENT_FAMILY_SEPARATOR

if TYPE_CHECKING:
    from sase.agent.launch_executor_types import LaunchSpawnRequest

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
    parent_project_name: str
    parent_is_running: bool = False
    parent_cl_name: str | None = None
    parent_workspace_dir: str | None = None
    parent_workspace_num: int | None = None
    sase_plan: str | None = None


@dataclass(frozen=True)
class FamilyAttachSibling:
    """Launch-batch sibling known before its async artifact metadata is written."""

    name: str
    family_base: str
    timestamp: str
    artifact_dir: str
    project_name: str
    cl_name: str | None = None
    workspace_dir: str | None = None
    workspace_num: int | None = None
    can_attach_parent: bool = True


class _FamilyAttachError(RuntimeError):
    """Raised when a ``%n(parent, suffix)`` launch cannot be prepared."""


_SUFFIX_TOKEN_RE = re.compile(r"^[A-Za-z0-9_]+$")


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


def _family_attach_parent_from_prompt(prompt: str) -> str | None:
    """Return the parent named by a top-level ``%n(parent, suffix)`` directive."""
    directive = _extract_family_attach_directive(prompt)
    return None if directive is None else directive.parent


def default_with_feedback_parent_from_family_attach(
    workflow_name: str,
    args: dict[str, Any],
    *,
    prompt: str,
    reference_offset: int | None = None,
    fenced_ranges: list[tuple[int, int]] | None = None,
) -> None:
    """Default ``#with_feedback``'s parent from a co-occurring family attach."""
    if workflow_name != "with_feedback" or args.get("parent"):
        return
    if reference_offset is not None:
        prompt = _prompt_segment_at_offset(
            prompt,
            reference_offset,
            fenced_ranges or [],
        )
    parent = _family_attach_parent_from_prompt(prompt)
    if parent:
        args["parent"] = parent


def _prompt_segment_at_offset(
    prompt: str,
    offset: int,
    fenced_ranges: list[tuple[int, int]],
) -> str:
    """Return the top-level ``---`` segment containing *offset*."""
    from sase.xprompt._parsing import _SEGMENT_SEPARATOR_RE

    start = 0
    end = len(prompt)
    for match in _SEGMENT_SEPARATOR_RE.finditer(prompt):
        if any(
            range_start <= match.start() < range_end
            for range_start, range_end in fenced_ranges
        ):
            continue
        if match.end() <= offset:
            start = match.end()
            continue
        end = match.start()
        break
    return prompt[start:end]


def prepare_family_attach_launch(
    prompt: str,
    context: Any,
    extra_env: dict[str, str] | None,
    *,
    pending_family_parents: list[FamilyAttachSibling] | None = None,
) -> tuple[Any, dict[str, str] | None]:
    """Resolve family attach metadata and return adjusted launch context/env."""

    directive = _extract_family_attach_directive(prompt)
    if directive is None:
        return context, extra_env

    plan = _resolve_family_attach_plan(
        directive,
        project_name=context.project_name,
        pending_family_parents=pending_family_parents,
    )
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
    if plan.parent_is_running and not context.is_home_mode:
        context_updates["deferred_workspace"] = True
        context_updates["use_preallocated_workspace"] = False
        if plan.parent_workspace_dir:
            context_updates["workspace_dir"] = plan.parent_workspace_dir
            env["SASE_AGENT_DEFERRED_TARGET_WORKSPACE_DIR"] = plan.parent_workspace_dir
        if plan.parent_workspace_num is not None and plan.parent_workspace_num > 0:
            context_updates["workspace_num"] = plan.parent_workspace_num
            env["SASE_AGENT_DEFERRED_TARGET_WORKSPACE_NUM"] = str(
                plan.parent_workspace_num
            )
    elif (
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
        parent_project_name=str(data.get("parent_project_name") or ""),
        parent_is_running=bool(data.get("parent_is_running", False)),
        parent_cl_name=_str_or_none(data.get("parent_cl_name")),
        parent_workspace_dir=_str_or_none(data.get("parent_workspace_dir")),
        parent_workspace_num=_int_or_none(data.get("parent_workspace_num")),
        sase_plan=_str_or_none(data.get("sase_plan")),
    )


def _resolve_family_attach_plan(
    directive: _FamilyAttachDirective,
    *,
    project_name: str,
    pending_family_parents: list[FamilyAttachSibling] | None = None,
) -> _FamilyAttachLaunchPlan:
    snapshot = _agent_family_snapshot(project_name)
    pending_siblings = tuple(pending_family_parents or ())
    sibling_candidates = [
        _candidate_from_sibling(sibling)
        for sibling in pending_siblings
        if sibling.can_attach_parent
    ]
    request = {
        "schema_version": 1,
        "parent_name": directive.parent,
        "project_name": project_name,
        "candidates": [
            *[_candidate_from_record(record) for record in snapshot.records],
            *sibling_candidates,
        ],
        "dismissed": _dismissed_identity_dicts(),
    }

    binding = _resolve_binding()
    result = dict(binding(request))
    kind = result.get("kind")
    if kind not in {"resolved", "running"}:
        raise _FamilyAttachError(
            _resolution_error_message(directive, result, project_name)
        )

    parent = dict(result.get("parent") or {})
    if not parent:
        raise _FamilyAttachError(
            f"Cannot attach family member to '{directive.parent}': "
            "resolved parent metadata is no longer available."
        )
    sibling_by_artifact_dir = _sibling_by_artifact_dir(pending_siblings)
    parent_sibling = sibling_by_artifact_dir.get(str(parent["artifact_dir"]))
    parent_record = _record_by_artifact_dir(snapshot.records).get(
        parent["artifact_dir"]
    )
    if parent_record is None or parent_record.agent_meta is None:
        if parent_sibling is None:
            raise _FamilyAttachError(
                f"Cannot attach family member to '{directive.parent}': "
                "resolved parent metadata is no longer available."
            )

    parent_name = parent["name"]
    parent_base = (
        parent_sibling.family_base
        if parent_sibling is not None
        else _family_base(parent_record, parent_name)
    )
    role_suffix = _resolve_role_suffix(
        directive.suffix,
        parent_base,
        snapshot.records,
        pending_family_parents=pending_family_parents,
    )
    agent_name = f"{parent_base}{role_suffix}"
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
    else:
        if parent_record is None or parent_record.agent_meta is None:
            raise _FamilyAttachError(
                f"Cannot attach family member to '{directive.parent}': "
                "resolved parent metadata is no longer available."
            )
        parent_cl_name = _record_cl_name(parent_record)
        parent_workspace_dir = parent_record.agent_meta.workspace_dir
        parent_workspace_num = parent_record.agent_meta.workspace_num

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
        parent_project_name=project_name,
        parent_is_running=kind == "running",
        parent_cl_name=parent_cl_name,
        parent_workspace_dir=parent_workspace_dir,
        parent_workspace_num=parent_workspace_num,
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
            f"Invalid %n family suffix '{suffix}'. Use letters, numbers, "
            "and underscores only, or @ to allocate the next free suffix."
        )
    return f"{AGENT_FAMILY_SEPARATOR}{suffix}"


def _resolve_role_suffix(
    suffix_arg: str,
    parent_base: str,
    records: list[Any],
    *,
    pending_family_parents: list[FamilyAttachSibling] | None = None,
) -> str:
    if suffix_arg == "@":
        from sase.plan_chain import allocate_agent_family_child_suffix

        known_suffixes = [
            *_known_family_suffixes(records, parent_base),
            *_known_family_suffixes_from_siblings(
                pending_family_parents or [],
                parent_base,
            ),
        ]
        return allocate_agent_family_child_suffix(
            parent_base,
            f"{AGENT_FAMILY_SEPARATOR}@",
            extra_reserved_suffixes=tuple(known_suffixes),
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
    *,
    pending_family_parents: list[FamilyAttachSibling] | None = None,
) -> None:
    from sase.agent.names import get_reserved_agent_names

    known_names = set(get_reserved_agent_names())
    if records is not None:
        known_names.update(_known_agent_names(records))
    known_names.update(_known_agent_names_from_siblings(pending_family_parents or []))
    if agent_name in known_names:
        raise _FamilyAttachError(
            f"Agent family member '{agent_name}' already exists. "
            f"Use %n({directive.parent}, @) to allocate the next free suffix."
        )


def build_family_attach_sibling_from_spawn(
    request: LaunchSpawnRequest,
    name: str,
    *,
    family_base: str | None = None,
    can_attach_parent: bool = True,
) -> FamilyAttachSibling | None:
    """Return the in-batch sibling descriptor for a successful spawn request."""

    if not name or not request.project_name or not request.workspace_dir:
        return None

    from sase.core.agent_artifact_paths import canonical_agent_artifact_path
    from sase.plan_chain import agent_family_base

    artifact_timestamp = _artifacts_timestamp_from_launch_timestamp(request.timestamp)
    base = family_base or agent_family_base(name) or name
    return FamilyAttachSibling(
        name=name,
        family_base=base,
        timestamp=artifact_timestamp,
        artifact_dir=str(
            canonical_agent_artifact_path(
                request.project_name,
                "ace-run",
                artifact_timestamp,
            )
        ),
        project_name=request.project_name,
        cl_name=request.cl_name or None,
        workspace_dir=request.workspace_dir,
        workspace_num=request.workspace_num,
        can_attach_parent=can_attach_parent,
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
        "artifact_dir": str(record.artifact_dir),
        "timestamp": record.timestamp,
        "cl_name": _record_cl_name(record) or record.project_name,
        "raw_suffix": record.timestamp,
        "parent_timestamp": None if meta is None else meta.parent_timestamp,
        "is_terminal": bool(record.has_done_marker),
    }


def _candidate_from_sibling(sibling: FamilyAttachSibling) -> dict[str, Any]:
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
    return {str(record.artifact_dir): record for record in records}


def _sibling_by_artifact_dir(
    siblings: tuple[FamilyAttachSibling, ...],
) -> dict[str, FamilyAttachSibling]:
    return {sibling.artifact_dir: sibling for sibling in siblings}


def _artifacts_timestamp_from_launch_timestamp(timestamp: str) -> str:
    if re.fullmatch(r"\d{14}", timestamp):
        return timestamp

    from sase.artifacts import convert_timestamp_to_artifacts_format

    return convert_timestamp_to_artifacts_format(timestamp)


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


def _known_family_suffixes_from_siblings(
    siblings: list[FamilyAttachSibling],
    parent_base: str,
) -> list[str]:
    suffixes: list[str] = []
    prefix = f"{parent_base}{AGENT_FAMILY_SEPARATOR}"
    for sibling in siblings:
        if sibling.family_base and sibling.family_base != parent_base:
            continue
        if sibling.name.startswith(prefix):
            suffixes.append(sibling.name[len(parent_base) :])
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


def _known_agent_names_from_siblings(
    siblings: list[FamilyAttachSibling],
) -> list[str]:
    return [sibling.name for sibling in siblings if sibling.name]


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
