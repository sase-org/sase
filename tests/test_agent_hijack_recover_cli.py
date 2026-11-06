"""CLI and fake-provider coverage for keep-work hijack recovery."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from sase.agent.hijack.preview import RecoveryAction, RecoveryPreview
from sase.agent.hijack.recover_common import RecoveryResult
from sase.agent.hijack.recover_target import RecoveryTarget
from sase.agents.cli_recover import handle_agents_recover
from sase.main.parser import create_parser
from tests._agent_hijack_recovery_transaction_support import Transaction


def _preview() -> RecoveryPreview:
    return RecoveryPreview(
        hijack_id="h-123",
        revision=7,
        header={
            "agent_name": "acme--3",
            "workspace_num": 3,
            "model_display": "claude/opus@high",
            "run_duration_display": "45m",
            "hijacked_ago": "3m",
            "files_changed": 2,
            "insertions": 12,
            "deletions": 4,
            "last_tool": "Bash just check",
            "last_tool_age": "2m",
        },
        default_action="escalate",
        actions=(
            RecoveryAction(
                "escalate",
                True,
                None,
                "Escalate",
                "@large → @xlarge",
                "claude/opus@xhigh",
            ),
            RecoveryAction(
                "continue", True, None, "Continue", "same model", "claude/opus@high"
            ),
            RecoveryAction(
                "instruct", True, None, "Instruct", "add guidance, then continue", None
            ),
            RecoveryAction(
                "restart", False, "not yet available in this phase", "Restart", "", None
            ),
            RecoveryAction(
                "dismiss", False, "not yet available in this phase", "Dismiss", "", None
            ),
        ),
        state="held",
        _record={"hijack_id": "h-123", "provider": "claude", "model": "opus"},
        _artifacts_dir="/tmp/artifacts",
    )


def _args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "name": "acme--3",
        "action": None,
        "dry_run": False,
        "json": False,
        "model": None,
        "prompt_file": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_recover_parser_has_sorted_public_options_and_supported_actions() -> None:
    parser = create_parser()
    args = parser.parse_args(
        [
            "agent",
            "recover",
            "-a",
            "continue",
            "-n",
            "-j",
            "-m",
            "sonnet@high",
            "acme--3",
        ]
    )
    agent_parser = next(
        action.choices["agent"]
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    agent_action = next(
        action
        for action in agent_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    help_text = agent_action.choices["recover"].format_help()
    option_help = help_text.rsplit("options:", maxsplit=1)[1]

    assert args.action == "continue"
    assert args.dry_run is True
    assert args.json is True
    assert args.model == "sonnet@high"
    assert option_help.index("--action") < option_help.index("--dry-run")
    assert option_help.index("--dry-run") < option_help.index("--json")
    assert option_help.index("--json") < option_help.index("--model")
    assert option_help.index("--model") < option_help.index("--prompt-file")
    assert "Restart and dismiss are shown as unavailable" in help_text


def test_bare_recover_renders_grouped_menu_and_disabled_reasons() -> None:
    buffer = io.StringIO()
    code = handle_agents_recover(
        _args(),
        preview_fn=lambda _name: _preview(),
        console=Console(file=buffer, no_color=True, width=100),
    )

    output = buffer.getvalue()
    assert code == 0
    assert "KEEP THE WORK" in output
    assert "START OVER" in output
    assert "INSPECT OR LEAVE" in output
    assert "claude/opus@xhigh" in output
    assert "not yet available in this phase" in output


def test_bare_recover_json_uses_stable_menu_envelope(capsys: Any) -> None:
    code = handle_agents_recover(_args(json=True), preview_fn=lambda _name: _preview())

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["mode"] == "menu"
    assert payload["default_action"] == "escalate"
    assert payload["hijack_id"] == "h-123"
    assert payload["actions"][3]["reason"] == "not yet available in this phase"
    assert payload["action"] is None
    assert payload["result"] is None


def test_action_passes_preview_identity_and_full_prompt_to_backend(
    tmp_path: Path, capsys: Any
) -> None:
    prompt_file = tmp_path / "continue.md"
    prompt_file.write_text("%model:claude/sonnet@low\n\nContinue the work.\n")
    calls: dict[str, Any] = {}

    def recover(name: str, **kwargs: Any) -> RecoveryResult:
        calls["name"] = name
        calls.update(kwargs)
        return RecoveryResult(
            kind="queued",
            hijack_id="h-123",
            revision=8,
            action="instruct",
            successor="acme--4",
            concrete_target="claude/sonnet@low",
            model_changed=True,
            message="queued acme--4",
        )

    code = handle_agents_recover(
        _args(
            action="continue",
            model="claude/sonnet@low",
            prompt_file=str(prompt_file),
            json=True,
        ),
        preview_fn=lambda _name: _preview(),
        recover_fn=recover,
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert calls["name"] == "acme--3"
    assert calls["action"] == "continue"
    assert calls["prompt"] == prompt_file.read_text(encoding="utf-8")
    assert calls["expected_hijack_id"] == "h-123"
    assert calls["expected_revision"] == 7
    assert payload["result"]["kind"] == "queued"
    assert payload["target"] == "claude/sonnet@low"


def test_dry_run_preflights_target_without_calling_backend(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(
        "sase.agents.cli_recover.resolve_effective_target",
        lambda **_kwargs: RecoveryTarget(
            action="continue",
            concrete_target="claude/opus@high",
            model_changed=False,
            prompt="",
            context_mode="",
        ),
    )
    monkeypatch.setattr(
        "sase.agents.cli_recover._preflight_prompt",
        lambda *_args: type(
            "Prepared",
            (),
            {
                "context_mode": "fork",
                "transcript_path": "/tmp/chat.md",
                "expanded_prompt_bytes": 120,
                "budget_decision": {"kind": "fits"},
            },
        )(),
    )

    def never_recover(*_args: Any, **_kwargs: Any) -> RecoveryResult:
        raise AssertionError("dry-run must not call the recovery executor")

    code = handle_agents_recover(
        _args(action="continue", dry_run=True, json=True),
        preview_fn=lambda _name: _preview(),
        recover_fn=never_recover,
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["mode"] == "dry_run"
    assert payload["target"] == "claude/opus@high"
    assert payload["plan"]["context_mode"] == "fork"
    assert payload["result"] is None


def test_prompt_file_errors_refuse_before_recovery(tmp_path: Path, capsys: Any) -> None:
    def never_recover(*_args: Any, **_kwargs: Any) -> RecoveryResult:
        raise AssertionError("input failures must happen before resolution")

    code = handle_agents_recover(
        _args(
            action="continue",
            json=True,
            prompt_file=str(tmp_path / "missing.md"),
        ),
        preview_fn=lambda _name: _preview(),
        recover_fn=never_recover,
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"]["code"] == "invalid_input"
    assert "Could not read prompt file" in payload["error"]["message"]


@pytest.mark.parametrize(
    ("action", "model", "prompt_text", "target", "changed"),
    [
        ("continue", None, None, "claude/opus@high", False),
        ("escalate", "claude/sonnet@low", None, "claude/sonnet@low", True),
        (
            "continue",
            "claude/sonnet@low",
            "%model:claude/opus@high\n\nKeep working.\n",
            "claude/sonnet@low",
            True,
        ),
    ],
    ids=("continue", "escalate", "instruct"),
)
def test_cli_recovery_keeps_fake_provider_work_in_both_repositories(
    action: str,
    model: str | None,
    prompt_text: str | None,
    target: str,
    changed: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    txn = Transaction(monkeypatch, tmp_path)
    prompt_file = None
    if prompt_text is not None:
        prompt_file = tmp_path / "edited-continuation.md"
        prompt_file.write_text(prompt_text, encoding="utf-8")

    from sase.agents.cli_recover import handle_agents_recover as run_cli

    code = run_cli(
        _args(
            action=action,
            model=model,
            prompt_file=str(prompt_file) if prompt_file else None,
            json=True,
        ),
        recover_fn=lambda _name, **kwargs: txn.recover(**kwargs),
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0, payload
    assert payload["result"]["kind"] == "launched"
    assert payload["target"] == target
    child = txn.children()[0]
    from sase.agent.hijack.recovery_successor import read_recovery_ack

    ack = read_recovery_ack(str(child))
    assert ack is not None
    assert ack["concrete_target"] == target
    assert ack["baseline_inherited"] is True
    assert ack["goal"] == "goal-1"
    assert ack["bead"] == "sase-1"
    assert ack["scope_verified"] is True
    assert ack["lineage"]["to_rung"] == target
    assert ack["lineage"]["predecessor"] == "acme--3"
    for filename in (
        "commit_finalizer_baseline.json",
        "opened_linked_workspaces.json",
    ):
        assert (child / filename).read_bytes() == (txn.parent / filename).read_bytes()
    assert txn.provider_calls[0]["primary_work"].startswith("# primary fixture change")
    assert txn.provider_calls[0]["linked_work"].startswith("# linked fixture change")
    assert txn.provider_calls[0]["workspace_dir"] == str(txn.workspace_dir)
    done = json.loads((txn.parent / "done.json").read_text(encoding="utf-8"))
    assert done["outcome"] == "hijacked"
    assert done["recovery"]["state"] == "resolved"
    assert done["recovery"]["action"] in {"continue", "escalate", "instruct"}
    assert done["recovery"]["model_changed"] is changed


def test_settlement_cli_escalate_without_model_uses_preview_target(
    capsys: Any,
) -> None:
    calls: dict[str, Any] = {}

    def recover(name: str, **kwargs: Any) -> RecoveryResult:
        calls.update(kwargs)
        return RecoveryResult(
            kind="queued",
            hijack_id="h-123",
            revision=8,
            action="escalate",
            successor="acme--4",
            concrete_target="claude/opus@xhigh",
            model_changed=True,
            message="queued acme--4",
        )

    code = handle_agents_recover(
        _args(action="escalate", json=True),
        preview_fn=lambda _name: _preview(),
        recover_fn=recover,
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert calls["model"] is None
    assert calls["expected_hijack_id"] == "h-123"
    assert payload["result"]["kind"] == "queued"
    assert payload["target"] == "claude/opus@xhigh"


def test_settlement_cli_queued_and_resume_kinds_exit_zero(capsys: Any) -> None:
    from sase.agents.cli_recover import recovery_exit_code

    for kind in ("queued", "launched", "already_resolved"):
        result = RecoveryResult(kind=kind, hijack_id="h-123", revision=8)
        assert recovery_exit_code(result) == 0
    refused = RecoveryResult(kind="refused", hijack_id="h-123", revision=8)
    assert recovery_exit_code(refused) == 2

    def recover_queued(name: str, **kwargs: Any) -> RecoveryResult:
        return RecoveryResult(
            kind="queued",
            hijack_id="h-123",
            revision=8,
            action="escalate",
            successor="acme--4",
            message="still queued",
        )

    code = handle_agents_recover(
        _args(action="escalate", json=True),
        preview_fn=lambda _name: _preview(),
        recover_fn=recover_queued,
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["result"]["kind"] == "queued"

    # persist-recover shares the executor and exit mapping, so JSON agrees.
    from sase.ops.commands._agent_persist_recover import _result_payload

    queued = RecoveryResult(kind="queued", hijack_id="h-123", revision=8)
    assert recovery_exit_code(queued) == 0
    assert _result_payload("escalate", queued)["status"] == "queued"
