"""Real registry coverage for a bead waiter's refreshed name claim."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import (
    NameCollisionError,
    claim_registered_name,
    lookup_registered_name,
    rebuild_name_registry,
    reserve_registered_clan_name,
    reserve_registered_name,
)
from sase.agent.names import _registry
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.axe.run_agent_runner_refresh import (
    RUNNER_CODE_REFRESHED_ENV,
    refresh_runner_code_after_wait,
)
from sase.axe.run_agent_wait_markers import record_wait_completed_at
from tests._agent_names_fixtures import make_agent
from tests._agent_names_extract_fixtures import mock_provider


def _configure_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )


def _extract(prompt: str, workspace: Path, artifacts: Path) -> object:
    from sase.axe.run_agent_directives import extract_directives_and_write_meta

    with (
        patch("sase.macro.process_macro_references", side_effect=lambda p, **kw: p),
        patch(
            "sase.llm_provider.registry.get_default_provider_name",
            return_value="test",
        ),
        patch("sase.llm_provider.registry.get_provider", return_value=mock_provider()),
        patch(
            "sase.llm_provider.registry.resolve_model_provider",
            return_value=("test", "test-model"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
    ):
        return extract_directives_and_write_meta(
            prompt,
            str(workspace),
            str(artifacts),
            workspace_num=7,
        )


def _registry_entry(home: Path, name: str) -> dict[str, object]:
    with patch.object(Path, "home", return_value=home):
        entry = lookup_registered_name(name)
    assert entry is not None
    return entry


def test_generated_bead_waiter_reconciles_registry_only_owner_after_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale registry owner must not displace this run's assigned identity."""
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home / ".sase"))
    _configure_identity(monkeypatch)
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv("SASE_AGENT_GENERATED_NAME", raising=False)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifacts = home / ".sase/projects/proj/artifacts/ace-run/20261029010000"
    artifacts.mkdir(parents=True)
    prompt = (
        "%clan(rc, tribe=research)\n"
        "%id(rc.assigned, bead=sase-12v)\n"
        "%wait(bead=sase-99.1)\nDo work"
    )
    prompt_file = tmp_path / "submitted-prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    from sase.agent.clan_membership import (
        AGENT_CLAN_FIELD,
        AGENT_CLAN_GENERATION_FIELD,
        CLAN_MEMBERSHIP_ENV,
        ClanMembershipPlan,
        encode_clan_membership_plan,
    )

    with patch.object(Path, "home", return_value=home):
        clan_dir = home / ".sase/projects/proj/artifacts/ace-run/20261028000000"
        clan_dir.mkdir(parents=True)
        reserve_registered_clan_name("rc", "20261028000000", clan_dir)
        reserve_registered_name("rc.assigned", artifacts)
        monkeypatch.setenv("SASE_AGENT_PLANNED_NAME", "rc.assigned")
        monkeypatch.setenv("SASE_AGENT_GENERATED_NAME", "1")
        monkeypatch.setenv(
            CLAN_MEMBERSHIP_ENV,
            encode_clan_membership_plan(
                ClanMembershipPlan(clan_name="rc", generation="20261028000000")
            ),
        )
        first = _extract(prompt, workspace, artifacts)

        assert first.name == "rc.assigned"
        assert "SASE_AGENT_GENERATED_NAME" not in os.environ
        assert CLAN_MEMBERSHIP_ENV not in os.environ
        meta_path = artifacts / "agent_meta.json"
        first_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        first_meta["wait_completed_at"] = (
            datetime.now(UTC) - timedelta(hours=41)
        ).isoformat()
        wait_completed_at = record_wait_completed_at(
            str(artifacts), first_meta, wait_release_source="runner_fallback"
        )
        assert json.loads(meta_path.read_text(encoding="utf-8"))[
            "wait_completed_at"
        ] == (wait_completed_at)

        # Leave behind a registry-only owner as if the durable index was read
        # from an older snapshot. The wake replay must rebuild from the real
        # artifact before claiming this name again.
        stale_owner = (
            home / ".sase/projects/proj/artifacts/ace-run/20261028010000-missing"
        )
        claim_registered_name("rc.assigned", stale_owner, replace_existing=True)
        raw_registry = _registry._read_registry(_registry._registry_path())
        assert raw_registry is not None
        assert any(
            entry.get("artifacts_dir") == str(stale_owner)
            for entry in raw_registry["entries"].values()
        ), raw_registry["entries"]

        exec_env: dict[str, str] = {}

        def capture_exec(*_args: object) -> None:
            exec_env.update(os.environ)

        with (
            patch(
                "sase.axe.run_agent_runner_refresh.runner_code_identity",
                return_value="b" * 40,
            ),
            patch(
                "sase.axe.run_agent_runner_refresh.os.execv",
                side_effect=capture_exec,
            ),
        ):
            refresh_runner_code_after_wait(
                "a" * 40,
                blocking_wait_occurred=True,
                killed=False,
                prompt_file=str(prompt_file),
                submitted_prompt=prompt,
                agent_name="rc.assigned",
                artifacts_dir=str(artifacts),
            )

        assert RUNNER_CODE_REFRESHED_ENV in exec_env
        assert "SASE_AGENT_PLANNED_NAME" not in exec_env
        assert "SASE_AGENT_GENERATED_NAME" not in exec_env
        refresh_env = dict(exec_env)

        # The refreshed directive claim must perform the production freshness
        # proof and rebuild the stale owner away before its idempotent claim.
        with (
            patch.dict(os.environ, refresh_env, clear=True),
            patch.object(
                _registry,
                "rebuild_name_registry",
                wraps=_registry.rebuild_name_registry,
            ) as rebuild,
        ):
            second = _extract(prompt, workspace, artifacts)
        rebuild.assert_called()

        assert second.name == first.name
        assert second.meta[AGENT_CLAN_FIELD] == first.meta[AGENT_CLAN_FIELD]
        assert (
            second.meta[AGENT_CLAN_GENERATION_FIELD]
            == first.meta[AGENT_CLAN_GENERATION_FIELD]
        )
        assert second.meta["bead_id"] == "sase-12v"
        assert second.meta["wait_for_beads"] == ["sase-99.1"]
        assert second.meta["workspace_num"] == 7
        assert second.meta["wait_completed_at"] == wait_completed_at
        entry = _registry_entry(home, "rc.assigned")
        assert entry["reservation_kind"] == "claimed"
        assert entry["artifacts_dir"] == str(artifacts)
        assert not entry.get("collision_owners")

        # A ready/replay signal cannot refresh the same process a second time;
        # the durable wait stamp also short-circuits the dependency barrier.
        from sase.axe.run_agent_wait import wait_for_dependencies

        with patch(
            "sase.axe.run_agent_wait.resolve_initial_wait_release",
            side_effect=AssertionError("completed wait barrier was re-run"),
        ):
            assert (
                wait_for_dependencies(
                    [],
                    str(artifacts),
                    "",
                    "20261029010000",
                    second.meta,
                )
                is False
            )

        # A refreshed process proceeds from the recovered extraction to one
        # workflow launch. Its completed wait stamp keeps the barrier from
        # resolving dependencies again.
        from sase.axe import run_agent_runner as runner
        from sase.axe.run_agent_runner_bootstrap import RunnerBootstrap
        from sase.axe.run_agent_runner_state import RunnerRunState

        refreshed_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        bootstrap = RunnerBootstrap(
            info=second,
            agent_meta=refreshed_meta,
            retry_handoff=None,
            deferred_workspace=False,
            has_dependency_wait=True,
            has_wait=True,
        )
        state = RunnerRunState(
            cl_name="feature",
            project_file=str(tmp_path / "proj.sase"),
            prompt_file=str(prompt_file),
            output_path=str(tmp_path / "agent.log"),
            workflow_name="ace(run)-20261029_010000",
            timestamp="261029_010000",
            update_target="",
            is_home_mode=False,
            workspace_dir=str(workspace),
            workspace_num=7,
            project_name="proj",
            artifacts_timestamp="20261029010000",
            artifacts_dir=str(artifacts),
            prompt=prompt,
            submitted_prompt=prompt,
            agent_name=second.name,
            agent_model=second.model,
            agent_llm_provider=second.llm_provider,
            agent_vcs_provider=second.vcs_provider,
            agent_hidden=second.hidden,
        )
        with (
            patch.dict(os.environ, refresh_env, clear=True),
            patch.object(runner, "bootstrap_agent_run", return_value=bootstrap),
            patch.object(runner, "detect_repeat_stop", return_value=None),
            patch.object(
                runner,
                "expand_deferred_launch_macros",
                side_effect=lambda p, *_a, **_k: p,
            ),
            patch.object(runner, "wait_for_runner_slot", return_value="started"),
            patch.object(runner, "record_run_started_at"),
            patch.object(runner, "_bump_spawn_telemetry"),
            patch.object(runner, "launch_agent_run") as launch,
            patch(
                "sase.axe.run_agent_runner_refresh.runner_code_identity",
                return_value="b" * 40,
            ),
            patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
        ):
            runner._run_agent(state)

        launch.assert_called_once_with(state, bootstrap)
        execv.assert_not_called()
        assert state.agent_name == first.name


