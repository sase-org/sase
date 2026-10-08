"""Neutral plan gate loading and response execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.actions._durable_ops import (
    durable_fingerprint,
    durable_request_payload,
    sase_argv,
)
from sase.ops.names import GATE_ANSWER
from ._notification_plan_response import (
    plan_approval_choice_for_status,
    request_agents_after_plan_response,
)
from sase.plan_approval_choices import PlanApprovalModalChoice

if TYPE_CHECKING:
    from sase.notification_gates.paths import ResolvedGateBundle
    from sase.notifications import Notification

    from ...models import Agent
    from ...modals import GateBranchData, PlanApprovalResult
    from ...modals.gate_action_controls import GateActionsData


@dataclass(frozen=True)
class PlanGateModalLoad:
    """Worker-loaded data needed to compose a neutral plan gate."""

    plan_file: str
    plan_content: str
    default_choice: PlanApprovalModalChoice
    gate: GateBranchData
    actions: GateActionsData
    bundle: ResolvedGateBundle
    decision_definitions: tuple[dict[str, Any], ...] = ()
    review_revision: int | None = None
    request_id: str = ""
    settled_text: str | None = None


def load_neutral_plan_modal_data(
    notification: Notification,
) -> PlanGateModalLoad:
    """Verify a v2 plan bundle and read its display content off the UI thread."""
    if not notification.files:
        raise RuntimeError("plan file is missing")
    from sase.notification_gates.hashing import load_and_verify_bundle
    from sase.notification_gates.paths import resolve_notification_bundle

    from ._notification_gate_actions import load_gate_actions
    from ...modals import GateBranchData

    bundle = resolve_notification_bundle(notification)
    if bundle is None or bundle.legacy:
        raise RuntimeError("notification does not reference a neutral plan gate")
    envelope, _adapter = load_and_verify_bundle(bundle.root)
    kind = envelope.get("kind")
    default_choice: PlanApprovalModalChoice = "epic" if kind == "epic_plan" else "tale"
    plan_file = notification.files[0]
    plan_content = Path(plan_file).expanduser().read_text(encoding="utf-8")
    payload = envelope.get("payload") if isinstance(envelope, dict) else None
    definitions = (
        list(payload.get("decisions", []))
        if isinstance(payload, dict) and isinstance(payload.get("decisions"), list)
        else []
    )
    try:
        revision = (
            int(envelope.get("review_revision", 1)) if isinstance(envelope, dict) else 1
        )
    except Exception:
        revision = 1
    request_id = str(notification.action_data.get("request_id") or notification.id)
    settled_text = _settled_text_for_bundle(bundle, definitions, default_choice)
    return PlanGateModalLoad(
        plan_file=plan_file,
        plan_content=plan_content,
        default_choice=default_choice,
        gate=GateBranchData.from_envelope(envelope),
        actions=load_gate_actions(bundle.root, dict(envelope)),
        bundle=bundle,
        decision_definitions=tuple(
            item for item in definitions if isinstance(item, dict)
        ),
        review_revision=revision,
        request_id=request_id,
        settled_text=settled_text,
    )


def _settled_text_for_bundle(
    bundle: Any,
    definitions: list[dict[str, Any]],
    default_choice: PlanApprovalModalChoice,
) -> str | None:
    """Return the settled-elsewhere banner, or ``None`` when still pending."""
    try:
        from sase.notification_gates.debug_artifacts import terminal_artifact
        from sase.notification_gates.debug_models import GateDebugBundlePaths

        paths = GateDebugBundlePaths(
            bundle.root,
            bundle.request,
            bundle.response,
            bundle.cancellation,
            bundle.legacy,
        )
        terminal, payload, kind = terminal_artifact(paths)
    except Exception:
        return None
    if kind != "response":
        return None
    try:
        status_ok = terminal.status == "ok"
    except Exception:
        status_ok = False
    if not status_ok:
        return None
    if not isinstance(payload, dict) or not payload.get("selected_option_ids"):
        return None
    surface = "another surface"
    try:
        raw_source = str(payload.get("source") or "").strip().lower()
        if raw_source in ("telegram", "cli", "tui", "mobile"):
            surface = {
                "telegram": "Telegram",
                "cli": "CLI",
                "tui": "ACE",
                "mobile": "Mobile",
            }[raw_source]
    except Exception:
        pass
    selected = tuple(payload.get("selected_option_ids") or ())
    if "reject" in selected:
        return f"Rejected via {surface}"
    if "feedback" in selected:
        return f"Feedback via {surface}"
    summary = ""
    try:
        from sase.ace.tui.modals.plan_decision_sheet import (
            PlanDecisionDraft,
            verdict_for_selection,
        )

        values: dict[str, Any] = {}
        option_inputs = payload.get("option_inputs")
        if isinstance(option_inputs, dict):
            for inputs in option_inputs.values():
                if not isinstance(inputs, dict):
                    continue
                for key, value in inputs.items():
                    if str(key).startswith("decision_"):
                        decision_id = str(key).removeprefix("decision_")
                        if decision_id not in values:
                            values[decision_id] = value
        draft = PlanDecisionDraft(definitions, values=values or None)
        epic = default_choice == "epic"
        commit = "commit" in selected
        run = "approve" in selected
        verdict = verdict_for_selection(commit_plan=commit, run_coder=run, epic=epic)
        summary = draft.full_summary(verdict)
    except Exception:
        summary = ""
    if summary:
        return f"Approved via {surface} · {summary}"
    return f"Approved via {surface}"


def submit_neutral_plan_response(
    app: object,
    notification: Notification,
    agent: Agent | None,
    result: PlanApprovalResult,
) -> bool:
    """Execute a neutral plan choice as tracked background work."""
    choice = result.choice or plan_approval_choice_for_status(result)
    if choice is None:
        choice = "feedback" if result.feedback else "reject"

    durable_submitted = _submit_durable_neutral_plan_response(
        app,
        notification,
        agent,
        result,
        choice,
    )
    if durable_submitted is not None:
        return durable_submitted

    submit = getattr(app, "_submit_session_worker", None)
    if not callable(submit):
        app.notify("Plan execution is unavailable", severity="error")  # type: ignore[attr-defined]
        return False

    from ...actions.proc_actions import TrackedProcResult
    from sase.main.plan_pending import plan_context_from_notification
    from sase.plan_approval_actions import execute_plan_approval_response

    def work() -> TrackedProcResult[object]:
        try:
            kwargs: dict[str, Any] = {
                "feedback": result.feedback,
                "commit_plan": result.commit_plan,
                "run_coder": result.run_coder,
                "coder_prompt": result.coder_prompt,
                "coder_model": result.coder_model,
                "wait": result.wait_spec,
                "capacity": result.capacity,
                "epic_launch_mode": "launch",
                "epic_launch_origin": "ace",
                "option_inputs": result.option_inputs or None,
                "source": "tui",
            }
            if result.review_revision is not None:
                kwargs["expected_review_revision"] = result.review_revision
            action_result = execute_plan_approval_response(
                plan_context_from_notification(notification),
                choice,
                **kwargs,  # type: ignore[arg-type]
            )
        except Exception as exc:
            return TrackedProcResult(
                success=False,
                message=str(exc),
                error=str(exc),
                payload={"code": getattr(exc, "code", None)},
            )
        return TrackedProcResult(
            success=True,
            message=action_result.message,
            payload=action_result,
        )

    def on_complete(completion: object) -> None:
        if not getattr(completion, "success", False):
            payload = getattr(completion, "payload", None)
            code = payload.get("code") if isinstance(payload, dict) else None
            if code is None:
                try:
                    from sase.notification_gates.models import GateError as _GateError

                    err = getattr(completion, "error", "")
                    if isinstance(err, _GateError):
                        code = err.code
                except Exception:
                    code = None
            if code == "stale_review":
                if _handle_stale_review(app, notification, result):
                    return
            app.notify(  # type: ignore[attr-defined]
                getattr(completion, "message", "Plan command failed"),
                severity="error",
            )
            return
        if agent is not None:
            if result.action == "reject" and result.feedback is None:
                app._agent_status_overrides.pop(agent.identity, None)  # type: ignore[attr-defined]
                app._do_kill_agent(agent)  # type: ignore[attr-defined]
            else:
                request_agents_after_plan_response(app, agent)
        app._refresh_notification_count()  # type: ignore[attr-defined]

    cl_name = (
        notification.action_data.get("agent_cl_name")
        or Path(notification.files[0]).stem
    )
    project_file = notification.action_data.get("agent_project_file") or (
        notification.action_data.get("project_dir") or notification.files[0]
    )
    submit(
        "plan-gate",
        work,
        display_name=f"Plan response: {choice}",
        cl_name=str(cl_name),
        project_file=str(project_file),
        on_complete=on_complete,
    )
    return True


def _submit_durable_neutral_plan_response(
    app: object,
    notification: Notification,
    agent: Agent | None,
    result: PlanApprovalResult,
    choice: PlanApprovalModalChoice | str,
) -> bool | None:
    """Submit a neutral plan response through ACE's durable proc queue."""
    submit = getattr(app, "_submit_durable_proc", None)
    if not callable(submit):
        return None

    from sase.notification_gates.paths import resolve_notification_bundle

    bundle = resolve_notification_bundle(notification)
    if bundle is None or bundle.legacy:
        return None

    request_id = str(notification.action_data.get("request_id") or notification.id)
    request_kind = str(notification.action_data.get("request_kind") or bundle.kind)
    selected_option_ids, input_data, per_option_inputs = _plan_gate_submission_payload(
        notification,
        result,
        choice,
    )

    def on_complete(completion: object) -> None:
        if not getattr(completion, "success", False):
            payload = getattr(completion, "payload", None)

            def report_failure() -> None:
                app.notify(  # type: ignore[attr-defined]
                    getattr(completion, "message", "Plan command failed"),
                    severity="error",
                )
                _refresh_notifications(app)

            if isinstance(payload, dict) and payload.get("code") == "stale_review":
                if _handle_stale_review(app, notification, result):
                    return
                report_failure()
                return
            if isinstance(payload, dict) and payload.get("code") == "partial_attempt":
                from ._notification_gate_execution import (
                    GateSubmission,
                    offer_partial_attempt_retry,
                )

                offer_partial_attempt_retry(
                    app,
                    notification,
                    GateSubmission(
                        selected_option_ids,
                        feedback=result.feedback,
                        input_data=(
                            None if per_option_inputs is not None else input_data
                        ),
                        option_inputs=per_option_inputs,
                    ),
                    bundle.root,
                    on_unavailable=report_failure,
                )
                return
            report_failure()
            return
        if agent is not None:
            if result.action == "reject" and result.feedback is None:
                app._agent_status_overrides.pop(agent.identity, None)  # type: ignore[attr-defined]
                app._do_kill_agent(agent)  # type: ignore[attr-defined]
            else:
                request_agents_after_plan_response(app, agent)
        _refresh_notifications(app)

    cl_name = str(
        notification.action_data.get("agent_cl_name")
        or (Path(notification.files[0]).stem if notification.files else request_id)
    )
    project_file = str(
        notification.action_data.get("agent_project_file")
        or notification.action_data.get("project_dir")
        or (notification.files[0] if notification.files else bundle.root)
    )

    payload_kwargs: dict[str, Any] = {
        "feedback": result.feedback,
        "input_data": None if per_option_inputs is not None else input_data,
        "option_ids": list(selected_option_ids),
        "option_inputs": per_option_inputs,
        "source": "tui",
    }
    if result.review_revision is not None:
        payload_kwargs["review_revision"] = result.review_revision
    task = submit(
        sase_argv(
            "gate",
            "answer",
            "--id",
            request_id,
            "--kind",
            request_kind,
            "--no-detach",
            "--json",
        ),
        operation=GATE_ANSWER,
        request=durable_request_payload(**payload_kwargs),
        request_fingerprint=durable_fingerprint(
            GATE_ANSWER,
            request_kind,
            request_id,
            ",".join(selected_option_ids),
            "tui",
        ),
        concurrency_keys=(f"notification-gate:{notification.id}",),
        label=f"Plan response: {choice}",
        display_name=f"Plan response: {choice}",
        cl_name=cl_name,
        project_file=project_file,
        on_complete=on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
    )
    if task is None:
        return False

    from ._notification_utils import schedule_gate_decision_receipt_refresh

    schedule_gate_decision_receipt_refresh(
        app,
        notification=notification,
        bundle_path=bundle.root,
        agent=agent,
    )
    return True


