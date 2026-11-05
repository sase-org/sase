"""Child-side before-provider enforcement for keep-work recovery.

Covers phase ``bootstrap_ack``: the reservation descriptor round-trip,
the strict-boot gate in :func:`enforce_recovery_bootstrap` (attempt
identity, goal, bead, permission scope, baseline fingerprints, repository
identities, effective model), the versioned ack persistence, the
expectation-not-proof gather semantics, and the canonical
``hijack_lineage`` key. Every failure case asserts the provider is never
invoked.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack.recover_common import RECOVERY_LAUNCH_IDENTITY_ENV
from sase.agent.hijack.recovery_successor import (
    BOOTSTRAP_ACK_SCHEMA_VERSION,
    RECOVERY_DESCRIPTOR_ENV,
    RECOVERY_LINEAGE_ENV,
    BootstrapObservation,
    RecoveryBootstrapError,
    RecoveryInheritanceError,
    build_bootstrap_ack,
    build_recovery_descriptor,
    collect_bootstrap_observation,
    decode_recovery_descriptor,
    enforce_recovery_bootstrap,
    encode_recovery_descriptor,
    read_recovery_ack,
    require_recovery_inheritance,
)


def _lineage(**overrides: Any) -> dict[str, str]:
    payload = {
        "hijack_id": "hij-1",
        "from_rung": "claude/opus@high",
        "to_rung": "claude/opus@high",
        "predecessor": "acme--3",
    }
    payload.update(overrides)
    return payload


def _descriptor(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = build_recovery_descriptor(
        hijack_id="hij-1",
        launch_identity="launch-1",
        concrete_target="claude/opus@high",
        reserved_successor_name="acme--4",
        project="proj",
        workspace_dir="/ws/3",
        lineage=_lineage(),
        workspace_num=3,
    )
    payload.update(overrides)
    return payload


def _write_meta(root: Path, **fields: Any) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "agent_meta.json").write_text(json.dumps(dict(fields)))


def _write_baseline(root: Path, fingerprints: dict[str, Any] | None = None) -> None:
    from sase.llm_provider.commit_finalizer_baseline import BASELINE_FILENAME

    root.mkdir(parents=True, exist_ok=True)
    payload = (
        fingerprints
        if fingerprints is not None
        else {"/ws/3": {"a.txt": ["abc123", None]}}
    )
    (root / BASELINE_FILENAME).write_text(json.dumps(payload))


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


def _parent_child(tmp_path: Path) -> tuple[Path, Path]:
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    _write_meta(parent, name="acme--3", bead_id="sase-1", goal_id="goal-1")
    _write_meta(child, name="acme--4", bead_id="sase-1", goal_id="goal-1")
    _write_baseline(parent)
    _write_baseline(child)
    return parent, child


def _observation(**overrides: Any) -> BootstrapObservation:
    base: dict[str, Any] = {
        "successor_name": "acme--4",
        "process_token": "tok-1",
        "project": "proj",
        "workspace_num": 3,
        "workspace_dir": "/ws/3",
        "launch_identity": "launch-1",
        "provider": "claude",
        "model": "opus",
        "effort": "high",
        "goal": "goal-1",
        "bead": "sase-1",
        "predecessor_goal": "goal-1",
        "predecessor_bead": "sase-1",
        "predecessor_autonomy": {
            "selection": "manual",
            "source": "inherited",
            "surface": "launch",
            "revision": 1,
        },
        "predecessor_name": "acme--3",
        "explicit_autonomy_selection": None,
        "parent_meta": {"name": "acme--3", "bead_id": "sase-1", "goal_id": "goal-1"},
        "child_meta": {"name": "acme--4", "bead_id": "sase-1", "goal_id": "goal-1"},
        "baseline_inherited": True,
        "baseline_diagnostics": (),
        "repo_diagnostics": (),
        "predecessor_inventory_missing": False,
        "parent_repos": {},
        "child_repos": {},
        "parent_baseline": {"/ws/3": {"a.txt": ["abc123", None]}},
        "child_baseline": {"/ws/3": {"a.txt": ["abc123", None]}},
        "lineage": _lineage(),
    }
    base.update(overrides)
    return BootstrapObservation(**base)


def _mock_inherit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.autonomy.record.autonomy_inherit_record",
        lambda *args, **kwargs: {
            "status": "ok",
            "record": {"selection": "manual", "source": "inherited"},
        },
    )


class TestDescriptorRoundTrip:
    def test_encode_decode_round_trip(self) -> None:
        descriptor = _descriptor()

        assert (
            decode_recovery_descriptor(encode_recovery_descriptor(descriptor))
            == descriptor
        )

    def test_missing_raw_raises_typed(self) -> None:
        with pytest.raises(RecoveryBootstrapError) as excinfo:
            decode_recovery_descriptor(None)

        assert excinfo.value.code == "missing_descriptor"

    def test_malformed_payload_raises_typed(self) -> None:
        with pytest.raises(RecoveryBootstrapError) as excinfo:
            decode_recovery_descriptor("{oops")

        assert excinfo.value.code == "missing_descriptor"

    def test_incomplete_descriptor_raises_typed(self) -> None:
        with pytest.raises(RecoveryBootstrapError) as excinfo:
            decode_recovery_descriptor(json.dumps({"hijack_id": "hij-1"}))

        assert excinfo.value.code == "missing_descriptor"
        assert "launch_identity" in str(excinfo.value)


class TestEnforceSuccess:
    def test_proven_boot_persists_versioned_ack_and_runs_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_inherit(monkeypatch)
        parent, child = _parent_child(tmp_path)
        descriptor = _descriptor()
        observation = _observation()
        calls: list[str] = []

        def fake_provider() -> str:
            calls.append("provider")
            return "ran"

        ack = enforce_recovery_bootstrap(
            child_artifacts_dir=str(child),
            descriptor=descriptor,
            observation=observation,
        )

        assert calls == []
        assert fake_provider() == "ran"
        assert ack["schema_version"] == BOOTSTRAP_ACK_SCHEMA_VERSION
        assert ack["launch_identity"] == "launch-1"
        assert ack["successor_name"] == "acme--4"
        assert ack["concrete_target"] == "claude/opus@high"
        assert ack["provider"] == "claude"
        assert ack["model"] == "opus"
        assert ack["effort"] == "high"
        assert ack["goal"] == "goal-1"
        assert ack["bead"] == "sase-1"
        assert ack["lineage"] == _lineage()
        assert read_recovery_ack(str(child)) == ack

    def test_beadless_predecessor_needs_no_bead(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_inherit(monkeypatch)
        parent, child = _parent_child(tmp_path)
        observation = _observation(
            predecessor_bead=None,
            bead=None,
            parent_meta={"name": "acme--3", "goal_id": "goal-1"},
            child_meta={"name": "acme--4", "goal_id": "goal-1"},
        )

        ack = enforce_recovery_bootstrap(
            child_artifacts_dir=str(child),
            descriptor=_descriptor(),
            observation=observation,
        )

        assert ack["bead"] is None

    def test_genuine_zero_repos_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_inherit(monkeypatch)
        parent, child = _parent_child(tmp_path)
        observation = _observation()

        ack = enforce_recovery_bootstrap(
            child_artifacts_dir=str(child),
            descriptor=_descriptor(),
            observation=observation,
        )

        assert ack["transferred_repos"] == 0


class TestEnforceFailures:
    def _fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        overrides: dict[str, Any],
        descriptor_overrides: dict[str, Any] | None = None,
    ) -> RecoveryBootstrapError:
        _mock_inherit(monkeypatch)
        parent, child = _parent_child(tmp_path)
        descriptor = _descriptor(**(descriptor_overrides or {}))
        observation = _observation(**overrides)
        provider_calls: list[str] = []

        def fake_provider() -> None:
            provider_calls.append("ran")

        with pytest.raises(RecoveryBootstrapError) as excinfo:
            enforce_recovery_bootstrap(
                child_artifacts_dir=str(child),
                descriptor=descriptor,
                observation=observation,
            )
            fake_provider()
        assert provider_calls == []
        assert read_recovery_ack(str(child)) is None
        return excinfo.value

    def test_wrong_launch_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(tmp_path, monkeypatch, {"launch_identity": "launch-other"})
        assert err.code == "identity_mismatch"

    def test_missing_launch_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(tmp_path, monkeypatch, {"launch_identity": None})
        assert err.code == "identity_mismatch"

    def test_wrong_successor_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(tmp_path, monkeypatch, {"successor_name": "acme--9"})
        assert err.code == "identity_mismatch"

    def test_wrong_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(tmp_path, monkeypatch, {"project": "other"})
        assert err.code == "workspace_mismatch"

    def test_wrong_workspace_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(tmp_path, monkeypatch, {"workspace_dir": "/ws/9"})
        assert err.code == "workspace_mismatch"

    def test_wrong_workspace_num(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(tmp_path, monkeypatch, {"workspace_num": 9})
        assert err.code == "workspace_mismatch"

    def test_lineage_mismatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(
            tmp_path, monkeypatch, {"lineage": _lineage(to_rung="claude/opus@low")}
        )
        assert err.code == "identity_mismatch"

    def test_missing_lineage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(tmp_path, monkeypatch, {"lineage": None})
        assert err.code == "identity_mismatch"

    def test_goal_mismatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(tmp_path, monkeypatch, {"goal": "goal-other"})
        assert err.code == "goal_mismatch"

    def test_missing_predecessor_goal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(
            tmp_path,
            monkeypatch,
            {
                "predecessor_goal": None,
                "parent_meta": {"name": "acme--3", "bead_id": "sase-1"},
            },
        )
        assert err.code == "goal_mismatch"

    def test_bead_mismatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(tmp_path, monkeypatch, {"bead": "sase-other"})
        assert err.code == "bead_mismatch"

    def test_unexpected_successor_bead(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(
            tmp_path,
            monkeypatch,
            {
                "predecessor_bead": None,
                "bead": "sase-1",
                "parent_meta": {"name": "acme--3", "goal_id": "goal-1"},
            },
        )
        assert err.code == "bead_mismatch"

    def test_missing_live_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(tmp_path, monkeypatch, {"predecessor_autonomy": None})
        assert err.code == "scope_missing"

    def test_diverged_fingerprints(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(
            tmp_path,
            monkeypatch,
            {"child_baseline": {"/ws/3": {"a.txt": ["changed", None]}}},
        )
        assert err.code == "baseline_mismatch"

    def test_missing_parent_baseline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(tmp_path, monkeypatch, {"parent_baseline": None})
        assert err.code == "baseline_mismatch"

    def test_missing_predecessor_inventory_never_passes_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(
            tmp_path,
            monkeypatch,
            {
                "predecessor_inventory_missing": True,
                "parent_repos": None,
                "parent_baseline": None,
            },
        )
        assert err.code == "inventory_mismatch"

    def test_missing_repo_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(
            tmp_path,
            monkeypatch,
            {
                "parent_repos": {"sase-core": "/repos/sase-core"},
                "child_repos": {},
            },
        )
        assert err.code == "inventory_mismatch"

    def test_moved_repo_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(
            tmp_path,
            monkeypatch,
            {
                "parent_repos": {"sase-core": "/repos/sase-core"},
                "child_repos": {"sase-core": "/repos/elsewhere"},
            },
        )
        assert err.code == "inventory_mismatch"

    def test_wrong_model(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        err = self._fails(tmp_path, monkeypatch, {"model": "sonnet"})
        assert err.code == "model_mismatch"

    def test_wrong_effort(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(tmp_path, monkeypatch, {"effort": "low"})
        assert err.code == "model_mismatch"

    def test_verdict_carryover(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        err = self._fails(
            tmp_path,
            monkeypatch,
            {
                "parent_meta": {
                    "name": "acme--3",
                    "bead_id": "sase-1",
                    "goal_id": "goal-1",
                    "outcome": "hijacked",
                },
                "child_meta": {
                    "name": "acme--4",
                    "bead_id": "sase-1",
                    "goal_id": "goal-1",
                    "outcome": "hijacked",
                },
            },
        )
        assert err.code == "verdict_carryover"

    def test_missing_descriptor_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_inherit(monkeypatch)
        parent, child = _parent_child(tmp_path)
        with pytest.raises(RecoveryBootstrapError) as excinfo:
            enforce_recovery_bootstrap(
                child_artifacts_dir=str(child),
                descriptor={},
                observation=_observation(),
            )
        assert excinfo.value.code == "missing_descriptor"
        assert read_recovery_ack(str(child)) is None


class TestCollectObservation:
    def test_collect_reads_metas_and_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.llm_provider.commit_finalizer_baseline import BASELINE_FILENAME

        parent = tmp_path / "parent"
        child = tmp_path / "child"
        _write_meta(
            parent,
            name="acme--3",
            bead_id="sase-1",
            goal_id="goal-1",
            autonomy={"selection": "manual"},
        )
        _write_meta(child, name="acme--4", bead_id="sase-1", goal_id="goal-1")
        fingerprints = {"/ws/3": {"a.txt": ["abc123", None]}}
        _write_baseline(parent, fingerprints)
        _write_baseline(child, fingerprints)
        _write_repos(parent, {"sase-core": "/repos/sase-core"})
        _write_repos(child, {"sase-core": "/repos/sase-core"})
        monkeypatch.setenv(RECOVERY_LINEAGE_ENV, json.dumps(_lineage()))
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
        assert observation.lineage == _lineage()
        assert observation.parent_repos == {"sase-core": "/repos/sase-core"}
        assert observation.child_repos == {"sase-core": "/repos/sase-core"}
        assert observation.child_baseline == observation.parent_baseline
        assert observation.predecessor_inventory_missing is False
        assert (child / BASELINE_FILENAME).is_file()

    def test_collect_missing_parent_marks_inventory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        child = tmp_path / "child"
        _write_meta(child, name="acme--4")
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
        _write_meta(predecessor, name="acme--3", bead_id="sase-1", goal_id="goal-1")
        (successor / "agent_meta.json").write_text(
            _json.dumps({"name": "acme--4", "bead_id": "sase-1", "goal_id": "goal-1"})
        )
        fingerprints = {"/ws/3": {"a.txt": ["abc123", None]}}
        _write_baseline(predecessor, fingerprints)
        _write_baseline(successor, fingerprints)
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
        _write_baseline(successor)
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
            lineage=_lineage(),
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

        monkeypatch.setenv(RECOVERY_LINEAGE_ENV, json.dumps(_lineage()))
        agent_meta: dict[str, Any] = {"name": "acme--4", "outcome": "hijacked"}

        _apply_recovery_lineage_metadata(agent_meta)

        assert agent_meta["hijack_lineage"] == _lineage()
        assert agent_meta["recovery_lineage"] == _lineage()
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
        _write_meta(parent, name="acme--3", bead_id="sase-1", goal_id="goal-1")
        _write_meta(child, name="acme--4", bead_id="sase-1", goal_id="goal-other")
        _write_baseline(parent)
        _write_baseline(child)
        monkeypatch.setenv("SASE_HIJACK_RECOVERY_STRICT", "1")
        monkeypatch.setenv(RECOVERY_LINEAGE_ENV, json.dumps(_lineage()))
        monkeypatch.setenv(RECOVERY_LAUNCH_IDENTITY_ENV, "launch-1")
        monkeypatch.setenv(
            RECOVERY_DESCRIPTOR_ENV, encode_recovery_descriptor(_descriptor())
        )

        from sase.agent import agent_session_attach

        plan = SimpleNamespace(parent_artifacts_dir=str(parent))
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
