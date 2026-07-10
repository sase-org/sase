"""Tests for ``sase memory init`` planning and memory validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.amd.constants import PROVIDER_SHIM_CONTENT, PROVIDER_SHIM_FILES
from sase.main import init_memory_handler
from sase.main.init_memory.inventory import unreferenced_memory_files
from sase.main.init_memory_handler import plan_init_memory
from sase.main.init_registry import iter_init_command_specs
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_handler,
    run_memory,
    write,
)


@pytest.mark.parametrize(
    "local_config",
    [
        None,
        "memory:\n  enabled: false\nlinked_repos:\n  - malformed\n",
        'amd_h1_title: "Legacy title is not an opt-in"\n',
    ],
)
def test_unmanaged_project_does_not_manage_memory_or_root_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local_config: str | None,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    config_path = project_root / "sase.yml"
    if local_config is None:
        config_path.unlink()
    else:
        write(config_path, local_config)
    # A merged/global opt-in must not authorize project writes.
    write(config_dir / "sase.yml", "memory:\n  enabled: true\n")
    agents_content = "# Custom Project Instructions\n\nDo not replace this.\n"
    memory_content = "---\ntype: long\nparent: memory/missing.md\n---\n# Existing\n"
    write(project_root / "AGENTS.md", agents_content)
    write(project_root / "memory" / "existing.md", memory_content)

    plan = plan_memory()

    project_actions = tuple(
        action for action in plan.actions if action.path.is_relative_to(project_root)
    )
    assert plan.blockers == ()
    assert {action.path for action in project_actions} == {
        project_root / filename for filename in PROVIDER_SHIM_FILES
    }
    assert project_root / "AGENTS.md" not in {action.path for action in project_actions}

    assert run_memory() == 0
    assert (project_root / "AGENTS.md").read_text(encoding="utf-8") == agents_content
    assert (project_root / "memory" / "existing.md").read_text(
        encoding="utf-8"
    ) == memory_content
    assert not (project_root / "memory" / "sase.md").exists()
    for filename in PROVIDER_SHIM_FILES:
        assert (project_root / filename).read_text(encoding="utf-8") == agents_content


@pytest.mark.parametrize(
    "config_text, expected_error",
    [
        ("- not\n- a mapping\n", "expected a YAML mapping"),
        ("memory: null\n", "memory must be a mapping"),
        ("memory: []\n", "memory must be a mapping"),
        ('memory:\n  enabled: "yes"\n', "memory.enabled must be a boolean"),
        ("memory:\n  enabled: 1\n", "memory.enabled must be a boolean"),
    ],
)
def test_invalid_project_memory_opt_in_blocks_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_text: str,
    expected_error: str,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(project_root / "sase.yml", config_text)

    plan = plan_memory()

    assert plan.actions == ()
    assert any(expected_error in blocker for blocker in plan.blockers)
    assert run_memory() == 1
    assert not (project_root / "memory").exists()
    assert not (project_root / "AGENTS.md").exists()
    assert not (home_root / "memory").exists()


def test_unmanaged_project_copies_root_and_nested_agents_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    nested = project_root / "demos" / "tapes"
    standalone = project_root / "docs"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(project_root / "sase.yml", "memory:\n  enabled: false\n")
    root_content = "# Root\n\nRoot bytes stay exact.\n"
    nested_content = "# Nested\n\nNested bytes stay exact.\n"
    standalone_content = "# Standalone Claude instructions\n"
    write(project_root / "AGENTS.md", root_content)
    write(nested / "AGENTS.md", nested_content)
    write(standalone / "CLAUDE.md", standalone_content)

    assert run_memory() == 0

    for filename in PROVIDER_SHIM_FILES:
        assert (project_root / filename).read_text(encoding="utf-8") == root_content
        assert (nested / filename).read_text(encoding="utf-8") == nested_content
    assert (standalone / "CLAUDE.md").read_text(encoding="utf-8") == (
        standalone_content
    )
    for filename in set(PROVIDER_SHIM_FILES) - {"CLAUDE.md"}:
        assert not (standalone / filename).exists()
    assert not (project_root / "memory").exists()
    assert plan_memory().actions == ()


def test_memory_plan_missing_tree_reports_create_actions_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    plan = plan_memory()

    assert {action.operation for action in plan.actions} == {"create"}
    assert project_root / "memory" / "sase.md" in {
        action.path for action in plan.actions
    }
    assert project_root / "AGENTS.md" in {action.path for action in plan.actions}
    assert not (project_root / "memory").exists()
    assert not (home_root / "memory").exists()


def test_memory_plan_non_project_reports_home_only_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        project_is_vcs=False,
    )
    write(
        project_root / "sase.yml",
        """