def _plan_gate_submission_payload(
    notification: Notification,
    result: PlanApprovalResult,
    choice: PlanApprovalModalChoice | str,
) -> tuple[tuple[str, ...], dict[str, object], dict[str, object] | None]:
    """Return gate.answer option ids and input payload for one plan result."""
    from sase.plan_approval_choices import plan_approval_selection_for_choice

    tier: Literal["tale", "epic"] = (
        "epic"
        if notification.action == "EpicApproval"
        or notification.action_data.get("request_kind") == "epic_plan"
        else "tale"
    )
    selected_option_ids = result.selected_option_ids
    if not selected_option_ids:
        selected_option_ids = plan_approval_selection_for_choice(
            str(choice),
            tier=tier,
            commit_plan=result.commit_plan,
            run_coder=result.run_coder,
        )

    input_data: dict[str, object] = {}
    if result.feedback is not None:
        input_data["feedback"] = result.feedback
    if "approve" in selected_option_ids and tier == "tale":
        if result.coder_prompt is not None:
            input_data["coder_prompt"] = result.coder_prompt
        if result.coder_model is not None:
            input_data["coder_model"] = result.coder_model
    if result.wait_spec is not None and any(
        option_id in selected_option_ids for option_id in ("approve", "commit")
    ):
        input_data["wait"] = result.wait_spec
    if tier == "epic" and selected_option_ids == ("approve",):
        input_data["epic_launch_mode"] = "launch"
        if result.capacity is not None:
            input_data["capacity"] = result.capacity

    per_option_inputs: dict[str, object] | None = None
    if result.option_inputs and any(result.option_inputs.values()):
        per_option_inputs = {
            option_id: {
                **input_data,
                **dict(result.option_inputs.get(option_id, {})),
            }
            for option_id in selected_option_ids
        }
    return selected_option_ids, input_data, per_option_inputs


