"""Read-only resolver for gateless ``sase plan approve`` runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DirectApprovalKind = Literal["tale", "commit", "approve", "epic"]
DirectApprovalLocation = Literal["scratch", "proposal", "committed"]
PlacementMode = Literal["session", "standalone"]
RetiredGateState = Literal["orphaned", "expired"]


@dataclass(frozen=True)
class DirectApprovalRequest:
    selector: str
    kind: DirectApprovalKind | None = None
    kind_explicit: bool = False
    coder_model: str | None = None
    coder_prompt: str | None = None
    wait: object = None
    project: str | None = None
    cwd: Path | None = None


@dataclass(frozen=True)
class CoderPlacement:
    mode: PlacementMode
    parent: str | None = None
    member_name: str | None = None
    agent_session: str | None = None
    reason: str | None = None
    planner_artifacts_dir: str | None = None


@dataclass(frozen=True)
class RetiredGate:
    notification_id: str
    state: RetiredGateState
    bundle_path: Path | None = None
    action_data: dict[str, str] | None = None


@dataclass(frozen=True)
class DirectApprovalPlan:
    request: DirectApprovalRequest
    kind: DirectApprovalKind
    source_path: Path
    location: DirectApprovalLocation
    name: str
    title: str | None
    size: str | None
    project: str
    project_tag: str
    planner: str | None
    gate: RetiredGate | None
    placement: CoderPlacement
    model_directive: str
    bead: str | None = None
    predicted_plan_ref: str = ""
    coder_prompt_preview: str = ""


@dataclass(frozen=True)
class DirectApprovalRefusal:
    code: str
    header: str
    detail_lines: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()


class DirectApprovalRefused(Exception):
    def __init__(self, refusal: DirectApprovalRefusal) -> None:
        super().__init__(refusal.header)
        self.refusal = refusal


def resolve_direct_approval(
    request: DirectApprovalRequest,
) -> DirectApprovalPlan | DirectApprovalRefusal | None:
    """Resolve *request* to a plan, refusal, or ``None`` (no plan file)."""
    from sase.main.plan_pending_diagnosis import classify_plan_gate_history
    from sase.main.plan_pending_diagnosis import locate_plan_candidates

    candidates = locate_plan_candidates(request.selector)
    if not candidates:
        return None
    if len(candidates) > 1:
        names = ", ".join(sorted(str(path) for path in candidates))
        return DirectApprovalRefusal(
            code="ambiguous",
            header=f"{request.selector.strip()} matches more than one plan",
            detail_lines=(names,),
            hints=(f"sase plan approve {candidates[0]}",),
        )
    source_path = candidates[0]
    location = _classify_location(source_path, request.cwd)
    name = _plan_stem(source_path)

    from sase.main.plan_inventory_paths import plan_metadata_for_path

    metadata = plan_metadata_for_path(str(source_path))
    title = metadata.title or name

    kind: DirectApprovalKind = request.kind or "tale"

    if location == "committed" and kind in ("tale", "commit"):
        ref = _committed_plan_ref(source_path)
        detail = (
            f"{name} is already committed as {ref}"
            if ref
            else f"{name} is already committed"
        )
        return DirectApprovalRefusal(
            code="already_committed",
            header=f"\u2717 {detail}",
            detail_lines=(
                "A committed tale is already approved. To run another coder on it:",
            ),
            hints=(f"sase run '#coder({source_path})'",),
        )

    # Validation: always as a tale. Raises PlanApprovalValidationError.
    from sase.plan_approval_actions import require_plan_approval_validation

    validation = require_plan_approval_validation(source_path, "tale")
    size = _validation_size(validation)

    history = classify_plan_gate_history(source_path)
    gate = _retired_gate_from_history(history)
    handled_refusal = _handled_refusal(request, source_path, name, title, history)
    if handled_refusal is not None:
        return handled_refusal

    planner = _resolve_planner(source_path, history)
    project_refusal_or_name = _resolve_project(request, source_path, history, planner)
    if isinstance(project_refusal_or_name, DirectApprovalRefusal):
        return project_refusal_or_name
    project = project_refusal_or_name
    project_tag = _project_tag_for(project)

    # Epic-guard and gateless-epic refusals need the authored tier.
    authored_tier = _authored_tier(source_path)
    if authored_tier == "epic" and not request.kind_explicit:
        return DirectApprovalRefusal(
            code="epic_guard",
            header=f"\u2717 {name} is an epic plan",
            detail_lines=(
                f"Approve it as an epic:        sase plan approve {request.selector.strip()} -k epic",
                f"Or run it as a single tale:   sase plan approve {request.selector.strip()} -k tale",
            ),
            hints=(
                f"sase plan approve {request.selector.strip()} -k epic",
                f"sase plan approve {request.selector.strip()} -k tale",
            ),
        )
    if kind == "epic":
        return DirectApprovalRefusal(
            code="epic_without_gate",
            header=f"\u2717 {name} is an epic plan without a live approval gate",
            detail_lines=(
                f"Launch it with:               sase bead work {source_path}",
                f"Or run it as a single tale:   sase plan approve {request.selector.strip()} -k tale",
            ),
            hints=(
                f"sase bead work {source_path}",
                f"sase plan approve {request.selector.strip()} -k tale",
            ),
        )

    placement = _resolve_placement(planner, project, history, plan_name=name)
    if isinstance(placement, DirectApprovalRefusal):
        return placement

    model_directive = _resolve_model_directive(
        source_path, request.coder_model, request.coder_prompt
    )
    bead = _resolve_bead(source_path, placement, project)
    predicted_ref = _predicted_plan_ref(source_path, kind, location)
    wait_spec = _parse_wait(request.wait)
    prompt_preview = compose_coder_prompt(
        project_tag=project_tag,
        model_directive=model_directive,
        plan_argument=predicted_ref or str(source_path),
        extra_prompt=request.coder_prompt,
        wait=wait_spec,
        bead=bead,
        placement=placement,
    )
    return DirectApprovalPlan(
        request=request,
        kind=kind,
        source_path=source_path,
        location=location,
        name=name,
        title=title,
        size=size,
        project=project,
        project_tag=project_tag,
        planner=planner,
        gate=gate,
        placement=placement,
        model_directive=model_directive,
        bead=bead,
        predicted_plan_ref=predicted_ref,
        coder_prompt_preview=prompt_preview,
    )


def compose_coder_prompt(
    *,
    project_tag: str,
    model_directive: str,
    plan_argument: str,
    extra_prompt: str | None,
    wait: object,
    bead: str | None,
    placement: CoderPlacement,
) -> str:
    """Compose the ``#coder`` prompt used for previews and recovery hints."""
    from sase.xprompt._parsing_args import escape_for_xprompt

    argument = plan_argument.strip()
    if _needs_quoting(argument):
        argument = f'"{escape_for_xprompt(argument)}"'
    if placement.mode == "session" and placement.parent:
        id_part = f"%id(code, session={placement.parent})"
    elif bead:
        id_part = f"%id(bead={bead})"
    else:
        id_part = ""
    model_part = f"%model:{model_directive}" if model_directive else ""
    head = " ".join(part for part in (project_tag.strip(), model_part, id_part) if part)
    lines = [f"{head} #coder({argument})" if head else f"#coder({argument})"]
    if extra_prompt and extra_prompt.strip():
        lines += ["", "Additional instructions:", extra_prompt.strip()]
    prompt = "\n".join(lines)
    if wait is not None:
        try:
            from sase.xprompt.directive_edit import set_prompt_wait

            prompt = set_prompt_wait(prompt, wait)  # type: ignore[arg-type]
        except Exception:
            pass
    return prompt