linked_repos:
  - name: core
    path: ../sase-core
""",
    )

    plan = plan_memory()
    action_paths = {action.path for action in plan.actions}

    assert plan.blockers == ()
    assert home_root / "memory" / "sase.md" in action_paths
    assert home_root / "AGENTS.md" in action_paths
    assert project_root / "memory" / "sase.md" not in action_paths
    assert project_root / "AGENTS.md" not in action_paths
    assert not (project_root / "memory").exists()
    assert not (home_root / "memory").exists()


def test_memory_check_missing_tree_reports_drift_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    assert run_memory(check=True) == 1

    assert not (project_root / "memory").exists()
    assert not (home_root / "memory").exists()
    out = capsys.readouterr().out
    assert "SASE initialization check" in out
    assert "Needs attention:" in out
    assert "init memory" in out


def test_memory_plan_identical_generated_memory_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    assert run_memory() == 0

    plan = plan_memory()

    assert plan.actions == ()
    assert plan.blockers == ()
    assert "current" in plan.summary


def test_memory_check_current_generated_memory_exits_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    assert run_memory() == 0
    capsys.readouterr()

    assert run_memory(check=True) == 0

    out = capsys.readouterr().out
    assert "SASE is initialized. No init subcommands need to run." in out
    assert "Checked: memory." in out


def test_memory_plan_stale_provider_shim_reports_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    assert run_memory() == 0
    (project_root / "CLAUDE.md").write_text("old instructions\n", encoding="utf-8")

    plan = plan_memory()

    assert {(action.operation, action.path) for action in plan.actions} == {
        ("overwrite", project_root / "CLAUDE.md")
    }


def test_memory_plan_stale_home_provider_shim_reports_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    assert run_memory() == 0
    (home_root / "CLAUDE.md").write_text(PROVIDER_SHIM_CONTENT, encoding="utf-8")

    plan = plan_memory()

    assert {(action.operation, action.path) for action in plan.actions} == {
        ("overwrite", home_root / "CLAUDE.md")
    }


def test_memory_plan_creates_nested_agent_doc_provider_shims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    nested = project_root / "demos" / "tapes"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    assert run_memory() == 0
    write(nested / "AGENTS.md", "# Tape Instructions\n\nUse vhs for tapes.\n")

    plan = plan_memory()

    assert plan.blockers == ()
    assert {(action.operation, action.path) for action in plan.actions} == {
        ("create", nested / filename) for filename in PROVIDER_SHIM_FILES
    }


def test_memory_apply_creates_nested_agent_doc_provider_shims_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    nested = project_root / "demos" / "tapes"
    agents_content = "# Tape Instructions\n\nUse vhs for tapes.\n"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    assert run_memory() == 0
    write(nested / "AGENTS.md", agents_content)

    assert run_memory() == 0

    for filename in PROVIDER_SHIM_FILES:
        assert (nested / filename).read_text(encoding="utf-8") == agents_content
    assert plan_memory().actions == ()


def test_memory_plan_prunes_ignored_nested_agent_docs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    assert run_memory() == 0
    write(project_root / ".sase" / "AGENTS.md", "# Ignored\n")
    write(project_root / "node_modules" / "pkg" / "AGENTS.md", "# Ignored\n")

    plan = plan_memory()

    assert plan.actions == ()
    assert not (project_root / ".sase" / "CLAUDE.md").exists()
    assert not (project_root / "node_modules" / "pkg" / "CLAUDE.md").exists()


def test_memory_plan_preserves_existing_user_agents_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    (project_root / "sase.yml").unlink()
    write(
        project_root / "AGENTS.md",
        "# Custom Instructions\n\n@memory/sase.md\n",
    )

    plan = plan_memory()

    assert project_root / "AGENTS.md" not in {action.path for action in plan.actions}
    assert (
        (project_root / "AGENTS.md")
        .read_text(encoding="utf-8")
        .startswith("# Custom Instructions")
    )


def test_memory_plan_invalid_linked_repo_config_returns_blocker_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(
        project_root / "sase.yml",
        """
memory:
  enabled: true
linked_repos:
  - name: core
    path: ../sase-core
