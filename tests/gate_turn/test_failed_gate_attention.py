"""Accepted-but-failed gate attention (phase failed-gate-attention)."""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.gate_turn import store as store_mod
from sase.gate_turn.execution_failure import (
    build_gate_execution_failure,
    clear_gate_execution_failure,
    gate_execution_failure_resurfaced,
    mark_gate_execution_failure_resurfaced,
    read_gate_execution_failure,
    write_gate_execution_failure,
)
from sase.gate_turn.models import GateTurnRecord
from sase.gate_turn.projection import gate_turn_runtime_json
from sase.gate_turn.status import (
    GATE_STATUS_FAILURE_STYLE,
    effective_gate_status,
    gate_status_glyph,
    gate_status_pair,
    gate_status_style,
)
from tests.gate_turn._reclaim_helpers import make_reclaim_record


def _failed_record(**overrides: Any) -> GateTurnRecord:
    failure = build_gate_execution_failure(
        stage="command",
        code="command_failed",
        message="option replace failed with exit status 1",
        error_record="errors/abc.json",
        error_report_path="/tmp/bundle/errors/abc.json",
        acceptance_id="acc-1",
        attempt_id="attempt-1",
        outcome_id="out-1",
        resume_command="sase gate answer --kind custom --id g1 --option replace --resume",
        restart_command="sase gate answer --kind custom --id g1 --option replace --restart",
        cancel_command="sase gate cancel --kind custom --id g1",
        recovery_actions="resume,restart,cancel",
        bundle_path="/tmp/bundle",
        request_id="g1",
        request_kind="custom",
    )
    record = make_reclaim_record(gate_id="g1", member_agent_name="lane--gate")
    record = dataclasses.replace(record, gate_state="settling")
    return dataclasses.replace(record, execution_failure=failure, **overrides)


def test_failed_projection_bucket_label_glyph_style() -> None:
    record = _failed_record()
    assert record.status_bucket == "Stopped"
    payload = gate_turn_runtime_json(record)
    assert payload["status_label"].endswith(" ✗")
    assert len(payload["status_label"]) <= 20
    pair = gate_status_pair(record.start_status, record.stop_status)
    assert gate_status_glyph(record.gate_state, has_failure=True) == "✗"
    assert (
        gate_status_style(
            pair, gate_state=record.gate_state, accent=record.accent, has_failure=True
        )
        == GATE_STATUS_FAILURE_STYLE
    )
    assert effective_gate_status(
        pair,
        gate_state=record.gate_state,
        settled=False,
        has_failure=True,
    ).endswith(" ✗")
    assert payload["execution_failure"] is not None
    assert payload["needs_attention"] is True
    assert payload["followup_needs_attention"] is False
    assert payload["recovery_commands"] is not None
    assert "resume_command" in payload["recovery_commands"]


def test_terminal_failed_record_keeps_terminal_bucket() -> None:
    record = _failed_record()
    terminal = dataclasses.replace(record, gate_state="failed")
    assert terminal.is_terminal
    assert terminal.has_execution_failure is False


def test_write_clears_settler_pid_and_roundtrips(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "process_identity": "tok", "proc_id": "p1"}),
        encoding="utf-8",
    )
    failure = build_gate_execution_failure(
        stage="command",
        code="command_failed",
        message="boom",
        error_record="errors/x.json",
        error_report_path=str(tmp_path / "errors/x.json"),
        acceptance_id="acc-1",
        attempt_id="a1",
        outcome_id="o1",
    )
    write_gate_execution_failure(str(artifacts), failure)
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["pid"] is None
    assert meta["gate_execution_failure"]["code"] == "command_failed"
    assert read_gate_execution_failure(str(artifacts)) is not None


def test_clear_removes_failure(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"gate_execution_failure": {"stage": "command"}}),
        encoding="utf-8",
    )
    clear_gate_execution_failure(str(artifacts))
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert "gate_execution_failure" not in meta


def test_resurface_flag_once_per_acceptance(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "gate_execution_failure": build_gate_execution_failure(
                    stage="command",
                    code="command_failed",
                    message="boom",
                    error_record="e.json",
                    error_report_path="e.json",
                    acceptance_id="acc-1",
                    attempt_id="a1",
                    outcome_id="o1",
                )
            }
        ),
        encoding="utf-8",
    )
    assert (
        mark_gate_execution_failure_resurfaced(str(artifacts), acceptance_id="acc-1")
        is True
    )
    assert (
        mark_gate_execution_failure_resurfaced(str(artifacts), acceptance_id="acc-1")
        is False
    )
    assert (
        gate_execution_failure_resurfaced(str(artifacts), acceptance_id="acc-1") is True
    )
    assert (
        gate_execution_failure_resurfaced(str(artifacts), acceptance_id="acc-2")
        is False
    )


