"""Fleet setup command opens persistent Machines administration."""

from __future__ import annotations

from sase.ace.tui.actions.agents._fleet import AgentFleetMixin


class _SetupHost:
    def __init__(self) -> None:
        self.opened_tabs: list[str] = []

    def _open_config_center(self, tab: str) -> None:
        self.opened_tabs.append(tab)

    def notify(self, message: str, timeout: object = None) -> None:
        del timeout
        raise AssertionError(f"setup should not use toast-only guidance: {message}")


def test_setup_agent_machine_opens_machines_pane() -> None:
    host = _SetupHost()
    AgentFleetMixin.action_setup_agent_machine(host)  # type: ignore[arg-type]
    assert host.opened_tabs == ["machines"]


def test_connect_agent_machine_opens_machines_pane() -> None:
    host = _SetupHost()
    AgentFleetMixin.action_connect_agent_machine(host)  # type: ignore[arg-type]
    assert host.opened_tabs == ["machines"]
