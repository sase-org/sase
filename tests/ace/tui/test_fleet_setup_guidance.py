"""Fleet setup command teaches canonical init rather than discover+add."""

from __future__ import annotations

from sase.ace.tui.actions.agents._fleet import AgentFleetMixin


class _SetupHost:
    def __init__(self, *, available: bool) -> None:
        self._available = available
        self.messages: list[str] = []

    def _fleet_mode_available(self) -> bool:
        return self._available

    def notify(self, message: str, timeout: object = None) -> None:
        del timeout
        self.messages.append(message)


def test_setup_agent_machine_teaches_bootstrap_and_canonical_init() -> None:
    host = _SetupHost(available=False)
    AgentFleetMixin.action_setup_agent_machine(host)  # type: ignore[arg-type]
    assert len(host.messages) == 1
    message = host.messages[0]
    assert "sase machine bootstrap --json" in message
    assert "sase machine init -B" in message
    assert "sase machine discover" not in message
    assert "sase machine add" not in message


def test_setup_agent_machine_teaches_rescan_when_machines_exist() -> None:
    host = _SetupHost(available=True)
    AgentFleetMixin.action_setup_agent_machine(host)  # type: ignore[arg-type]
    assert len(host.messages) == 1
    message = host.messages[0]
    assert "sase machine init" in message
    assert "rescan" in message
    assert "sase machine list" in message
    assert "sase machine status" in message
