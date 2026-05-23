"""Tests for ``sase memory write`` CLI behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.memory.cli_write import handle_memory_write_command
from sase.memory.proposals import read_memory_proposals


def test_memory_write_json_creates_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    evidence_path = tmp_path / "evidence.md"
    evidence_path.write_text("evidence\n", encoding="utf-8")
    args = create_parser().parse_args(
        [
            "memory",
            "write",
            "--title",
            "Memory",
            "--slug",
            "memory",
            "--evidence",
            "evidence.md",
            "--keyword",
            "memory",
            "--keyword",
            "memory",
            "--body",
            "Body\n",
            "--json",
        ]
    )

    handle_memory_write_command(args)

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    proposal = payload["proposal"]
    assert proposal["status"] == "pending"
    assert proposal["target_path"] == "long/memory.md"
    assert proposal["keywords"] == ["memory"]
    assert proposal["author_name"] == "agent-a"
    assert Path(payload["draft_path"]).read_text(encoding="utf-8") == "Body\n"
    states = read_memory_proposals(ledger_path=Path(payload["ledger_path"]))
    assert len(states) == 1
    assert states[0].proposal_id == proposal["proposal_id"]


def test_memory_write_rejects_missing_required_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    args = create_parser().parse_args(
        [
            "memory",
            "write",
            "--title",
            "Memory",
            "--slug",
            "memory",
            "--body",
            "Body\n",
        ]
    )

    with pytest.raises(SystemExit) as exc:
        handle_memory_write_command(args)

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "require evidence" in captured.err


def test_memory_write_rejects_missing_body_without_touching_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    args = create_parser().parse_args(
        [
            "memory",
            "write",
            "--title",
            "Memory",
            "--slug",
            "memory",
            "--evidence",
            "chat:abc",
        ]
    )

    with pytest.raises(SystemExit) as exc:
        handle_memory_write_command(args)

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "body is required" in captured.err
    assert not (home / ".sase").exists()


def test_memory_write_manual_author_is_visible_test_escape_hatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    args = create_parser().parse_args(
        [
            "memory",
            "write",
            "--title",
            "Memory",
            "--target",
            "long/memory.md",
            "--evidence",
            "chat:abc",
            "--body",
            "Body\n",
            "--manual-author",
            "demo-user",
            "--json",
        ]
    )

    handle_memory_write_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["proposal"]["author_name"] == "demo-user"
    assert payload["proposal"]["author_source"] == "manual"