def test_generated_waiter_refresh_refuses_a_live_foreign_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rebuild must retain a genuine different owner as a collision."""
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home / ".sase"))
    _configure_identity(monkeypatch)
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifacts = home / ".sase/projects/proj/artifacts/ace-run/20261029010000"
    artifacts.mkdir(parents=True)
    prompt = "%id(assigned, bead=sase-12v)\n%wait(bead=sase-99.1)\nDo work"
    prompt_file = tmp_path / "submitted-prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")

    with patch.object(Path, "home", return_value=home):
        reserve_registered_name("assigned", artifacts)
        monkeypatch.setenv("SASE_AGENT_PLANNED_NAME", "assigned")
        monkeypatch.setenv("SASE_AGENT_GENERATED_NAME", "1")
        first = _extract(prompt, workspace, artifacts)
        assert first.name == "assigned"

        foreign = make_agent(
            home,
            "proj",
            "20261028010000",
            "assigned",
            pid=os.getpid(),
        )
        rebuilt = rebuild_name_registry()
        entry_before = rebuilt["entries"]["assigned"]
        assert entry_before["artifacts_dir"] in {str(artifacts), str(foreign)}
        assert entry_before.get("collision_owners")

        exec_env: dict[str, str] = {}

        def capture_exec(*_args: object) -> None:
            exec_env.update(os.environ)

        with (
            patch(
                "sase.axe.run_agent_runner_refresh.runner_code_identity",
                return_value="b" * 40,
            ),
            patch(
                "sase.axe.run_agent_runner_refresh.os.execv",
                side_effect=capture_exec,
            ),
        ):
            refresh_runner_code_after_wait(
                "a" * 40,
                blocking_wait_occurred=True,
                killed=False,
                prompt_file=str(prompt_file),
                submitted_prompt=prompt,
                agent_name="assigned",
                artifacts_dir=str(artifacts),
            )

        with patch.dict(os.environ, exec_env, clear=True):
            with pytest.raises(NameCollisionError):
                _extract(prompt, workspace, artifacts)

        assert json.loads((artifacts / "agent_meta.json").read_text())["name"] == (
            "assigned"
        )
        entry_after = _registry_entry(home, "assigned")
        assert entry_after["artifacts_dir"] in {str(artifacts), str(foreign)}
        assert entry_after.get("collision_owners")


def test_waiter_without_source_update_launches_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unchanged source identity crosses the wait and launches once."""
    from sase.axe import run_agent_runner as runner
    from sase.axe.run_agent_runner_bootstrap import RunnerBootstrap
    from sase.axe.run_agent_runner_state import RunnerRunState

    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home / ".sase"))
    _configure_identity(monkeypatch)
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifacts = home / ".sase/projects/proj/artifacts/ace-run/20261029010000"
    artifacts.mkdir(parents=True)
    prompt = "%id(assigned, bead=sase-12v)\n%wait(bead=sase-99.1)\nDo work"
    prompt_file = tmp_path / "submitted-prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")

    with patch.object(Path, "home", return_value=home):
        reserve_registered_name("assigned", artifacts)
        monkeypatch.setenv("SASE_AGENT_PLANNED_NAME", "assigned")
        monkeypatch.setenv("SASE_AGENT_GENERATED_NAME", "1")
        info = _extract(prompt, workspace, artifacts)
        agent_meta = json.loads((artifacts / "agent_meta.json").read_text())
        agent_meta["wait_completed_at"] = (
            datetime.now(UTC) - timedelta(hours=41)
        ).isoformat()
        record_wait_completed_at(str(artifacts), agent_meta)

        bootstrap = RunnerBootstrap(
            info=info,
            agent_meta=agent_meta,
            retry_handoff=None,
            deferred_workspace=False,
            has_dependency_wait=True,
            has_wait=True,
        )
        state = RunnerRunState(
            cl_name="feature",
            project_file=str(tmp_path / "proj.sase"),
            prompt_file=str(prompt_file),
            output_path=str(tmp_path / "agent.log"),
            workflow_name="ace(run)-20261029_010000",
            timestamp="261029_010000",
            update_target="",
            is_home_mode=False,
            workspace_dir=str(workspace),
            workspace_num=7,
            project_name="proj",
            artifacts_timestamp="20261029_010000",
            artifacts_dir=str(artifacts),
            prompt=prompt,
            submitted_prompt=prompt,
            agent_name=info.name,
            agent_model=info.model,
            agent_llm_provider=info.llm_provider,
            agent_vcs_provider=info.vcs_provider,
            agent_hidden=info.hidden,
        )

        with (
            patch.object(runner, "bootstrap_agent_run", return_value=bootstrap),
            patch.object(runner, "_wait_for_dependencies_phase", return_value=True),
            patch.object(runner, "detect_repeat_stop", return_value=None),
            patch.object(
                runner,
                "expand_deferred_launch_macros",
                side_effect=lambda p, *_a, **_k: p,
            ),
            patch.object(runner, "wait_for_runner_slot", return_value="started"),
            patch.object(runner, "record_run_started_at"),
            patch.object(runner, "_bump_spawn_telemetry"),
            patch.object(runner, "launch_agent_run") as launch,
            patch(
                "sase.axe.run_agent_runner_refresh.runner_code_identity",
                return_value=runner._STARTUP_CODE_IDENTITY,
            ),
            patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
        ):
            runner._run_agent(state)

        launch.assert_called_once_with(state, bootstrap)
        execv.assert_not_called()
        assert _registry_entry(home, "assigned")["artifacts_dir"] == str(artifacts)


