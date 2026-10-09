"""Real custom gate-shell lifecycle acceptance for runner-slot capacity.

Drives the production gate capacity-claim paths -- not hand-authored gate
records -- through real locked claim attempts against the shared
``_RunnerSlotFakeyHarness`` (see ``test_runner_slots_e2e.py``). Plan gate
capacity acceptance lives in the sibling ``test_gate_capacity_plan_e2e.py``;
monitor capacity acceptance lives in ``test_monitor_capacity_e2e.py``.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
import threading

import pytest

from sase.gate_turn.log import bind_gate_turn_execution_callbacks
from sase.gate_turn.member import create_gate_turn_member
from sase.gate_turn.store import read_gate_turn_marker
from sase.main.gate_handler import handle_gate_command
from sase.main.parser_gate import register_gate_parser
import sase.notification_gates.cli_answer_handle as gate_cli_answer_module
from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.model_turn import GateTurnSpec
from sase.notification_gates.models import GateSpec
from sase.notification_gates.paths import bundle_paths
from sase.notification_gates.registry import adapter_for_kind
from sase.notification_gates.service import create_gate

from tests.fakey._gate_capacity_helpers import (
    MONITOR_PROJECT,
    dispatch_gate_answer,
    make_blocking_gate,
)
from tests.fakey._runner_slot_harness import (
    _WAIT_TIMEOUT,
    _RunnerSlotFakeyHarness,
    _wait_for_condition,
)


def test_creation_time_auto_resolved_shell_gate_reuses_creators_claim_without_double_charge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A creation-time ``%auto``-resolved shell-backed gate (production's
    plan/epic ``%auto`` and question auto-approve routes) runs its real
    command under the creator's own already-held claim -- reused, not
    doubly acquired -- and settles the gate shell for real (pid, gate.log,
    terminal state) even though auto-resolution runs inline inside the
    creator's own process/turn, never a separate answering process.

    At cap 1 the creator's own 1.0 claim leaves no free capacity; if
    auto-resolution acquired a second, independent claim instead of riding
    the creator's existing one (the historical gap this test closes), it
    would block forever waiting for capacity that can never free while the
    still-live creator waits on it.
    """
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    creator = harness.create_agent(
        0, name="creator", queue_weight=1.0, queue_weight_explicit=True
    )
    harness.start(creator)
    harness.wait_started(creator)
    creator_owner_key = harness.agent_meta(creator)["runner_claim_owner_key"]

    from sase.user_question_actions import user_question_gate_spec

    shell_block: dict[str, object] = {
        "pending_status": "GATE",
        "settled_status": "GATED",
    }
    spec_dict = user_question_gate_spec(
        [{"question": "Proceed?", "options": [{"label": "Yes"}]}],
        session_id="auto-1",
        producer={"agent": "test"},
        auto=True,
    )
    assert isinstance(spec_dict["presentation"], dict)
    spec_dict["presentation"].update(
        {
            "icon": "🧪",
            "title": "Auto-resolved capacity acceptance",
            "notes": ["Exercise real runner-slot capacity reuse for %auto."],
        }
    )
    spec_dict["turn"] = shell_block

    # Production's real `create_gate_turn` orchestration creates the
    # pending gate-shell member -- inheriting the creator's own weight and
    # `runner_claim_owner_key` -- before ever calling `create_gate`, since
    # `%auto` resolves synchronously inside that same call.
    parsed_turn = GateTurnSpec.from_mapping(shell_block, branches=(("submit",),))
    gate_dir = create_gate_turn_member(
        MONITOR_PROJECT,
        {
            "name": "auto--gate",
            "agent_session": "auto",
            "model": "test",
            "queue_weight": 1.0,
            "queue_weight_explicit": True,
            "runner_claim_owner_key": creator_owner_key,
        },
        lane="auto",
        suffix="--gate",
        prev_artifacts_timestamp=creator.artifacts_dir.name,
        workspace_num=None,
        gate_id="auto-1",
        gate_kind="question",
        label="Auto-resolved capacity acceptance",
        reason="auto-approve",
        creator_agent="creator",
        timeout_seconds=86_400.0,
        request_fingerprint=None,
        turn=parsed_turn,
    )

    # Under E1 every automatic outcome comes from core ``evaluate()``,
    # which only auto-resolves the registered auto-capable kinds (plan,
    # epic_plan, question); a custom gate always asks. This capacity test
    # drives the real registered question adapter, so the creation-time
    # auto-resolved shell still runs through the same production
    # `_start_gate_creation` -> `_resolve_auto_gate` path every kind
    # shares.
    import sase.notification_gates.service_creation as gate_service_module
    from sase.axe.run_agent_helpers_artifacts import update_meta_field
    from sase.notification_gates.models import GateSpec
    from sase.user_question_actions import QUESTION_COMMAND_PATH

    question_adapter = adapter_for_kind("question")
    spec = GateSpec.from_mapping(spec_dict)
    paths = bundle_paths(question_adapter.kind, spec.request_id or "auto-1")
    gate = gate_service_module._start_gate_creation(spec, question_adapter, paths)
    update_meta_field(gate_dir, "gate_bundle_path", str(gate.bundle_path))

    response = json.loads((gate.bundle_path / "response.json").read_text())
    assert response["selected_option_ids"] == ["submit"]
    gate_meta = json.loads((Path(gate_dir) / "agent_meta.json").read_text())
    assert gate_meta["gate_state"] == "answered"
    assert gate_meta["runner_claim_owner_key"] == creator_owner_key
    assert isinstance(gate_meta.get("pid"), int)
    gate_log = (Path(gate_dir) / "gate.log").read_text()
    assert QUESTION_COMMAND_PATH in gate_log

    # The creator's own claim is exactly what the gate shell rode -- never
    # touched or duplicated.
    assert harness.agent_meta(creator)["runner_claim_owner_key"] == creator_owner_key
    harness.release_agent(creator)
    harness.join(creator)