def _refresh_notifications(app: object) -> None:
    schedule_refresh = getattr(app, "_schedule_notification_snapshot_refresh", None)
    if callable(schedule_refresh):
        schedule_refresh()
        return
    refresh = getattr(app, "_refresh_notification_count", None)
    if callable(refresh):
        refresh()


def prepare_settled_texts_for_notifications(
    notifications: list[Any],
) -> dict[str, str]:
    """Off-thread settled check: request id -> truthful banner, no UI work."""
    settled: dict[str, str] = {}
    try:
        from sase.notification_gates.paths import resolve_notification_bundle
    except Exception:
        return settled
    for notification in notifications or []:
        try:
            action = getattr(notification, "action", "")
            if action not in ("PlanApproval", "EpicApproval"):
                continue
            bundle = resolve_notification_bundle(notification)
            if bundle is None or getattr(bundle, "legacy", False):
                continue
            from sase.notification_gates.hashing import load_and_verify_bundle

            try:
                envelope, _adapter = load_and_verify_bundle(bundle.root)
            except Exception:
                continue
            payload = envelope.get("payload") if isinstance(envelope, dict) else None
            definitions = (
                list(payload.get("decisions", []))
                if isinstance(payload, dict)
                and isinstance(payload.get("decisions"), list)
                else []
            )
            kind = envelope.get("kind")
            default_choice: PlanApprovalModalChoice = (
                "epic" if kind == "epic_plan" else "tale"
            )
            text = _settled_text_for_bundle(bundle, definitions, default_choice)
            if text is None:
                continue
            request_id = str(
                getattr(notification, "action_data", {}).get("request_id")
                or getattr(notification, "id", "")
            )
            if request_id:
                settled[request_id] = text
        except Exception:
            continue
    return settled