def _classify_location(source_path: Path, cwd: Path | None) -> DirectApprovalLocation:
    try:
        resolved = source_path.expanduser().resolve(strict=False)
    except Exception:
        return "scratch"
    try:
        from sase.core.paths import sase_home

        plans_root = sase_home().expanduser().resolve(strict=False) / "plans"
        resolved.relative_to(plans_root)
    except (ValueError, OSError):
        pass
    else:
        return "proposal"
    committed_ref = _committed_plan_ref(source_path)
    if committed_ref is not None:
        return "committed"
    return "scratch"


def _committed_plan_ref(source_path: Path) -> str | None:
    try:
        from sase.sdd.plan_refs import (
            canonicalize_plan_reference_from_roots,
            resolve_plan_roots,
            workspace_context_for_plan_resolution,
        )
    except Exception:
        return None
    try:
        cwd = Path.cwd()
        workspace_dir, workspace_num = workspace_context_for_plan_resolution(cwd)
        roots = resolve_plan_roots(workspace_dir, workspace_num)
        return canonicalize_plan_reference_from_roots(
            source_path.expanduser().resolve(strict=False), roots=roots
        )
    except Exception:
        return None


def _plan_stem(source_path: Path) -> str:
    name = source_path.stem
    if name.startswith("sase_plan_"):
        name = name[len("sase_plan_") :]
    return name


