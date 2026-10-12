"""Public apply entry-point implementation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sase.project_onboarding.events import emit_event
from sase.project_onboarding.journal import set_journal_status
from sase.project_onboarding._apply_run import run_request


def apply_plan(
    request: Mapping[str, Any],
    *,
    emit: Callable[..., None] | None = None,
    proc_id: str = "",
    plan: Mapping[str, Any] | None = None,
    lock_timeout: float = 30.0,
) -> dict[str, Any]:
    """Execute the add-mode steps of *request* and return the result event.

    The plan is re-derived under cooperating locks before any effect; a
    changed or blocked plan is reported before the checkout is touched.
    Exactly one ``result`` event is emitted per call. ``plan`` optionally
    carries the document the caller reviewed, so a changed plan is
    reported instead of executed. Unexpected internal errors are
    returned as a failed result with journal evidence preserved.
    """

    send = emit_event if emit is None else emit
    try:
        return run_request(
            request,
            send=send,
            proc_id=proc_id,
            preview=plan,
            lock_timeout=lock_timeout,
        )
    except Exception as exc:  # noqa: BLE001 - executor ends with one result
        identity = ""
        try:
            identity = str((request.get("target") or {}).get("identity_key"))
        except Exception:
            identity = ""
        message = f"internal error during project onboarding: {exc}"
        if identity:
            try:
                set_journal_status(identity, "failed", message=message)
            except Exception:
                pass
        result = {
            "event": "result",
            "status": "failed",
            "project": {"key": "", "name": ""},
            "next_argv": [],
            "message": message,
        }
        try:
            send(result)
        except Exception:
            pass
        return result


__all__ = ["apply_plan"]