def test_session_attach_payload_is_readable_across_a_wait_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The attach payload loader reads the same payload on both runner passes."""
    from sase.agent.agent_session_attach import (
        AgentSessionAttachLaunchPlan,
        load_agent_session_attach_plan_from_env,
    )
    from sase.agent.detached_child import agent_session_attach_env

    plan = AgentSessionAttachLaunchPlan(
        parent_arg="review",
        suffix_arg="reviewer",
        parent_name="foo--0",
        parent_base="foo",
        parent_timestamp="20261028000000",
        parent_artifacts_dir=str(tmp_path / "parent"),
        role_suffix="--reviewer",
        agent_name="foo--reviewer",
        agent_session_role="reviewer",
        parent_agent_session_member_name="foo--0",
        parent_agent_session_role_suffix="--0",
        parent_needs_rename=False,
        parent_project_name="proj",
        parent_is_running=True,
        parent_workspace_dir=str(tmp_path / "workspace"),
        parent_workspace_num=7,
    )
    payload = agent_session_attach_env(plan)
    with patch.dict(os.environ, payload, clear=False):
        before = load_agent_session_attach_plan_from_env()
        after = load_agent_session_attach_plan_from_env()

        assert before == plan
        assert after == plan
        assert (
            os.environ["SASE_AGENT_SESSION_ATTACH"]
            == payload["SASE_AGENT_SESSION_ATTACH"]
        )