def _authored_tier(source_path: Path) -> str | None:
    try:
        from sase.sdd.plan_tiers import read_plan_tier
    except Exception:
        return None
    try:
        return read_plan_tier(source_path)
    except Exception:
        return None


def _validation_size(validation: object) -> str | None:
    size = getattr(getattr(validation, "plan", None), "size", None)
    return str(size).strip() or None if isinstance(size, str) else None


def _retired_gate_from_history(history: object) -> RetiredGate | None:
    kind = getattr(history, "kind", "none")
    if kind != "orphaned" and kind != "expired":
        return None
    notification_id = getattr(history, "notification_id", None)
    if not isinstance(notification_id, str) or not notification_id.strip():
        return None
    state: RetiredGateState = "orphaned" if kind == "orphaned" else "expired"
    return RetiredGate(
        notification_id=notification_id.strip(),
        state=state,
        bundle_path=getattr(history, "bundle_path", None),
        action_data=getattr(history, "action_data", None),
    )


def _handled_refusal(
    request: DirectApprovalRequest,
    source_path: Path,
    name: str,
    title: str,
    history: object,
) -> DirectApprovalRefusal | None:
    kind = getattr(history, "kind", "none")
    if kind == "direct":
        action = getattr(history, "action", None) or "tale"
        age = getattr(history, "age", "") or ""
        try:
            from sase.plan_approval_receipts import read_direct_approval_receipt

            receipt = read_direct_approval_receipt(source_path)
            coder = receipt.coder_agent if receipt is not None else None
        except Exception:
            coder = None
        coder_bit = f" \u00b7 coder {coder}" if coder else ""
        return DirectApprovalRefusal(
            code="already_approved",
            header=f"{name} is not awaiting approval",
            detail_lines=(
                f"{title}",
                f"{source_path}",
                f"This plan was already approved as a {action} via"
                f" sase plan approve{age}{coder_bit}.",
                f"Inspect it with: sase plan show {name}",
            ),
            hints=(f"sase plan show {name}",),
        )
    if kind == "handled":
        from sase.main.plan_pending_diagnosis import diagnose_located_plan_miss

        miss = diagnose_located_plan_miss(request.selector, source_path)
        return DirectApprovalRefusal(
            code="conflict_already_handled",
            header=miss.header,
            detail_lines=miss.detail_lines,
            hints=(f"sase plan show {name}",),
        )
    return None


def _resolve_planner(source_path: Path, history: object) -> str | None:
    action_data = getattr(history, "action_data", None)
    if isinstance(action_data, dict):
        for key in ("agent_name", "agent_cl_name"):
            value = action_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    try:
        from sase.bead.attribution import plan_proposed_by
    except Exception:
        return None
    try:
        return plan_proposed_by(source_path)
    except Exception:
        return None


def _resolve_project(
    request: DirectApprovalRequest,
    source_path: Path,
    history: object,
    planner: str | None,
) -> str | DirectApprovalRefusal:
    if request.project:
        canonical = _canonicalize_project(request.project)
        if canonical is None:
            return DirectApprovalRefusal(
                code="unknown_project",
                header=f"\u2717 unknown project {request.project}",
                detail_lines=("See `sase project list` for known projects.",),
                hints=("sase project list",),
            )
        return canonical
    action_data = getattr(history, "action_data", None)
    if isinstance(action_data, dict) and action_data:
        project = _project_from_action_data(action_data)
        if project:
            return project
    if planner:
        project = _project_from_planner(planner)
        if project:
            return project
    project = _project_from_marker(source_path)
    if project:
        return project
    project = _project_from_cwd()
    if project:
        return project
    name = _plan_stem(source_path)
    return DirectApprovalRefusal(
        code="unknown_project",
        header=f"\u2717 cannot tell which project {name} belongs to",
        detail_lines=("Pass one with -P/--project (see `sase project list`)",),
        hints=("sase project list",),
    )


def _project_from_action_data(action_data: dict[str, str]) -> str | None:
    try:
        from sase._plan_approval_artifacts import resolve_plan_action_project_name

        return resolve_plan_action_project_name(action_data)
    except Exception:
        return None


