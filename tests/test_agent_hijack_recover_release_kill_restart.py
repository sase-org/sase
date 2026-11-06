"""Kill and restart routing tests for hijack release recovery."""

from __future__ import annotations

from typing import Any

import pytest

from sase.agent.hijack.recover_common import RecoveryResult
from tests._agent_hijack_recover_release_support import (
    recover_args,
    release_preview_for_cli,
)


class TestKillRestartHijackRouting:
    def test_kill_refuses_hijacked_target(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        import sase.agents.cli_kill as kill_module

        monkeypatch.setattr(
            kill_module,
            "held_record_for_agent",
            lambda name: {"state": "held", "agent_name": name},
        )

        def never_kill(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("hijacked rows must not reach kill")

        monkeypatch.setattr(kill_module, "kill_named_agent", never_kill)
        with pytest.raises(SystemExit) as excinfo:
            kill_module.handle_agents_kill(recover_args(name="acme--3", action=None))
        assert excinfo.value.code == 2
        captured = capsys.readouterr()
        assert "already stopped (hijacked)" in captured.err
        assert "sase agent recover acme--3 -a dismiss" in captured.err

    def test_kill_passes_through_when_not_hijacked(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        import sase.agents.cli_kill as kill_module
        from sase.agent.running import _KillResult

        monkeypatch.setattr(kill_module, "held_record_for_agent", lambda name: None)
        monkeypatch.setattr(
            kill_module,
            "kill_named_agent",
            lambda name, **kwargs: _KillResult(
                True, f"Killed agent {name!r}", changed=True
            ),
        )
        with pytest.raises(SystemExit) as excinfo:
            kill_module.handle_agents_kill(recover_args(name="acme--3", action=None))
        assert excinfo.value.code == 0

    def test_restart_routes_hijacked_to_release(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        import sase.agents.cli_restart as restart_module

        monkeypatch.setattr(
            restart_module,
            "held_record_for_agent",
            lambda name: {"state": "held", "agent_name": name},
        )
        calls: dict[str, Any] = {}

        def release(name: str, **kwargs: Any) -> RecoveryResult:
            calls["name"] = name
            calls.update(kwargs)
            return RecoveryResult(
                kind="launched",
                hijack_id="h-123",
                revision=8,
                action="restart",
                successor="acme--3",
                message="Restarted hijacked agent",
            )

        monkeypatch.setattr(
            "sase.agent.hijack.recover_release.recover_release_action", release
        )
        monkeypatch.setattr(
            "sase.agent.hijack.preview.hijack_recovery_preview",
            lambda name: release_preview_for_cli(),
        )
        code = restart_module.handle_agents_restart(
            recover_args(name="acme--3", action=None)
        )
        assert code == 0
        assert calls["action"] == "restart"
        assert "Restarted hijacked agent" in capsys.readouterr().out

    def test_restart_hijacked_dry_run_prints_menu(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        import io

        from rich.console import Console

        import sase.agents.cli_restart as restart_module

        monkeypatch.setattr(
            restart_module,
            "held_record_for_agent",
            lambda name: {"state": "held", "agent_name": name},
        )
        monkeypatch.setattr(
            "sase.agent.hijack.preview.hijack_recovery_preview",
            lambda name: release_preview_for_cli(),
        )
        buffer = io.StringIO()
        code = restart_module.handle_agents_restart(
            recover_args(name="acme--3", action=None, dry_run=True),
            console=Console(file=buffer, no_color=True, width=100),
        )
        assert code == 0
        assert "acme--3" in buffer.getvalue()
