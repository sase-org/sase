"""Custom notification-gate loading and modal dispatch."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...modals import CustomGateModalData
    from sase.notifications import Notification


_TEXT_PREVIEW_SUFFIXES = frozenset(
    {
        ".diff",
        ".json",
        ".md",
        ".patch",
        ".py",
        ".sh",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)
_MAX_PREVIEW_BYTES = 128 * 1024


def handle_custom_gate(app: object, notification: Notification) -> bool:
    """Load a verified generic gate off-pump and open its branch modal."""
    from ...util.pump_tasks import spawn_pump_free_task

    async def load_and_open() -> None:
        try:
            data = await asyncio.to_thread(_load_custom_gate_modal_data, notification)
        except Exception as exc:
            app.notify(  # type: ignore[attr-defined]
                f"Could not open gate: {exc}; press d on the notification to debug",
                severity="error",
            )
            return

        from ...modals import CustomGateModal, CustomGateModalResult
        from sase.notification_gates.debug import debug_context_from_notification
        from ._notification_gate_execution import (
            GateSubmission,
            submit_gate_execution_task,
        )

        def on_dismiss(result: object) -> None:
            if not isinstance(result, CustomGateModalResult):
                return
            submit_gate_execution_task(
                app,
                notification,
                GateSubmission(
                    selected_option_ids=result.selected_option_ids,
                    feedback=result.feedback,
                    input_data={},
                ),
            )

        app.push_screen(  # type: ignore[attr-defined]
            CustomGateModal(
                data,
                debug_context=debug_context_from_notification(notification),
                gate_keymaps=getattr(
                    getattr(app, "_keymap_registry", None), "gate", None
                ),
            ),
            on_dismiss,
        )

    task = spawn_pump_free_task(
        app,
        load_and_open(),
        name=f"custom-gate-open:{notification.id}",
        registry_attr="_custom_gate_open_tasks",
    )
    if task is None:
        app.notify("Custom gate loading is unavailable", severity="error")  # type: ignore[attr-defined]
        return False
    return True


def _load_custom_gate_modal_data(notification: Notification) -> CustomGateModalData:
    """Read and verify the custom gate bundle in a worker thread."""
    from ...modals import CustomGateModalData, GateBranchData
    from ...modals.notification_modal_constants import notification_icon
    from ...modals.notification_modal_tags import notification_origin_agent
    from sase.notification_gates.hashing import load_and_verify_bundle
    from sase.notification_gates.models import GateError
    from sase.notification_gates.paths import resolve_notification_bundle

    bundle = resolve_notification_bundle(notification)
    if bundle is None or bundle.legacy:
        raise GateError(
            "missing_gate",
            notification.id,
            "notification does not reference a neutral generic gate",
        )
    envelope, adapter = load_and_verify_bundle(bundle.root)
    if not adapter.generic_form:
        raise GateError(
            "missing_gate",
            notification.id,
            "notification does not reference a neutral generic gate",
        )
    gate = GateBranchData.from_envelope(
        envelope,
        default_feedback=adapter.default_feedback,
    )
    preview_path = _preview_path(notification)
    preview_text = _read_text_preview(preview_path)
    attachments = tuple(dict.fromkeys(Path(path).name for path in notification.files))
    return CustomGateModalData(
        request_id=str(envelope.get("request_id") or notification.id),
        title=adapter.display_title,
        sender=notification.sender,
        icon=notification_icon(notification.action, notification.icon),
        notes=tuple(notification.notes),
        attachments=attachments,
        preview_name=None if preview_path is None else preview_path.name,
        preview_text=preview_text,
        gate=gate,
        origin_agent=notification_origin_agent(notification),
    )


def _preview_path(notification: Notification) -> Path | None:
    raw = notification.action_data.get("preview_path")
    if raw:
        return Path(raw).expanduser()
    for value in notification.files:
        path = Path(value).expanduser()
        if path.suffix.lower() in _TEXT_PREVIEW_SUFFIXES:
            return path
    return None


def _read_text_preview(path: Path | None) -> str | None:
    if path is None or path.suffix.lower() not in _TEXT_PREVIEW_SUFFIXES:
        return None
    try:
        with path.open("rb") as stream:
            value = stream.read(_MAX_PREVIEW_BYTES + 1)
    except OSError as exc:
        return f"[Preview unavailable: {exc}]"
    if len(value) > _MAX_PREVIEW_BYTES:
        value = value[:_MAX_PREVIEW_BYTES]
        suffix = b"\n\n[Preview truncated]"
    else:
        suffix = b""
    return (value + suffix).decode("utf-8", errors="replace")


__all__ = ["handle_custom_gate"]