def apply_settled_text_to_open_modal(app: object, settled: dict[str, str]) -> None:
    """UI-thread banner + block for an open plan modal that just settled."""
    if not settled:
        return
    try:
        screen = getattr(app, "screen", None)
    except Exception:
        return
    # The open plan modal is the current screen when reviewing.
    try:
        from ...modals.plan_approval_modal import PlanApprovalModal

        modal = screen if isinstance(screen, PlanApprovalModal) else None
        if modal is None:
            # Also check a pushed modal on the stack when available.
            stack = getattr(app, "screen_stack", None) or []
            for entry in reversed(list(stack)):
                candidate = getattr(entry, "screen", entry)
                if isinstance(candidate, PlanApprovalModal):
                    modal = candidate
                    break
    except Exception:
        return
    if modal is None:
        return
    try:
        request_id = str(getattr(modal, "_request_id", "") or "")
    except Exception:
        return
    text = settled.get(request_id)
    if not text:
        return
    if getattr(modal, "_settled_text", None) == text:
        return
    modal._settled_text = text  # type: ignore[attr-defined]
    try:
        from textual.widgets import Static as _Static

        try:
            banner = modal.query_one("#plan-settled-banner", _Static)
            banner.update(text)
            try:
                banner.remove_class("hidden")
            except Exception:
                pass
        except Exception:
            try:
                modal.mount(_Static(text, id="plan-settled-banner"))
            except Exception:
                pass
    except Exception:
        pass
    try:
        from ...modals.gate_branch_controls import GateBranchControls

        branch = modal.query_one(GateBranchControls)
        branch.block_submission("Settled elsewhere; submit is disabled")
    except Exception:
        pass


