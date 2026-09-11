"""Real gate-shell lifecycle acceptance for weighted runner-slot capacity.

Drives the production gate capacity-claim paths -- not hand-authored gate
records -- through real ``wait_for_runner_slot`` contention against the
shared ``_RunnerSlotFakeyHarness`` (see ``test_runner_slots_e2e.py``).
Monitor capacity acceptance lives in the sibling ``test_monitor_capacity_e2e.py``.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import threading

import pytest

from sase.gate_shell.log import bind_gate_shell_execution_callbacks
from sase.gate_shell.member import create_gate_shell_member
from sase.main.gate_handler import handle_gate_command
from sase.main.parser_gate import register_gate_parser
import sase.notification_gates.cli_answer as gate_cli_answer_module
from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.model_shell import GateShellSpec
from sase.notification_gates.service import create_gate

from tests.fakey._runner_slot_harness import (
    _WAIT_TIMEOUT,
    _RunnerSlotFakeyHarness,
    _wait_for_condition,
)

_MONITOR_PROJECT = "fakey-slots"


def _blocking_gate_command_script(started: Path, release: Path) -> str:
    """Return a gate-option command script that signals then blocks."""
    return (
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys, time\n"
        "json.load(sys.stdin)\n"
        f"pathlib.Path({str(started)!r}).write_text('1')\n"
        f"deadline = time.monotonic() + {_WAIT_TIMEOUT}\n"
        f"while not pathlib.Path({str(release)!r}).exists():\n"
        "    if time.monotonic() > deadline:\n"
        "        sys.exit(1)\n"
        "    time.sleep(0.01)\n"
        "print(json.dumps({'status': 'ok'}))\n"
    )


def _make_blocking_gate(
    *,
    request_id: str,
    member_name: str,
    lane: str,
    started: Path,
    release: Path,
    queue_weight: float = 1.0,
    queue_weight_explicit: bool = False,
) -> tuple[Path, str]:
    """Create a real gate bundle plus its gate-shell member.

    The bundle's one option runs a command that blocks until *release*
    exists, so a test can drive real ``wait_for_runner_slot`` contention
    around the gate's execution window.
    """
    shell_block: dict[str, object] = {
        "pending_status": "GATE",
        "settled_status": "GATED",
    }
    spec: dict[str, object] = {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "🧪",
            "title": "Runner-slot capacity acceptance",
            "notes": ["Exercise real runner-slot capacity contention."],
        },
        "query": "run",
        "primary_branch": ["run"],
        "options": [
            {"id": "run", "label": "Run", "command": {"argv": ["commands/run"]}}
        ],
        "resources": [
            {
                "path": "commands/run",
                "role": "command",
                "content": _blocking_gate_command_script(started, release),
            }
        ],
        "shell": shell_block,
    }
    gate = create_gate(spec)
    parsed_shell = GateShellSpec.from_mapping(shell_block, branches=(("run",),))
    artifacts_dir = create_gate_shell_member(
        _MONITOR_PROJECT,
        {
            "name": member_name,
            "agent_family": lane,
            "model": "test",
            "queue_weight": queue_weight,
            "queue_weight_explicit": queue_weight_explicit,
        },
        lane=lane,
        suffix="--gate",
        prev_artifacts_timestamp="20260713090098",
        workspace_num=None,
        gate_id=request_id,
        gate_kind="custom",
        label="Runner-slot capacity acceptance",
        reason="wait for reviewer",
        creator_agent=member_name,
        timeout_seconds=86_400.0,
        request_fingerprint=None,
        shell=parsed_shell,
    )
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    update_meta_field(artifacts_dir, "gate_bundle_path", str(gate.bundle_path))
    return gate.bundle_path, artifacts_dir


def test_pending_gate_shell_holds_zero_runner_slot_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=2)
    _bundle_path, gate_dir = _make_blocking_gate(
        request_id="pending-1",
        member_name="pending--gate",
        lane="pending",
        started=harness.root / "signals" / "pending.started",
        release=harness.root / "signals" / "pending.release",
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    gate_meta = json.loads((Path(gate_dir) / "agent_meta.json").read_text())
    assert gate_meta["gate_state"] == "pending"

    first = harness.create_agent(0, name="first", queue_weight=1.0)
    second = harness.create_agent(1, name="second", queue_weight=1.0)
    harness.start(first)
    harness.wait_started(first)
    harness.start(second)
    harness.wait_started(second)

    gate_meta = json.loads((Path(gate_dir) / "agent_meta.json").read_text())
    assert gate_meta["gate_state"] == "pending"
    assert harness.claim_order == ["first", "second"]

    harness.release_agent(first)
    harness.join(first)
    harness.release_agent(second)
    harness.join(second)


def test_synchronous_gate_answer_claims_and_releases_runner_slot_capacity_like_an_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default (non-detached) answer route claims real runner-slot
    capacity before its command executes, and releases it like any agent --
    without disturbing an unrelated owner's already-live claim.
    """
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=2)
    unrelated = harness.create_agent(0, name="unrelated", queue_weight=1.0)
    harness.start(unrelated)
    harness.wait_started(unrelated)
    unrelated_owner_key = harness.agent_meta(unrelated)["runner_claim_owner_key"]

    gate_started = harness.root / "signals" / "answer.started"
    gate_release = harness.root / "signals" / "answer.release"
    bundle_path, gate_dir = _make_blocking_gate(
        request_id="answer-1",
        member_name="answer--gate",
        lane="answer",
        started=gate_started,
        release=gate_release,
        queue_weight=1.0,
        queue_weight_explicit=True,
    )

    errors: list[BaseException] = []

    def run_gate() -> None:
        try:
            callbacks = bind_gate_shell_execution_callbacks(gate_dir)
            execute_gate_selection(
                bundle_path, ["run"], {}, source="test", **callbacks.as_kwargs()
            )
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors`
            errors.append(exc)

    thread = threading.Thread(target=run_gate, daemon=True)
    thread.start()
    _wait_for_condition(gate_started.exists, "gate command to start")

    gate_meta = json.loads((Path(gate_dir) / "agent_meta.json").read_text())
    assert gate_meta["gate_state"] == "settling"
    gate_owner_key = gate_meta.get("runner_claim_owner_key")
    assert isinstance(gate_owner_key, str) and gate_owner_key
    assert gate_owner_key != unrelated_owner_key
    assert gate_meta["queue_weight"] == 1.0

    competitor = harness.create_agent(1, name="competitor", queue_weight=1.0)
    harness.start(competitor)
    harness.wait_parked(competitor)

    assert (
        harness.agent_meta(unrelated)["runner_claim_owner_key"] == unrelated_owner_key
    )

    gate_release.parent.mkdir(parents=True, exist_ok=True)
    gate_release.touch()
    thread.join(_WAIT_TIMEOUT)
    assert not thread.is_alive()
    assert not errors

    harness.wait_started(competitor)
    harness.release_agent(competitor)
    harness.join(competitor)
    harness.release_agent(unrelated)
    harness.join(unrelated)


def _dispatch_gate_answer(argv: list[str]) -> tuple[int, dict[str, object]]:
    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["gate", *argv, "--json"])
    out = io.StringIO()
    with redirect_stdout(out):
        with pytest.raises(SystemExit) as excinfo:
            handle_gate_command(args)
    code = int(excinfo.value.code or 0)
    payload = json.loads(out.getvalue()) if out.getvalue().strip() else {}
    return code, payload


def test_detached_gate_route_reacquires_runner_slot_capacity_through_the_real_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sase gate answer --detach`` submits a real re-invocation; once that
    re-invocation runs (simulated here as the real background proc would run
    it), it claims runner-slot capacity through the identical production
    path the synchronous route uses.
    """
    from sase.gate_shell.store import read_gate_shell_marker

    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=2)
    unrelated = harness.create_agent(0, name="unrelated", queue_weight=1.0)
    harness.start(unrelated)
    harness.wait_started(unrelated)

    gate_started = harness.root / "signals" / "detached.started"
    gate_release = harness.root / "signals" / "detached.release"
    _bundle_path, gate_dir = _make_blocking_gate(
        request_id="detached-1",
        member_name="detached--gate",
        lane="detached",
        started=gate_started,
        release=gate_release,
        queue_weight=1.0,
        queue_weight_explicit=True,
    )

    record = read_gate_shell_marker(_MONITOR_PROJECT, gate_dir)
    assert record is not None
    monkeypatch.setattr(
        gate_cli_answer_module, "find_gate_shell_by_gate_id", lambda _p, _g: record
    )

    submitted: dict[str, object] = {}

    def fake_submit(request: object) -> object:
        submitted["argv"] = request.argv  # type: ignore[attr-defined]
        return type("Proc", (), {"proc_id": "proc-1"})()

    monkeypatch.setattr(gate_cli_answer_module, "submit_proc_request", fake_submit)

    code, payload = _dispatch_gate_answer(
        ["answer", "-i", "detached-1", "-k", "custom", "-o", "run", "--detach"]
    )
    assert code == 0
    assert payload["detached"] is True
    assert submitted["argv"] == [
        "sase",
        "gate",
        "answer",
        "--id",
        "detached-1",
        "--kind",
        "custom",
        "--no-detach",
        "--json",
    ]
    assert not gate_started.exists()

    errors: list[BaseException] = []

    def run_detached() -> None:
        # This runs concurrently with the harness's own competitor thread,
        # and `redirect_stdout` is process-global, so this dispatch (unlike
        # the synchronous one above) must not capture stdout for parsing.
        parser = argparse.ArgumentParser(prog="sase")
        register_gate_parser(parser.add_subparsers(dest="command"))
        args = parser.parse_args(
            [
                "gate",
                "answer",
                "-i",
                "detached-1",
                "-k",
                "custom",
                "-o",
                "run",
                "--no-detach",
                "--json",
            ]
        )
        try:
            with pytest.raises(SystemExit):
                handle_gate_command(args)
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors`
            errors.append(exc)

    thread = threading.Thread(target=run_detached, daemon=True)
    thread.start()
    _wait_for_condition(gate_started.exists, "detached gate command to start")

    gate_meta = json.loads((Path(gate_dir) / "agent_meta.json").read_text())
    assert gate_meta["gate_state"] == "settling"
    assert isinstance(gate_meta.get("runner_claim_owner_key"), str)

    competitor = harness.create_agent(1, name="competitor", queue_weight=1.0)
    harness.start(competitor)
    harness.wait_parked(competitor)

    gate_release.parent.mkdir(parents=True, exist_ok=True)
    gate_release.touch()
    thread.join(_WAIT_TIMEOUT)
    assert not thread.is_alive()
    assert not errors

    harness.wait_started(competitor)
    harness.release_agent(competitor)
    harness.join(competitor)
    harness.release_agent(unrelated)
    harness.join(unrelated)


