"""Per-record capacity accounting through the real Rust binding.

Covers the screenshot shape from the machine-capacity-transparency plan:
three workers, two verify monitors, and one explicit-zero cutover monitor
report 5.0 occupied with one accounting entry per record.
"""

from __future__ import annotations

from sase.core.runner_slots import runner_capacity_snapshot
from tests._runner_slots_helpers import _always_live, _record


def _accounting(snapshot: dict, artifact_dir: str) -> dict:
    for entry in snapshot["accounting"]:
        if entry["artifact_dir"] == artifact_dir:
            return entry
    raise AssertionError(f"no accounting entry for {artifact_dir}")


def _screenshot_records() -> list:
    return [
        _record("/worker-a", run_started=True),
        _record("/worker-b", run_started=True),
        _record("/worker-c", run_started=True),
        _record(
            "/verify-a",
            agent_session="verify-a",
            agent_session_role="monitor",
            monitor_id="verify-a-turn",
            queue_weight=1.0,
        ),
        _record(
            "/verify-b",
            agent_session="verify-b",
            agent_session_role="monitor",
            monitor_id="verify-b-turn",
            queue_weight=1.0,
        ),
        _record(
            "/cutover",
            agent_session="cutover",
            agent_session_role="monitor",
            monitor_id="cutover-turn",
            queue_weight=0.0,
            queue_weight_explicit=True,
        ),
    ]


def test_screenshot_shape_reports_five_occupied_with_six_entries() -> None:
    snapshot = runner_capacity_snapshot(
        _screenshot_records(), _always_live, effective_limit=8.0
    )
    assert snapshot["occupied_capacity"] == 5.0
    assert snapshot["accounting_valid"] is True
    assert len(snapshot["accounting"]) == 6

    for artifact_dir in ("/worker-a", "/worker-b", "/worker-c"):
        holding = _accounting(snapshot, artifact_dir)
        assert holding["state"] == "holding"
        assert holding["charged_weight"] == 1.0
        assert holding["weight_source"] == "default"
        assert holding.get("reason_code") is None

    for artifact_dir in ("/verify-a", "/verify-b"):
        holding = _accounting(snapshot, artifact_dir)
        assert holding["state"] == "holding"
        assert holding["charged_weight"] == 1.0
        assert holding["weight_source"] == "inherited"

    zero = _accounting(snapshot, "/cutover")
    assert zero["state"] == "holding"
    assert zero["charged_weight"] == 0.0
    assert zero["weight_source"] == "explicit_zero"
    assert zero["reason_code"] == "explicit_zero_weight"

    # The charged weights add back up to the reported total.
    assert (
        sum(entry["charged_weight"] for entry in snapshot["accounting"])
        == snapshot["occupied_capacity"]
    )


def test_overridden_monitor_weight_is_not_reported_as_inherited() -> None:
    record = _record(
        "/epic-launch",
        agent_session="epic-launch",
        agent_session_role="monitor",
        monitor_id="epic-launch-turn",
        queue_weight=0.0,
        queue_weight_explicit=True,
    )
    assert record.agent_meta is not None
    object.__setattr__(record.agent_meta, "monitor_queue_weight_overridden", True)

    snapshot = runner_capacity_snapshot([record], _always_live, effective_limit=8.0)
    (entry,) = snapshot["accounting"]
    assert entry["weight_source"] == "explicit_zero"
    assert entry["state"] == "holding"
