"""Planner management tests for ``sase repo init``."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.main._repo_init_sidecars import plan_sidecar_actions
from sase.main.init_registry import iter_init_command_specs
from sase.main.repo_init_handler import plan_repo_init, run_repo_init
from sase.sdd._sidecar_init import SidecarInitSpec
from sase.sdd.store import SddStore
from tests.main._test_repo_init_plan_helpers import (
    make_plan_args,
    mark_plan_project,
)


def _mark_github_managed_project(tmp_path: Path) -> None:
    mark_plan_project(tmp_path)
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/acme/widget.git",
        ],
        cwd=tmp_path,
        check=True,
    )


def test_plan_non_project_reports_blocker(tmp_path: Path) -> None:
    plan = plan_repo_init(make_plan_args(tmp_path))

    assert plan.actions == ()
    assert plan.blockers
    assert "not a project directory" in plan.blockers[0]


@pytest.mark.parametrize(
    "config_text",
    [
        None,
        "is_sase_managed: false\n",
        "memory:\n  enabled: true\n",
    ],
)
def test_unmanaged_plan_skips_before_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_text: str | None,
) -> None:
    mark_plan_project(tmp_path, managed=False)
    if config_text is not None:
        config = tmp_path / "sase" / "sase.yml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(config_text, encoding="utf-8")
    provider_calls: list[Path] = []
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda root: provider_calls.append(root) or "local",
    )

    plan = plan_repo_init(make_plan_args(tmp_path))

    assert plan.actions == ()
    assert plan.blockers == ()
    assert "not SASE-managed" in plan.summary
    assert provider_calls == []
    assert not (tmp_path / ".sase").exists()


@pytest.mark.parametrize(
    "config_text, expected_error",
    [
        ('is_sase_managed: "yes"\n', "must be a boolean"),
        ("is_sase_managed: [\n", "failed to parse YAML"),
        ("- not\n- a mapping\n", "expected a YAML mapping"),
    ],
)
def test_invalid_management_config_blocks_before_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_text: str,
    expected_error: str,
) -> None:
    mark_plan_project(tmp_path, managed=False)
    (tmp_path / "sase.yml").write_text(config_text, encoding="utf-8")
    provider_calls: list[Path] = []
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda root: provider_calls.append(root) or "local",
    )

    plan = plan_repo_init(make_plan_args(tmp_path))

    assert plan.actions == ()
    assert any(expected_error in blocker for blocker in plan.blockers)
    assert provider_calls == []


def test_unmanaged_check_is_informative_and_successful(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mark_plan_project(tmp_path, managed=False)

    assert run_repo_init(make_plan_args(tmp_path, check=True)) == 0

    assert "not SASE-managed" in capsys.readouterr().out
    assert not (tmp_path / ".sase").exists()


def test_unmanaged_apply_skips_before_store_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mark_plan_project(tmp_path, managed=False)
    calls: list[Path] = []
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda root, _workspace: calls.append(root),
    )

    assert run_repo_init(make_plan_args(tmp_path)) == 0

    assert "not SASE-managed" in capsys.readouterr().out
    assert calls == []


def test_run_uses_materialized_path_and_updates_project_wiring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark_plan_project(tmp_path)
    sdd_dir = tmp_path / ".sase" / "sdd"
    store = SddStore("separate_repo", sdd_dir, sdd_dir, "github", "remote")
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda _path, _workspace_num, **_options: store,
    )

    assert run_repo_init(make_plan_args(tmp_path)) == 0
    assert (sdd_dir / "README.md").is_file()
    assert "      plans:\n" in (tmp_path / "sase" / "sase.yml").read_text(
        encoding="utf-8"
    )
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "/sase/repos/\n"


def test_plan_skips_agents_sidecar_without_a_resolvable_project_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark_plan_project(tmp_path)
    specs = (
        SidecarInitSpec(role="plans", description="Durable plans."),
        SidecarInitSpec(
            role="agents",
            visibility="private",
            description="Commit-associated agents.",
        ),
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda _root: None,
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root, **_kwargs: specs,
    )

    plan = plan_repo_init(make_plan_args(tmp_path))

    assert plan.blockers == ()
    details = {action.detail for action in plan.actions}
    assert any("plans sidecar repository" in detail for detail in details)
    assert not any("agents sidecar repository" in detail for detail in details)
    assert not any("agents sidecar README.md" in detail for detail in details)
    assert any(
        "skipped agents sidecar planning" in warning for warning in plan.warnings
    )


def test_materialized_sidecar_run_still_fails_without_a_project_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main._repo_init_sidecars import run_materialized_sidecars
    from sase.sdd.store import SddMaterializationError

    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda _root: None,
    )
    specs = (SidecarInitSpec(role="agents", description="Agents."),)

    with pytest.raises(SddMaterializationError, match="owning SASE project key"):
        run_materialized_sidecars(tmp_path, specs, frozenset())


def test_init_registry_uses_repo_runner() -> None:
    specs = {spec.name: spec for spec in iter_init_command_specs()}
    assert tuple(specs) == ("config", "machine", "memory", "repo", "service", "skills")
    assert specs["repo"].plan is plan_repo_init
    assert specs["repo"].run is run_repo_init


def test_missing_attachments_private_plans_warning_not_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing optional attachment store warns instead of blocking check."""
    specs = (
        SidecarInitSpec(
            role="attachments-private",
            repo="acme/widget--attachments-private",
            visibility="private",
        ),
    )
    missing_root = tmp_path / "attachments-private"
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.resolve_sidecar_clone_root",
        lambda _root, _role: missing_root,
    )
    monkeypatch.setattr(
        "sase.main._repo_init_sidecars.is_bare_sidecar_clone",
        lambda _root: False,
    )

    actions, warnings, requires_tty = plan_sidecar_actions(tmp_path, specs, frozenset())

    assert actions == []
    assert requires_tty is False
    assert any("attachments-private is not set up" in warning for warning in warnings)
    assert any("attachments stay local-only" in warning for warning in warnings)


def test_plan_new_project_previews_newly_declared_research_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A brand-new managed project previews research creation without writing."""
    _mark_github_managed_project(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda _root: "gh_acme__widget",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._primary_repo_visibility",
        lambda _root: None,
    )

    before = (tmp_path / "sase" / "sase.yml").read_bytes()

    plan = plan_repo_init(make_plan_args(tmp_path))

    assert any(
        action.detail == "create or connect the provider research sidecar repository"
        for action in plan.actions
    )
    assert plan.requires_tty is True
    assert (tmp_path / "sase" / "sase.yml").read_bytes() == before


def test_plan_upgrade_previews_research_declaration_and_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declaring research also previews its creation in the same plan."""
    _mark_github_managed_project(tmp_path)
    (tmp_path / "sase" / "sase.yml").write_text(
        """\
is_sase_managed: true
repos:
  sidecar:
    builtin:
      plans:
        auto_clone: true
        auto_sync: true
        ref:
          use: builtin@plan
      beads:
        auto_sync: true
      agents:
        description: Hidden sidecar that stores commit-associated sase agent data.
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda _root: "gh_acme__widget",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._primary_repo_visibility",
        lambda _root: None,
    )

    plan = plan_repo_init(make_plan_args(tmp_path))

    assert any(
        action.path.name == "sase.yml" and "research" in action.detail
        for action in plan.actions
    )
    assert any(
        action.detail == "create or connect the provider research sidecar repository"
        for action in plan.actions
    )
    assert plan.requires_tty is True
