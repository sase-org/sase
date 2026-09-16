"""ACE preflight that confirms broad ``%hold`` directives before a launch submits.

Structured like :mod:`._launch_provider_guard`: a cheap synchronous check keeps
the no-hold fast path free, and a broad hold plans/captures off the UI thread
before a :class:`ConfirmActionModal` blocks the submit. Declining leaves the
prompt bar mounted, exactly like the provider guard's own abort path -- there
is nothing to "restore" because the bar was never unmounted.
"""

from __future__ import annotations

import logging
from typing import Any

from sase.agent.launch_hold_preview import hold_confirmation_body, prompt_mentions_hold

from ._types import PromptSessionId, current_prompt_session, prompt_session_is_live

log = logging.getLogger(__name__)

_HOLD_GUARD_GROUP = "launch-hold-guard"
_HOLD_ABORT_TOAST = "Launch aborted; your prompt is still here."
_HOLD_STALE_TOAST = (
    "Launch cancelled; the prompt bar was closed while resolving the hold."
)


class LaunchHoldGuardMixin:
    """Confirm a broad ``%hold`` before chaining into the provider guard."""

    def _preflight_provider_disables(
        self,
        prompt: str,
        keep_bar: bool,
        *,
        owner_session_id: PromptSessionId | None = None,
    ) -> None:
        """Implemented by :class:`LaunchProviderGuardMixin`."""
        del prompt, keep_bar, owner_session_id
        raise NotImplementedError

    def _preflight_hold_confirm(
        self,
        prompt: str,
        keep_bar: bool,
        *,
        owner_session_id: PromptSessionId | None = None,
    ) -> None:
        session = current_prompt_session(self)
        if session is None or (
            owner_session_id is not None and session.session_id != owner_session_id
        ):
            self._notify_stale_hold_guard()
            return
        owner_session_id = session.session_id
        if not prompt_mentions_hold(prompt):
            self._preflight_provider_disables(
                prompt, keep_bar, owner_session_id=owner_session_id
            )
            return
        project = self._hold_guard_project()
        self._run_hold_guard_worker(
            lambda: hold_confirmation_body(prompt, project=project),
            lambda body: self._on_hold_confirm_planned(
                prompt, keep_bar, body, owner_session_id=owner_session_id
            ),
        )

    def _hold_guard_project(self) -> str | None:
        context = getattr(self, "_prompt_context", None)
        project = getattr(context, "project_name", None)
        return project if isinstance(project, str) else None

    def _on_hold_confirm_planned(
        self,
        prompt: str,
        keep_bar: bool,
        body: str | None,
        *,
        owner_session_id: PromptSessionId | None,
    ) -> None:
        if not prompt_session_is_live(self, owner_session_id):
            self._notify_stale_hold_guard()
            return
        if body is None:
            self._preflight_provider_disables(
                prompt, keep_bar, owner_session_id=owner_session_id
            )
            return

        from ...modals import ConfirmActionModal, ConfirmKind

        def _on_decision(confirmed: bool | None) -> None:
            if not confirmed:
                self.notify(_HOLD_ABORT_TOAST)  # type: ignore[attr-defined]
                return
            self._preflight_provider_disables(
                prompt, keep_bar, owner_session_id=owner_session_id
            )

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Arm this hold?",
                body,
                kind=ConfirmKind.DANGER,
                confirm_label="Arm",
                cancel_label="Cancel",
            ),
            _on_decision,
        )

    def _run_hold_guard_worker(self, work: Any, on_success: Any) -> None:
        run_worker = getattr(self, "run_worker", None)

        def task() -> None:
            try:
                result = work()
            except Exception:
                log.warning(
                    "hold confirmation preflight failed; launching without the panel",
                    exc_info=True,
                )
                result = None
            self._call_from_ui_hold_guard(on_success, result)

        if not callable(run_worker):
            task()
            return
        run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_HOLD_GUARD_GROUP,
        )

    def _call_from_ui_hold_guard(self, callback: Any, *args: Any) -> None:
        caller = getattr(self, "call_from_thread", None)
        if callable(caller):
            caller(callback, *args)
            return
        callback(*args)

    def _notify_stale_hold_guard(self) -> None:
        self.notify(_HOLD_STALE_TOAST, severity="warning")  # type: ignore[attr-defined]


__all__ = ["LaunchHoldGuardMixin"]
