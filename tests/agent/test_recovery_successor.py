"""Strict recovery successor preparation and mandatory inheritance.

Covers phase ``strict_successor``: the recovery successor seam in
:mod:`sase.agent.hijack.recovery_successor` (workspace pair validation,
lineage transport, mandatory goal/bead/baseline/repository/permission
inheritance, verdict non-carryover, ack rollback) plus the strict
follow-up workspace handling in :mod:`sase.turns.followup` and the strict
recovery boot path in :mod:`sase.axe.run_agent_runner_bootstrap`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.detached_child import AgentSessionAttachDirective
from sase.agent.hijack import (
    _recovery_successor_common as recovery_common,
    _recovery_successor_launch as recovery_launch,
)
from sase.agent.hijack.recovery_successor import (
    RECOVERY_ACK_FILENAME,
    RECOVERY_LINEAGE_ENV,
    RECOVERY_STRICT_ENV,
    RecoveryInheritanceError,
    decode_recovery_lineage,
    prepare_recovery_successor,
    read_recovery_ack,
    require_recovery_inheritance,
    rollback_recovery_preparation,
    spawn_recovery_successor,
    write_recovery_ack,
)
from sase.agent.launch_types import AgentLaunchResult


def _lineage(**overrides: Any) -> dict[str, str]:
    payload = {
        "hijack_id": "hij-1",
        "from_rung": "@l2",
        "to_rung": "@l1",
        "predecessor": "acme--3",
    }
    payload.update(overrides)
    return payload


def _inheritance_kwargs(**overrides: Any) -> dict[str, Any]:
    from sase.autonomy.record import resolve_selection

    predecessor = resolve_selection("manual", source="inherited", surface="launch")
    kwargs: dict[str, Any] = {
        "predecessor_goal": "goal-1",
        "successor_goal": "goal-1",
        "predecessor_bead": "sase-1qz.6.1.3",
        "successor_bead": "sase-1qz.6.1.3",
        "baseline_inherited": True,
        "baseline_diagnostics": [],
        "predecessor_repo_count": 1,
        "transferred_repo_count": 1,
        "repo_diagnostics": [],
        "predecessor_autonomy": predecessor,
        "predecessor_name": "acme--3",
        "explicit_autonomy_selection": None,
        "parent_meta": {"name": "acme--3", "outcome": "hijacked"},
        "child_meta": {"name": "acme--4"},
    }
    kwargs.update(overrides)
    return kwargs


class TestRecoveryLineage:
    def test_round_trips_through_encode_and_decode(self) -> None:
        lineage = recovery_common.normalize_recovery_lineage(_lineage())

        assert (
            decode_recovery_lineage(recovery_common.encode_recovery_lineage(lineage))
            == lineage
        )
        assert lineage.as_dict() == _lineage()

    def test_missing_fields_raise(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="hijack_id"):
            recovery_common.normalize_recovery_lineage(_lineage(hijack_id=""))

        with pytest.raises(RecoveryInheritanceError, match="predecessor"):
            recovery_common.normalize_recovery_lineage({"hijack_id": "h"})

    def test_missing_payload_raises(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match=RECOVERY_LINEAGE_ENV):
            decode_recovery_lineage(None)

    def test_malformed_payload_raises(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="not valid JSON"):
            decode_recovery_lineage("{oops")

    def test_child_env_carries_lineage_and_strict_boot(self) -> None:
        env = recovery_launch._recovery_child_env(_lineage())

        assert json.loads(env[RECOVERY_LINEAGE_ENV]) == _lineage()
        assert env[RECOVERY_STRICT_ENV] == "1"


class TestRecoveryWorkspacePair:
    def test_valid_pair_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "sase.running_field.get_workspace_directory_for_num",
            lambda num, project_name, clean=False: ("/ws/3", None),
        )
        recovery_launch._validate_recovery_workspace_pair(
            project_name="proj", workspace_num=3, workspace_dir="/ws/3"
        )

    def test_unresolvable_canonical_dir_keeps_positivity_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(
            num: int, project_name: str, clean: bool = False
        ) -> tuple[str, None]:
            raise RuntimeError("no running field here")

        monkeypatch.setattr(
            "sase.running_field.get_workspace_directory_for_num", _raise
        )
        recovery_launch._validate_recovery_workspace_pair(
            project_name="proj", workspace_num=3, workspace_dir="/ws/3"
        )

    @pytest.mark.parametrize("num", [0, -1, True, "3", None])
    def test_non_positive_numbers_raise(self, num: object) -> None:
        with pytest.raises(RecoveryInheritanceError, match="positive workspace"):
            recovery_launch._validate_recovery_workspace_pair(
                project_name="proj", workspace_num=num, workspace_dir="/ws/3"
            )

    def test_empty_directory_raises(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="workspace directory"):
            recovery_launch._validate_recovery_workspace_pair(
                project_name="proj", workspace_num=3, workspace_dir="  "
            )

    def test_metadata_mismatch_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "sase.running_field.get_workspace_directory_for_num",
            lambda num, project_name, clean=False: ("/ws/other", None),
        )
        with pytest.raises(RecoveryInheritanceError, match="mismatch"):
            recovery_launch._validate_recovery_workspace_pair(
                project_name="proj", workspace_num=3, workspace_dir="/ws/3"
            )


class TestRequireRecoveryInheritance:
    def test_success_returns_observable_ack(self) -> None:
        ack = require_recovery_inheritance(**_inheritance_kwargs())

        assert ack["goal"] == "goal-1"
        assert ack["bead"] == "sase-1qz.6.1.3"
        assert ack["baseline_inherited"] is True
        assert ack["transferred_repos"] == 1
        assert isinstance(ack["permission"], dict) and ack["permission"]

    def test_missing_predecessor_goal_raises(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="bound goal"):
            require_recovery_inheritance(**_inheritance_kwargs(predecessor_goal=None))

    def test_goal_mismatch_raises(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="same goal"):
            require_recovery_inheritance(**_inheritance_kwargs(successor_goal="goal-2"))

    def test_bead_mismatch_raises(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="bead claim"):
            require_recovery_inheritance(
                **_inheritance_kwargs(successor_bead="sase-other")
            )

    def test_beadless_predecessor_needs_no_bead(self) -> None:
        ack = require_recovery_inheritance(
            **_inheritance_kwargs(predecessor_bead=None, successor_bead=None)
        )
        assert ack["bead"] is None

    def test_unexpected_successor_bead_raises(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="never held"):
            require_recovery_inheritance(
                **_inheritance_kwargs(
                    predecessor_bead=None, successor_bead="sase-1qz.6.1.3"
                )
            )

    def test_fresh_baseline_fallback_raises(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="finalizer baseline"):
            require_recovery_inheritance(
                **_inheritance_kwargs(baseline_inherited=False)
            )

    def test_baseline_diagnostics_raise(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="finalizer baseline"):
            require_recovery_inheritance(
                **_inheritance_kwargs(baseline_diagnostics=["repo X unavailable"])
            )

    def test_partial_repo_transfer_raises(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="opened-repository"):
            require_recovery_inheritance(
                **_inheritance_kwargs(transferred_repo_count=0)
            )

    def test_repo_diagnostics_raise(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="opened-repository"):
            require_recovery_inheritance(
                **_inheritance_kwargs(repo_diagnostics=["audit failed for linked"])
            )

    def test_zero_repos_transfers_vacuously(self) -> None:
        ack = require_recovery_inheritance(
            **_inheritance_kwargs(predecessor_repo_count=0, transferred_repo_count=0)
        )
        assert ack["transferred_repos"] == 0

    def test_missing_predecessor_permission_record_fails_closed(self) -> None:
        # An unreadable predecessor must not let the successor adopt a wider
        # ambient policy, even when the prompt carries an explicit %auto.
        with pytest.raises(RecoveryInheritanceError, match="live permission record"):
            require_recovery_inheritance(
                **_inheritance_kwargs(
                    predecessor_autonomy=None,
                    explicit_autonomy_selection="manual",
                )
            )

    def test_widening_refusal_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "sase.autonomy.record.autonomy_inherit_record",
            lambda *args, **kwargs: {
                "status": "refused",
                "record": {"selection": "manual"},
                "reason": "explicit selection widens the predecessor",
            },
        )
        with pytest.raises(RecoveryInheritanceError, match="refused"):
            require_recovery_inheritance(**_inheritance_kwargs())

    def test_copied_verdicts_raise(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="must not copy"):
            require_recovery_inheritance(
                **_inheritance_kwargs(
                    child_meta={"name": "acme--4", "outcome": "hijacked"}
                )
            )


class TestVerdictCarryover:
    def test_clean_child_passes(self) -> None:
        recovery_common.ensure_no_verdict_carryover(
            parent_meta={"name": "acme--3", "outcome": "hijacked"},
            child_meta={"name": "acme--4", "recovery_lineage": _lineage()},
        )

    def test_missing_metas_pass(self) -> None:
        recovery_common.ensure_no_verdict_carryover(parent_meta=None, child_meta=None)

    @pytest.mark.parametrize("key", ["outcome", "receipts", "declarations"])
    def test_copied_keys_raise(self, key: str) -> None:
        with pytest.raises(RecoveryInheritanceError, match="must not copy"):
            recovery_common.ensure_no_verdict_carryover(
                parent_meta={"name": "acme--3", key: "hijacked"},
                child_meta={"name": "acme--4", key: "hijacked"},
            )


class TestRecoveryAckRoundTrip:
    def test_write_and_read_ack(self, tmp_path: Path) -> None:
        ack = require_recovery_inheritance(**_inheritance_kwargs())

        ack_path = write_recovery_ack(str(tmp_path), ack)

        assert Path(ack_path).name == RECOVERY_ACK_FILENAME
        assert read_recovery_ack(str(tmp_path)) == ack

    def test_missing_ack_reads_none(self, tmp_path: Path) -> None:
        assert read_recovery_ack(str(tmp_path / "absent")) is None

    def test_rollback_removes_staged_ack(self, tmp_path: Path) -> None:
        write_recovery_ack(str(tmp_path), {"schema_version": 1})

        assert rollback_recovery_preparation(artifacts_dir=str(tmp_path)) is True
        assert read_recovery_ack(str(tmp_path)) is None

    def test_rollback_without_ack_is_quiet(self, tmp_path: Path) -> None:
        assert rollback_recovery_preparation(artifacts_dir=str(tmp_path)) is False
        assert rollback_recovery_preparation(artifacts_dir=None) is False


def _fake_plan(**overrides: Any) -> Any:
    from sase.agent._agent_session_attach_types import AgentSessionAttachLaunchPlan

    defaults: dict[str, Any] = {
        "parent_arg": "acme",
        "suffix_arg": "@",
        "parent_name": "acme--3",
        "parent_base": "acme",
        "parent_timestamp": "20260812120000",
        "parent_artifacts_dir": "/tmp/acme",
        "role_suffix": "--4",
        "agent_name": "acme--4",
        "agent_session_role": "root",
        "parent_agent_session_member_name": "acme--3",
        "parent_agent_session_role_suffix": "--3",
        "parent_needs_rename": False,
        "parent_project_name": "proj",
    }
    defaults.update(overrides)
    return AgentSessionAttachLaunchPlan(**defaults)


def _fake_result(**overrides: Any) -> AgentLaunchResult:
    defaults: dict[str, Any] = {
        "pid": 4242,
        "workspace_num": 3,
        "workspace_dir": "/ws/3",
        "output_path": "/tmp/acme--4.txt",
        "agent_name": "acme--4",
    }
    defaults.update(overrides)
    return AgentLaunchResult(**defaults)


class TestPrepareRecoverySuccessor:
    def test_resolves_exact_member_with_strict_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "sase.running_field.get_workspace_directory_for_num",
            lambda num, project_name, clean=False: ("/ws/3", None),
        )
        plan = _fake_plan()
        seen: dict[str, Any] = {}

        def fake_resolve(directive: Any, *, project_name: str) -> Any:
            seen["directive"] = directive
            seen["project_name"] = project_name
            return plan

        directive = AgentSessionAttachDirective(parent="acme", suffix="@")
        resolved, env = prepare_recovery_successor(
            directive,
            project_name="proj",
            prompt="continue",
            workspace_dir="/ws/3",
            workspace_num=3,
            transfer_from_pid=111,
            lineage=_lineage(),
            resolve_plan=fake_resolve,
        )

        assert resolved.agent_name == plan.agent_name
        assert resolved.predecessor_artifacts_dir == plan.parent_artifacts_dir
        assert resolved.predecessor_name == "acme--3"
        assert seen["directive"] is directive
        assert json.loads(env[RECOVERY_LINEAGE_ENV]) == _lineage()
        assert env[RECOVERY_STRICT_ENV] == "1"

    def test_invalid_pair_raises_before_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "sase.running_field.get_workspace_directory_for_num",
            lambda num, project_name, clean=False: ("/ws/3", None),
        )
        calls: list[Any] = []

        def fake_resolve(directive: Any, **kwargs: Any) -> Any:
            calls.append(directive)
            return _fake_plan()

        with pytest.raises(RecoveryInheritanceError, match="positive workspace"):
            prepare_recovery_successor(
                AgentSessionAttachDirective(parent="acme", suffix="@"),
                project_name="proj",
                prompt="continue",
                workspace_dir="/ws/3",
                workspace_num=0,
                transfer_from_pid=111,
                lineage=_lineage(),
                resolve_plan=fake_resolve,
            )
        assert calls == []

    def test_hijacked_member_is_predecessor_even_when_attached_to_root(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "sase.running_field.get_workspace_directory_for_num",
            lambda num, project_name, clean=False: ("/ws/3", None),
        )
        monkeypatch.setattr(
            "sase.agent.hijack.ledger.load_record",
            lambda _hijack_id: {"artifacts_dir": "/tmp/hijacked"},
        )
        plan = _fake_plan(parent_name="acme--0", parent_artifacts_dir="/tmp/root")
        resolved, _ = prepare_recovery_successor(
            AgentSessionAttachDirective(parent="acme", suffix="@"),
            project_name="proj",
            prompt="continue",
            workspace_dir="/ws/3",
            workspace_num=3,
            transfer_from_pid=111,
            lineage=_lineage(),
            resolve_plan=lambda *args, **kwargs: plan,
        )
        assert resolved.parent_artifacts_dir == "/tmp/root"
        assert resolved.predecessor_artifacts_dir == "/tmp/hijacked"
        assert resolved.predecessor_name == "acme--3"

    def test_bad_lineage_raises_before_resolution(self) -> None:
        with pytest.raises(RecoveryInheritanceError, match="lineage"):
            prepare_recovery_successor(
                AgentSessionAttachDirective(parent="acme", suffix="@"),
                project_name="proj",
                prompt="continue",
                workspace_dir="/ws/3",
                workspace_num=3,
                transfer_from_pid=111,
                lineage={"hijack_id": "hij-1"},
                resolve_plan=lambda *args, **kwargs: _fake_plan(),
            )


class TestSpawnRecoverySuccessor:
    def test_spawn_uses_resolved_member_and_same_pair(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "sase.running_field.get_workspace_directory_for_num",
            lambda num, project_name, clean=False: ("/ws/3", None),
        )
        plan = _fake_plan()
        captured: dict[str, Any] = {}

        def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
            captured.update(kwargs)
            return _fake_result(timestamp=kwargs["timestamp"])

        result = spawn_recovery_successor(
            AgentSessionAttachDirective(parent="acme", suffix="@"),
            project_name="proj",
            prompt="continue",
            workspace_dir="/ws/3",
            workspace_num=3,
            transfer_from_pid=111,
            lineage=_lineage(),
            spawn_fn=fake_spawn,
            resolve_plan=lambda *args, **kwargs: plan,
        )

        assert result.agent_name == "acme--4"
        assert captured["workspace_num"] == 3
        assert captured["workspace_dir"] == "/ws/3"
        assert captured["retry_transfer_from_pid"] == 111
        assert captured["cl_name"] == "acme--4"
        assert json.loads(captured["extra_env"][RECOVERY_LINEAGE_ENV]) == _lineage()
        assert captured["extra_env"][RECOVERY_STRICT_ENV] == "1"

    def test_spawn_never_falls_back_on_invalid_pair(self) -> None:
        calls: list[Any] = []

        def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
            calls.append(kwargs)
            return _fake_result(timestamp=kwargs["timestamp"])

        with pytest.raises(RecoveryInheritanceError, match="positive workspace"):
            spawn_recovery_successor(
                AgentSessionAttachDirective(parent="acme", suffix="@"),
                project_name="proj",
                prompt="continue",
                workspace_dir="/ws/3",
                workspace_num=-2,
                transfer_from_pid=111,
                lineage=_lineage(),
                spawn_fn=fake_spawn,
                resolve_plan=lambda *args, **kwargs: _fake_plan(),
            )
        assert calls == []


class TestStrictRecoveryBootstrap:
    def _patch_inherit(
        self, monkeypatch: pytest.MonkeyPatch, *, result: bool
    ) -> dict[str, Any]:
        from sase.agent import agent_session_attach
        from sase.agent._agent_session_attach_types import (
            AgentSessionAttachLaunchPlan,
        )

        plan = AgentSessionAttachLaunchPlan(
            parent_arg="acme",
            suffix_arg="@",
            parent_name="acme--3",
            parent_base="acme",
            parent_timestamp="20260812120000",
            parent_artifacts_dir="/tmp/parent",
            role_suffix="--4",
            agent_name="acme--4",
            agent_session_role="root",
            parent_agent_session_member_name="acme--3",
            parent_agent_session_role_suffix="--3",
            parent_needs_rename=False,
            parent_project_name="proj",
            parent_is_running=False,
            parent_workspace_dir="/ws/3",
            parent_workspace_num=3,
            host_composed=True,
        )
        monkeypatch.setattr(
            agent_session_attach,
            "load_agent_session_attach_plan_from_env",
            lambda env=None: plan,
        )
        calls: dict[str, Any] = {"fallback": 0}
        import sase.llm_provider.commit_finalizer_baseline as baseline
        import sase.llm_provider.commit_finalizer_inheritance as inheritance

        monkeypatch.setattr(
            inheritance,
            "inherit_commit_finalizer_responsibility",
            lambda **kwargs: result,
        )

        def _fallback(project_dir: str, artifacts_dir: str) -> None:
            calls["fallback"] += 1

        monkeypatch.setattr(baseline, "capture_dirty_baseline", _fallback)
        return calls

    def test_strict_inheritance_skips_fresh_baseline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_runner_bootstrap import (
            _capture_commit_finalizer_baseline,
        )

        calls = self._patch_inherit(monkeypatch, result=True)

        assert (
            _capture_commit_finalizer_baseline(
                str(tmp_path),
                workspace_dir="/ws/3",
                workspace_num=3,
                project_name="proj",
                strict_recovery=True,
            )
            is True
        )
        assert calls["fallback"] == 0

    def test_strict_inheritance_failure_never_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_runner_bootstrap import (
            _capture_commit_finalizer_baseline,
        )

        calls = self._patch_inherit(monkeypatch, result=False)

        with pytest.raises(RecoveryInheritanceError, match="must not replace"):
            _capture_commit_finalizer_baseline(
                str(tmp_path),
                workspace_dir="/ws/3",
                workspace_num=3,
                project_name="proj",
                strict_recovery=True,
            )
        assert calls["fallback"] == 0

    def test_partial_repo_diagnostics_fail_strict_boot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_runner_bootstrap import (
            _capture_commit_finalizer_baseline,
        )
        from sase.llm_provider.commit_finalizer_inheritance import (
            INHERITANCE_DIAGNOSTICS_FILENAME,
        )

        calls = self._patch_inherit(monkeypatch, result=True)
        (tmp_path / INHERITANCE_DIAGNOSTICS_FILENAME).write_text(
            json.dumps({"diagnostics": ["repo linked:checkout unavailable"]}),
            encoding="utf-8",
        )

        with pytest.raises(RecoveryInheritanceError, match="opened-repository"):
            _capture_commit_finalizer_baseline(
                str(tmp_path),
                workspace_dir="/ws/3",
                workspace_num=3,
                project_name="proj",
                strict_recovery=True,
            )
        assert calls["fallback"] == 0

    def test_strict_boot_without_plan_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.agent import agent_session_attach
        from sase.axe.run_agent_runner_bootstrap import (
            _capture_commit_finalizer_baseline,
        )

        monkeypatch.setattr(
            agent_session_attach,
            "load_agent_session_attach_plan_from_env",
            lambda env=None: None,
        )

        with pytest.raises(RecoveryInheritanceError, match="attach plan"):
            _capture_commit_finalizer_baseline(
                str(tmp_path),
                workspace_dir="/ws/3",
                workspace_num=3,
                project_name="proj",
                strict_recovery=True,
            )


class TestRecoveryLineageMetadata:
    def test_lineage_env_lands_in_agent_meta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_directive_metadata_build import (
            _apply_recovery_lineage_metadata,
        )

        monkeypatch.setenv(
            RECOVERY_LINEAGE_ENV,
            recovery_common.encode_recovery_lineage(_lineage()),
        )
        agent_meta: dict[str, Any] = {
            "name": "acme--4",
            "outcome": "hijacked",
            "receipts": ["r1"],
        }

        _apply_recovery_lineage_metadata(agent_meta)

        assert agent_meta["hijack_lineage"] == _lineage()
        assert agent_meta["recovery_lineage"] == _lineage()
        assert "outcome" not in agent_meta
        assert "receipts" not in agent_meta

    def test_absent_lineage_leaves_meta_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_directive_metadata_build import (
            _apply_recovery_lineage_metadata,
        )

        monkeypatch.delenv(RECOVERY_LINEAGE_ENV, raising=False)
        agent_meta: dict[str, Any] = {"name": "acme--4"}

        _apply_recovery_lineage_metadata(agent_meta)

        assert agent_meta == {"name": "acme--4"}