def _handle_stale_review(
    app: object,
    notification: Any,
    result: Any,
) -> bool:
    """Reload a stale review, keeping values by id; True when handled."""
    try:
        reloaded = load_neutral_plan_modal_data(notification)
    except Exception:
        return False
    try:
        kept = dict(getattr(result, "option_inputs", None) or {})
        # Flatten decision_* values by decision id from the stale submit.
        kept_values: dict[str, Any] = {}
        for inputs in kept.values():
            if not isinstance(inputs, dict):
                continue
            for key, value in inputs.items():
                if str(key).startswith("decision_"):
                    decision_id = str(key).removeprefix("decision_")
                    if decision_id not in kept_values:
                        kept_values[decision_id] = value
        try:
            new_definitions = list(
                getattr(reloaded, "decision_definitions", None) or []
            )
        except Exception:
            new_definitions = []
        new_ids = {str(d.get("id", "")) for d in new_definitions if isinstance(d, dict)}
        filtered_submit = {
            key: value for key, value in kept_values.items() if key in new_ids
        }
        try:
            from ...modals.plan_approval_modal import PlanApprovalModal

            screen = getattr(app, "screen", None)
            modal = screen if isinstance(screen, PlanApprovalModal) else None
            if modal is None:
                try:
                    stack = getattr(app, "screen_stack", None) or []
                    for entry in reversed(list(stack)):
                        candidate = getattr(entry, "screen", entry)
                        if isinstance(candidate, PlanApprovalModal):
                            modal = candidate
                            break
                except Exception:
                    modal = None
        except Exception:
            modal = None
        try:
            request_id = str(
                getattr(notification, "action_data", {}).get("request_id")
                or getattr(notification, "id", "")
            )
        except Exception:
            request_id = ""
        try:
            modal_request = (
                str(getattr(modal, "_request_id", "") or "")
                if modal is not None
                else ""
            )
        except Exception:
            modal_request = ""
        is_open = bool(modal is not None and request_id and modal_request == request_id)
        if is_open and modal is not None:
            # Open modal: do not push a second modal. Merge live draft as base
            # with the submit overlay, filtered to the new ids.
            merged: dict[str, Any] = {}
            try:
                from ...modals.plan_decision_sheet import PlanDecisionDraft

                current = dict(modal._decision_draft.values())  # type: ignore[attr-defined]
                merged = {
                    key: value
                    for key, value in {**current, **kept_values}.items()
                    if key in new_ids
                }
                modal._decision_definitions = list(new_definitions)  # type: ignore[attr-defined]
                modal._review_revision = getattr(  # type: ignore[attr-defined]
                    reloaded, "review_revision", None
                )
                modal._decision_draft = PlanDecisionDraft(  # type: ignore[attr-defined]
                    list(new_definitions),
                    values=merged or None,
                    review_revision=int(
                        getattr(reloaded, "review_revision", None) or 0
                    ),
                )
            except Exception:
                pass
            # Reload, not a keypress: new plan text refreshes fold + spans.
            try:
                new_content = getattr(reloaded, "plan_content", None)
                if isinstance(new_content, str):
                    modal._plan_content = new_content  # type: ignore[attr-defined]
                    try:
                        modal._last_fold_content = None  # type: ignore[attr-defined, assignment]
                    except Exception:
                        pass
                    try:
                        modal._ensure_callout_spans(new_content)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    try:
                        folded = modal._ensure_fold_cache(new_content)  # type: ignore[attr-defined]
                    except Exception:
                        folded = new_content
                else:
                    try:
                        folded = getattr(modal, "_folded_text", "")  # type: ignore[attr-defined]
                    except Exception:
                        folded = ""
            except Exception:
                folded = ""
            # Rebuild rows from the new sheet + definitions.
            try:
                from ...modals.plan_decision_rows import PlanDecisionRows

                sheet_rows: list[dict[str, Any]] = []
                try:
                    sheet_rows = list(
                        modal._decision_draft.sheet().get("rows", [])  # type: ignore[attr-defined]
                    )
                except Exception:
                    sheet_rows = []
                try:
                    rows = modal.query_one("#plan-decision-rows", PlanDecisionRows)  # type: ignore[attr-defined]
                    rows.rebuild(sheet_rows, list(new_definitions))
                except Exception:
                    pass
            except Exception:
                pass
            try:
                from textual.widgets import Static as _Static

                try:
                    modal.query_one("#plan-approval-content", _Static).update(  # type: ignore[attr-defined]
                        modal._document_renderable(folded)  # type: ignore[attr-defined]
                    )
                except Exception:
                    pass
            except Exception:
                pass
            try:
                modal._refresh_verdict_summary()  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                from textual.widgets import Static as _StaticFooter

                try:
                    modal.query_one("#plan-approval-footer", _StaticFooter).update(  # type: ignore[attr-defined]
                        modal._footer_text()  # type: ignore[attr-defined]
                    )
                except Exception:
                    pass
            except Exception:
                pass
            try:
                from ...modals._plan_approval_modal_state import esc_drafts as _drafts

                if request_id:
                    # Keep screen + later Esc reopen in sync.
                    try:
                        _drafts[request_id] = dict(
                            modal._decision_draft.values()  # type: ignore[attr-defined]
                        )
                    except Exception:
                        _drafts[request_id] = dict(merged)
            except Exception:
                pass
        else:
            # Closed modal: stash filtered submit values and push a fresh modal.
            try:
                from ...modals._plan_approval_modal_state import esc_drafts

                if request_id:
                    esc_drafts[request_id] = dict(filtered_submit)
            except Exception:
                pass
            try:
                from ...modals.plan_approval_modal import PlanApprovalModal as _Modal

                plan_file = getattr(reloaded, "plan_file", None) or (
                    notification.files[0]
                    if getattr(notification, "files", [])
                    else "/tmp/plan.md"
                )
                push_kwargs: dict[str, Any] = {
                    "plan_file": str(plan_file),
                    "default_choice": getattr(reloaded, "default_choice", None)
                    or "tale",
                    "gate": getattr(reloaded, "gate", None),
                    "plan_content": getattr(reloaded, "plan_content", None),
                    "decision_definitions": list(new_definitions),
                    "review_revision": getattr(reloaded, "review_revision", None),
                    "request_id": request_id or getattr(reloaded, "request_id", ""),
                    "settled_text": getattr(reloaded, "settled_text", None),
                }
                # Match _notification_modals fields the load carries; drop Nones
                # the constructor already defaults except actions/gate.
                actions = getattr(reloaded, "actions", None)
                if actions is not None:
                    push_kwargs["actions"] = actions
                # Gate is required; skip push when the stand-in lacks it.
                if push_kwargs.get("gate") is not None:
                    app.push_screen(_Modal(**push_kwargs))  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            app.notify(  # type: ignore[attr-defined]
                "The plan changed; your review was reloaded with your values kept.",
                severity="warning",
            )
        except Exception:
            pass
        try:
            _refresh_notifications(app)
        except Exception:
            pass
        return True
    except Exception:
        return False
