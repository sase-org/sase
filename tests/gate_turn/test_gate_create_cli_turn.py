"""CLI-level regression tests for ``sase gate create`` turn routing."""

from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from sase.gate_turn.store import find_gate_turn_by_gate_id
from sase.main.gate_handler import handle_gate_command
from sase.main.parser_gate import register_gate_parser
from tests._notification_gates_fixtures import custom_gate_spec
from tests.gate_turn._settlement_followup_helpers import sandbox_home
from tests.monitor._fixtures import make_starter_agent, write_project_file

__all__ = ["sandbox_home"]


def _prepare_creator(monkeypatch: pytest.MonkeyPatch, project: str) -> None:
    """Mirror the hermetic creator setup from the direct-transaction test."""
    write_project_file(project)
    creator_dir = make_starter_agent(
        project,
        "20260812120000",
        "lane",
        agent_session="lane",
        agent_session_role="root",
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "lane")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", creator_dir)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.delenv("SASE_FINALIZER_OWNED_TURN", raising=False)
    # A test must never signal the real runner.
    import sase.gate_turn.agent_handoff as agent_handoff

    monkeypatch.setattr(
        agent_handoff, "will_handoff_gate_to_agent_runner", lambda: False
    )
    import sase.gate_turn as gate_turn_pkg

    monkeypatch.setattr(
        gate_turn_pkg,
        "will_handoff_gate_to_agent_runner",
        lambda: False,
        raising=False,
    )


def _run_create(
    monkeypatch: pytest.MonkeyPatch,
    spec: dict[str, object],
    argv: list[str],
) -> tuple[int, str, str]:
    """Run one ``sase gate create`` invocation and capture its output."""
    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(argv)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(spec)))
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        with pytest.raises(SystemExit) as excinfo:
            handle_gate_command(args)
    return int(excinfo.value.code or 0), out.getvalue(), err.getvalue()


def _list_gate_ids(project: str) -> list[str]:
    """Return every gate-turn id visible to ``sase gate list --all --json``."""
    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["gate", "list", "--all", "--project", project, "--json"])
    out = io.StringIO()
    with redirect_stdout(out):
        with pytest.raises(SystemExit) as excinfo:
            handle_gate_command(args)
    assert int(excinfo.value.code or 0) == 0
    payload = json.loads(out.getvalue())
    return [entry["gate_id"] for entry in payload["gate_turns"]]


def test_canonical_turn_block_registers_row_via_cli(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A canonical JSON ``turn`` block with no flags registers a gate-turn row."""
    del gate_home
    project = "cli-turn-canonical"
    _prepare_creator(monkeypatch, project)
    request_id = "cli-turn-canonical"
    spec = custom_gate_spec(request_id=request_id)
    spec["turn"] = {"next": {"prompt": "Verify the cleanup landed."}}

    code, out, _err = _run_create(monkeypatch, spec, ["gate", "create"])

    assert code == 0
    descriptor = json.loads(out)
    assert descriptor["continuation_mode"] == "gate_turn"
    record = find_gate_turn_by_gate_id(project, request_id)
    assert record is not None
    assert record.gate_id == request_id
    assert request_id in _list_gate_ids(project)


def test_turn_less_json_with_turn_next_flags_registers_row(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turn-less JSON plus ``--turn --next`` persists the next prompt."""
    del gate_home
    project = "cli-turn-flags"
    _prepare_creator(monkeypatch, project)
    request_id = "cli-turn-flags"
    spec = custom_gate_spec(request_id=request_id)

    code, out, _err = _run_create(
        monkeypatch,
        spec,
        ["gate", "create", "--turn", "--next", "Continue after approval"],
    )

    assert code == 0
    descriptor = json.loads(out)
    assert descriptor["continuation_mode"] == "gate_turn"
    assert find_gate_turn_by_gate_id(project, request_id) is not None
    bundle_path = Path(descriptor["bundle_path"])
    request = json.loads((bundle_path / "request.json").read_text(encoding="utf-8"))
    assert isinstance(request.get("turn"), dict)
    assert request["turn"]["next"]["prompt"] == "Continue after approval"
    assert request_id in _list_gate_ids(project)


def test_legacy_shell_block_registers_row_via_cli(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy JSON ``shell`` block with no flags still registers a row."""
    del gate_home
    project = "cli-shell-legacy"
    _prepare_creator(monkeypatch, project)
    request_id = "cli-shell-legacy"
    spec = custom_gate_spec(request_id=request_id)
    spec["shell"] = {"next": {"prompt": "Verify the cleanup landed."}}

    code, _out, _err = _run_create(monkeypatch, spec, ["gate", "create"])

    assert code == 0
    assert find_gate_turn_by_gate_id(project, request_id) is not None
    assert request_id in _list_gate_ids(project)


def test_legacy_shell_block_with_turn_status_flag(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy ``shell`` plus ``--turn-status`` registers the pending status."""
    del gate_home
    project = "cli-shell-status"
    _prepare_creator(monkeypatch, project)
    request_id = "cli-shell-status"
    spec = custom_gate_spec(request_id=request_id)
    spec["shell"] = {"next": {"prompt": "Verify the cleanup landed."}}

    code, out, _err = _run_create(
        monkeypatch, spec, ["gate", "create", "--turn-status", "P"]
    )

    assert code == 0
    descriptor = json.loads(out)
    assert descriptor["continuation_mode"] == "gate_turn"
    record = find_gate_turn_by_gate_id(project, request_id)
    assert record is not None
    assert record.start_status == "P"
    bundle_path = Path(descriptor["bundle_path"])
    request = json.loads((bundle_path / "request.json").read_text(encoding="utf-8"))
    assert request["turn"]["pending_status"] == "P"


def test_both_shell_and_turn_blocks_fail(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON with both blocks exits 1 with the combine error."""
    del gate_home
    project = "cli-both-blocks"
    _prepare_creator(monkeypatch, project)
    spec = custom_gate_spec(request_id="cli-both-blocks")
    spec["shell"] = {"next": {"prompt": "one"}}
    spec["turn"] = {"next": {"prompt": "other"}}

    code, _out, err = _run_create(monkeypatch, spec, ["gate", "create"])

    assert code == 1
    assert "shell and turn blocks cannot be combined" in err


def test_turn_less_json_without_flags_creates_plain_gate(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turn-less JSON with no flags stays a plain gate with no gate-turn row."""
    del gate_home
    project = "cli-plain-gate"
    _prepare_creator(monkeypatch, project)
    request_id = "cli-plain-gate"
    spec = custom_gate_spec(request_id=request_id)

    code, out, _err = _run_create(monkeypatch, spec, ["gate", "create"])

    assert code == 0
    descriptor = json.loads(out)
    assert descriptor["continuation_mode"] == "none"
    assert find_gate_turn_by_gate_id(project, request_id) is None
