"""Coder launch ladder for gateless ``sase plan approve`` runs."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from sase.main.plan_direct_approval_types import CoderPlacement, DirectApprovalPlan


@dataclass
class CoderLaunch:
    """Outcome of the coder launch ladder."""

    coder: object | None = None
    error: str | None = None
    prompt: str = ""
    placement: CoderPlacement | None = None
    notes: tuple[str, ...] = ()


def _host_composed_attach_env(prompt: str) -> dict[str, str]:
    """Return a trusted host-composed attach env for a session coder prompt.

    Direct approval and coder recovery launch a host-composed coder when a
    planner/session exists: the prompt's own ``%id(suffix, session=parent)``
    resolves through the existing session placement, but the child must
    inherit the planner's live autonomy record instead of resolving from
    its own prompt. Human-authored session attaches never pass through
    this helper and keep resolving from their own prompt. Failures return
    no env so the launch falls back to the historical path.
    """
    try:
        from dataclasses import replace as _replace

        from sase.agent._agent_session_attach_directives import (
            extract_agent_session_attach_directive,
        )
        from sase.agent._agent_session_attach_resolution import (
            resolve_agent_session_attach_plan,
        )
        from sase.agent.detached_child import agent_session_attach_env
        from sase.main.utils import ensure_project_file_and_get_workspace_num
    except Exception:
        return {}
    try:
        directive = extract_agent_session_attach_directive(prompt)
        if directive is None:
            return {}
        _, _, project_name = ensure_project_file_and_get_workspace_num(
            create_missing=False
        )
        if not project_name:
            return {}
        plan = resolve_agent_session_attach_plan(directive, project_name=project_name)
        plan = _replace(plan, host_composed=True)
        return agent_session_attach_env(plan)
    except Exception:
        return {}


def launch_coder_once(prompt: str, local_plan: Path) -> object:
    """Launch one coder exactly as the historical direct-approval path did."""
    from sase.agent.launch_cwd import launch_agents_from_cwd
    from sase.agent.launch_executor_workspace import (
        SASE_AGENT_PINNED_WORKSPACE_FALLBACK,
    )

    extra_env: dict[str, str] = {
        "SASE_PLAN": str(local_plan),
        SASE_AGENT_PINNED_WORKSPACE_FALLBACK: "pool",
    }
    extra_env.update(_host_composed_attach_env(prompt))
    results = launch_agents_from_cwd(
        prompt,
        extra_env=extra_env,
        origin="generated",
    )
    if not results:
        raise RuntimeError("agent launch produced no results")
    return results[0]


def launch_coder_with_fallbacks(
    plan: DirectApprovalPlan,
    local_plan: Path,
    plan_argument: str,
    *,
    launch: Callable[[str, Path], object] = launch_coder_once,
) -> CoderLaunch:
    """Launch a coder through the planned → standalone → transient ladder."""
    from sase.main.plan_direct_approval import compose_coder_prompt

    notes: list[str] = []
    # 1. Precheck: the only cheap unlaunchable-machine signal.
    try:
        from sase.config._owner import require_agent_owner_identity

        require_agent_owner_identity()
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        return CoderLaunch(
            coder=None,
            error=message,
            prompt="",
            placement=plan.placement,
            notes=tuple(notes),
        )

    # 2. Planned placement.
    prompt = compose_coder_prompt(
        project_tag=plan.project_tag,
        model_directive=plan.model_directive,
        plan_argument=plan_argument,
        extra_prompt=plan.request.coder_prompt,
        wait=plan.request.wait,
        bead=plan.bead,
        placement=plan.placement,
    )
    try:
        coder = launch(prompt, local_plan)
        relocation = getattr(coder, "workspace_relocation", None)
        if relocation:
            notes.append(str(relocation))
        return CoderLaunch(
            coder=coder,
            error=None,
            prompt=prompt,
            placement=plan.placement,
            notes=tuple(notes),
        )
    except Exception as exc:
        if _is_fatal(exc):
            return CoderLaunch(
                coder=None,
                error=str(exc) or type(exc).__name__,
                prompt=prompt,
                placement=plan.placement,
                notes=tuple(notes),
            )
        last_error = exc
        last_error_message = str(exc) or type(exc).__name__
        notes.append(f"session attempt failed: {last_error_message}")
        effective_placement = plan.placement
        last_prompt = prompt

    # 3. Standalone fallback when the planned placement needed a session.
    if effective_placement.mode == "session" and not _is_fatal(last_error):
        session_name = (
            effective_placement.agent_session or effective_placement.parent or "unknown"
        )
        standalone = CoderPlacement(
            mode="standalone",
            parent=effective_placement.parent,
            reason=f"agent session launch failed: {last_error_message}",
            planner_artifacts_dir=effective_placement.planner_artifacts_dir,
        )
        try:
            from sase.main.plan_direct_approval_placement import resolve_bead

            bead = resolve_bead(plan.source_path, standalone, plan.project)
        except Exception:
            bead = None
        standalone_prompt = compose_coder_prompt(
            project_tag=plan.project_tag,
            model_directive=plan.model_directive,
            plan_argument=plan_argument,
            extra_prompt=plan.request.coder_prompt,
            wait=plan.request.wait,
            bead=bead,
            placement=standalone,
        )
        try:
            coder = launch(standalone_prompt, local_plan)
            relocation = getattr(coder, "workspace_relocation", None)
            if relocation:
                notes.append(str(relocation))
            notes.append(
                f"could not join agent session {session_name} "
                f"({last_error_message}); launched standalone"
            )
            return CoderLaunch(
                coder=coder,
                error=None,
                prompt=standalone_prompt,
                placement=standalone,
                notes=tuple(notes),
            )
        except Exception as exc:
            if _is_fatal(exc):
                return CoderLaunch(
                    coder=None,
                    error=str(exc) or type(exc).__name__,
                    prompt=standalone_prompt,
                    placement=standalone,
                    notes=tuple(notes),
                )
            last_error = exc
            last_error_message = str(exc) or type(exc).__name__
            notes.append(f"standalone attempt failed: {last_error_message}")
            effective_placement = standalone
            last_prompt = standalone_prompt

    # 4. One transient retry of the last placement.
    if _is_transient(last_error):
        time.sleep(2)
        try:
            coder = launch(last_prompt, local_plan)
            relocation = getattr(coder, "workspace_relocation", None)
            if relocation:
                notes.append(str(relocation))
            return CoderLaunch(
                coder=coder,
                error=None,
                prompt=last_prompt,
                placement=effective_placement,
                notes=tuple(notes),
            )
        except Exception as exc:
            last_error = exc
            last_error_message = str(exc) or type(exc).__name__
            notes.append(f"retry attempt failed: {last_error_message}")

    return CoderLaunch(
        coder=None,
        error=last_error_message,
        prompt=last_prompt,
        placement=effective_placement,
        notes=tuple(notes),
    )


def _is_fatal(exc: BaseException) -> bool:
    """Return whether *exc* must stop the ladder immediately."""
    try:
        from sase.agent.launch_guard import DisabledProviderLaunchError

        if isinstance(exc, DisabledProviderLaunchError):
            return True
    except Exception:
        pass
    try:
        from sase.agent.launch_request_types import TypedAdmissionRequiredError

        if isinstance(exc, TypedAdmissionRequiredError):
            return True
    except Exception:
        pass
    try:
        from sase.project_tags.tags import ProjectTagError

        if isinstance(exc, ProjectTagError):
            return True
    except Exception:
        pass
    try:
        from sase.workspace_provider.utils import ProjectProviderMismatchError

        if isinstance(exc, ProjectProviderMismatchError):
            return True
    except Exception:
        pass
    return False


def _is_transient(exc: BaseException) -> bool:
    """Return whether *exc* warrants one retry of the last placement."""
    try:
        from sase.running_field import WorkspaceClaimError

        if isinstance(exc, WorkspaceClaimError):
            return True
    except Exception:
        pass
    if isinstance(exc, (TimeoutError, BlockingIOError, InterruptedError)):
        return True
    try:
        from sase.notification_gates.model_validation import GateError

        if isinstance(exc, GateError) and getattr(exc, "code", None) == "lock_timeout":
            return True
    except Exception:
        pass
    return False


__all__ = ["CoderLaunch", "launch_coder_once", "launch_coder_with_fallbacks"]