def test_write_preserves_history_across_same_acceptance(tmp_path: Path) -> None:
    """A repeated failure on the same acceptance never earns a second allowance."""
    from sase.gate_turn.execution_failure import RESURFACED_HISTORY_KEY

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(json.dumps({}), encoding="utf-8")
    first = build_gate_execution_failure(
        stage="command",
        code="command_failed",
        message="boom",
        error_record="e.json",
        error_report_path="e.json",
        acceptance_id="acc-1",
        attempt_id="a1",
        outcome_id="o1",
    )
    write_gate_execution_failure(str(artifacts), first)
    assert (
        mark_gate_execution_failure_resurfaced(str(artifacts), acceptance_id="acc-1")
        is True
    )
    # Identical retry replays the same acceptance: history keeps the marker.
    second = build_gate_execution_failure(
        stage="command",
        code="command_failed",
        message="boom again",
        error_record="e2.json",
        error_report_path="e2.json",
        acceptance_id="acc-1",
        attempt_id="a2",
        outcome_id="o2",
    )
    write_gate_execution_failure(str(artifacts), second)
    assert (
        gate_execution_failure_resurfaced(str(artifacts), acceptance_id="acc-1") is True
    )
    stored = read_gate_execution_failure(str(artifacts))
    assert stored is not None and stored.get("resurfaced") is True
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert "acc-1" in meta.get(RESURFACED_HISTORY_KEY, {})
    # A genuinely new acceptance starts a new allowance.
    third = build_gate_execution_failure(
        stage="command",
        code="command_failed",
        message="new acceptance",
        error_record="e3.json",
        error_report_path="e3.json",
        acceptance_id="acc-2",
        attempt_id="a3",
        outcome_id="o3",
    )
    write_gate_execution_failure(str(artifacts), third)
    assert (
        gate_execution_failure_resurfaced(str(artifacts), acceptance_id="acc-2")
        is False
    )
    assert (
        gate_execution_failure_resurfaced(str(artifacts), acceptance_id="acc-1") is True
    )


