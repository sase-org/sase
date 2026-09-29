"""Axe quit, restart, and output-clear actions for sase's TUI app."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from sase.axe.state import clear_lumberjack_output_log

from ..bgcmd import clear_slot_output
from ..exit_action import AceExitAction
from ..tab_order import SERVICES_TAB

if TYPE_CHECKING:
    from ...patch import Patch
    from ..modals import QuitOption
    from ..quit_impact import TuiExitImpact

# Type alias for tab names
TabName = Literal["artifacts", "agents", "services"]


def _load_inflight_launches() -> list[Any]:
    """Load scheduler in-flight launches; import at call time for tests."""
    import sase.axe.state as axe_state

    try:
        return list(axe_state.find_inflight_chop_launches())
    except Exception:
        return []


class AxeQuitMixin:
    """Mixin providing axe quit, restart, and output-clear actions."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    exit_action: AceExitAction
    _bgcmd_slots: list[Any]
    _axe_bgcmd_details: dict[int, Any]

    def action_stop_axe_and_quit(self) -> None:
        """Open the quit / restart options panel."""
        from ..modals import QuitOptionsModal
        from ..quit_impact import TuiExitImpact, collect_tui_exit_impact

        if getattr(self, "_quit_options_open", False):
            return
        if getattr(self, "_quit_confirm_open", False):
            return
        self._quit_options_open = True  # type: ignore[attr-defined]
        impact: TuiExitImpact = collect_tui_exit_impact(self)

        def _on_choice(choice: QuitOption | None) -> None:
            self._quit_options_open = False  # type: ignore[attr-defined]
            if choice is None:
                return
            if getattr(self, "_quit_confirm_open", False):
                return
            if choice == "restart_tui":
                self._confirm_restart_tui_if_needed()
                return
            self._confirm_scheduler_quit_if_needed(choice)

        self.push_screen(  # type: ignore[attr-defined]
            QuitOptionsModal(
                tui_task_count=impact.task_count,
            ),
            callback=_on_choice,
        )

    def _confirm_restart_tui_if_needed(self) -> None:
        """Confirm a plain TUI restart when in-process work would be lost."""
        from ..modals.confirm_action_modal import ConfirmActionModal
        from ..modals.confirm_dialog import ConfirmKind
        from ..quit_impact import TuiExitImpact, collect_tui_exit_impact

        impact: TuiExitImpact = collect_tui_exit_impact(self)
        if impact.is_empty:
            self._restart_tui(restart_axe=False)
            return
        if getattr(self, "_quit_confirm_open", False):
            return
        self._quit_confirm_open = True  # type: ignore[attr-defined]

        def _on_confirm(confirmed: bool | None) -> None:
            self._quit_confirm_open = False  # type: ignore[attr-defined]
            if confirmed is True:
                self._restart_tui(restart_axe=False)

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Restart sase's TUI?",
                "\n".join(impact.summary_lines()),
                kind=ConfirmKind.DANGER,
                confirm_label="Restart",
                cancel_label="Stay",
            ),
            _on_confirm,
        )

    def _confirm_scheduler_quit_if_needed(self, choice: Any) -> None:
        """Confirm quit/stop or restart+host when work would be interrupted."""
        import asyncio as _asyncio

        from ..quit_impact import TuiExitImpact, collect_tui_exit_impact
        from ..util.pump_tasks import spawn_pump_free_task

        impact: TuiExitImpact = collect_tui_exit_impact(self)

        async def _gather() -> None:
            try:
                launches = await _asyncio.to_thread(_load_inflight_launches)
            except Exception:
                launches = []
            self._finish_scheduler_quit_choice(choice, impact, launches)

        task = spawn_pump_free_task(
            self,
            _gather(),
            name="quit-confirm-gather",
            registry_attr="_quit_confirm_tasks",
        )
        if task is None:
            try:
                launches = _load_inflight_launches()
            except Exception:
                launches = []
            self._finish_scheduler_quit_choice(choice, impact, launches)

    def _finish_scheduler_quit_choice(
        self,
        choice: Any,
        impact: TuiExitImpact,
        launches: list[Any],
    ) -> None:
        """Show the quit confirmation when needed, else run the exit path."""
        from ..modals.confirm_action_modal import ConfirmActionModal
        from ..modals.confirm_dialog import ConfirmKind

        if impact.is_empty and not launches:
            if choice == "quit_stop_axe":
                self.run_worker(self._stop_axe_and_quit())  # type: ignore[attr-defined]
            else:
                self._restart_tui(restart_axe=True)
            return
        if getattr(self, "_quit_confirm_open", False):
            return
        self._quit_confirm_open = True  # type: ignore[attr-defined]
        lines = list(impact.summary_lines())
        lines.extend(launch.summary_line() for launch in launches)
        message = "\n".join(lines)
        if choice == "quit_stop_axe":
            title = "Quit sase's TUI and stop the scheduler?"
            confirm_label = "Quit"
        else:
            title = "Restart sase's TUI and service host?"
            confirm_label = "Restart"

        def _on_confirm(confirmed: bool | None) -> None:
            self._quit_confirm_open = False  # type: ignore[attr-defined]
            if confirmed is not True:
                return
            if choice == "quit_stop_axe":
                self.run_worker(self._stop_axe_and_quit())  # type: ignore[attr-defined]
            else:
                self._restart_tui(restart_axe=True)

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                title,
                message,
                kind=ConfirmKind.DANGER,
                confirm_label=confirm_label,
                cancel_label="Stay",
            ),
            _on_confirm,
        )

    async def _stop_axe_and_quit(self) -> None:
        """Stop the Scheduler, then quit."""
        stash_quit_draft = getattr(self, "_stash_quit_draft_or_cancel", None)
        if callable(stash_quit_draft):
            if stash_quit_draft() is False:
                return
        stop_watchdog = getattr(self, "_stop_tui_stall_watchdog", None)
        if callable(stop_watchdog):
            stop_watchdog()

        try:
            from sase.service.actions import stop_service_proc

            # Stops Scheduler only; the service host is never stopped here.
            await asyncio.to_thread(
                stop_service_proc,
                "scheduler",
                actor="tui",
                reason="ace quit",
            )
        except Exception:
            pass
        finally:
            begin_exit = getattr(self, "_begin_controlled_exit", None)
            if callable(begin_exit):
                await begin_exit()
            else:
                self._do_quit()  # type: ignore[attr-defined]

    def _restart_tui(self, *, restart_axe: bool) -> None:
        """Quit this TUI and ask the command handler to re-exec it."""
        self.exit_action = (
            AceExitAction.RESTART_TUI_AND_AXE
            if restart_axe
            else AceExitAction.RESTART_TUI
        )

        stop_watchdog = getattr(self, "_stop_tui_stall_watchdog", None)
        if callable(stop_watchdog):
            stop_watchdog()

        draft_stashed = False
        stash_before_restart = getattr(self, "_stash_prompt_bar_before_restart", None)
        if callable(stash_before_restart):
            try:
                draft_stashed = bool(stash_before_restart())
            except Exception:
                draft_stashed = False
        # The restart stash already ran with source="restart": mark the
        # quit-draft attempt done so _request_controlled_exit below does not
        # stash the same draft a second time with source="quit".
        self._quit_draft_stash_attempted = True  # type: ignore[attr-defined]
        if draft_stashed:
            try:
                self.notify(  # type: ignore[attr-defined]
                    "Prompt draft stashed; press @ to restore after restart"
                )
            except Exception:
                pass

        request_exit = getattr(self, "_request_controlled_exit", None)
        if callable(request_exit):
            request_exit()
        else:
            self._do_quit()  # type: ignore[attr-defined]

    def action_clear_axe_output(self) -> None:
        """Clear the output log for the current view."""
        from ..widgets.bgcmd_list import BgCmdItem, ChopItem, LumberjackItem

        if self.current_tab != SERVICES_TAB:
            return

        # Derive what to clear from the selected item. Chop run history is
        # immutable from the TUI (the safer default): the affordance is
        # a no-op on chop rows and surfaces a warning instead of silently
        # mutating the parent lumberjack log behind the user's back.
        axe_items = self._axe_items  # type: ignore[attr-defined]
        if not axe_items or self.current_idx >= len(axe_items):
            return

        item = axe_items[self.current_idx]
        match item:
            case LumberjackItem(name=name):
                clear_lumberjack_output_log(name)
                self._refresh_axe_display()  # type: ignore[attr-defined]
                self.notify("Output cleared")  # type: ignore[attr-defined]
            case ChopItem():
                self.notify(  # type: ignore[attr-defined]
                    "Job run history is immutable from the TUI",
                    severity="warning",
                )
            case BgCmdItem(slot=slot):
                info = dict(self._bgcmd_slots).get(slot)
                if info is None:
                    return
                if getattr(self, "_axe_bgcmd_details", None):
                    snap = self._axe_bgcmd_details.get(slot)
                    if snap is not None:
                        snap.output_tail = ""
                self.run_worker(  # type: ignore[attr-defined]
                    lambda: clear_slot_output(slot, info),
                    thread=True,
                    exclusive=False,
                    exit_on_error=False,
                    group="bgcmd-clear-output",
                )
                self._refresh_axe_display()  # type: ignore[attr-defined]
                self.notify("Output cleared")  # type: ignore[attr-defined]