def test_pending_gate_turn_holds_zero_runner_slot_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=2)
    _bundle_path, gate_dir = make_blocking_gate(
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
    bundle_path, gate_dir = make_blocking_gate(
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
            callbacks = bind_gate_turn_execution_callbacks(gate_dir)
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


def test_detached_gate_route_reacquires_runner_slot_capacity_through_the_real_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sase gate answer --detach`` submits a real re-invocation; once that
    re-invocation runs (simulated here as the real background proc would run
    it), it claims runner-slot capacity through the identical production
    path the synchronous route uses.
    """
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=2)
    unrelated = harness.create_agent(0, name="unrelated", queue_weight=1.0)
    harness.start(unrelated)
    harness.wait_started(unrelated)

    gate_started = harness.root / "signals" / "detached.started"
    gate_release = harness.root / "signals" / "detached.release"
    _bundle_path, gate_dir = make_blocking_gate(
        request_id="detached-1",
        member_name="detached--gate",
        lane="detached",
        started=gate_started,
        release=gate_release,
        queue_weight=1.0,
        queue_weight_explicit=True,
    )

    record = read_gate_turn_marker(MONITOR_PROJECT, gate_dir)
    assert record is not None
    monkeypatch.setattr(
        gate_cli_answer_module, "find_gate_turn_by_gate_id", lambda _p, _g: record
    )

    submitted: dict[str, object] = {}

    def fake_submit(request: object) -> object:
        submitted["argv"] = request.argv  # type: ignore[attr-defined]
        return type("Proc", (), {"proc_id": "proc-1"})()

    monkeypatch.setattr(
        "sase.notification_gates.cli_answer_submit.submit_proc_request", fake_submit
    )

    code, payload = dispatch_gate_answer(
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
    bundle_a, gate_dir_a = make_blocking_gate(
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
    # This test establishes the gate-shell row itself below: mark the spec
    # the way the production transaction does so the shell-row guard accepts
    # the setup.
    gate_b = create_gate(replace(GateSpec.from_mapping(spec_b), turn_row_managed=True))
    from sase.notification_gates.paths import owned_resource_path

    owned_resource_path(gate_b.bundle_path, "commands/run").chmod(0o644)
    parsed_turn_b = GateTurnSpec.from_mapping(
        {"pending_status": "GATE", "settled_status": "GATED"}, branches=(("run",),)
    )
    gate_dir_b = create_gate_turn_member(
        MONITOR_PROJECT,
        {
            "name": "failstart--gate",
            "agent_session": "failstart",
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
        turn=parsed_turn_b,
    )
    update_meta_field(gate_dir_b, "gate_bundle_path", str(gate_b.bundle_path))

    with pytest.raises(GateError):
        execute_gate_selection(
            gate_b.bundle_path,
            ["run"],
            {},
            source="test",
            **bind_gate_turn_execution_callbacks(gate_dir_b).as_kwargs(),
        )

    assert (
        harness.agent_meta(unrelated)["runner_claim_owner_key"] == unrelated_owner_key
    )

    harness.release_agent(unrelated)
    harness.join(unrelated)