def test_unrelated_visible_notification_cannot_block_recovery(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Identity first: an unrelated visible failure never suppresses the target."""
    import sase.gate_turn._reclaim_pending as reclaim_mod
    from contextlib import contextmanager
    from datetime import UTC, datetime

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    old = time.time() - 7200
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "gate_execution_failure": build_gate_execution_failure(
                    stage="command",
                    code="command_failed",
                    message="boom",
                    error_record="e.json",
                    error_report_path="e.json",
                    acceptance_id="acc-1",
                    attempt_id="a1",
                    outcome_id="o1",
                    at_unix=old,
                )
            }
        ),
        encoding="utf-8",
    )
    record = make_reclaim_record(gate_id="g1", member_agent_name="lane--gate")
    record = dataclasses.replace(record, artifacts_dir=str(artifacts))
    facts = SimpleNamespace(receipt={"acceptance_id": "acc-1"})
    _dismissed_at_str = datetime.fromtimestamp(old, tz=UTC).isoformat()

    class _UnrelatedVisible:
        action = "GateExecutionFailed"
        dismissed = False
        id = "unrelated"
        action_data = {"request_id": "other", "acceptance_id": "other-acc"}
        dismissed_at = None

    class _TargetDismissed:
        action = "GateExecutionFailed"
        dismissed = True
        id = "notif-1"
        action_data = {
            "request_id": "g1",
            "request_kind": "custom",
            "acceptance_id": "acc-1",
        }

    _TargetDismissed.dismissed_at = _dismissed_at_str

    @contextmanager
    def _locked(_project: str, _lane: str):
        yield True

    monkeypatch.setattr("sase.gate_turn.lane_lock.try_gate_lane_lock", _locked)
    monkeypatch.setattr(
        "sase.gate_turn.store.read_gate_turn_marker", lambda _p, _a: record
    )
    monkeypatch.setattr(
        "sase.notifications.store.load_notifications",
        lambda **_k: [_UnrelatedVisible(), _TargetDismissed()],
    )
    monkeypatch.setattr(
        "sase.gate_turn._reclaim_pending._core_resurface_eligible",
        lambda **_k: True,
    )
    notified: list[str] = []

    def _fake_restore(notification_id: str) -> bool:
        notified.append(notification_id)
        return True

    monkeypatch.setattr(
        "sase.notifications.store.restore_dismissed_notification", _fake_restore
    )
    reclaim_mod._maybe_resurface_failure_notification(
        record, Path("/tmp/bundle"), facts, now=time.time()
    )
    assert notified == ["notif-1"]


def test_cli_list_and_markdown_render_failure_summary() -> None:
    """Both human list formats render the same failure facts as show."""
    from sase.main.gate_turn_render import (
        gate_turn_list_markdown,
        gate_turn_table,
    )

    record = _failed_record()
    table = gate_turn_table([record], title="Gate turns")
    assert table is not None
    markdown = gate_turn_list_markdown([record])
    assert "execution failed" in markdown
    assert "resume with:" in markdown
    assert "restart with:" in markdown
    assert "cancel with:" in markdown


def test_snapshot_only_failure_projects_without_artifacts_dir() -> None:
    """A supplied snapshot renders failure even when the dir is unavailable."""
    from sase.gate_turn.store import _with_execution_failure

    record = _failed_record()
    missing = dataclasses.replace(record, artifacts_dir="/nonexistent/dir-xyz")
    # Wire already carries the failure: no filesystem read may clear it.
    projected = _with_execution_failure(missing)
    assert projected.execution_failure is not None
    assert projected.status_bucket == "Stopped"
    payload = gate_turn_runtime_json(projected)
    assert payload["needs_attention"] is True
    assert payload["recovery_commands"] is not None


def test_dismiss_clears_member_failure(tmp_path: Path, monkeypatch: Any) -> None:
    from sase.notification_gates import failure_notifications as fn_mod

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"gate_execution_failure": {"stage": "command"}}),
        encoding="utf-8",
    )
    record = make_reclaim_record(gate_id="g1", member_agent_name="lane--gate")
    record = dataclasses.replace(record, artifacts_dir=str(artifacts))
    monkeypatch.setattr(store_mod, "find_gate_turn_by_gate_id", lambda _p, _g: record)
    import sase.notification_gates.hashing as hashing_mod

    monkeypatch.setattr(
        hashing_mod, "load_and_verify_bundle", lambda _b: ({"request_id": "g1"}, None)
    )
    fn_mod.dismiss_gate_execution_failed(bundle_path=Path("/tmp/bundle"))
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert "gate_execution_failure" not in meta


def test_maybe_resurface_only_after_hour_and_once(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import sase.gate_turn._reclaim_pending as reclaim_mod
    from contextlib import contextmanager

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    old = time.time() - 7200
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "gate_execution_failure": build_gate_execution_failure(
                    stage="command",
                    code="command_failed",
                    message="boom",
                    error_record="e.json",
                    error_report_path="e.json",
                    acceptance_id="acc-1",
                    attempt_id="a1",
                    outcome_id="o1",
                    at_unix=old,
                )
            }
        ),
        encoding="utf-8",
    )
    record = make_reclaim_record(gate_id="g1", member_agent_name="lane--gate")
    record = dataclasses.replace(record, artifacts_dir=str(artifacts))
    facts = SimpleNamespace(receipt={"acceptance_id": "acc-1"})
    notified = {"undismissed": []}

    from datetime import UTC, datetime

    dismissed_at = datetime.fromtimestamp(old, tz=UTC).isoformat()

    class _FakeNotification:
        action = "GateExecutionFailed"
        dismissed = True
        id = "notif-1"
        action_data = {
            "request_id": "g1",
            "request_kind": "custom",
            "acceptance_id": "acc-1",
        }

    # Dismissal age comes from dismissed_at, never failure time; the lane
    # lock serializes competing reclaimers and the changed write proves
    # this invocation restored the row.
    @contextmanager
    def _locked(_project: str, _lane: str):
        yield True

    monkeypatch.setattr("sase.gate_turn.lane_lock.try_gate_lane_lock", _locked)
    monkeypatch.setattr(
        "sase.gate_turn.store.read_gate_turn_marker",
        lambda _p, _a: record,
    )
    monkeypatch.setattr(
        "sase.notifications.store.load_notifications",
        lambda **_k: [_FakeNotification()],
    )
    # Attach the dismissal timestamp the Rust contract now persists.
    _FakeNotification.dismissed_at = dismissed_at  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "sase.gate_turn._reclaim_pending._core_resurface_eligible",
        lambda **_k: True,
    )

    def _fake_restore(notification_id: str) -> bool:
        notified["undismissed"].append(notification_id)
        return True

    monkeypatch.setattr(
        "sase.notifications.store.restore_dismissed_notification", _fake_restore
    )
    reclaim_mod._maybe_resurface_failure_notification(
        record, Path("/tmp/bundle"), facts, now=time.time()
    )
    assert notified["undismissed"] == ["notif-1"]
    notified["undismissed"].clear()
    reclaim_mod._maybe_resurface_failure_notification(
        record, Path("/tmp/bundle"), facts, now=time.time()
    )
    assert notified["undismissed"] == []


def test_maybe_resurface_skips_recent_failure(tmp_path: Path, monkeypatch: Any) -> None:
    import sase.gate_turn._reclaim_pending as reclaim_mod

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "gate_execution_failure": build_gate_execution_failure(
                    stage="command",
                    code="command_failed",
                    message="boom",
                    error_record="e.json",
                    error_report_path="e.json",
                    acceptance_id="acc-1",
                    attempt_id="a1",
                    outcome_id="o1",
                    at_unix=time.time(),
                )
            }
        ),
        encoding="utf-8",
    )
    record = make_reclaim_record(gate_id="g1", member_agent_name="lane--gate")
    record = dataclasses.replace(record, artifacts_dir=str(artifacts))
    facts = SimpleNamespace(receipt={"acceptance_id": "acc-1"})
    called = {"n": 0}
    monkeypatch.setattr(
        "sase.notifications.store.load_notifications",
        lambda **_k: (_ for _ in ()).throw(AssertionError("must not scan")),
    )
    monkeypatch.setattr(
        "sase.notifications.store.mark_undismissed",
        lambda _nid: called.__setitem__("n", called["n"] + 1) or True,
    )
    reclaim_mod._maybe_resurface_failure_notification(
        record, Path("/tmp/bundle"), facts, now=time.time()
    )
    assert called["n"] == 0


def test_backfill_writes_missing_failure(tmp_path: Path, monkeypatch: Any) -> None:
    import sase.gate_turn._reclaim_pending as reclaim_mod
    from contextlib import contextmanager
    from sase.notification_gates.journal import ExecutionFailureFacts

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(json.dumps({}), encoding="utf-8")
    record = make_reclaim_record(gate_id="g1", member_agent_name="lane--gate")
    record = dataclasses.replace(
        record, artifacts_dir=str(artifacts), bundle_path=str(tmp_path / "bundle")
    )

    @contextmanager
    def _locked(_project: str, _lane: str):
        yield True

    monkeypatch.setattr("sase.gate_turn.lane_lock.try_gate_lane_lock", _locked)
    monkeypatch.setattr(
        "sase.gate_turn.store.read_gate_turn_marker", lambda _p, _a: record
    )
    failure = ExecutionFailureFacts(
        outcome_id="o1",
        acceptance_id="acc-1",
        attempt_id="a1",
        stage="command",
        code="command_failed",
        message="boom",
        at_unix=time.time(),
        error_record="errors/e.json",
    )
    monkeypatch.setattr(
        "sase.notification_gates.journal.current_gate_execution_failure",
        lambda _b, _r, **_k: failure,
    )
    monkeypatch.setattr(
        reclaim_mod,
        "load_and_verify_bundle",
        lambda _b: ({"request_id": "g1", "kind": "custom"}, None),
    )
    monkeypatch.setattr(
        "sase.notification_gates.failure_notifications.gate_failure_action_data",
        lambda _b, _e, _f: {
            "resume_command": "resume",
            "restart_command": "restart",
            "cancel_command": "cancel",
            "recovery_actions": "resume,restart,cancel",
            "error_report_path": "errors/e.json",
        },
    )
    facts = SimpleNamespace(receipt={"acceptance_id": "acc-1"})
    reclaim_mod._backfill_member_failure(record, tmp_path / "bundle", facts)
    assert read_gate_execution_failure(str(artifacts)) is not None