def _project_from_planner(planner: str) -> str | None:
    try:
        from sase.agent.names import find_named_agent
    except Exception:
        return None
    try:
        named = find_named_agent(planner)
    except Exception:
        return None
    if named is None:
        return None
    artifacts_dir = getattr(named, "artifacts_dir", None)
    if not artifacts_dir:
        return None
    try:
        from sase.core.agent_artifact_paths import parse_agent_artifact_path

        info = parse_agent_artifact_path(artifacts_dir)
    except Exception:
        return None
    return info.project_name if info is not None else None


def _project_from_marker(source_path: Path) -> str | None:
    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(source_path.expanduser().parent))
    except Exception:
        return None
    if found is None:
        return None
    project_key = getattr(found[1], "project_key", "")
    return project_key or None


def _project_from_cwd() -> str | None:
    try:
        from sase.main.utils import ensure_project_file_and_get_workspace_num

        project_info = ensure_project_file_and_get_workspace_num(create_missing=False)
    except Exception:
        return None
    if project_info is None:
        return None
    return project_info[2]


def _canonicalize_project(project: str) -> str | None:
    try:
        from sase.project_aliases import resolve_project_alias_ref
    except Exception:
        resolve_project_alias_ref = None  # type: ignore[assignment]
    value = project.strip()
    if resolve_project_alias_ref is not None:
        try:
            value = resolve_project_alias_ref(value)
        except Exception:
            pass
    try:
        from sase.core.paths import is_valid_sase_project_name

        if not is_valid_sase_project_name(value):
            return None
    except Exception:
        if not value:
            return None
    return value


def _project_tag_for(project: str) -> str:
    try:
        from sase.project_tags.catalog import load_project_tag_catalog
        from sase.project_tags.tags import known_project_tag_for

        tag = known_project_tag_for(load_project_tag_catalog(), project)
    except Exception:
        tag = None
    return tag or f"+{project}"


def _resolve_placement(
    planner: str | None,
    project: str,
    history: object,
    *,
    plan_name: str = "",
) -> CoderPlacement | DirectApprovalRefusal:
    planner_artifacts_dir = _planner_artifacts_dir(history)
    if not planner:
        return CoderPlacement(
            mode="standalone",
            reason="this plan records no planner",
            planner_artifacts_dir=planner_artifacts_dir,
        )
    try:
        from sase.agent.agent_session_attach import AgentSessionAttachDirective
        from sase.agent.agent_session_attach import AgentSessionAttachError
        from sase.agent.agent_session_attach import resolve_agent_session_attach_plan
    except Exception:
        return CoderPlacement(
            mode="standalone",
            parent=planner,
            reason="agent session lookup is unavailable",
            planner_artifacts_dir=planner_artifacts_dir,
        )
    try:
        attach = resolve_agent_session_attach_plan(
            AgentSessionAttachDirective(parent=planner, suffix="code"),
            project_name=project,
        )
    except AgentSessionAttachError as exc:
        reason = _strip_attach_prefix(str(exc))
        return CoderPlacement(
            mode="standalone",
            parent=planner,
            reason=reason,
            planner_artifacts_dir=planner_artifacts_dir
            or getattr(exc, "artifacts_dir", None),
        )
    except Exception as exc:
        return CoderPlacement(
            mode="standalone",
            parent=planner,
            reason=str(exc) or "agent session lookup failed",
            planner_artifacts_dir=planner_artifacts_dir,
        )
    if attach.parent_is_running:
        return DirectApprovalRefusal(
            code="planner_running",
            header=f"\u2717 {plan_name or 'plan'}'s planner {planner} is still running",
            detail_lines=(
                "Its approval gate may still appear \u2014 check with: sase plan list",
            ),
            hints=("sase plan list",),
        )
    return CoderPlacement(
        mode="session",
        parent=planner,
        member_name=attach.agent_name,
        agent_session=attach.parent_base,
        planner_artifacts_dir=planner_artifacts_dir or attach.parent_artifacts_dir,
    )


def _planner_artifacts_dir(history: object) -> str | None:
    action_data = getattr(history, "action_data", None)
    if not isinstance(action_data, dict):
        return None
    try:
        from sase._plan_approval_artifacts import resolve_plan_agent_artifacts_dir

        return resolve_plan_agent_artifacts_dir(action_data)
    except Exception:
        return None


