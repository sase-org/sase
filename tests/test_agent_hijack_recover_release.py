"""CLI and persistence tests for hijack release recovery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack.ledger import HijackLedgerConflict
from sase.agent.hijack.recover_common import RecoveryResult
from sase.agent.hijack.recover_release import (
    RELEASE_ACTIONS,
    recover_release_action,
    restart_availability_reason,
    restart_replacement_conflicts,
)
from tests._agent_hijack_recover_helpers import record as make_record
from tests._agent_hijack_recover_helpers import subject as make_subject


from tests._agent_hijack_recover_release_support import (
    ReleaseLedger,
    ReleasePreview,
    ReleaseRow,
    held_artifacts,
    install_release_ledger,
    recover_args,
    record_for,
    release_deps,
    release_preview,
    release_preview_for_cli,
    release_subject,
)


class TestReleaseCli:
    def _preview(self, **row_overrides: Any) -> ReleasePreview:
        rows = {
            "restart": ReleaseRow("restart", True, None),
            "edit": ReleaseRow("edit", True, None),
            "dismiss": ReleaseRow("dismiss", True, None),
            "escalate": ReleaseRow("escalate", True, None, "t"),
            "continue": ReleaseRow("continue", True, None, "t"),
            "instruct": ReleaseRow("instruct", True, None, "t"),
        }
        rows.update(row_overrides)
        return ReleasePreview(
            revision=7,
            rows=(
                rows["escalate"],
                rows["continue"],
                rows["instruct"],
                rows["restart"],
                rows["edit"],
                rows["dismiss"],
            ),
        )

    def test_recover_restart_routes_to_release_backend(self, capsys: Any) -> None:
        from sase.agents.cli_recover import handle_agents_recover

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

        code = handle_agents_recover(
            recover_args(action="restart", json=True),
            preview_fn=lambda _name: self._preview(),
            release_fn=release,
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert calls["action"] == "restart"
        assert calls["prompt"] is None
        assert calls["discard_without_snapshot"] is False
        assert calls["expected_hijack_id"] == "h-123"
        assert calls["expected_revision"] == 7
        assert payload["result"]["kind"] == "launched"
        assert payload["target"] is None

    def test_recover_restart_with_prompt_uses_edit_row_and_passes_prompt(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        from sase.agents.cli_recover import handle_agents_recover

        prompt_file = tmp_path / "edited.md"
        prompt_file.write_text("Do the other thing.\n", encoding="utf-8")
        calls: dict[str, Any] = {}

        def release(name: str, **kwargs: Any) -> RecoveryResult:
            calls.update(kwargs)
            return RecoveryResult(
                kind="launched",
                hijack_id="h-123",
                revision=8,
                action="restart",
                successor="acme--3",
                message="Relaunched",
            )

        preview = ReleasePreview(
            revision=7,
            rows=(
                ReleaseRow("escalate", True, None, "t"),
                ReleaseRow("continue", True, None, "t"),
                ReleaseRow("instruct", True, None, "t"),
                ReleaseRow("restart", False, "fanout: fan-out prompt"),
                ReleaseRow("edit", True, None),
                ReleaseRow("dismiss", True, None),
            ),
        )
        code = handle_agents_recover(
            recover_args(action="restart", prompt_file=str(prompt_file), json=True),
            preview_fn=lambda _name: preview,
            release_fn=release,
        )
        assert code == 0, capsys.readouterr().out
        assert calls["prompt"] == "Do the other thing.\n"

    def test_recover_unavailable_release_row_refuses(self, capsys: Any) -> None:
        from sase.agents.cli_recover import handle_agents_recover

        def never_release(*args: Any, **kwargs: Any) -> RecoveryResult:
            raise AssertionError("unavailable rows must not reach the backend")

        code = handle_agents_recover(
            recover_args(action="dismiss", json=True),
            preview_fn=lambda _name: self._preview(
                dismiss=ReleaseRow("dismiss", False, "already being resolved")
            ),
            release_fn=never_release,
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == 2
        assert payload["error"]["code"] == "action_unavailable"

    def test_recover_release_option_validation(self, capsys: Any) -> None:
        from sase.agents.cli_recover import handle_agents_recover

        def never(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("invalid input must fail before backends")

        cases = [
            recover_args(action="restart", dry_run=True, json=True),
            recover_args(action="restart", model="claude/opus@high", json=True),
            recover_args(action="dismiss", prompt_file="/tmp/x.md", json=True),
            recover_args(action="continue", discard_without_snapshot=True, json=True),
        ]
        for args in cases:
            code = handle_agents_recover(
                args,
                preview_fn=lambda _name: self._preview(),
                recover_fn=never,
                release_fn=never,
            )
            payload = json.loads(capsys.readouterr().out)
            assert code == 2, args
            assert payload["error"]["code"] == "invalid_input", payload

    def test_bare_menu_lists_edit_row(self) -> None:
        import io

        from rich.console import Console

        from sase.agents._recover_render import render_recovery_menu
        from sase.agent.hijack.preview import RecoveryAction, RecoveryPreview

        preview = RecoveryPreview(
            hijack_id="h-123",
            revision=7,
            header={
                "agent_name": "acme--3",
                "workspace_num": 3,
                "model_display": "m",
                "run_duration_display": "1m",
                "hijacked_ago": "",
                "files_changed": 0,
                "insertions": 0,
                "deletions": 0,
                "last_tool": "",
                "last_tool_age": "",
            },
            default_action="escalate",
            actions=(
                RecoveryAction("escalate", True, None, "Escalate", "up", "t"),
                RecoveryAction("continue", True, None, "Continue", "same", "t"),
                RecoveryAction("instruct", True, None, "Instruct", "guide", None),
                RecoveryAction(
                    "restart",
                    True,
                    None,
                    "Restart",
                    "same prompt, same name, fresh workspace",
                    None,
                ),
                RecoveryAction("edit", True, None, "Edit", "edit the prompt", None),
                RecoveryAction(
                    "dismiss", True, None, "Dismiss", "snapshot first", None
                ),
            ),
            state="held",
            _record={},
            _artifacts_dir="/tmp/artifacts",
        )
        buffer = io.StringIO()
        Console(file=buffer, no_color=True, width=100).print(
            render_recovery_menu(preview)
        )
        output = buffer.getvalue()
        assert "START OVER" in output
        assert "Edit" in output
        assert "Dismiss" in output

    def test_actions_constant_covers_release_set(self) -> None:
        assert RELEASE_ACTIONS == frozenset({"dismiss", "restart"})


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


class TestPersistRecoverRelease:
    def _request(self, tmp_path: Path, payload: dict[str, Any]) -> tuple[Any, Path]:
        from sase.main.parser import create_parser
        from sase.ops import DurableOperationRequest, write_operation_request
        from sase.ops.names import AGENT_PERSIST_RECOVER

        request_path = tmp_path / "req.json"
        result_path = tmp_path / "res.json"
        write_operation_request(
            request_path,
            DurableOperationRequest(operation=AGENT_PERSIST_RECOVER, payload=payload),
        )
        args = create_parser().parse_args(
            [
                "agent",
                "persist-recover",
                "-Q",
                str(request_path),
                "-R",
                str(result_path),
            ]
        )
        return args, result_path

    def test_persist_recover_dismiss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.ops import read_operation_result
        from sase.ops.commands.agent import handle_agent_operation

        captured: dict[str, Any] = {}

        def release(name: str, **kwargs: Any) -> RecoveryResult:
            captured["name"] = name
            captured.update(kwargs)
            return RecoveryResult(
                kind="launched",
                hijack_id="h-123",
                revision=8,
                action="dismiss",
                message="Dismissed",
            )

        monkeypatch.setattr(
            "sase.ops.commands._agent_persist_recover.recover_release_action", release
        )
        args, result_path = self._request(
            tmp_path,
            {
                "name": "sase-7f.2",
                "action": "dismiss",
                "expected_hijack_id": "h-123",
                "expected_revision": 7,
                "discard_without_snapshot": True,
            },
        )
        monkeypatch.setenv("SASE_PROC_ID", "proc-release")
        assert handle_agent_operation(args) == 0
        assert captured["action"] == "dismiss"
        assert captured["discard_without_snapshot"] is True
        loaded = read_operation_result(result_path, expected_proc_id="proc-release")
        assert loaded.success is True
        assert loaded.payload["status"] == "launched"

    def test_persist_recover_rejects_bad_action(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.ops import read_operation_result
        from sase.ops.commands.agent import handle_agent_operation

        args, result_path = self._request(
            tmp_path,
            {
                "name": "sase-7f.2",
                "action": "nuke",
                "expected_hijack_id": "h-123",
                "expected_revision": 7,
            },
        )
        monkeypatch.setenv("SASE_PROC_ID", "proc-release")
        assert handle_agent_operation(args) != 0
        loaded = read_operation_result(result_path, expected_proc_id="proc-release")
        assert loaded.success is False
        assert "must be" in (loaded.error or "")
