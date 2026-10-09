"""Neutral plan gate loading and settled-banner helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.plan_approval_choices import PlanApprovalModalChoice

if TYPE_CHECKING:
    from sase.notification_gates.paths import ResolvedGateBundle
    from sase.notifications import Notification

    from ...modals import GateBranchData
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


def refresh_notifications(app: object) -> None:
    """Refresh notification counts through the newest available entry point."""
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
