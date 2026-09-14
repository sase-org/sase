"""Real plan gate-shell lifecycle acceptance for runner-slot capacity."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.gate_shell.log import bind_gate_shell_execution_callbacks
from sase.gate_shell.settlement import settle_gate_shell
from sase.gate_shell.store import read_gate_shell_marker
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.paths import RESPONSE_FILENAME

from tests.fakey._gate_capacity_helpers import MONITOR_PROJECT, make_plan_gate
from tests.fakey._runner_slot_harness import _RunnerSlotFakeyHarness
from tests.plan_validation_helpers import VALID_TALE_PLAN


@pytest.mark.parametrize(
    ("option_ids", "request_id", "lane"),
    [
        (("approve", "commit"), "plan-approve-full", "plan-approve"),
        (("reject",), "plan-reject-full", "plan-reject"),
    ],
)
def test_full_capacity_plan_gate_answers_complete_without_waiting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    option_ids: tuple[str, ...],
    request_id: str,
    lane: str,
) -> None:
    """Approve and reject on a shell-backed plan gate must not park at cap."""
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    occupant = harness.create_agent(0, name="occupant", queue_weight=1.0)
    harness.start(occupant)
    harness.wait_started(occupant)

    plan_file = harness.workspace / f"{request_id}.md"
    plan_file.write_text(VALID_TALE_PLAN, encoding="utf-8")
    bundle_path, gate_dir = make_plan_gate(
        request_id=request_id,
        member_name=f"{lane}--gate",
        lane=lane,
        plan_file=plan_file,
    )

    saved = harness.workspace / "sdd" / "plans" / "202609" / plan_file.name

    def archive(*_args: object, **_kwargs: object) -> object:
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(plan_file.read_text(encoding="utf-8"), encoding="utf-8")
        from sase._plan_archive_approval import _ApprovedPlanArchive

        return _ApprovedPlanArchive(saved, f"plan:202609/{plan_file.name}")

    with patch(
        "sase.plan_approval_actions._archive_plan_for_approval",
        side_effect=archive,
    ):
        execute_gate_selection(
            bundle_path,
            option_ids,
            {},
            source="test",
            **bind_gate_shell_execution_callbacks(gate_dir).as_kwargs(),
        )

    assert (bundle_path / RESPONSE_FILENAME).is_file()
    assert not (Path(gate_dir) / "waiting.json").exists()
    gate_meta = json.loads((Path(gate_dir) / "agent_meta.json").read_text())
    assert gate_meta["gate_state"] == "pending"
    assert "runner_claim_owner_key" not in gate_meta
    assert isinstance(gate_meta.get("pid"), int)

    record = read_gate_shell_marker(MONITOR_PROJECT, gate_dir)
    assert record is not None
    with patch(
        "sase.gate_shell.settlement.launch_or_record_followup",
        lambda *_args, **_kwargs: None,
    ):
        settle_gate_shell(record, gate_state="answered", reason="test answer")
    settled = json.loads((Path(gate_dir) / "agent_meta.json").read_text())
    assert settled["gate_state"] == "answered"
    assert not (Path(gate_dir) / "waiting.json").exists()

    harness.release_agent(occupant)
    harness.join(occupant)


def test_successor_after_unclaimed_gate_execution_parks_instead_of_reusing_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A follow-up after unclaimed gate execution must self-acquire capacity."""
    from sase.axe.run_agent_markers import write_agent_meta

    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    occupant = harness.create_agent(0, name="occupant", queue_weight=1.0)
    harness.start(occupant)
    harness.wait_started(occupant)

    plan_file = harness.workspace / "plan-successor.md"
    plan_file.write_text(VALID_TALE_PLAN, encoding="utf-8")
    bundle_path, gate_dir = make_plan_gate(
        request_id="plan-successor-full",
        member_name="plan-successor--gate",
        lane="plan-successor",
        plan_file=plan_file,
    )
    execute_gate_selection(
        bundle_path,
        ["reject"],
        {},
        source="test",
        **bind_gate_shell_execution_callbacks(gate_dir).as_kwargs(),
    )

    gate_meta = json.loads((Path(gate_dir) / "agent_meta.json").read_text())
    assert gate_meta["gate_state"] == "pending"
    assert "runner_claim_owner_key" not in gate_meta
    assert not (Path(gate_dir) / "waiting.json").exists()

    successor = harness.create_agent(
        2,
        name="successor",
        parent_timestamp=Path(gate_dir).name,
        agent_family="plan-successor",
        queue_weight=1.0,
        queue_weight_explicit=True,
    )
    owner = gate_meta.get("runner_claim_owner_key")
    if isinstance(owner, str) and owner:
        successor.meta["runner_claim_owner_key"] = owner
        write_agent_meta(str(successor.artifacts_dir), successor.meta)

    harness.start(successor)
    harness.wait_parked(successor)
    harness.assert_parked_not_started(successor)

    harness.release_agent(occupant)
    harness.join(occupant)
    harness.wait_started(successor)
    harness.release_agent(successor)
    harness.join(successor)
