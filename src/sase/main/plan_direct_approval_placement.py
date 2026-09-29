"""Coder placement, model directive, and bead helpers for direct approval."""

from __future__ import annotations

from pathlib import Path

from sase.main.plan_direct_approval_types import (
    CoderPlacement,
    DirectApprovalRefusal,
)


def resolve_placement(
    planner: str | None,
    project: str,
    history: object,
    *,
    plan_name: str = "",
    recovery: bool = False,
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
    attach_error: AgentSessionAttachError | None = None
    attach = None
    try:
        attach = resolve_agent_session_attach_plan(
            AgentSessionAttachDirective(parent=planner, suffix="code"),
            project_name=project,
        )
    except AgentSessionAttachError as exc:
        if getattr(exc, "reason", None) == "name_taken":
            try:
                attach = resolve_agent_session_attach_plan(
                    AgentSessionAttachDirective(parent=planner, suffix="@"),
                    project_name=project,
                )
            except AgentSessionAttachError as retry_exc:
                attach_error = retry_exc
            except Exception as retry_error:
                return CoderPlacement(
                    mode="standalone",
                    parent=planner,
                    reason=str(retry_error) or "agent session lookup failed",
                    planner_artifacts_dir=planner_artifacts_dir,
                )
            if attach is not None:
                return CoderPlacement(
                    mode="session",
                    parent=planner,
                    member_name=attach.agent_name,
                    agent_session=attach.parent_base,
                    planner_artifacts_dir=planner_artifacts_dir
                    or attach.parent_artifacts_dir,
                    suffix="@",
                )
        else:
            attach_error = exc
        if attach is None and attach_error is not None:
            reason = _strip_attach_prefix(str(attach_error))
            return CoderPlacement(
                mode="standalone",
                parent=planner,
                reason=reason,
                planner_artifacts_dir=planner_artifacts_dir
                or getattr(attach_error, "artifacts_dir", None),
            )
    except Exception as exc:
        return CoderPlacement(
            mode="standalone",
            parent=planner,
            reason=str(exc) or "agent session lookup failed",
            planner_artifacts_dir=planner_artifacts_dir,
        )
    if attach is None:
        return CoderPlacement(
            mode="standalone",
            parent=planner,
            reason="agent session lookup failed",
            planner_artifacts_dir=planner_artifacts_dir,
        )
    if attach.parent_is_running and not recovery:
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


def resolve_model_directive(
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


def resolve_bead(
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


__all__ = ["resolve_bead", "resolve_model_directive", "resolve_placement"]
