"""Application and settlement contracts for agent hijack latches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.hijack import core, ledger, latch
from sase.agent.hijack import _latch_apply as latch_apply
from sase.agent.hijack._stop_models import HijackTarget
from sase.agent.hijack._stop_claim import apply_latched_settlement
from tests._agent_hijack_latch_support import (
    install_subjects,
    make_subject,
    make_target,
    shared_latch_store,
)

__all__ = ["shared_latch_store"]


def test_application_holds_claim_and_retries_snapshot_failure(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path / "member")
    install_subjects(monkeypatch, make_subject(target))
    requested = latch.request_latch(target.name)
    pin_calls: list[int] = []
    settlement_calls: list[str] = []
    evidence_calls: list[list[dict[str, Any]]] = []
    evidence_results = iter(("snapshot failed", None))

    monkeypatch.setattr(
        latch_apply, "pin_claim", lambda value: pin_calls.append(value.pid or 0) or True
    )
    monkeypatch.setattr(
        latch_apply,
        "apply_latched_settlement",
        lambda _target, hijack_id: settlement_calls.append(hijack_id),
    )
    monkeypatch.setattr(
        core,
        "hijack_latch_force_eligibility",
        lambda *_args: pytest.fail(
            "a force retry must not re-evaluate age after apply"
        ),
    )

    def attach_evidence(
        hijack_id: str,
        _target: HijackTarget,
        *,
        deps: Any,
        existing_snapshots: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, str | None, str | None]:
        evidence_calls.append(existing_snapshots)
        error = next(evidence_results)
        record = ledger.load_record(hijack_id)
        return record, None, error

    monkeypatch.setattr(latch_apply, "collect_and_attach_evidence", attach_evidence)
    first = latch.apply_latch_at_boundary(
        str(requested["target_key"]),
        "staged_adoption",
        "handoff",
        target=target,
        suppressed_followup={"kind": "pipe", "ref": "/tmp/followup.json"},
    )
    assert first["verdict"] == "applied"
    assert first["code"] == "snapshot_pending"
    assert first["record"]["state"] == "stopping"
    assert first["record"]["boundary_outcome"] == "handoff"
    assert first["record"]["suppressed_followup"] == {
        "kind": "pipe",
        "ref": "/tmp/followup.json",
    }

    second = latch.apply_latch_at_boundary(
        str(requested["target_key"]),
        "staged_adoption",
        "handoff",
        target=target,
        forced=True,
    )
    assert second["verdict"] == "applied"
    assert second["record"]["state"] == "held"
    assert second["record"]["forced"] is False
    assert pin_calls == [42, 42]
    assert settlement_calls == [requested["hijack_id"], requested["hijack_id"]]
    assert evidence_calls == [[], []]


def test_cancel_race_winner_is_reported_without_releasing_application_custody(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path / "member")
    install_subjects(monkeypatch, make_subject(target))
    requested = latch.request_latch(target.name)
    cancelled = latch.cancel_latch(str(requested["target_key"]))
    assert cancelled["verdict"] == "cancelled"
    applied = latch.apply_latch_at_boundary(
        str(requested["target_key"]),
        "run_end",
        "completed",
        target=target,
    )
    assert applied["verdict"] == "no_latch"
    assert ledger.load_record(str(requested["hijack_id"]))["state"] == "cancelled"


def test_latched_settlement_rewrites_only_the_matching_artifact_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path / "member")
    done_path = Path(target.artifacts_dir) / "done.json"
    done_path.write_text(
        '{"project_file":"/tmp/sample.sase",'
        '"artifacts_timestamp":"20261116000100","outcome":"completed"}',
        encoding="utf-8",
    )
    written: list[dict[str, Any]] = []

    def write_marker(_artifacts_dir: str, marker: dict[str, Any]) -> str:
        written.append(marker)
        done_path.write_text(json.dumps(marker), encoding="utf-8")
        return str(done_path)

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_markers.write_done_marker_and_update_index",
        write_marker,
    )
    apply_latched_settlement(target, "hijack-1")
    assert written[0]["outcome"] == "hijacked"
    assert written[0]["recovery"]["hijack_id"] == "hijack-1"

    done_path.write_text(
        '{"project_file":"/tmp/other.sase",'
        '"artifacts_timestamp":"20261116000100","outcome":"completed"}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="different project or artifacts generation"):
        apply_latched_settlement(target, "hijack-2")
    assert len(written) == 1
