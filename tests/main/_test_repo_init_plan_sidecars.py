"""Planner sidecar tests for ``sase repo init``."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
import subprocess

import pytest
from rich.console import Console

from sase.main._repo_init_config import configured_sidecar_specs
from sase.main.init_preview import render_plan_diff
from sase.main.repo_init_handler import plan_repo_init
from sase.sdd._sidecar_init import SidecarInitSpec
from tests.main._test_repo_init_plan_helpers import (
    make_plan_args,
    mark_plan_project,
)


def test_plan_providerless_project_includes_store_config_and_ignore_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark_plan_project(tmp_path)
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: None,
    )

    plan = plan_repo_init(make_plan_args(tmp_path))

    assert plan.has_changes is True
    config_action = next(
        action for action in plan.actions if action.path.name == "sase.yml"
    )
    assert config_action.new_content is not None
    assert "    builtin:\n" in config_action.new_content
    assert "      plans:\n" in config_action.new_content
    assert "      beads:\n" in config_action.new_content
    assert "      agents:\n" in config_action.new_content
    assert "    custom:\n" in config_action.new_content
    assert "      research:\n" in config_action.new_content
    assert "plans, beads, research, and agents sidecars" in plan.summary
    assert any(action.path.name == ".gitignore" for action in plan.actions)
    assert any(
        action.path.is_relative_to(tmp_path / ".sase" / "sdd")
        for action in plan.actions
    )
    assert not (tmp_path / ".sase" / "sdd").exists()


def test_plan_github_reports_every_configured_sidecar_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark_plan_project(tmp_path)
    specs = (
        SidecarInitSpec(role="plans", description="Durable plans."),
        SidecarInitSpec(role="research", description="Durable research."),
        SidecarInitSpec(role="artifacts", description="Durable artifacts."),
        SidecarInitSpec(
            role="agents",
            visibility="private",
            description="Commit-associated agents.",
        ),
    )
    state_root = tmp_path / "state"
    monkeypatch.setenv("SASE_HOME", str(state_root))
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda _root: "gh_acme__widget",
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

    details = {action.detail for action in plan.actions}
    assert any("plans sidecar repository" in detail for detail in details)
    assert any("research sidecar repository" in detail for detail in details)
    assert any("artifacts sidecar repository" in detail for detail in details)
    agents_connection = next(
        action
        for action in plan.actions
        if "agents sidecar repository" in action.detail
    )
    assert "with private visibility" in agents_connection.detail
    assert "machine-level hidden path" in agents_connection.detail
    assert agents_connection.path == (
        state_root / "projects" / "gh_acme__widget" / "repos" / "agents"
    )
    assert any("plans sidecar README.md" in detail for detail in details)
    assert any("research sidecar README.md" in detail for detail in details)
    assert any("artifacts sidecar README.md" in detail for detail in details)
    agents_actions = [
        action
        for action in plan.actions
        if action.path.is_relative_to(agents_connection.path)
    ]
    assert {
        action.path.relative_to(agents_connection.path).as_posix()
        for action in agents_actions
    } == {
        ".",
        "README.md",
        "schema.json",
        "assets/agents-directory-map.png",
        "agents/.gitkeep",
        "families/.gitkeep",
        "sessions/.gitkeep",
        "users/.gitkeep",
    }
    assert all(
        not action.path.is_relative_to(tmp_path / "sase" / "repos" / "agents")
        for action in plan.actions
    )
    assert not (tmp_path / "sase" / "repos").exists()
    assert not state_root.exists()
    assert plan.requires_tty is True

    output = StringIO()
    render_plan_diff(Console(file=output, width=400, no_color=True), plan)
    rendered = output.getvalue()
    assert "with private visibility" in rendered
    assert str(agents_connection.path) in rendered
    assert "manifest.json" in rendered
    assert "agents/.gitkeep" in rendered


def test_plan_reports_asset_only_agents_guide_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark_plan_project(tmp_path)
    config = tmp_path / "sase" / "sase.yml"
    config.write_text(
        """\
is_sase_managed: true
repos:
  sidecar:
    builtin:
      plans:
        ref:
          use: builtin@plan
      beads: {}
      agents: {}
    custom:
      research: {}
