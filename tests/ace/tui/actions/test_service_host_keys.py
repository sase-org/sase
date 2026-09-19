"""Service-host x / !x key routing."""

from __future__ import annotations

from sase.ace.tui.actions.axe import AxeMixin


class _Host:
    def __init__(self) -> None:
        self._axe_current_view: str | int = "axe"
        self._axe_service_selection: str | None = None
        self._axe_chop_selection: tuple[str, str] | None = None
        self._axe_lumberjack_idx: int | None = None
        self._service_host_enabled = True
        self.axe_running = False
        self.current_tab = "axe"
        self._bgcmd_slots: list[object] = []
        self.calls: list[tuple[str, str] | str] = []

    def _toggle_selected_service_proc(self, name: str) -> None:
        self.calls.append(("proc", name))

    def _start_service_host(self) -> None:
        self.calls.append("start-host")

    def _stop_service_host(self) -> None:
        self.calls.append("stop-host")

    def _start_axe(self) -> None:
        self.calls.append("start-axe")

    def _stop_axe(self) -> None:
        self.calls.append("stop-axe")

    def _confirm_kill_bgcmd(self, slot: object) -> None:
        self.calls.append(("kill-bgcmd", str(slot)))

    def _show_process_selector(self) -> None:
        self.calls.append("selector")


_Host._toggle_host_or_axe_daemon = AxeMixin._toggle_host_or_axe_daemon  # type: ignore[method-assign]
_Host._toggle_or_kill_axe_view = AxeMixin._toggle_or_kill_axe_view  # type: ignore[method-assign]
_Host._toggle_axe_global = AxeMixin._toggle_axe_global  # type: ignore[method-assign]


def test_x_starts_the_selected_service_proc_not_the_host() -> None:
    host = _Host()
    host._axe_service_selection = "gateway"
    host._toggle_or_kill_axe_view()
    assert host.calls == [("proc", "gateway")]


def test_x_does_not_toggle_the_host_on_nested_scheduler_rows() -> None:
    host = _Host()
    host._axe_service_selection = None
    host._axe_chop_selection = ("routines", "daily")
    host._axe_lumberjack_idx = 0
    host._toggle_or_kill_axe_view()
    assert host.calls == []


def test_bang_x_toggles_the_service_host() -> None:
    host = _Host()
    host._toggle_axe_global()
    assert host.calls == ["start-host"]
    host.calls.clear()
    host.axe_running = True
    host._toggle_axe_global()
    assert host.calls == ["stop-host"]
