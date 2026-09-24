"""Services-tab binding computation for :class:`KeybindingFooter`."""

from __future__ import annotations

from typing import TYPE_CHECKING


class AxeBindingsMixin:
    """Entry-dependent bindings for the Services tab."""

    if TYPE_CHECKING:

        def _kd(self, action_name: str) -> str: ...

    def _compute_axe_bindings(
        self,
        axe_current_view: str | int,
        *,
        selected_slot_done: bool = False,
        chop_run_total: int = 0,
        chop_selected: bool = False,
        chop_selected_running: bool = False,
        chop_selected_enabled: bool = True,
        service_selected: bool = False,
        service_running: bool = False,
        service_enabled: bool = True,
        service_available: bool = True,
        config_row_selected: bool = False,
        description_expanded: bool = True,
    ) -> list[tuple[str, str]]:
        """Compute entry-dependent bindings for Services tab.

        ``x`` is entry-dependent: it toggles the selected service proc, or
        kills the selected background command on a bgcmd slot view. Bare
        ``x`` is a no-op on host chrome, empty selection, and nested
        scheduler rows; the host toggle is ``!x``.
        ``r`` is dispatched off the selected row: ``re-run`` on a done
        background command, ``run chop`` on an idle chop row, or ``running``
        on a chop whose newest run is still active (the backend refuses an
        overlapping launch, so the affordance reflects that).
        ``e`` edits lumberjack/base-chop configuration. ``E`` opens recorded
        chop output and is shown only when that output exists.
        ``d`` expands or collapses the description panel on service proc,
        routine, and job rows.
        Ctrl+N / Ctrl+P surface only on chop rows with at least two recorded
        runs, since with zero or one run the keys cannot do anything useful.
        """
        bindings: list[tuple[str, str]] = []
        if service_selected:
            if not service_available:
                label = "unavailable"
            elif service_running:
                label = "stop service"
            elif service_enabled:
                label = "start service"
            else:
                label = "disabled"
            bindings.append((self._kd("kill_agent"), label))
        elif axe_current_view != "axe":
            bindings.append((self._kd("kill_agent"), "kill"))
        if selected_slot_done:
            bindings.append((self._kd("run_workflow"), "re-run"))
        elif service_selected and service_available and service_enabled:
            bindings.append((self._kd("run_workflow"), "restart service"))
        elif chop_selected and chop_selected_enabled:
            label = "running" if chop_selected_running else "run job"
            bindings.append((self._kd("run_workflow"), label))
        if config_row_selected:
            bindings.append((self._kd("edit_spec"), "edit config"))
        if config_row_selected or service_selected:
            bindings.append(
                (
                    self._kd("toggle_axe_description"),
                    "collapse desc" if description_expanded else "expand desc",
                )
            )
        if chop_selected and chop_run_total >= 1:
            bindings.append((self._kd("edit_panel"), "edit output"))
        if axe_current_view == "axe" and chop_run_total >= 2:
            bindings.append(
                (
                    f"{self._kd('next_chop_run')}/{self._kd('prev_chop_run')}",
                    "job run",
                )
            )
        return bindings
