"""Observation gathering and ack checks for recovery bootstrap."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack._recovery_successor_bootstrap_observation import (
    collect_bootstrap_observation,
)
from sase.agent.hijack._recovery_successor_common import (
    RECOVERY_DESCRIPTOR_ENV,
    RECOVERY_LINEAGE_ENV,
    RecoveryBootstrapError,
    RecoveryInheritanceError,
)
from sase.agent.hijack._recovery_successor_descriptor import (
    encode_recovery_descriptor,
)
from sase.agent.hijack._recovery_successor_inheritance import (
    build_bootstrap_ack,
    read_recovery_ack,
    require_recovery_inheritance,
)
from sase.agent.hijack.recover_common import RECOVERY_LAUNCH_IDENTITY_ENV
from tests.agent._recovery_bootstrap_shared import (
    descriptor as make_descriptor,
)
from tests.agent._recovery_bootstrap_shared import (
    lineage as make_lineage,
)
from tests.agent._recovery_bootstrap_shared import write_baseline, write_meta


def _write_repos(root: Path, names: dict[str, str] | None = None) -> None:
    from sase._linked_repo_markers import OPENED_LINKED_FILENAME

    root.mkdir(parents=True, exist_ok=True)
    entries = [
        {
            "name": name,
            "workspace_dir": workspace_dir,
            "kind": "linked",
            "reason": "test",
            "opened_at": "test",
        }
        for name, workspace_dir in (names if names is not None else {}).items()
    ]
    (root / OPENED_LINKED_FILENAME).write_text(
        json.dumps({"schema_version": 3, "linked_repos": entries})
    )


class TestCollectObservation:
    def test_collect_reads_metas_and_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.llm_provider.commit_finalizer_baseline import BASELINE_FILENAME

        parent = tmp_path / "parent"
        child = tmp_path / "child"
        write_meta(
            parent,
            name="acme--3",
            bead_id="sase-1",
            goal_id="goal-1",
            autonomy={"selection": "manual"},
        )
        write_meta(child, name="acme--4", bead_id="sase-1", goal_id="goal-1")
        fingerprints = {"/ws/3": {"a.txt": ["abc123", None]}}
        write_baseline(parent, fingerprints)
        write_baseline(child, fingerprints)
        _write_repos(parent, {"sase-core": "/repos/sase-core"})
        _write_repos(child, {"sase-core": "/repos/sase-core"})
        monkeypatch.setenv(RECOVERY_LINEAGE_ENV, json.dumps(make_lineage()))
        monkeypatch.setenv(RECOVERY_LAUNCH_IDENTITY_ENV, "launch-1")
        monkeypatch.setenv("SASE_HIJACK_RECOVERY_STRICT", "1")

        observation = collect_bootstrap_observation(
            child_artifacts_dir=str(child),
            parent_artifacts_dir=str(parent),
            successor_name="acme--4",
            process_token="tok-1",
            project="proj",
            workspace_num=3,
            workspace_dir="/ws/3",
            provider="claude",
            model="opus",
            effort="high",
        )

        assert observation.goal == "goal-1"
        assert observation.bead == "sase-1"
        assert observation.predecessor_goal == "goal-1"
        assert observation.predecessor_bead == "sase-1"
        assert observation.launch_identity == "launch-1"
        assert observation.lineage == make_lineage()
        assert observation.parent_repos == {"sase-core": "/repos/sase-core"}
        assert observation.child_repos == {"sase-core": "/repos/sase-core"}
        assert observation.child_baseline == observation.parent_baseline
        assert observation.predecessor_inventory_missing is False
        assert (child / BASELINE_FILENAME).is_file()

    def test_collect_missing_parent_marks_inventory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        child = tmp_path / "child"
        write_meta(child, name="acme--4")
        monkeypatch.delenv(RECOVERY_LINEAGE_ENV, raising=False)

        observation = collect_bootstrap_observation(
            child_artifacts_dir=str(child),
            parent_artifacts_dir=str(tmp_path / "ghost"),
            successor_name="acme--4",
            process_token=None,
            project="proj",
            workspace_num=3,
            workspace_dir="/ws/3",
            provider="claude",
            model="opus",
            effort=None,
        )

        assert observation.predecessor_inventory_missing is True
        assert observation.predecessor_goal is None
        assert observation.lineage is None


class TestParentSideProof:
    def test_gather_prefers_observed_meta_over_caller_values(
        self, tmp_path: Path
    ) -> None:
        import json as _json

        from sase.agent.hijack.recover_settle import gather_recovery_inheritance
        from tests._agent_hijack_recover_helpers import record as make_record
        from tests._agent_hijack_recover_helpers import subject as make_subject

        predecessor = tmp_path / "artifacts"
        predecessor.mkdir()
        successor = tmp_path / "succ"
        successor.mkdir()
        write_meta(predecessor, name="acme--3", bead_id="sase-1", goal_id="goal-1")
        (successor / "agent_meta.json").write_text(
            _json.dumps({"name": "acme--4", "bead_id": "sase-1", "goal_id": "goal-1"})
        )
        fingerprints = {"/ws/3": {"a.txt": ["abc123", None]}}
        write_baseline(predecessor, fingerprints)
        write_baseline(successor, fingerprints)
        subject = make_subject(make_record(predecessor))

        evidence = gather_recovery_inheritance(
            subject, str(successor), goal="goal-1", bead="sase-1"
        )

        assert evidence is not None
        assert evidence.successor_goal == "goal-1"
        assert evidence.successor_bead == "sase-1"
        assert evidence.baseline_inherited is True
        assert evidence.predecessor_inventory_missing is False

    def test_gather_rejects_mismatched_caller_expectation(self, tmp_path: Path) -> None:
        import json as _json

        from sase.agent.hijack.recover_settle import gather_recovery_inheritance
        from tests._agent_hijack_recover_helpers import record as make_record
        from tests._agent_hijack_recover_helpers import subject as make_subject

        predecessor = tmp_path / "artifacts"
        predecessor.mkdir()
        successor = tmp_path / "succ"
        successor.mkdir()
        (successor / "agent_meta.json").write_text(
            _json.dumps({"name": "acme--4", "bead_id": "sase-1", "goal_id": "goal-1"})
        )
        write_baseline(successor)
        subject = make_subject(make_record(predecessor))

        with pytest.raises(RecoveryInheritanceError, match="expected goal"):
            gather_recovery_inheritance(subject, str(successor), goal="goal-other")

    def test_require_fails_closed_on_missing_inventory(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="inventory"):
            require_recovery_inheritance(
                predecessor_goal="goal-1",
                successor_goal="goal-1",
                predecessor_bead=None,
                successor_bead=None,
                baseline_inherited=True,
                baseline_diagnostics=(),
                predecessor_repo_count=0,
                transferred_repo_count=0,
                repo_diagnostics=(),
                predecessor_inventory_missing=True,
            )


class TestVersionedAck:
    def test_ack_carries_identity_and_verified_flags(self) -> None:
        ack = build_bootstrap_ack(
            goal="goal-1",
            bead="sase-1",
            baseline_inherited=True,
            transferred_repos=2,
            permission={"selection": "manual"},
            launch_identity="launch-1",
            successor_name="acme--4",
            concrete_target="claude/opus@high",
            provider="claude",
            model="opus",
            effort="high",
            lineage=make_lineage(),
        )

        assert ack["schema_version"] == 1
        assert ack["goal_verified"] is True
        assert ack["bead_verified"] is True
        assert ack["scope_verified"] is True
        assert ack["baselines_verified"] is True
        assert ack["inventory_verified"] is True


class TestLineageKeys:
    def test_boot_writes_canonical_and_alias_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_directive_metadata_build import (
            _apply_recovery_lineage_metadata,
        )

        monkeypatch.setenv(RECOVERY_LINEAGE_ENV, json.dumps(make_lineage()))
        agent_meta: dict[str, Any] = {"name": "acme--4", "outcome": "hijacked"}

        _apply_recovery_lineage_metadata(agent_meta)

        assert agent_meta["hijack_lineage"] == make_lineage()
        assert agent_meta["recovery_lineage"] == make_lineage()
        assert "outcome" not in agent_meta

    def test_preview_reads_alias_key(self) -> None:
        from sase.agent.hijack.preview import _lineage_to_rung

        assert _lineage_to_rung({"recovery_lineage": {"to_rung": "@l1"}}) == "@l1"
        assert _lineage_to_rung({"hijack_lineage": {"to_rung": "@l2"}}) == "@l2"


class TestStrictBootstrapEntry:
    def test_strict_entry_blocks_provider_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_runner_bootstrap import (
            _enforce_strict_recovery_bootstrap,
        )

        parent = tmp_path / "parent"
        child = tmp_path / "child"
        write_meta(parent, name="acme--3", bead_id="sase-1", goal_id="goal-1")
        write_meta(child, name="acme--4", bead_id="sase-1", goal_id="goal-other")
        write_baseline(parent)
        write_baseline(child)
        monkeypatch.setenv("SASE_HIJACK_RECOVERY_STRICT", "1")
        monkeypatch.setenv(RECOVERY_LINEAGE_ENV, json.dumps(make_lineage()))
        monkeypatch.setenv(RECOVERY_LAUNCH_IDENTITY_ENV, "launch-1")
        monkeypatch.setenv(
            RECOVERY_DESCRIPTOR_ENV, encode_recovery_descriptor(make_descriptor())
        )

        from sase.agent import agent_session_attach

        plan = SimpleNamespace(
            parent_artifacts_dir=str(tmp_path / "session-root"),
            parent_name="acme--0",
            predecessor_artifacts_dir=str(parent),
            predecessor_name="acme--3",
        )
        monkeypatch.setattr(
            agent_session_attach,
            "load_agent_session_attach_plan_from_env",
            lambda env=None: plan,
        )
        state = SimpleNamespace(
            artifacts_dir=str(child),
            agent_name="acme--4",
            project_name="proj",
            workspace_num=3,
            workspace_dir="/ws/3",
        )
        info = SimpleNamespace(
            bead_id="sase-1",
            llm_provider="claude",
            model="opus",
            meta={"reasoning_effort": "high"},
        )
        provider_calls: list[str] = []
        with pytest.raises(RecoveryBootstrapError) as excinfo:
            _enforce_strict_recovery_bootstrap(state, info)  # type: ignore[arg-type]

        assert excinfo.value.code == "goal_mismatch"
        assert provider_calls == []
        assert read_recovery_ack(str(child)) is None

    def test_non_strict_entry_is_a_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_runner_bootstrap import (
            _enforce_strict_recovery_bootstrap,
        )

        monkeypatch.delenv("SASE_HIJACK_RECOVERY_STRICT", raising=False)
        state = SimpleNamespace(artifacts_dir=str(tmp_path))
        info = SimpleNamespace()

        assert (
            _enforce_strict_recovery_bootstrap(state, info)  # type: ignore[arg-type]
            is None
        )