""",
    )

    plan = plan_memory()

    assert plan.actions == ()
    assert any("cannot generate project memory" in blocker for blocker in plan.blockers)
    assert not (project_root / "memory").exists()


def test_memory_check_blockers_render_through_shared_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(
        project_root / "sase.yml",
        """
memory:
  enabled: true
linked_repos:
  - name: core
    path: ../sase-core
""",
    )

    assert run_memory(check=True) == 1

    captured = capsys.readouterr()
    assert "Blockers:" in captured.out
    assert "cannot generate project memory" in captured.out
    assert captured.err == ""
    assert not (project_root / "memory").exists()


def test_memory_reference_validation_uses_rendered_overlay(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    write(root / "AGENTS.md", "@memory/generated.md\n")
    write(root / "memory" / "detail.md", "# Detail\n")

    unreferenced = unreferenced_memory_files(
        root,
        overlay={
            root / "memory" / "generated.md": "@memory/detail.md\n",
        },
    )

    assert unreferenced == ()


def test_memory_plan_uses_amd_agents_overlay_when_project_is_opted_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(
        project_root / "sase.yml",
        'memory:\n  enabled: true\namd_h1_title: "Managed Instructions"\n',
    )
    write(project_root / "AGENTS.md", "# Stale Instructions\n")
    write(
        project_root / "memory" / "detail.md",
        "---\ntype: long\nparent: AGENTS.md\n---\n# Detail\n",
    )

    plan = plan_memory()

    assert plan.blockers == ()
    assert ("overwrite", project_root / "AGENTS.md") in {
        (action.operation, action.path) for action in plan.actions
    }
    assert ("update", project_root / "memory" / "detail.md") in {
        (action.operation, action.path) for action in plan.actions
    }


def test_memory_plan_repairs_unreferenced_long_memory_without_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    # Enabled project memory with no ``amd_h1_title`` derives a stable title.
    write(
        project_root / "sase.yml",
        "memory:\n  enabled: true\nsdd:\n  version_controlled: true\n",
    )
    write(project_root / "AGENTS.md", "# Agent Instructions\n\n@memory/sase.md\n")
    write(
        project_root / "memory" / "sase.md",
        "---\ntype: short\nparent: AGENTS.md\n---\n# SASE\n",
    )
    write(
        project_root / "memory" / "cli_rules.md",
        "---\ntype: long\nparent: AGENTS.md\ndescription: CLI rules reference.\n---\n"
        "# CLI Rules\n",
    )

    plan = plan_memory()

    assert plan.blockers == ()
    assert ("overwrite", project_root / "AGENTS.md") in {
        (action.operation, action.path) for action in plan.actions
    }


def test_memory_apply_repairs_unreferenced_long_memory_without_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(
        project_root / "sase.yml",
        "memory:\n  enabled: true\nsdd:\n  version_controlled: true\n",
    )
    write(project_root / "AGENTS.md", "# Agent Instructions\n\n@memory/sase.md\n")
    write(
        project_root / "memory" / "cli_rules.md",
        "---\ntype: long\nparent: AGENTS.md\ndescription: CLI rules reference.\n---\n"
        "# CLI Rules\n",
    )

    assert run_memory() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    first_line = agents.splitlines()[0]
    assert first_line.startswith("# ")
    assert first_line.endswith(" - Agent Instructions")
    assert "## Tier 1 (short-term) Memory" in agents
    assert "## Tier 2 (long-term) Memory" in agents
    assert "**`memory/cli_rules.md`**" in agents
    # The repaired graph must validate cleanly on a follow-up run.
    assert run_memory() == 0
    assert plan_memory().actions == ()


def test_memory_plan_invalid_amd_title_still_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(
        project_root / "sase.yml",
        "memory:\n  enabled: true\namd_h1_title: 123\n",
    )
    write(
        project_root / "memory" / "cli_rules.md",
        "---\ntype: long\nparent: AGENTS.md\ndescription: CLI rules reference.\n---\n"
        "# CLI Rules\n",
    )

    plan = plan_memory()

    assert any("amd_h1_title must be a string" in blocker for blocker in plan.blockers)


def test_run_init_memory_returns_int_and_wrapper_raises_system_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    assert run_memory() == 0
    assert run_handler() == 0


def test_init_memory_registry_starts_with_memory() -> None:
    specs = {spec.name: spec for spec in iter_init_command_specs()}
    names = tuple(spec.name for spec in iter_init_command_specs())

    assert names == ("memory", "sdd", "skills")
    assert specs["memory"].plan is plan_init_memory
    assert specs["memory"].run is init_memory_handler.run_init_memory