def test_gate_cancellation_and_failed_startup_do_not_disturb_an_unrelated_owners_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling a still-pending gate, and a gate command that fails to
    start, must both leave an unrelated, already-live owner's claim alone.
    """
    from sase.axe.run_agent_helpers_artifacts import update_meta_field
    from sase.notification_gates.models import GateError

    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=2)
    unrelated = harness.create_agent(0, name="unrelated", queue_weight=1.0)
    harness.start(unrelated)
    harness.wait_started(unrelated)
    unrelated_owner_key = harness.agent_meta(unrelated)["runner_claim_owner_key"]

    # -- cancellation: a still-pending gate never claimed capacity at all --
    bundle_a, gate_dir_a = _make_blocking_gate(
        request_id="cancel-1",
        member_name="cancel--gate",
        lane="cancel",
        started=harness.root / "signals" / "cancel.started",
        release=harness.root / "signals" / "cancel.release",
    )
    cancel_gate(bundle_a, reason="test cancellation")
    assert (bundle_a / "cancellation.json").exists()
    gate_meta_a = json.loads((Path(gate_dir_a) / "agent_meta.json").read_text())
    assert gate_meta_a["gate_state"] == "pending"
    assert (
        harness.agent_meta(unrelated)["runner_claim_owner_key"] == unrelated_owner_key
    )

    # -- failed startup: the claim is taken, then the command itself can
    # never start (its executable bit is stripped after a valid creation),
    # which must not touch the unrelated owner's own claim either.
    spec_b: dict[str, object] = {
        "schema_version": 3,
        "request_id": "failstart-1",
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "🧪",
            "title": "Failed startup acceptance",
            "notes": ["A stripped command resource must fail to start."],
        },
        "query": "run",
        "primary_branch": ["run"],
        "options": [
            {"id": "run", "label": "Run", "command": {"argv": ["commands/run"]}}
        ],
        "resources": [
            {
                "path": "commands/run",
                "role": "command",
                "content": "not a script\n",
                "executable": True,
            }
        ],
        "shell": {"pending_status": "GATE", "settled_status": "GATED"},
    }
    gate_b = create_gate(spec_b)
    from sase.notification_gates.paths import owned_resource_path

    owned_resource_path(gate_b.bundle_path, "commands/run").chmod(0o644)
    parsed_shell_b = GateShellSpec.from_mapping(
        {"pending_status": "GATE", "settled_status": "GATED"}, branches=(("run",),)
    )
    gate_dir_b = create_gate_shell_member(
        _MONITOR_PROJECT,
        {
            "name": "failstart--gate",
            "agent_family": "failstart",
            "model": "test",
            "queue_weight": 1.0,
            "queue_weight_explicit": True,
        },
        lane="failstart",
        suffix="--gate",
        prev_artifacts_timestamp="20260713090097",
        workspace_num=None,
        gate_id="failstart-1",
        gate_kind="custom",
        label="Failed startup acceptance",
        reason="wait for reviewer",
        creator_agent="failstart--gate",
        timeout_seconds=86_400.0,
        request_fingerprint=None,
        shell=parsed_shell_b,
    )
    update_meta_field(gate_dir_b, "gate_bundle_path", str(gate_b.bundle_path))

    with pytest.raises(GateError):
        execute_gate_selection(
            gate_b.bundle_path,
            ["run"],
            {},
            source="test",
            **bind_gate_shell_execution_callbacks(gate_dir_b).as_kwargs(),
        )

    assert (
        harness.agent_meta(unrelated)["runner_claim_owner_key"] == unrelated_owner_key
    )

    harness.release_agent(unrelated)
    harness.join(unrelated)
