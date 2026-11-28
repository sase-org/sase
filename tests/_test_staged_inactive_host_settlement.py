"""Inactive settlement eligibility, idempotence, and admission-slot cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    build_questions_staged_record,
    write_adoption_receipt,
)
from tests._staged_inactive_host_helpers import (
    OTHER_STAGED_ID,
    STAGED_ID,
    artifact_dir,
    write_held_receipt,
    write_monitor_stage,
    write_origin_meta,
)


def _write_adopted_receipt(artifact: Path, staged_id: str = STAGED_ID) -> None:
    write_adoption_receipt(
        {
            "staged_id": staged_id,
            "adopted_at": "2026-10-28T12:02:00Z",
            "outcome": "adopted",
            "refs": {},
        },
        artifacts_dir=str(artifact),
    )


def test_adopted_stage_never_settles(monkeypatch, tmp_path) -> None:
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    _write_adopted_receipt(artifact)
    write_origin_meta(artifact, "sase-1.2")
    settlement = _settle_inactive_staged_handoff(str(artifact))
    assert settlement.settled is False
    assert (artifact / ".sase_handoff_settled_inactive.json").exists() is False


def test_settlement_is_idempotent_and_keeps_recovery_evidence(
    monkeypatch, tmp_path
) -> None:
    from sase.agent._staged_handoff_inactive import _read_inactive_settlement
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    write_origin_meta(artifact, "sase-1.2")
    first = _settle_inactive_staged_handoff(str(artifact))
    assert first.settled is True
    assert first.already_settled is False
    assert first.cleanup_complete is True
    assert first.staged_id == STAGED_ID
    assert first.reason == "origin_failed"
    marker = _read_inactive_settlement(str(artifact))
    assert marker is not None
    assert marker["staged_id"] == STAGED_ID
    # Recovery evidence survives settlement.
    assert (artifact / STAGED_HANDOFF_FILENAME).is_file()
    assert (artifact / ".sase_handoff_adopted.json").is_file()
    second = _settle_inactive_staged_handoff(str(artifact))
    assert second.settled is True
    assert second.already_settled is True
    assert second.cleanup_complete is True
    assert second.staged_id == STAGED_ID


def test_settlement_requires_failed_terminal_evidence(monkeypatch, tmp_path) -> None:
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    (artifact / "agent_meta.json").write_text(
        json.dumps({"name": "sase-1.2", "agent_session": "sase-1.2"}),
        encoding="utf-8",
    )
    settlement = _settle_inactive_staged_handoff(str(artifact))
    assert settlement.settled is False
    assert (artifact / ".sase_handoff_settled_inactive.json").exists() is False


def test_submitted_proc_blocks_settlement(monkeypatch, tmp_path) -> None:
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    write_origin_meta(artifact, "sase-1.2")

    class _Proc:
        pass

    monkeypatch.setattr("sase.procs.store.get_proc", lambda _pid: _Proc())
    settlement = _settle_inactive_staged_handoff(str(artifact))
    assert settlement.settled is False
    assert (artifact / ".sase_handoff_settled_inactive.json").exists() is False


def test_unreadable_proc_store_blocks_settlement(monkeypatch, tmp_path) -> None:
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    write_origin_meta(artifact, "sase-1.2")

    def _boom(_pid: str):
        raise OSError("proc store unreadable")

    monkeypatch.setattr("sase.procs.store.get_proc", _boom)
    settlement = _settle_inactive_staged_handoff(str(artifact))
    assert settlement.settled is False
    assert (artifact / ".sase_handoff_settled_inactive.json").exists() is False


def test_settled_origin_releases_admission_slot(monkeypatch, tmp_path) -> None:
    from sase.agent._staged_handoff_admission import occupying_handoff_names
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    write_origin_meta(artifact, "sase-1.2")
    assert occupying_handoff_names(str(artifact)) == (STAGED_HANDOFF_FILENAME,)
    settlement = _settle_inactive_staged_handoff(str(artifact))
    assert settlement.settled is True
    # Settlement releases live ownership, not the write slot. The saved
    # stage still occupies this turn so later work cannot replace it.
    assert occupying_handoff_names(str(artifact)) == (STAGED_HANDOFF_FILENAME,)


def test_replacement_stage_is_not_suppressed_by_old_settlement(
    monkeypatch, tmp_path
) -> None:
    from sase.agent._staged_handoff_admission import occupying_handoff_names
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    write_origin_meta(artifact, "sase-1.2")
    assert _settle_inactive_staged_handoff(str(artifact)).settled is True
    write_monitor_stage(artifact, staged_id=OTHER_STAGED_ID)
    assert occupying_handoff_names(str(artifact)) == (STAGED_HANDOFF_FILENAME,)


def test_settled_origin_refuses_same_turn_questions_overwrite(
    monkeypatch, tmp_path
) -> None:
    from sase.agent.staged_handoff import StagedHandoffError, write_staged_handoff
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    origin = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(origin)
    write_held_receipt(origin)
    write_origin_meta(origin, "sase-1.2")
    original = (origin / STAGED_HANDOFF_FILENAME).read_bytes()
    original_receipt = (origin / ".sase_handoff_adopted.json").read_bytes()
    monkeypatch.setenv("SASE_AGENT", "1")
    assert _settle_inactive_staged_handoff(str(origin)).settled is True
    questions = build_questions_staged_record(
        questions=[{"question": "overwrite?"}],
        dirty_obligations_at_stage=[],
    )
    with pytest.raises(StagedHandoffError, match="pending handoff already exists"):
        write_staged_handoff(questions, artifacts_dir=str(origin))
    assert (origin / STAGED_HANDOFF_FILENAME).read_bytes() == original
    assert (origin / ".sase_handoff_adopted.json").read_bytes() == original_receipt
    saved = json.loads((origin / STAGED_HANDOFF_FILENAME).read_text(encoding="utf-8"))
    assert saved["kind"] == "monitor"
    assert saved["staged_id"] == STAGED_ID


def test_live_origin_still_refuses_second_handoff(monkeypatch, tmp_path) -> None:
    from sase.agent.staged_handoff import StagedHandoffError, write_staged_handoff

    monkeypatch.setenv("SASE_AGENT", "1")
    origin = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(origin)
    write_held_receipt(origin)
    (origin / "agent_meta.json").write_text(
        json.dumps({"name": "sase-1.2", "agent_session": "sase-1.2"}),
        encoding="utf-8",
    )
    original = (origin / STAGED_HANDOFF_FILENAME).read_bytes()
    questions = build_questions_staged_record(
        questions=[{"question": "second?"}],
        dirty_obligations_at_stage=[],
    )
    with pytest.raises(StagedHandoffError, match="pending handoff already exists"):
        write_staged_handoff(questions, artifacts_dir=str(origin))
    assert (origin / STAGED_HANDOFF_FILENAME).read_bytes() == original
