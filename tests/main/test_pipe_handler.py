"""Tests for ``sase pipe`` CLI guards, JSON shape, and print-before-kill."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.pending_handoff import PIPE_PENDING_MARKER
from sase.main.parser import create_parser
from sase.main.pipe_handler import handle_pipe_command
from tests.main.parser_help_helpers import (
    assert_metavar_option_documented,
    flat_help,
    parser_for,
)


def _write_meta(artifacts_dir: Path, **fields: Any) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    payload = {"name": "family", "pid": 1, **fields}
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _run_pipe(
    monkeypatch: pytest.MonkeyPatch,
    artifacts_dir: Path,
    prompt: str,
    **kwargs: Any,
) -> tuple[int, list[str]]:
    killed: list[str] = []

    def fake_kill(target: str) -> None:
        killed.append(target)
        raise SystemExit(0)

    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setattr(
        "sase.main.pipe_handler.kill_agent_runner_group",
        fake_kill,
    )
    with pytest.raises(SystemExit) as exit_info:
        handle_pipe_command(prompt, **kwargs)
    return int(exit_info.value.code or 0), killed


def test_pipe_help_documents_flags_example_and_turn_warning() -> None:
    help_text = flat_help(parser_for(("sase", "pipe")).format_help())

    assert "This ends your turn" in help_text
    assert "-f, --fresh" in help_text
    assert "-j, --json" in help_text
    assert_metavar_option_documented(help_text, "-m", "--model", "MODEL")
    assert_metavar_option_documented(help_text, "-n", "--name", "TOKEN")
    assert_metavar_option_documented(help_text, "-r", "--reason", "TEXT")
    assert "sase pipe 'implement the approved plan'" in help_text
    args = create_parser().parse_args(
        ["pipe", "do the rest", "-f", "-j", "-m", "opus", "-n", "review", "-r", "why"]
    )
    assert args.command == "pipe"
    assert args.prompt == "do the rest"
    assert args.fresh is True
    assert args.json is True
    assert args.model == "opus"
    assert args.name == "review"
    assert args.reason == "why"


def test_pipe_help_options_are_alphabetical() -> None:
    help_text = parser_for(("sase", "pipe")).format_help()
    flags = [flag for flag in ("-f", "-j", "-m", "-n", "-r") if flag in help_text]
    assert flags == ["-f", "-j", "-m", "-n", "-r"]


def test_pipe_outside_an_agent_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    with pytest.raises(SystemExit) as exit_info:
        handle_pipe_command("continue")
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "`sase pipe` is only available inside a sase agent" in err


def test_pipe_rejects_empty_or_whitespace_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_meta(tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    with pytest.raises(SystemExit) as exit_info:
        handle_pipe_command("   \n")
    assert exit_info.value.code == 1
    assert "prompt must not be empty" in capsys.readouterr().err
    assert not (tmp_path / PIPE_PENDING_MARKER).exists()


@pytest.mark.parametrize("token", ["plan", "code", "epic", "commit", "mon"])
def test_pipe_rejects_reserved_name_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    token: str,
) -> None:
    _write_meta(tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    with pytest.raises(SystemExit) as exit_info:
        handle_pipe_command("continue", name=token)
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "reserved suffix" in err
    assert token in err
    assert not (tmp_path / PIPE_PENDING_MARKER).exists()


def test_pipe_rejects_invalid_name_token_characters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_meta(tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    with pytest.raises(SystemExit) as exit_info:
        handle_pipe_command("continue", name="foo-bar")
    assert exit_info.value.code == 1
    assert "invalid --name token" in capsys.readouterr().err
    assert not (tmp_path / PIPE_PENDING_MARKER).exists()


def test_pipe_accepts_review_name_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_meta(tmp_path)
    code, killed = _run_pipe(monkeypatch, tmp_path, "continue", name="review")
    assert code == 0
    assert killed == [str(tmp_path)]
    marker = json.loads((tmp_path / PIPE_PENDING_MARKER).read_text(encoding="utf-8"))
    assert marker["name_token"] == "review"


def test_pipe_accepts_retired_q_name_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_meta(tmp_path)
    code, killed = _run_pipe(monkeypatch, tmp_path, "continue", name="q")
    assert code == 0
    assert killed == [str(tmp_path)]
    marker = json.loads((tmp_path / PIPE_PENDING_MARKER).read_text(encoding="utf-8"))
    assert marker["name_token"] == "q"


def test_pipe_refuses_when_next_link_exceeds_chain_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_meta(tmp_path, pipe_depth=8)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sase.main.pipe_handler.get_max_agent_pipe_chain",
        lambda: 8,
    )
    with pytest.raises(SystemExit) as exit_info:
        handle_pipe_command("continue")
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "max_agent_pipe_chain=8" in err
    assert "chain length reached: 8" in err
    assert not (tmp_path / PIPE_PENDING_MARKER).exists()


def test_pipe_json_shape_and_print_before_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_meta(tmp_path, pipe_depth=1)
    monkeypatch.setattr(
        "sase.main.pipe_handler.get_max_agent_pipe_chain",
        lambda: 8,
    )
    code, killed = _run_pipe(
        monkeypatch,
        tmp_path,
        "finish the review",
        json_output=True,
        fresh=True,
        model="opus",
        name="review",
        reason="hand off",
    )
    assert code == 0
    assert killed == [str(tmp_path)]
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["command"] == "pipe"
    assert payload["agent"] == "family"
    assert payload["prompt"] == "finish the review"
    assert payload["reason"] == "hand off"
    assert payload["model"] == "opus"
    assert payload["name"] == "review"
    assert payload["fresh"] is True
    assert payload["pipe_depth"] == 1
    assert payload["next_pipe_depth"] == 2
    assert payload["max_agent_pipe_chain"] == 8
    marker = json.loads((tmp_path / PIPE_PENDING_MARKER).read_text(encoding="utf-8"))
    assert marker["prompt"] == "finish the review"
    assert marker["fresh"] is True
    assert marker["name_token"] == "review"
    assert marker["pipe_depth"] == 1
    assert isinstance(marker["timestamp"], int | float)


def test_pipe_rich_summary_prints_before_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_meta(tmp_path)
    code, killed = _run_pipe(
        monkeypatch,
        tmp_path,
        "keep going",
        reason="context is spent",
    )
    assert code == 0
    assert killed == [str(tmp_path)]
    out = capsys.readouterr().out
    assert "This ends your turn" in out
    assert "keep going" in out
    assert "context is spent" in out
    assert "last output before the agent runner is killed" in out
    assert (tmp_path / PIPE_PENDING_MARKER).is_file()
