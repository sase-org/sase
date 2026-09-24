"""ACE preflight that confirms broad ``%hold`` directives after acceptance."""

from __future__ import annotations

import logging
from typing import Any

from sase.agent.launch_hold_preview import hold_confirmation_body, prompt_mentions_hold

from ._pending_launch import (
    PendingLaunch,
    PendingLaunchStage,
    cancel_pending_launch,
    pending_launch,
    pending_launch_can_show_modal,
    restore_pending_launch_prompt,
    set_pending_launch_stage,
)

log = logging.getLogger(__name__)

_HOLD_GUARD_GROUP = "launch-hold-guard"


class LaunchHoldGuardMixin:
    """Confirm a broad ``%hold`` before chaining into the provider guard.

    A hold check begins only after ``_accept_resolved_launch`` has retired the
    prompt bar. Every callback therefore uses the immutable pending-launch
    snapshot rather than the app's current prompt state.
    """

    def _preflight_provider_disables(self, launch_id: str) -> None:
        """Implemented by :class:`LaunchProviderGuardMixin`."""
        del launch_id
        raise NotImplementedError

    def _preflight_hold_confirm(self, launch_id: str) -> None:
        launch = pending_launch(self, launch_id)
        if launch is None:
            return
        set_pending_launch_stage(self, launch_id, PendingLaunchStage.HOLD_CHECK)
        if not prompt_mentions_hold(launch.prompt):
            self._preflight_provider_disables(launch_id)
            return
        project = launch.context.project_name
        self._run_hold_guard_worker(
            lambda: hold_confirmation_body(launch.prompt, project=project),
            lambda body: self._on_hold_confirm_planned(launch_id, body),
            launch_id=launch_id,
        )

    def _on_hold_confirm_planned(self, launch_id: str, body: str | None) -> None:
        launch = pending_launch(self, launch_id)
        if launch is None:
            return
        if body is None:
            self._preflight_provider_disables(launch_id)
            return
        if not pending_launch_can_show_modal(self):
            self._abort_pending_hold(
                launch,
                "Launch needs %hold confirmation while another prompt or modal is active",
            )
            return

        from ...modals import ConfirmActionModal, ConfirmKind

        set_pending_launch_stage(self, launch_id, PendingLaunchStage.HOLD_CONFIRM)

        def _on_decision(confirmed: bool | None) -> None:
            live = pending_launch(self, launch_id)
            if live is None:
                return
            if not confirmed:
                self._abort_pending_hold(live, "Launch aborted")
                return
            self._preflight_provider_disables(launch_id)

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Arm this hold?",
                body,
                kind=ConfirmKind.DANGER,
                confirm_label="Arm",
                cancel_label="Cancel",
                default="cancel",
            ),
            _on_decision,
        )

    def _abort_pending_hold(self, launch: PendingLaunch, reason: str) -> None:
        cancel_pending_launch(self, launch)
        restore_pending_launch_prompt(self, launch, reason=reason, explicit=False)

    def _run_hold_guard_worker(
        self, work: Any, on_success: Any, *, launch_id: str
    ) -> None:
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
            exclusive=False,
            group=f"{_HOLD_GUARD_GROUP}:{launch_id}",
        )

    def _call_from_ui_hold_guard(self, callback: Any, *args: Any) -> None:
        caller = getattr(self, "call_from_thread", None)
        if callable(caller):
            caller(callback, *args)
            return
        callback(*args)


__all__ = ["LaunchHoldGuardMixin"]
