"""Inheritance evidence collection tests for hijack recovery."""

from __future__ import annotations

from pathlib import Path

from sase.agent.hijack.recover_settle import gather_recovery_inheritance
from tests._agent_hijack_recover_helpers import (
    record as make_record,
    subject as make_subject,
)


class TestGatherInheritance:
    def test_no_successor_meta_is_not_ready(self, tmp_path: Path) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        subject = make_subject(make_record(artifacts))
        assert (
            gather_recovery_inheritance(subject, str(tmp_path / "succ-ghost")) is None
        )

    def test_populated_successor_gathers(self, tmp_path: Path) -> None:
        import json

        from sase.llm_provider.commit_finalizer_baseline import BASELINE_FILENAME

        predecessor = tmp_path / "artifacts"
        predecessor.mkdir()
        successor = tmp_path / "succ"
        successor.mkdir()
        (predecessor / "agent_meta.json").write_text(
            json.dumps({"name": "acme--3", "bead_id": "sase-1", "goal_id": "goal-1"})
        )
        (successor / "agent_meta.json").write_text(
            json.dumps({"name": "acme--4", "bead_id": "sase-1", "goal_id": "goal-1"})
        )
        fingerprints = {"/ws/3": {"a.txt": ["abc123", None]}}
        (predecessor / BASELINE_FILENAME).write_text(json.dumps(fingerprints))
        (successor / BASELINE_FILENAME).write_text(json.dumps(fingerprints))
        subject = make_subject(make_record(predecessor))
        evidence = gather_recovery_inheritance(subject, str(successor))
        assert evidence is not None
        assert evidence.baseline_inherited is True
        assert evidence.baseline_diagnostics == ()
        assert evidence.predecessor_repo_count == 0
        assert evidence.transferred_repo_count == 0
        assert evidence.predecessor_inventory_missing is False
        assert evidence.successor_goal == "goal-1"
        assert evidence.successor_bead == "sase-1"

    def test_diagnostics_fail_the_baseline(self, tmp_path: Path) -> None:
        import json

        from sase.llm_provider.commit_finalizer_baseline import BASELINE_FILENAME
        from sase.llm_provider.commit_finalizer_inheritance import (
            INHERITANCE_DIAGNOSTICS_FILENAME,
        )

        predecessor = tmp_path / "artifacts"
        predecessor.mkdir()
        successor = tmp_path / "succ"
        successor.mkdir()
        (successor / "agent_meta.json").write_text(json.dumps({"name": "acme--4"}))
        (successor / BASELINE_FILENAME).write_text(json.dumps({"ok": True}))
        (successor / INHERITANCE_DIAGNOSTICS_FILENAME).write_text(
            json.dumps({"diagnostics": ["repo linked:checkout unavailable"]})
        )
        subject = make_subject(make_record(predecessor))
        evidence = gather_recovery_inheritance(subject, str(successor))
        assert evidence is not None
        assert evidence.baseline_inherited is False
        assert evidence.repo_diagnostics == ("repo linked:checkout unavailable",)
