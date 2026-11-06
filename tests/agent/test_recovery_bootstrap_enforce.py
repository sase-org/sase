"""Descriptor round-trip and strict-boot enforcement for recovery bootstrap."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.hijack._recovery_successor_bootstrap_observation import (
    BootstrapObservation,
)
from sase.agent.hijack._recovery_successor_bootstrap_validation import (
    enforce_recovery_bootstrap,
)
from sase.agent.hijack._recovery_successor_common import (
    BOOTSTRAP_ACK_SCHEMA_VERSION,
    RecoveryBootstrapError,
)
from sase.agent.hijack._recovery_successor_descriptor import (
    decode_recovery_descriptor,
    encode_recovery_descriptor,
)
from sase.agent.hijack._recovery_successor_inheritance import read_recovery_ack
from tests.agent._recovery_bootstrap_shared import (
    descriptor as make_descriptor,
)
from tests.agent._recovery_bootstrap_shared import (
    lineage as make_lineage,
)
from tests.agent._recovery_bootstrap_shared import write_baseline, write_meta


def _parent_child(tmp_path: Path) -> tuple[Path, Path]:
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    write_meta(parent, name="acme--3", bead_id="sase-1", goal_id="goal-1")
    write_meta(child, name="acme--4", bead_id="sase-1", goal_id="goal-1")
    write_baseline(parent)
    write_baseline(child)
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
        "lineage": make_lineage(),
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
        descriptor = make_descriptor()

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
        descriptor = make_descriptor()
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
        assert ack["lineage"] == make_lineage()
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
            descriptor=make_descriptor(),
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
            descriptor=make_descriptor(),
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
        descriptor = make_descriptor(**(descriptor_overrides or {}))
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
            tmp_path, monkeypatch, {"lineage": make_lineage(to_rung="claude/opus@low")}
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
