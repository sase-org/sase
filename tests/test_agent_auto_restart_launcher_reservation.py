"""Launcher reservation handoff and parser-error identity regressions.

Covers the tale repair: owned planned-name recovery uses the real launch
guard, foreign ownership is preserved, races fail closed, invalid prompts
do not mutate reservations, failed spawn stays terminal, and parser
failures never become guessed month-keyed ledger identities.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent.auto_restart.healer import HealerTarget, heal_one
from tests._agent_auto_restart_healer_helpers import (
    healer_failed_row,  # noqa: F401
    healer_quiet_notifications,  # noqa: F401
    healer_tmp_home,  # noqa: F401
    ok_probe_result,
    ok_quiescence,
    relaunch_verdict,
)


def _launcher_target(failed_row: Path) -> HealerTarget:
    (failed_row / "agent_meta.json").write_text("{}\n", encoding="utf-8")
    return HealerTarget(
        artifacts_dir=failed_row,
        project="sase",
        agent_name=failed_row.name,
    )


def _reset_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.agent.names import reset_name_registry_caches_for_tests

    reset_name_registry_caches_for_tests()
    monkeypatch.setattr("sase.agent.names._registry._CACHE_PATH", None, raising=False)


def test_launcher_releases_owned_reservation_with_real_guard(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = tmp_home
    _reset_registry(monkeypatch)
    from sase.agent import launcher
    from sase.agent.auto_restart import healer_relaunch_claim
    from sase.agent.launch_validation import validate_launch_name_requests
    from sase.agent.names import (
        planned_registered_name_belongs_to_artifact,
        reserve_registered_name,
    )

    raw_prompt = "%id:bootstrap-agent\nResume the requested work.\n"
    (failed_row / "raw_prompt.md").write_text(raw_prompt, encoding="utf-8")
    target = _launcher_target(failed_row)

    reserve_registered_name("bootstrap-agent", failed_row)
    assert planned_registered_name_belongs_to_artifact("bootstrap-agent", failed_row)
    from sase.agent.launch_validation import AgentNameLaunchCollisionError

    with pytest.raises(AgentNameLaunchCollisionError):
        validate_launch_name_requests([raw_prompt])

    replacement_dir = failed_row.parent / "20261009T120100"
    launched: list[str] = []

    def fake_launch(prompt: str, *, extra_env, origin, source_surface):
        # Exercise the real guard: it must pass only after the healer
        # releases the failed row's own reservation.
        validate_launch_name_requests([prompt])
        assert origin == "generated"
        assert source_surface == "auto_restart"
        launched.append(prompt)
        return [SimpleNamespace(artifacts_dir=str(replacement_dir))]

    monkeypatch.setattr(
        healer_relaunch_claim, "launcher_project_cwd", lambda _p: tmp_home
    )
    monkeypatch.setattr(launcher, "launch_agents_from_cwd", fake_launch)

    outcome = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=ok_quiescence,
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
        plan_restart=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("launcher rows must not use name-based planning")
        ),
    )

    assert outcome.action == "relaunched", outcome.reason_text
    assert launched == [raw_prompt]
    assert outcome.launched_artifacts_dir == str(replacement_dir)
    from sase.agent.auto_restart import ledger as ledger_mod

    stored = ledger_mod.load_ledger_record(outcome.ledger_key)
    assert stored is not None
    assert stored.record.state == "launched"
    assert stored.record.planned_name == "bootstrap-agent"
    assert stored.record.launched_artifacts_dir == str(replacement_dir)
    recovery = json.loads((failed_row / "done.json").read_text())["recovery"]
    assert recovery["state"] == "relaunched"
    assert recovery["ledger_key"] == outcome.ledger_key
    # Failed artifacts and prompt survive; replacement mapping is recorded.
    assert (failed_row / "raw_prompt.md").is_file()
    assert (failed_row / "done.json").is_file()
    assert len(quiet_notifications["relaunch"]) == 1

    again = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=ok_quiescence,
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
    )
    assert again.action == "declined"
    assert len(launched) == 1


def test_launcher_preserves_foreign_reservation(
    tmp_home: Path,
    failed_row: Path,
    tmp_path: Path,
    quiet_notifications: dict[str, list],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = tmp_home
    _reset_registry(monkeypatch)
    from sase.agent import launcher
    from sase.agent.auto_restart import healer_relaunch_claim
    from sase.agent.names import (
        planned_registered_name_belongs_to_artifact,
        reserve_registered_name,
    )

    other_dir = tmp_path / "other" / "20261009T120000"
    other_dir.mkdir(parents=True)
    reserve_registered_name("foreign-agent", other_dir)

    raw_prompt = "%id:foreign-agent\nResume the requested work.\n"
    (failed_row / "raw_prompt.md").write_text(raw_prompt, encoding="utf-8")
    target = _launcher_target(failed_row)

    def _must_not_launch(*args, **kwargs):
        raise AssertionError("foreign-owned names must never launch")

    monkeypatch.setattr(
        healer_relaunch_claim, "launcher_project_cwd", lambda _p: tmp_home
    )
    monkeypatch.setattr(launcher, "launch_agents_from_cwd", _must_not_launch)

    outcome = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=ok_quiescence,
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
        plan_restart=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not plan")
        ),
    )

    assert outcome.action == "declined"
    assert outcome.reason == "execute_failed"
    # Foreign reservation is untouched.
    assert planned_registered_name_belongs_to_artifact("foreign-agent", other_dir)
    assert (failed_row / "done.json").is_file()


def test_launcher_ownership_race_fails_closed(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = tmp_home
    _ = quiet_notifications
    _reset_registry(monkeypatch)
    from sase.agent import launcher
    from sase.agent.auto_restart import healer_relaunch_claim
    from sase.agent.names import reserve_registered_name
    import sase.agent.names as names_mod

    raw_prompt = "%id:race-agent\nResume the requested work.\n"
    (failed_row / "raw_prompt.md").write_text(raw_prompt, encoding="utf-8")
    target = _launcher_target(failed_row)
    reserve_registered_name("race-agent", failed_row)

    real_belongs = names_mod.planned_registered_name_belongs_to_artifact
    calls: list[str] = []

    def _flaky(name: str, artifact_dir) -> bool:
        calls.append(name)
        if len(calls) == 1:
            return real_belongs(name, artifact_dir)
        return False

    monkeypatch.setattr(
        names_mod, "planned_registered_name_belongs_to_artifact", _flaky
    )
    monkeypatch.setattr(
        healer_relaunch_claim, "launcher_project_cwd", lambda _p: tmp_home
    )
    monkeypatch.setattr(
        launcher,
        "launch_agents_from_cwd",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("raced ownership must not launch")
        ),
    )

    outcome = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=ok_quiescence,
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
    )
    assert outcome.action == "declined"
    assert outcome.reason == "execute_failed"
    assert "changed owner" in outcome.reason_text


@pytest.mark.parametrize(
    ("prompt", "reason"),
    [
        (None, "launcher_prompt_missing"),
        (" \n\t", "launcher_prompt_empty"),
        ("first segment\n---\nsecond segment", "multi_segment"),
        ("%id:!forced-agent\nResume.\n", "launcher_force_reuse"),
    ],
)
def test_launcher_invalid_prompts_do_not_mutate_reservations(
    tmp_home: Path,
    failed_row: Path,
    prompt: str | None,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = tmp_home
    _reset_registry(monkeypatch)
    from sase.agent import launcher
    from sase.agent.auto_restart import healer_relaunch_claim
    from sase.agent.names import (
        planned_registered_name_belongs_to_artifact,
        reserve_registered_name,
    )

    (failed_row / "agent_meta.json").write_text("{}\n", encoding="utf-8")
    if prompt is not None:
        (failed_row / "raw_prompt.md").write_text(prompt, encoding="utf-8")
    elif (failed_row / "raw_prompt.md").exists():
        (failed_row / "raw_prompt.md").unlink()
    # Seed an owned reservation that invalid prompts must not touch.
    reserve_registered_name("bootstrap-agent", failed_row)
    target = HealerTarget(
        artifacts_dir=failed_row, project="sase", agent_name=failed_row.name
    )

    monkeypatch.setattr(
        healer_relaunch_claim,
        "launcher_project_cwd",
        lambda _p: (_ for _ in ()).throw(
            AssertionError("invalid prompts decline before project lookup")
        ),
    )
    monkeypatch.setattr(
        launcher,
        "launch_agents_from_cwd",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("invalid prompts must not launch")
        ),
    )

    outcome = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=ok_quiescence,
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
        plan_restart=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not plan")
        ),
    )
    assert outcome.action == "declined"
    assert outcome.reason == reason
    assert planned_registered_name_belongs_to_artifact("bootstrap-agent", failed_row)


def test_launcher_failed_spawn_stays_terminal(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = tmp_home
    _ = quiet_notifications
    _reset_registry(monkeypatch)
    from sase.agent import launcher
    from sase.agent.auto_restart import healer_relaunch_claim
    from sase.agent.names import reserve_registered_name

    raw_prompt = "%id:bootstrap-agent\nResume the requested work.\n"
    (failed_row / "raw_prompt.md").write_text(raw_prompt, encoding="utf-8")
    target = _launcher_target(failed_row)
    reserve_registered_name("bootstrap-agent", failed_row)

    calls: list[str] = []

    def _failing_launch(prompt: str, *, extra_env, origin, source_surface):
        calls.append(prompt)
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(
        healer_relaunch_claim, "launcher_project_cwd", lambda _p: tmp_home
    )
    monkeypatch.setattr(launcher, "launch_agents_from_cwd", _failing_launch)

    outcome = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=ok_quiescence,
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
    )
    assert outcome.action == "declined"
    assert outcome.reason == "execute_failed"
    assert "spawn failed" in outcome.reason_text
    assert len(calls) == 1

    again = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=ok_quiescence,
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
    )
    assert again.action == "declined"
    assert len(calls) == 1


def test_workspace_replacement_gets_different_slot_while_hold_remains(
    tmp_path: Path,
) -> None:
    from sase.running_field import claim_next_axe_workspace

    project_file = tmp_path / "demo.sase"
    project_file.write_text("# Test Project\n\nNAME: Demo\nSTATUS: Ready\n")
    first = claim_next_axe_workspace(str(project_file), "demo-flow", 11111)
    second = claim_next_axe_workspace(str(project_file), "demo-flow", 22222)
    assert first != second


def test_parser_error_does_not_become_month_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.core.agent_artifact_paths as artifact_paths
    from sase.agent.auto_restart import healer_targets, history

    projects_root = tmp_path / "projects"
    sharded = (
        projects_root
        / "gh_demo__repo"
        / "artifacts"
        / "ace-run"
        / "202611"
        / "12"
        / "20261112052956"
    )
    sharded.mkdir(parents=True)
    monkeypatch.setattr(artifact_paths, "sase_projects_dir", lambda: projects_root)

    def _boom(path, **kwargs):
        raise RuntimeError("parser unavailable")

    monkeypatch.setattr(artifact_paths, "parse_agent_artifact_path", _boom)
    with pytest.raises(RuntimeError):
        healer_targets._project_for_artifacts_dir(sharded)
    with pytest.raises(RuntimeError):
        history._project_for_done({}, sharded)

    # History enumeration skips the poisoned row instead of month-keying it.
    (sharded / "done.json").write_text(
        json.dumps({"outcome": "failed", "finished_at": 1762950000.0})
    )
    (sharded / "agent_meta.json").write_text(json.dumps({}))
    candidates = history.collect_failed_candidates(
        projects_root=projects_root,
        bundles_root=tmp_path / "bundles",
        workflows_root=tmp_path / "workflows",
    )
    assert all(str(c.artifacts_dir) != str(sharded) for c in candidates)


def test_project_helpers_cover_valid_none_and_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.core.agent_artifact_paths as artifact_paths
    from sase.agent.auto_restart import healer_targets, history

    projects_root = tmp_path / "projects"
    project = "gh_x__y"
    stamp = "20261112052956"
    sharded = (
        projects_root / project / "artifacts" / "ace-run" / "202611" / "12" / stamp
    )
    sharded.mkdir(parents=True)
    (sharded / "agent_meta.json").write_text(json.dumps({"name": "n"}))
    legacy = projects_root / project / "artifacts" / "ace-run" / stamp
    legacy.mkdir(parents=True)
    (legacy / "agent_meta.json").write_text(json.dumps({"name": "legacy"}))
    monkeypatch.setattr(artifact_paths, "sase_projects_dir", lambda: projects_root)

    assert healer_targets._project_for_artifacts_dir(sharded) == project
    assert healer_targets._project_for_artifacts_dir(legacy) == project
    assert history._project_for_done({}, sharded) == project
    assert history._project_for_done({}, legacy) == project
    assert history._project_for_done({"cl_name": "explicit"}, sharded) == "explicit"

    outside = tmp_path / "elsewhere" / "20261112052956"
    outside.mkdir(parents=True)
    monkeypatch.setattr(
        artifact_paths, "parse_agent_artifact_path", lambda *a, **k: None
    )
    # Positional fallback survives only when parsing returns None.
    assert healer_targets._project_for_artifacts_dir(outside) == outside.parents[1].name
