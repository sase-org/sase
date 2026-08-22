"""Modal-based notification action handler exports.

Keeps historical imports stable while focused modules handle individual flows.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ._notification_custom_gate import handle_custom_gate as handle_custom_gate
from ._notification_hitl_modal import handle_hitl as handle_hitl
from ._notification_launch_approval import (
    handle_launch_approval as handle_launch_approval,
)
from ._notification_modal_responses import write_workflow_action_response
from ._notification_plan_background import (
    add_saved_plan_to_response as _add_saved_plan_to_response,
    archive_plan_for_approval as _archive_plan_for_approval,
    call_on_app_thread as _call_on_app_thread,
    finish_plan_approval_background_work as _finish_plan_approval_background_work,
)
from ._notification_plan_gate import (
    PlanGateModalLoad as _PlanGateModalLoad,
    load_neutral_plan_modal_data as _load_neutral_plan_modal_data,
    submit_neutral_plan_response as submit_neutral_plan_response,
)
from ._notification_plan_persistence import (
    persist_plan_approved as persist_plan_approved,
)
from ._notification_plan_response import (
    build_plan_approval_response as _build_plan_approval_response,
    plan_approval_choice_for_status as _plan_approval_choice_for_status,
    plan_approval_persist_action as _plan_approval_persist_action,
    plan_approval_protocol_fields as _plan_approval_protocol_fields,
    plan_approval_status as _plan_approval_status,
    refresh_agents_from_cache as _refresh_agents_from_cache,
)
from ._notification_question_modal import (
    handle_user_question as handle_user_question,
    open_user_question_modal_from_marker as open_user_question_modal_from_marker,
)
from sase.plan_approval_choices import (
    PlanApprovalModalChoice,
    approval_choice_archives_plan,
)

if TYPE_CHECKING:
    from sase.notification_gates.paths import ResolvedGateBundle
    from sase.notifications import Notification

    from ...models import Agent
    from ...modals import GateBranchData, PlanApprovalResult
    from ...modals.gate_action_controls import GateActionsData
    from ...modals.gate_action_runner import GateActionRunner


log = logging.getLogger(__name__)


def handle_plan_approval(
    app: object,
    notification: Notification,
    pending_approve_state: object | None = None,
    *,
    _loaded: _PlanGateModalLoad | None = None,
) -> bool:
    """Show the plan approval modal for a Claude Code plan.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            response_dir and session_id.
        pending_approve_state: Optional PendingApproveState to auto-push
            the custom approval modal with restored state.

    Returns:
        True if the plan approval modal was pushed.
    """
    from ...modals import PlanApprovalModal, PlanApprovalResult

    from sase.notification_gates.debug import debug_context_from_notification

    if _loaded is None and notification.action_data.get("bundle_path"):
        from ...util.pump_tasks import spawn_pump_free_task

        async def load_and_open() -> None:
            try:
                loaded = await asyncio.to_thread(
                    _load_neutral_plan_modal_data,
                    notification,
                )
            except Exception as exc:
                app.notify(  # type: ignore[attr-defined]
                    f"Could not open plan gate: {exc}; press d on the notification to debug",
                    severity="error",
                )
                return
            handle_plan_approval(
                app,
                notification,
                pending_approve_state,
                _loaded=loaded,
            )

        task = spawn_pump_free_task(
            app,
            load_and_open(),
            name=f"plan-gate-open:{notification.id}",
            registry_attr="_plan_gate_open_tasks",
        )
        if task is not None:
            return True
        try:
            _loaded = _load_neutral_plan_modal_data(notification)
        except Exception as exc:
            app.notify(  # type: ignore[attr-defined]
                f"Could not open plan gate: {exc}; press d on the notification to debug",
                severity="error",
            )
            return False

    if _loaded is not None:
        bundle = _loaded.bundle
    else:
        from sase.notification_gates.paths import resolve_notification_bundle

        resolved_bundle = resolve_notification_bundle(notification)
        if resolved_bundle is None:
            app.notify(  # type: ignore[attr-defined]
                "No plan request in notification; press d on the notification to debug",
                severity="warning",
            )
            return False
        bundle = resolved_bundle

    response_path = bundle.root
    request_path = bundle.request

    if _loaded is None and not request_path.exists():
        app.notify(  # type: ignore[attr-defined]
            "Plan approval request expired or not found; press d on the notification to debug",
            severity="warning",
        )
        return False
    # Get plan file path from the worker projection or legacy notification.
    if _loaded is None and not notification.files:
        app.notify(  # type: ignore[attr-defined]
            "No plan file in notification; press d on the notification to debug",
            severity="warning",
        )
        return False

    plan_file = _loaded.plan_file if _loaded is not None else notification.files[0]
    original_plan_file = notification.action_data.get("original_plan_file", "").strip()
    copy_plan_path = original_plan_file or plan_file
    plan_content = None if _loaded is None else _loaded.plan_content
    llm_provider = notification.action_data.get("llm_provider")
    model = notification.action_data.get("model")
    if _loaded is not None:
        default_choice: PlanApprovalModalChoice | None = _loaded.default_choice
        gate: GateBranchData | None = _loaded.gate
    else:
        from sase.sdd.plan_tiers import read_plan_tier

        authored_tier = read_plan_tier(Path(plan_file).expanduser())
        default_choice = (
            cast(PlanApprovalModalChoice, authored_tier)
            if authored_tier in {"tale", "epic"}
            else None
        )
        gate = None

    actions, action_runner = _plan_gate_actions(
        app,
        notification,
        bundle=bundle,
        loaded=_loaded,
        plan_file=plan_file,
    )

    def on_dismiss(result: object) -> None:
        if result is None:
            return
        if not isinstance(result, PlanApprovalResult):
            return

        # Feedback requested: dismiss modal and mount PromptInputBar in feedback mode
        if result.action == "feedback_requested":
            from ._notification_navigation import find_agent_for_notification as _find

            from ...widgets import PromptInputBar

            agent = _find(app, notification)
            agent_identity = agent.identity if agent is not None else None

            from ._types import PlanFeedbackContext

            app._plan_feedback_context = PlanFeedbackContext(  # type: ignore[attr-defined]
                notification_id=notification.id,
                response_path=response_path,
                agent_identity=agent_identity,
                plan_file=plan_file,
                notification=notification,
            )
            app.mount(PromptInputBar(mode="feedback", id="prompt-input-bar"))  # type: ignore[attr-defined]
            return

        # Approve prompt edit: delegate prompt editing to PromptInputBar
        if result.action == "approve_prompt_edit":
            from ...widgets import PromptInputBar

            from ._types import ApprovePromptContext

            app._approve_prompt_context = ApprovePromptContext(  # type: ignore[attr-defined]
                notification=notification,
                plan_file=plan_file,
                commit_plan=result.commit_plan,
                run_coder=result.run_coder,
                current_prompt=result.coder_prompt or "",
                coder_model=result.coder_model,
                choice=result.choice,
            )
            app.mount(  # type: ignore[attr-defined]
                PromptInputBar(
                    initial_value=result.coder_prompt or "",
                    mode="approve_prompt",
                    id="prompt-input-bar",
                )
            )
            return

        # Find matching agent for status override updates
        from ._notification_navigation import find_agent_for_notification

        agent = find_agent_for_notification(app, notification)

        if not bundle.legacy:
            submit_neutral_plan_response(app, notification, agent, result)
            return

        # Reject without feedback: write response file so external watchers
        # (e.g. Telegram) can detect the rejection, then kill the agent.
        if result.action == "reject" and result.feedback is None:
            plan_response_path = response_path / "plan_response.json"
            write_workflow_action_response(
                plan_response_path,
                {"action": "reject"},
                action_kind="plan_approval",
                notification_id=notification.id,
            )

            from sase.notifications import mark_dismissed

            mark_dismissed(notification.id)
            if agent is not None:
                # Clear overrides before kill (_do_kill_agent calls _load_agents)
                app._agent_status_overrides.pop(agent.identity, None)  # type: ignore[attr-defined]
                app._agent_pre_question_status.pop(agent.identity, None)  # type: ignore[attr-defined]
                app._do_kill_agent(agent)  # type: ignore[attr-defined]
            else:
                app.notify("Rejected plan (agent not found)")  # type: ignore[attr-defined]
            return

        # Write response file (for approve and reject with feedback). This is
        # the latency-sensitive part: blocked agent runners watch this file.
        plan_response_path = response_path / "plan_response.json"
        choice = _plan_approval_choice_for_status(result)
        if choice in {"tale", "epic"}:
            from sase.plan_approval_actions import (
                PlanApprovalValidationError,
                require_plan_approval_validation,
            )

            try:
                require_plan_approval_validation(plan_file, choice)
            except PlanApprovalValidationError as exc:
                app.notify(  # type: ignore[attr-defined]
                    str(exc),
                    title=f"{choice.title()} approval blocked",
                    severity="error",
                    timeout=15,
                )
                return

        response_data = _build_plan_approval_response(
            result,
            # Transitional compatibility for pre-upgrade agents.
            epic_launch_owner="host" if choice == "epic" else None,
        )
        prepared_saved_plan_path = response_data.get("saved_plan_path")
        try:
            from sase.plan_approval_actions import (
                PlanApprovalActionContext,
                PlanApprovalActionError,
                prepare_plan_terminal_response,
            )

            prepare_plan_terminal_response(
                PlanApprovalActionContext(
                    id=notification.id,
                    host_files=tuple(str(path) for path in notification.files),
                    host_action_data={
                        str(key): str(value)
                        for key, value in notification.action_data.items()
                    },
                ),
                choice or result.action,
                response_data,
            )
            prepared_saved_plan_path = response_data.get("saved_plan_path")
        except PlanApprovalActionError as exc:
            app.notify(  # type: ignore[attr-defined]
                str(exc),
                title="Plan archive failed",
                severity="error",
                timeout=15,
            )
            return

        try:
            write_workflow_action_response(
                plan_response_path,
                response_data,
                action_kind="plan_approval",
                notification_id=notification.id,
            )
            app.notify(f"Sent plan {result.action} response")  # type: ignore[attr-defined]
        except Exception as e:
            app.notify(f"Error writing response: {e}", severity="error")  # type: ignore[attr-defined]
            return

        if choice == "epic":
            _submit_legacy_epic_launch_task(
                app,
                notification,
                plan_file=plan_file,
                response_dir=response_path,
            )

        # Update the visible status from cached in-memory data immediately.
        if agent is not None:
            status = _plan_approval_status(result)
            if status is not None:
                app._agent_status_overrides[agent.identity] = status  # type: ignore[attr-defined]
                _refresh_agents_from_cache(app, agent)

        _start_plan_approval_background_worker(
            app,
            notification,
            agent,
            result,
            plan_response_path,
            prepared_saved_plan_path=(
                prepared_saved_plan_path
                if isinstance(prepared_saved_plan_path, str)
                else None
            ),
            archive_in_background=False,
        )

    app.push_screen(  # type: ignore[attr-defined]
        PlanApprovalModal(
            plan_file,
            pending_approve_state=pending_approve_state,  # type: ignore[arg-type]
            copy_plan_path=copy_plan_path,
            llm_provider=llm_provider,
            model=model,
            default_choice=default_choice,
            gate=gate,
            plan_content=plan_content,
            debug_context=debug_context_from_notification(notification),
            gate_keymaps=getattr(getattr(app, "_keymap_registry", None), "gate", None),
            actions=actions,
            action_runner=action_runner,
        ),
        on_dismiss,
    )
    return True


def _plan_gate_actions(
    app: object,
    notification: Notification,
    *,
    bundle: ResolvedGateBundle,
    loaded: _PlanGateModalLoad | None,
    plan_file: str,
) -> tuple[GateActionsData, GateActionRunner]:
    """Return the declared plan actions and the runner that executes them.

    A legacy notification has no bundle to accept an edit into, so it gets the
    synthesized edit action instead: the reviewer keeps ``e``, and the modal
    keeps one rendering path.
    """
    from ._notification_gate_actions import (
        NotificationGateActionRunner,
        PlainFileEditRunner,
        legacy_plan_edit_actions,
    )

    if loaded is None or bundle.legacy:
        return (
            legacy_plan_edit_actions(),
            PlainFileEditRunner(app=app, path=Path(plan_file).expanduser()),
        )
    return (
        loaded.actions,
        NotificationGateActionRunner(
            app=app,
            notification=notification,
            bundle_path=bundle.root,
            operations=loaded.actions.operations,
        ),
    )


def _submit_legacy_epic_launch_task(
    app: object,
    notification: Notification,
    *,
    plan_file: str,
    response_dir: Path,
) -> bool:
    """Run legacy epic launch preflight/submission as tracked TUI work."""
    from ...actions.proc_actions import TrackedProcResult
    from sase.main.plan_pending import plan_context_from_notification
    from sase.plan_approval_actions import (
        PlanApprovalActionError,
        prepare_epic_launch,
    )

    def work() -> TrackedProcResult[object]:
        try:
            task = prepare_epic_launch(
                plan_context_from_notification(notification),
                plan_file,
                mode="launch",
                response_dir=response_dir,
                origin="ace",
            )
        except PlanApprovalActionError as exc:
            return TrackedProcResult(
                success=False,
                message=str(exc),
                error=str(exc),
            )
        except Exception as exc:
            log.exception("Legacy epic launch task failed")
            return TrackedProcResult(
                success=False,
                message=str(exc),
                error=str(exc),
            )
        return TrackedProcResult(
            success=True,
            message="Epic launch submitted",
            payload=task,
        )

    def on_complete(completion: object) -> None:
        if getattr(completion, "success", False):
            return
        app.notify(  # type: ignore[attr-defined]
            getattr(completion, "message", "Epic launch failed"),
            title="Epic launch failed",
            severity="error",
            timeout=15,
        )

    submit = getattr(app, "_submit_session_worker", None)
    if not callable(submit):
        app.notify(  # type: ignore[attr-defined]
            "Epic launch execution is unavailable",
            title="Epic launch failed",
            severity="error",
            timeout=15,
        )
        return False

    cl_name = str(
        notification.action_data.get("agent_cl_name")
        or Path(plan_file).expanduser().stem
    )
    project_file = str(
        notification.action_data.get("agent_project_file")
        or notification.action_data.get("project_dir")
        or plan_file
    )
    submit(
        "launch",
        work,
        display_name=f"Launch epic: {Path(plan_file).expanduser().stem}",
        cl_name=cl_name,
        project_file=project_file,
        dedup_key=f"legacy-epic-launch:{notification.id}",
        on_complete=on_complete,
    )
    return True


def _start_plan_approval_background_worker(
    app: object,
    notification: Notification,
    agent: Agent | None,
    result: PlanApprovalResult,
    plan_response_path: Path,
    *,
    prepared_saved_plan_path: str | None = None,
    archive_in_background: bool = True,
) -> None:
    """Run non-critical plan approval side effects off the TUI keypress path."""

    def work() -> str | None:
        saved_plan_path: str | None = prepared_saved_plan_path
        try:
            from sase.notifications import mark_dismissed

            mark_dismissed(notification.id)
        except Exception:
            log.warning("Failed to dismiss plan approval notification", exc_info=True)

        persist_action = _plan_approval_persist_action(result)
        if agent is not None and persist_action is not None:
            try:
                persist_plan_approved(agent, action=persist_action)
            except Exception:
                log.warning("Failed to persist plan approval marker", exc_info=True)

        choice = _plan_approval_choice_for_status(result)
        if (
            archive_in_background
            and choice is not None
            and approval_choice_archives_plan(choice)
        ):
            archive = _archive_plan_for_approval(notification, result.action)
            if archive is not None:
                _add_saved_plan_to_response(plan_response_path, archive)
                saved_plan_path = str(archive)

        _call_on_app_thread(
            app,
            lambda: _finish_plan_approval_background_work(
                app,
                result,
                saved_plan_path,
            ),
        )
        return saved_plan_path

    run_worker = getattr(app, "run_worker", None)
    if callable(run_worker):
        try:
            run_worker(work, thread=True)
            return
        except Exception:
            log.debug(
                "Falling back to synchronous plan approval side effects", exc_info=True
            )

    work()
