"""A hijack cancels its own barrier without releasing dependent turns."""

import json
from pathlib import Path

import pytest

from sase.axe.run_agent_wait_deps import (
    read_ready_result,
    waiting_marker_dependencies_resolved,
)
from sase.axe.run_agent_wait_markers import (
    cancel_waiting_marker_for_hijack,
    publish_ready_marker,
)
from sase.axe.wait_marker_scan import scan_waiting_markers
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent


def test_cancelled_wait_cannot_be_released_by_late_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter = make_waiting_agent(tmp_path, "dependency")
    make_agent(tmp_path, "proj", "20260506010101", "dependency", done=True)
    ready = waiter / "ready.json"
    ready.write_text("{}")

    assert cancel_waiting_marker_for_hijack(str(waiter), "h-wait")
    assert not ready.exists()
    marker = json.loads((waiter / "waiting.json").read_text())
    assert marker["cancelled_by_hijack"] is True
    assert marker["hijack_id"] == "h-wait"
    assert cancel_waiting_marker_for_hijack(str(waiter), "h-wait")
    assert not cancel_waiting_marker_for_hijack(str(waiter), "h-other")
    assert not publish_ready_marker(str(waiter), {})
    # A writer that passed its existence check before cancellation may still
    # leave a ready marker. The reader must honor the durable tombstone.
    ready.write_text("{}")
    assert not read_ready_result(str(ready))
    assert not waiting_marker_dependencies_resolved(
        waiter / "waiting.json", project_name="proj", artifacts_dir=str(waiter)
    )
    scan = scan_waiting_markers(tmp_path / ".sase" / "projects")
    assert scan.waiting == 0


def test_cancelled_queue_does_not_claim_or_replace_its_tombstone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe.run_agent_wait_slots import _try_claim_runner_slot

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    artifacts = tmp_path / "queued"
    artifacts.mkdir()
    waiting = artifacts / "waiting.json"
    waiting.write_text(json.dumps({"slot_requested_at": 123.0}))
    assert cancel_waiting_marker_for_hijack(str(artifacts), "h-queue")
    tombstone = waiting.read_bytes()

    def unexpected_claim() -> str:
        pytest.fail("cancelled queue must not claim a newly available slot")

    assert _try_claim_runner_slot(
        artifacts_dir=str(artifacts),
        cl_name="task",
        timestamp="20261116100000",
        directive_threshold=None,
        claim=unexpected_claim,
    ) == (None, False)
    assert waiting.read_bytes() == tombstone


def test_waiters_of_hijacked_turn_stay_parked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter = make_waiting_agent(tmp_path, "held")
    held = make_agent(
        tmp_path, "proj", "20260506010101", "held", done=True, outcome="hijacked"
    )
    (held / "waiting.json").write_text(json.dumps({"waiting_for": ["upstream"]}))
    original = (waiter / "waiting.json").read_bytes()

    assert cancel_waiting_marker_for_hijack(str(held), "h-wait")
    assert (waiter / "waiting.json").read_bytes() == original
    assert not waiting_marker_dependencies_resolved(
        waiter / "waiting.json", project_name="proj", artifacts_dir=str(waiter)
    )
