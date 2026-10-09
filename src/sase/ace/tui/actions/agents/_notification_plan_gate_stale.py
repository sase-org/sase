"""Stale plan review reload for neutral plan gates."""

from __future__ import annotations

from typing import Any

from ._notification_plan_gate_load import (
    load_neutral_plan_modal_data,
    refresh_notifications,
)


def _extract_stale_kept_values(result: Any) -> dict[str, Any]:
    """Flatten stale submit decision_* values by decision id."""
    kept = dict(getattr(result, "option_inputs", None) or {})
    kept_values: dict[str, Any] = {}
    for inputs in kept.values():
        if not isinstance(inputs, dict):
            continue
        for key, value in inputs.items():
            if str(key).startswith("decision_"):
                decision_id = str(key).removeprefix("decision_")
                if decision_id not in kept_values:
                    kept_values[decision_id] = value
    return kept_values


def handle_stale_review(
    app: object,
    notification: Any,
    result: Any,
) -> bool:
    """Reload a stale review, keeping values by id; True when handled.

    The bundle reload runs off the message pump via ``spawn_pump_free_task``
    + ``asyncio.to_thread`` (the same path ``handle_plan_approval`` uses).
    Callers without a running loop fall back to a synchronous reload.
    """
    try:
        kept_values = _extract_stale_kept_values(result)
    except Exception:
        return False
    try:
        import asyncio

        from ...util.pump_tasks import spawn_pump_free_task

        loop: Any = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            try:
                request_name = str(
                    getattr(notification, "action_data", {}).get("request_id")
                    or getattr(notification, "id", "")
                )
            except Exception:
                request_name = ""

            async def _reload_and_apply() -> None:
                try:
                    reloaded = await asyncio.to_thread(
                        load_neutral_plan_modal_data,
                        notification,
                    )
                except Exception:
                    return
                try:
                    _apply_stale_reloaded(
                        app, notification, result, kept_values, reloaded
                    )
                except Exception:
                    return

            task = spawn_pump_free_task(
                app,
                _reload_and_apply(),
                name=f"stale-review-reload:{request_name or 'plan'}",
                registry_attr="_stale_review_reload_tasks",
            )
            if task is not None:
                return True
    except Exception:
        pass
    try:
        reloaded = load_neutral_plan_modal_data(notification)
    except Exception:
        return False
    return _apply_stale_reloaded(app, notification, result, kept_values, reloaded)


def _apply_stale_reloaded(
    app: object,
    notification: Any,
    result: Any,
    kept_values: dict[str, Any],
    reloaded: Any,
) -> bool:
    """Apply a reloaded stale bundle to the open modal or a fresh reopen.

    The closed-modal branch reopens through the real ``handle_plan_approval``
    open path (with its dismiss callback, action runner, gate keymaps, and
    copy-plan path) so a later submit is handled. Reviewer values stashed in
    ``esc_drafts`` are filtered to the new ids; vanished ids are dropped and
    new ids take their defaults. Returns True when handled.
    """
    try:
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
            # Closed modal: stash filtered submit values, then reopen through
            # the real open path so the fresh modal gets the dismiss callback,
            # action runner, gate keymaps, and copy-plan path. The modal reads
            # the stashed values; vanished ids stay dropped and new ids take
            # their defaults.
            try:
                from ...modals._plan_approval_modal_state import esc_drafts

                if request_id:
                    esc_drafts[request_id] = dict(filtered_submit)
            except Exception:
                pass
            try:
                from ._notification_modals import handle_plan_approval

                handle_plan_approval(app, notification, _loaded=reloaded)
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
            refresh_notifications(app)
        except Exception:
            pass
        return True
    except Exception:
        return False
