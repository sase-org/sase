"""Batch-flow tests for ``sase init --all``."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path

import pytest

from sase.main._init_chezmoi_deploy import defer_chezmoi_paths
from sase.main.init_onboarding import run_init_onboarding_all
from sase.main.init_plan import InitAction, InitPlan
from sase.main.init_project_scope import InitProjectInventory, InitProjectTarget
from sase.main.init_registry import InitCommandSpec
from tests.main.init_onboarding_helpers import _args, _reject_prompt


def _target(
    tmp_path: Path,
    name: str,
    *,
    display_name: str | None = None,
    unavailable: str | None = None,
    warnings: tuple[str, ...] = (),
) -> InitProjectTarget:
    workspace = tmp_path / name
    workspace.mkdir()
    project_file = tmp_path / f"{name}.sase"
    project_file.write_text("NAME: test\n", encoding="utf-8")
    return InitProjectTarget(
        project_name=name,
        display_name=display_name or name,
        project_file=project_file,
        workspace_dir=workspace,
        warnings=warnings,
        unavailable_reason=unavailable,
    )


def test_batch_check_isolates_failures_and_restores_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import init_onboarding

    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    alpha = _target(tmp_path, "alpha", display_name="Alpha")
    beta = _target(tmp_path, "beta", display_name="Beta", warnings=("old record",))
    missing = _target(
        tmp_path,
        "missing",
        display_name="Missing",
        unavailable="primary workspace is unavailable: /gone",
    )
    gamma = _target(tmp_path, "gamma", display_name="Gamma")
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory((alpha, beta, missing, gamma)),
    )
    planned_from: list[str] = []

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        name = Path.cwd().name
        planned_from.append(name)
        if name == "gamma":
            raise RuntimeError("broken planner")
        actions = (InitAction(Path("AGENTS.md"), "update"),) if name == "beta" else ()
        return InitPlan(command="memory", label="Memory", summary="", actions=actions)

    spec = InitCommandSpec(name="memory", label="Memory", plan=plan, run=lambda a: 0)

    exit_code = run_init_onboarding_all(
        _args(check=True, all_projects=True),
        specs=(spec,),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert Path.cwd() == original
    assert planned_from == ["alpha", "beta", "gamma"]
    out = capsys.readouterr().out
    assert out.index("Project: Alpha") < out.index("Project: Beta")
    assert out.index("Project: Beta") < out.index("Project: Missing")
    assert out.index("Project: Missing") < out.index("Project: Gamma")
    assert "Project inventory warnings:" in out
    assert "broken planner" in out
    assert (
        "Initialization summary: 3 checked, 1 current, 1 needs attention, "
        "1 unavailable, 1 failed"
    ) in out
    assert "Traceback" not in out


def test_batch_task_type_registry_reflects_each_project_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A batch run must not leak one project's task-type registry into the next.

    Regression test for the stale process-wide config-token cache: before the
    fix, ``get_task_type_registry()`` inside ``plan`` served the *first*
    project's registry for every project after it, because a bare ``chdir``
    never invalidated ``current_config_token()``.
    """
    from sase.main import init_onboarding
    from sase.task_types.registry import (
        get_task_type_registry,
        reset_task_type_registry_cache,
    )

    def _target_with_task_type(name: str) -> InitProjectTarget:
        target = _target(tmp_path, name)
        sase_dir = target.workspace_dir / "sase"
        sase_dir.mkdir()
        (sase_dir / "sase.yml").write_text(
            f"""
bead:
  task_types:
    - schema_version: 1
      task_type: {name}_only
      label: {name.title()} Only
      summary: A project-local task type declared only in {name}'s workspace.
      when_to_use: File one when exercising {name}'s registry.
      triage:
        min_plus_ones: 1
""",
            encoding="utf-8",
        )
        return target

    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    alpha = _target_with_task_type("alpha")
    beta = _target_with_task_type("beta")
    gamma = _target_with_task_type("gamma")
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory((alpha, beta, gamma)),
    )

    reset_task_type_registry_cache()
    seen_slugs: dict[str, set[str]] = {}

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        name = Path.cwd().name
        seen_slugs[name] = set(get_task_type_registry().by_slug)
        return InitPlan(command="memory", label="Memory", summary="")

    spec = InitCommandSpec(name="memory", label="Memory", plan=plan, run=lambda a: 0)

    exit_code = run_init_onboarding_all(
        _args(check=True, all_projects=True),
        specs=(spec,),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert set(seen_slugs) == {"alpha", "beta", "gamma"}
    for name in ("alpha", "beta", "gamma"):
        others = {
            f"{other}_only" for other in ("alpha", "beta", "gamma") if other != name
        }
        assert f"{name}_only" in seen_slugs[name]
        assert not others & seen_slugs[name]


def test_batch_yes_continues_after_failure_and_deploys_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import init_onboarding

    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    targets = tuple(_target(tmp_path, name) for name in ("alpha", "beta", "gamma"))
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory(targets),
    )
    calls: list[str] = []
    deploys: list[tuple[Path, ...]] = []
    shared_path = tmp_path / "chezmoi" / "home" / "AGENTS.md"

    def run(args: argparse.Namespace) -> int:
        assert args.all is False
        assert args.enable_project_memory is False
        assert not hasattr(args, "_project_memory_opt_in_prepared")
        assert not hasattr(args, "_project_config_changed")
        name = Path.cwd().name
        calls.append(name)
        if name == "beta":
            return 7
        assert defer_chezmoi_paths((shared_path,)) is True
        return 0

    spec = InitCommandSpec(
        name="memory",
        label="Memory",
        plan=lambda args: InitPlan(
            command="memory",
            label="Memory",
            summary="",
            actions=(InitAction(Path("AGENTS.md"), "update"),),
        ),
        run=run,
    )

    def deploy(deferred):  # type: ignore[no-untyped-def]
        deploys.append(tuple(deferred.paths))
        return 0

    monkeypatch.setattr(init_onboarding, "deploy_deferred_chezmoi", deploy)

    args = _args(yes=True, all_projects=True)
    args._project_memory_opt_in_prepared = True
    args._project_config_changed = True
    exit_code = run_init_onboarding_all(
        args,
        specs=(spec,),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert Path.cwd() == original
    assert calls == ["alpha", "beta", "gamma"]
    assert deploys == [(shared_path, shared_path)]


def test_batch_interactive_decline_reports_remaining_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import init_onboarding

    target = _target(tmp_path, "alpha")
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory((target,)),
    )
    calls: list[str] = []
    spec = InitCommandSpec(
        name="memory",
        label="Memory",
        plan=lambda args: InitPlan(
            command="memory",
            label="Memory",
            summary="update memory",
            actions=(InitAction(Path("AGENTS.md"), "update"),),
        ),
        run=lambda args: calls.append("memory") or 0,
    )

    exit_code = run_init_onboarding_all(
        _args(all_projects=True),
        specs=(spec,),
        stdin=type("TTY", (StringIO,), {"isatty": lambda self: True})(),
        input_func=lambda prompt: "no",
    )

    assert exit_code == 1
    assert calls == []
    assert "1 needs attention" in capsys.readouterr().out


