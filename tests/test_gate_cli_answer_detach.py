"""``sase gate answer --detach`` -- default-on for gate shells, opt-in otherwise."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.gate_shell.member import create_gate_shell_member
from sase.main.gate_handler import handle_gate_command
from sase.main.parser_gate import register_gate_parser
from sase.notification_gates.model_shell import GateShellSpec
from sase.notification_gates.service import create_gate

_ECHO_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "print(json.dumps({'status': 'ok', 'input': json.load(sys.stdin)}))\n"
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def _run(*argv: str) -> tuple[int, dict[str, Any]]:
    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["gate", *argv, "--json"])
    import io
    from contextlib import redirect_stdout

    out = io.StringIO()
    with redirect_stdout(out):
        with pytest.raises(SystemExit) as excinfo:
            handle_gate_command(args)
    code = int(excinfo.value.code or 0)
    payload = json.loads(out.getvalue()) if out.getvalue().strip() else {}
    return code, payload


def _spec(request_id: str, *, shell: bool = False) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "🧪",
            "title": "Reclaim disk space",
            "notes": ["Free up disk on the shared volume"],
        },
        "query": "cleanup",
        "primary_branch": ["cleanup"],
        "options": [
            {
                "id": "cleanup",
                "label": "Clean up",
                "command": {"argv": ["commands/cleanup"]},
            }
        ],
        "resources": [
            {"path": "commands/cleanup", "role": "command", "content": _ECHO_COMMAND}
        ],
    }
    if shell:
        spec["shell"] = {}
    return spec


def _make_gate_shell_member(request_id: str, bundle_path: Path) -> str:
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    shell = GateShellSpec.from_mapping(
        {"pending_status": "GATE", "settled_status": "GATED"},
        branches=(("cleanup",),),
    )
    artifacts_dir = create_gate_shell_member(
        "proj",
        {"name": "lane--0", "agent_family": "lane", "model": "gpt-5"},
        lane="lane",
        suffix="--gate",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=None,
        gate_id=request_id,
        gate_kind="custom",
        label="Reclaim disk space",
        reason="wait for reviewer",
        creator_agent="lane--0",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        shell=shell,
    )
    update_meta_field(artifacts_dir, "gate_bundle_path", str(bundle_path))
    return artifacts_dir


def _mock_submit(monkeypatch: pytest.MonkeyPatch, proc_id: str = "proc-1") -> MagicMock:
    mock = MagicMock(return_value=MagicMock(proc_id=proc_id))
    monkeypatch.setattr("sase.notification_gates.cli_answer.submit_proc_request", mock)
    return mock


def test_ordinary_gate_stays_synchronous_by_default(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del gate_home
    mock = _mock_submit(monkeypatch)
    gate = create_gate(_spec("plain-1"))

    code, payload = _run("answer", "-i", "plain-1", "-k", "custom", "-o", "cleanup")

    assert code == 0
    mock.assert_not_called()
    assert payload["status"] == "answered"
    assert gate.response_path.is_file()


def test_ordinary_gate_detaches_when_explicitly_asked(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del gate_home
    mock = _mock_submit(monkeypatch)
    gate = create_gate(_spec("plain-2"))

    code, payload = _run(
        "answer", "-i", "plain-2", "-k", "custom", "-o", "cleanup", "--detach"
    )

    assert code == 0
    mock.assert_called_once()
    submitted = mock.call_args.args[0]
    assert submitted.argv == [
        "sase",
        "gate",
        "answer",
        "--id",
        "plain-2",
        "--kind",
        "custom",
        "--no-detach",
        "--json",
    ]
    assert submitted.operation_payload == {"option_ids": ["cleanup"]}
    assert payload["detached"] is True
    assert payload["proc_id"] == "proc-1"
    assert not gate.response_path.exists()


def test_gate_shell_defaults_to_detached(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del gate_home
    mock = _mock_submit(monkeypatch)
    gate = create_gate(_spec("shell-1", shell=True))
    _make_gate_shell_member("shell-1", gate.bundle_path)

    code, payload = _run("answer", "-i", "shell-1", "-k", "custom", "-o", "cleanup")

    assert code == 0
    mock.assert_called_once()
    assert payload["detached"] is True
    assert not gate.response_path.exists()


def test_gate_shell_no_detach_runs_inline_and_settles(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the family-member glue with a stubbed scan lookup.

    ``find_gate_shell_by_gate_id`` resolves through the Rust artifact-index
    scanner, which does not yet propagate ``gate_*`` fields (that lands in
    the sibling ``gate-core-rs`` phase). Stubbing the lookup to return the
    real record -- built the same way ``read_gate_shell_marker`` would once
    the scanner catches up -- tests this phase's own wiring without taking
    on that dependency.
    """
    del gate_home
    mock = _mock_submit(monkeypatch)
    gate = create_gate(_spec("shell-2", shell=True))
    artifacts_dir = _make_gate_shell_member("shell-2", gate.bundle_path)
    from sase.gate_shell.store import read_gate_shell_marker

    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None
    monkeypatch.setattr(
        "sase.notification_gates.cli_answer.find_gate_shell_by_gate_id",
        lambda _project, _gate_id: record,
    )

    code, payload = _run(
        "answer", "-i", "shell-2", "-k", "custom", "-o", "cleanup", "--no-detach"
    )

    assert code == 0
    mock.assert_not_called()
    assert payload["status"] == "answered"
    assert gate.response_path.is_file()

    log_text = (Path(artifacts_dir) / "gate.log").read_text(encoding="utf-8")
    assert "$ commands/cleanup" in log_text

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["gate_state"] == "answered"
    assert meta["chat_path"]
