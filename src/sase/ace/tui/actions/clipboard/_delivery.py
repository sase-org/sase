"""One asynchronous clipboard-delivery seam for the ACE TUI."""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import Callable
from enum import StrEnum
from typing import Literal

from sase.core.clipboard import copy_to_system_clipboard

from ...util.pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)

# Terminal OSC 52 buffers are commonly capped near 64 KiB. Guard the encoded
# payload rather than the source text because the terminal receives base64.
OSC52_MAX_BASE64_BYTES = 64 * 1024

CopyFailurePolicy = Literal["modal", "toast", "silent"]
CopiedLabel = str | Callable[[], str]


class CopyDeliveryOutcome(StrEnum):
    """The strongest clipboard transport result that ACE can honestly report."""

    VERIFIED = "verified"
    OSC52_ONLY = "osc52_only"
    FAILED = "failed"


def _notification_owner(owner: object) -> object:
    app = getattr(owner, "app", None)
    return owner if callable(getattr(owner, "notify", None)) else (app or owner)


def _app_for(owner: object) -> object:
    return getattr(owner, "app", owner)


def _notify(
    owner: object,
    message: str,
    *,
    severity: Literal["information", "warning", "error"] = "information",
) -> None:
    notify = getattr(_notification_owner(owner), "notify", None)
    if callable(notify):
        notify(message, severity=severity)


def _emit_osc52(owner: object, value: str) -> bool:
    """Emit Textual's OSC 52 write when a live driver and payload allow it."""
    encoded_size = len(base64.b64encode(value.encode("utf-8")))
    if encoded_size > OSC52_MAX_BASE64_BYTES:
        return False

    app = _app_for(owner)
    if getattr(app, "_driver", object()) is None:
        return False
    copy_to_clipboard = getattr(app, "copy_to_clipboard", None)
    if not callable(copy_to_clipboard):
        return False
    try:
        copy_to_clipboard(value)
    except Exception:
        log.exception("OSC 52 clipboard emission failed")
        return False
    return True


def _show_fallback(owner: object, value: str) -> bool:
    from ...modals.copy_fallback_modal import CopyFallbackModal

    push_screen = getattr(_app_for(owner), "push_screen", None)
    if not callable(push_screen):
        return False
    try:
        push_screen(CopyFallbackModal(value))
    except Exception:
        log.exception("Unable to open clipboard fallback modal")
        return False
    return True


async def deliver_copy(
    owner: object,
    value: str | Callable[[], str],
    *,
    copied_label: CopiedLabel,
    on_failure: CopyFailurePolicy = "modal",
) -> CopyDeliveryOutcome:
    """Resolve and deliver clipboard content without blocking the event loop."""
    label = copied_label if isinstance(copied_label, str) else "content"
    try:
        resolved = await asyncio.to_thread(value) if callable(value) else value
        if callable(copied_label):
            label = copied_label()
    except Exception as exc:
        if on_failure != "silent":
            _notify(
                owner,
                f"Unable to copy {label} — {exc}",
                severity="error",
            )
        return CopyDeliveryOutcome.FAILED

    try:
        verified = await asyncio.to_thread(copy_to_system_clipboard, resolved)
    except Exception:
        log.exception("System clipboard transport failed unexpectedly")
        verified = False

    osc52_emitted = _emit_osc52(owner, resolved)
    if verified:
        _notify(owner, f"Copied {label}")
        return CopyDeliveryOutcome.VERIFIED
    if osc52_emitted:
        _notify(owner, f"Copied {label} (OSC 52)")
        return CopyDeliveryOutcome.OSC52_ONLY

    if on_failure == "modal" and _show_fallback(owner, resolved):
        return CopyDeliveryOutcome.FAILED
    if on_failure == "toast" or on_failure == "modal":
        _notify(
            owner,
            "No clipboard transport available",
            severity="error",
        )
    return CopyDeliveryOutcome.FAILED


def schedule_copy_delivery(
    owner: object,
    value: str | Callable[[], str],
    *,
    copied_label: CopiedLabel,
    task_name: str,
    on_failure: CopyFailurePolicy = "modal",
) -> asyncio.Task[CopyDeliveryOutcome] | None:
    """Schedule one copy outside Textual's pump, tracked by the owning app."""
    return spawn_pump_free_task(
        _app_for(owner),
        deliver_copy(
            owner,
            value,
            copied_label=copied_label,
            on_failure=on_failure,
        ),
        name=task_name,
        registry_attr="_pump_free_clipboard_tasks",
    )


__all__ = [
    "CopyDeliveryOutcome",
    "CopyFailurePolicy",
    "CopiedLabel",
    "OSC52_MAX_BASE64_BYTES",
    "deliver_copy",
    "schedule_copy_delivery",
]
