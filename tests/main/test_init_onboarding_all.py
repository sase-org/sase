"""Batch-flow tests for ``sase init --all``."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path

import pytest

from sase.dispatch._machine_init_review import MachineInitReviewStore
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import DiscoveryResult, MachineDiagnostic
from sase.main._init_chezmoi_deploy import defer_chezmoi_paths
from sase.main import init_onboarding
from sase.main.init_machine_handler import plan_init_machine
from sase.main.init_onboarding import run_init_onboarding, run_init_onboarding_all
from sase.main.init_plan import InitAction, InitPlan
from sase.main.init_project_scope import InitProjectInventory, InitProjectTarget
from sase.main.init_registry import InitCommandSpec
from tests.dispatch.machine_init_helpers import _candidate, _config, _pin
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
        return InitPlan(command="memory", label="Memory", summary="", actions=())

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


def test_batch_machine_offer_decline_prompts_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    targets = tuple(_target(tmp_path, name) for name in ("alpha", "beta", "gamma"))
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory(targets),
    )
    prompts: list[str] = []
    calls: list[str] = []
    spec = InitCommandSpec(
        name="machine",
        label="Machine",
        plan=lambda args: InitPlan(
            command="machine",
            label="Machine",
            summary="review machines",
            actions=(InitAction(Path("remote machine enrollment"), "validate"),),
        ),
        run=lambda args: calls.append(Path.cwd().name) or 0,
    )

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return "no"

    exit_code = run_init_onboarding_all(
        _args(all_projects=True),
        specs=(spec,),
        stdin=type("TTY", (StringIO,), {"isatty": lambda self: True})(),
        input_func=answer,
    )

    assert exit_code == 1
    assert calls == []
    assert len(prompts) == 1
    assert "sase machine init" in prompts[0]
    assert "sase init machine" not in prompts[0]
    assert "1 needs attention" in capsys.readouterr().out


def test_batch_machine_yes_runs_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    spec = InitCommandSpec(
        name="machine",
        label="Machine",
        plan=lambda args: InitPlan(
            command="machine",
            label="Machine",
            summary="review machines",
            actions=(InitAction(Path("remote machine enrollment"), "validate"),),
        ),
        run=lambda args: calls.append(Path.cwd().name) or 0,
    )

    exit_code = run_init_onboarding_all(
        _args(yes=True, all_projects=True),
        specs=(spec,),
        stdin=type("TTY", (StringIO,), {"isatty": lambda self: True})(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert calls == ["alpha"]


def test_batch_completed_machine_review_stays_quiet_across_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    targets = tuple(_target(tmp_path, name) for name in ("alpha", "beta", "gamma"))
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory(targets),
    )
    monkeypatch.setattr(
        "sase.dispatch.machine_init.load_dispatch_config",
        lambda: _config(),
    )
    review_store = MachineInitReviewStore(tmp_path / "review.json")
    assert (
        review_store.record_completed_review(
            (_candidate(endpoint="https://fleet.example.test", pin=_pin("a")),)
        )
        is None
    )
    diagnostic = MachineDiagnostic(
        code="tailnet_probe_timeout",
        severity="warning",
        message="tailnet health probe timed out",
    )
    calls = {"discover": 0}

    def discover_result(**_kwargs: object) -> DiscoveryResult:
        calls["discover"] += 1
        return DiscoveryResult(diagnostics=(diagnostic,))

    args = _args(all_projects=True)
    args._init_machine_service = MachineService(discover_result_fn=discover_result)
    args._init_review_store = review_store
    run_calls: list[str] = []

    exit_code = run_init_onboarding_all(
        args,
        specs=(
            InitCommandSpec(
                name="machine",
                label="Machine",
                plan=plan_init_machine,
                run=lambda args: run_calls.append(Path.cwd().name) or 0,
            ),
        ),
        stdin=type("TTY", (StringIO,), {"isatty": lambda self: True})(),
        input_func=_reject_prompt,
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert calls["discover"] == 0
    assert run_calls == []
    assert out.count("Project:") == 3
    assert "tailnet health probe timed out" not in out


def test_batch_machine_failure_consumes_offer_but_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    spec = InitCommandSpec(
        name="machine",
        label="Machine",
        plan=lambda args: InitPlan(
            command="machine",
            label="Machine",
            summary="review machines",
            actions=(InitAction(Path("remote machine enrollment"), "validate"),),
        ),
        run=lambda args: calls.append(Path.cwd().name) or 5,
    )

    exit_code = run_init_onboarding_all(
        _args(yes=True, all_projects=True),
        specs=(spec,),
        stdin=type("TTY", (StringIO,), {"isatty": lambda self: True})(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert calls == ["alpha"]
    out = capsys.readouterr().out
    assert "init machine failed with exit code 5" in out


def test_config_apply_refreshes_empty_machine_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "project"
    original.mkdir()
    monkeypatch.chdir(original)
    discovery_enabled = False
    calls: list[str] = []

    def config_run(args: argparse.Namespace) -> int:
        del args
        nonlocal discovery_enabled
        discovery_enabled = True
        calls.append("config")
        return 0

    def machine_plan(args: argparse.Namespace) -> InitPlan:
        del args
        return InitPlan(
            command="machine",
            label="Machine",
            summary="review machines",
            actions=(
                (InitAction(Path("remote machine enrollment"), "validate"),)
                if discovery_enabled
                else ()
            ),
        )

    specs = (
        InitCommandSpec(
            name="config",
            label="Config",
            plan=lambda args: InitPlan(
                command="config",
                label="Config",
                summary="configure identity",
                actions=(InitAction(Path(".sase/machine_name"), "update"),),
            ),
            run=config_run,
        ),
        InitCommandSpec(
            name="machine",
            label="Machine",
            plan=machine_plan,
            run=lambda args: calls.append("machine") or 0,
        ),
    )

    exit_code = run_init_onboarding(
        _args(yes=True),
        specs=specs,
        stdin=type("TTY", (StringIO,), {"isatty": lambda self: True})(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert calls == ["config", "machine"]


def test_batch_keyboard_interrupt_aborts_and_restores_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
        return InitPlan(command="memory", label="Memory", summary="", actions=())

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


def test_named_project_check_visits_only_selected_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    alpha = _target(tmp_path, "alpha", display_name="Alpha")
    beta = _target(tmp_path, "beta", display_name="Beta")
    gamma = _target(tmp_path, "gamma", display_name="Gamma")
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
        _args(check=True, project=["Gamma", "alpha"]),
        specs=(spec,),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert planned_from == ["gamma", "alpha"]
    out = capsys.readouterr().out
    assert "Project: Gamma" in out
    assert "Project: Alpha" in out
    assert "Project: Beta" not in out


def test_named_project_unknown_name_fails_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _target(tmp_path, "alpha")
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory((target,)),
    )

    exit_code = run_init_onboarding_all(
        _args(check=True, project=["missing"]),
        specs=(),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    err_out = capsys.readouterr().out
    assert "init --project:" in err_out
    assert "unknown or non-enabled project 'missing'" in err_out
    assert "alpha" in err_out


def _tty() -> StringIO:
    return type("TTY", (StringIO,), {"isatty": lambda self: True})()


def test_batch_service_yes_is_planned_and_applied_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    calls: list[str] = []

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        planned.append(Path.cwd().name)
        return InitPlan(
            command="service",
            label="Service",
            summary="install service host",
            actions=(InitAction(Path("sase.service"), "create"),),
        )

    spec = InitCommandSpec(
        name="service",
        label="Service",
        plan=plan,
        run=lambda args: calls.append(Path.cwd().name) or 0,
        scope="machine",
    )

    exit_code = run_init_onboarding_all(
        _args(yes=True, all_projects=True),
        specs=(spec,),
        stdin=_tty(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert planned == ["alpha"]
    assert calls == ["alpha"]


def test_batch_service_decline_prompts_once_and_records_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main.init_service_handler import decline_init_service
    from sase.service.platform import DECLINED_MARKER
    from sase.service.state import read_service_state

    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    targets = tuple(_target(tmp_path, name) for name in ("alpha", "beta", "gamma"))
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory(targets),
    )
    planned: list[str] = []
    declined: list[str] = []
    prompts: list[str] = []
    calls: list[str] = []

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        planned.append(Path.cwd().name)
        return InitPlan(
            command="service",
            label="Service",
            summary="install service host",
            actions=(InitAction(Path("sase.service"), "create"),),
        )

    def decline(args: argparse.Namespace) -> None:
        declined.append(Path.cwd().name)
        decline_init_service(args)

    spec = InitCommandSpec(
        name="service",
        label="Service",
        plan=plan,
        run=lambda args: calls.append(Path.cwd().name) or 0,
        scope="machine",
        decline=decline,
    )

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return "no"

    exit_code = run_init_onboarding_all(
        _args(all_projects=True),
        specs=(spec,),
        stdin=_tty(),
        input_func=answer,
    )

    assert exit_code == 1
    assert calls == []
    assert planned == ["alpha"]
    assert declined == ["alpha"]
    assert len(prompts) == 1
    assert "sase service init" in prompts[0]
    assert "sase init service" not in prompts[0]
    assert "1 needs attention" in capsys.readouterr().out
    snapshot = read_service_state(sase_home=tmp_path / ".sase")
    assert DECLINED_MARKER in snapshot.state.markers


def test_batch_service_check_plans_once_across_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        planned.append(Path.cwd().name)
        return InitPlan(
            command="service",
            label="Service",
            summary="install service host",
            actions=(InitAction(Path("sase.service"), "create"),),
        )

    spec = InitCommandSpec(
        name="service",
        label="Service",
        plan=plan,
        run=lambda args: 0,
        scope="machine",
    )

    exit_code = run_init_onboarding_all(
        _args(check=True, all_projects=True),
        specs=(spec,),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert planned == ["alpha"]


def test_batch_machine_and_service_scopes_are_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    targets = tuple(_target(tmp_path, name) for name in ("alpha", "beta"))
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory(targets),
    )
    calls: list[str] = []

    def _spec(name: str) -> InitCommandSpec:
        return InitCommandSpec(
            name=name,
            label=name.title(),
            plan=lambda args: InitPlan(
                command=name,
                label=name.title(),
                summary=f"offer {name}",
                actions=(InitAction(Path(name), "create"),),
            ),
            run=lambda args, n=name: calls.append(f"{n}:{Path.cwd().name}") or 0,
            scope="machine",
        )

    exit_code = run_init_onboarding_all(
        _args(yes=True, all_projects=True),
        specs=(_spec("machine"), _spec("service")),
        stdin=_tty(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert calls == ["machine:alpha", "service:alpha"]