def _strip_attach_prefix(message: str) -> str:
    import re

    stripped = re.sub(
        r"^Cannot attach session member to '[^']*':\s*", "", message.strip()
    )
    return stripped or message.strip() or "agent session lookup failed"


def _resolve_model_directive(
    source_path: Path,
    coder_model: str | None,
    coder_prompt: str | None,
) -> str:
    if coder_prompt and _has_custom_prompt_model(coder_prompt):
        # The -p text already carries the directive; no prefix is added.
        return ""
    if coder_model:
        if coder_model.strip() == "worker":
            return _size_directive(source_path)
        try:
            from sase.llm_provider.model_alias_config import (
                format_model_directive_value,
            )

            return format_model_directive_value(coder_model.strip())
        except Exception:
            return coder_model.strip()
    return _size_directive(source_path)


def _has_custom_prompt_model(coder_prompt: str) -> bool:
    try:
        from sase.axe.run_agent_exec_plan_accept_models import custom_coder_prompt_model

        return custom_coder_prompt_model(coder_prompt) is not None
    except Exception:
        return False


def _size_directive(source_path: Path) -> str:
    try:
        from sase.tale_followup_routing import validated_tale_followup_model_directive

        return validated_tale_followup_model_directive(source_path)
    except Exception:
        return "@medium"


def _resolve_bead(
    source_path: Path, placement: CoderPlacement, project: str
) -> str | None:
    if placement.mode != "standalone":
        return None
    try:
        from sase.sdd.frontmatter import parse_frontmatter

        content = source_path.expanduser().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        frontmatter, _body, _had_frontmatter = parse_frontmatter(content)
    except Exception:
        return None
    bead = frontmatter.get("bead")
    if not isinstance(bead, str) or not bead.strip():
        return None
    bead_id = bead.strip()
    try:
        from sase.bead.store_locator import bead_statuses_for_project

        statuses = bead_statuses_for_project(project, [bead_id])
    except Exception:
        return bead_id
    if statuses is None:
        return bead_id
    status = statuses.get(bead_id)
    if status is None:
        return None
    if status.strip().lower() in {"closed", "done"}:
        return None
    return bead_id


def _predicted_plan_ref(
    source_path: Path, kind: DirectApprovalKind, location: DirectApprovalLocation
) -> str:
    if kind == "approve" and location == "committed":
        return _committed_plan_ref(source_path) or str(
            source_path.expanduser().resolve(strict=False)
        )
    if kind == "approve":
        if location == "proposal":
            proposal_ref = _proposal_ref(source_path)
            if proposal_ref is not None:
                return proposal_ref
        return str(source_path.expanduser().resolve(strict=False))
    # tale/commit: canonical ref the archive will produce.
    return f"plan:{_archive_yyyymm()}/{_plan_stem(source_path)}.md"


def _archive_yyyymm() -> str:
    try:
        from sase.sdd.files import get_yyyymm

        return get_yyyymm()
    except Exception:
        pass
    from datetime import UTC, datetime

    try:
        from sase.core.time import get_timezone

        return datetime.now(get_timezone()).strftime("%Y%m")
    except Exception:
        return datetime.now(UTC).strftime("%Y%m")


def _proposal_ref(source_path: Path) -> str | None:
    try:
        resolved = source_path.expanduser().resolve(strict=False)
        parts = resolved.parts
        if len(parts) >= 3 and len(parts[-2]) == 6 and parts[-2].isdigit():
            return f"plan:{parts[-2]}/{resolved.name}"
    except Exception:
        return None
    return None


def _parse_wait(wait: object) -> object:
    if wait is None:
        return None
    from sase._plan_approval_response import parse_plan_approval_wait

    if isinstance(wait, str):
        return parse_plan_approval_wait(wait or None)
    return wait


def _needs_quoting(argument: str) -> bool:
    import re

    return re.search(r"[^A-Za-z0-9_/:.+-]", argument) is not None


__all__ = [
    "CoderPlacement",
    "DirectApprovalKind",
    "DirectApprovalLocation",
    "DirectApprovalPlan",
    "DirectApprovalRefusal",
    "DirectApprovalRefused",
    "DirectApprovalRequest",
    "PlacementMode",
    "RetiredGate",
    "RetiredGateState",
    "compose_coder_prompt",
    "resolve_direct_approval",
]
