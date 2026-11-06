"""CLI tests for hijack release recovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.agent.hijack.recover_common import RecoveryResult
from sase.agent.hijack.recover_release import RELEASE_ACTIONS
from tests._agent_hijack_recover_release_support import (
    ReleasePreview,
    ReleaseRow,
    recover_args,
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

        from sase.agent.hijack.preview import RecoveryAction, RecoveryPreview
        from sase.agents._recover_render import render_recovery_menu

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