""",
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text("/sase/repos/\n", encoding="utf-8")
    state_root = tmp_path / "state"
    agents_root = state_root / "projects" / "gh_acme__widget" / "repos" / "agents"
    (agents_root / ".git").mkdir(parents=True)
    (agents_root / "schema.json").write_text(
        (
            '{"authority":"owner-sharded","format":"sase-agents-sidecar",'
            '"relationship_schema_version":3,"schema_version":2}\n'
        ),
        encoding="utf-8",
    )
    for dirname in ("agents", "families", "sessions", "users"):
        (agents_root / dirname).mkdir()
        (agents_root / dirname / ".gitkeep").write_text("", encoding="utf-8")
    owner = agents_root / "users" / "alice" / "machines" / "athena"
    owner.mkdir(parents=True)
    (owner / "manifest.json").write_text("{}\n", encoding="utf-8")
    (agents_root / "README.md").write_text("# Derived\n", encoding="utf-8")
    monkeypatch.setenv("SASE_HOME", str(state_root))
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda _root: "gh_acme__widget",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root, **_kwargs: (SidecarInitSpec(role="agents"),),
    )

    plan = plan_repo_init(make_plan_args(tmp_path))

    agent_actions = [
        action for action in plan.actions if action.path.is_relative_to(agents_root)
    ]
    assert [
        action.path.relative_to(agents_root).as_posix() for action in agent_actions
    ] == ["assets/agents-directory-map.png"]
    assert all(action.path != config for action in plan.actions)
    assert plan.summary == "refresh sidecar guide files"
    assert (agents_root / "README.md").read_text(encoding="utf-8") == "# Derived\n"


def test_plan_does_not_materialize_recorded_lazy_sidecar_for_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark_plan_project(tmp_path)
    specs = (SidecarInitSpec(role="plans"), SidecarInitSpec(role="research"))
    plans_root = tmp_path / "sase" / "repos" / "plans"
    (plans_root / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._has_materialized_sidecar_store",
        lambda _root: True,
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._materialized_compatibility_roles",
        lambda _root: frozenset({"plans", "research"}),
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root, **_kwargs: specs,
    )

    plan = plan_repo_init(make_plan_args(tmp_path))

    assert all("research" not in str(action.path) for action in plan.actions)
    assert all(
        "research sidecar repository" not in action.detail for action in plan.actions
    )


def test_plan_reports_pending_bead_state_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark_plan_project(tmp_path)
    specs = (
        SidecarInitSpec(role="plans"),
        SidecarInitSpec(role="research"),
        SidecarInitSpec(role="beads"),
    )
    plans_root = tmp_path / "sase" / "repos" / "plans"
    (plans_root / ".git").mkdir(parents=True)
    (plans_root / "beads").mkdir()
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root, **_kwargs: specs,
    )

    plan = plan_repo_init(make_plan_args(tmp_path))

    adoption = [
        action
        for action in plan.actions
        if action.detail == "adopt bead state from the plans sidecar"
    ]
    assert len(adoption) == 1
    assert adoption[0].path == tmp_path / "sase" / "repos" / "beads"


def test_configured_sidecar_specs_preserve_pin_and_private_visibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    config = {
        "is_sase_managed": True,
        "repos": {
            "sidecar": {
                "builtin": {
                    "plans": {"auto_clone": True},
                    "agents": {
                        "repo": "acme/private-agents",
                        "visibility": "private",
                        "description": "Private commit-associated agents.",
                    },
                },
                "custom": {
                    "artifacts": {
                        "repo": "acme/shared-artifacts",
                        "visibility": "private",
                        "description": "Durable artifacts.",
                    }
                },
            }
        },
    }
    monkeypatch.setattr(
        "sase._linked_repo_config.resolution_config",
        lambda *rest: config,
    )
    monkeypatch.setattr(
        "sase._linked_repo_config.read_project_local_config",
        lambda *rest: config,
    )

    specs = configured_sidecar_specs(tmp_path)

    artifacts = next(spec for spec in specs if spec.role == "artifacts")
    agents = next(spec for spec in specs if spec.role == "agents")
    assert artifacts.repo == "acme/shared-artifacts"
    assert artifacts.remote_url == "git@github.com:acme/shared-artifacts.git"
    assert artifacts.visibility == "private"
    assert artifacts.description == "Durable artifacts."
    assert agents.repo == "acme/private-agents"
    assert agents.remote_url == "git@github.com:acme/private-agents.git"
    assert agents.visibility == "private"
    assert agents.description == "Private commit-associated agents."


def test_configured_sidecar_specs_suppress_disabled_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark_plan_project(tmp_path)
    config = {
        "is_sase_managed": True,
        "repos": {
            "sidecar": {
                "builtin": {
                    "plans": {"auto_clone": True},
                    "agents": {"disabled": True},
                },
                "custom": {"research": {}},
            }
        },
    }
    monkeypatch.setattr(
        "sase._linked_repo_config.resolution_config",
        lambda *rest: config,
    )
    monkeypatch.setattr(
        "sase._linked_repo_config.read_project_local_config",
        lambda *rest: config,
    )

    specs = configured_sidecar_specs(tmp_path)

    assert {spec.role for spec in specs} == {
        "plans",
        "research",
        "beads",
        "attachments",
        "attachments-private",
    }