def test_batch_keyboard_interrupt_aborts_and_restores_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import init_onboarding

    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    targets = tuple(_target(tmp_path, name) for name in ("alpha", "beta", "gamma"))
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory(targets),
    )
    planned: list[str] = []
    deploy_called = False

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        name = Path.cwd().name
        planned.append(name)
        if name == "beta":
            raise KeyboardInterrupt
        return InitPlan(command="memory", label="Memory", summary="")

    def deploy(deferred):  # type: ignore[no-untyped-def]
        del deferred
        nonlocal deploy_called
        deploy_called = True
        return 0

    spec = InitCommandSpec(name="memory", label="Memory", plan=plan, run=lambda a: 0)
    monkeypatch.setattr(init_onboarding, "deploy_deferred_chezmoi", deploy)

    exit_code = run_init_onboarding_all(
        _args(check=True, all_projects=True),
        specs=(spec,),
        stdin=StringIO(),
    )

    assert exit_code == 1
    assert Path.cwd() == original
    assert planned == ["alpha", "beta"]
    assert deploy_called is False
    out = capsys.readouterr().out
    assert "cancelled; aborting" in out
    assert "Traceback" not in out


def test_batch_project_flag_filters_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import init_onboarding

    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    alpha = _target(tmp_path, "alpha")
    beta = _target(tmp_path, "beta")
    gamma = _target(tmp_path, "gamma")
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory((alpha, beta, gamma)),
    )
    planned_from: list[str] = []

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        planned_from.append(Path.cwd().name)
        return InitPlan(command="memory", label="Memory", summary="", actions=())

    spec = InitCommandSpec(name="memory", label="Memory", plan=plan, run=lambda a: 0)

    exit_code = run_init_onboarding_all(
        _args(check=True, project=["gamma", "alpha"]),
        specs=(spec,),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert planned_from == ["alpha", "gamma"]
    out = capsys.readouterr().out
    assert "Project: alpha" in out
    assert "Project: gamma" in out
    assert "Project: beta" not in out


def test_batch_project_flag_unknown_name_fails_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import init_onboarding

    target = _target(tmp_path, "alpha")
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory((target,)),
    )
    planned = False

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        nonlocal planned
        planned = True
        return InitPlan(command="memory", label="Memory", summary="", actions=())

    spec = InitCommandSpec(name="memory", label="Memory", plan=plan, run=lambda a: 0)

    exit_code = run_init_onboarding_all(
        _args(check=True, project=["missing"]),
        specs=(spec,),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert planned is False
    err = capsys.readouterr().out
    assert "unknown or non-enabled project 'missing'" in err
