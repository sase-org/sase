"""Tests for managed AGENTS memory frontmatter and ordering behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.amd._agents_doc import parse_amd_agents_document
from sase.amd.init import plan_amd_memory_sync
from sase.memory.inventory_reachability import unreferenced_memory_files_for_init
from tests.main.init_memory_handler_helpers import (
    long_note,
    patch_standard_paths,
    plan_memory,
    run_handler,
    short_note,
    write,
)


def test_init_memory_orders_tier1_by_priority_then_path(
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
        'is_sase_managed: true\nmemory:\n  h1_title: "Managed Instructions"\n',
    )
    for stem in ("zeta", "alpha"):
        write(
            project_root / "sase" / "memory" / f"{stem}.md",
            f"---\ntype: core\nparent: AGENTS.md\npriority: 5\n---\n# {stem.title()}\n",
        )

    assert run_handler() == 0

    parsed = parse_amd_agents_document(
        (project_root / "AGENTS.md").read_text(encoding="utf-8")
    )
    assert parsed.short_memory_paths[:3] == (
        "sase/memory/alpha.md",
        "sase/memory/zeta.md",
        "sase/memory/sase.md",
    )


def test_plan_amd_memory_sync_keeps_path_order_without_priorities(
    tmp_path: Path,
) -> None:
    write(tmp_path / "sase.yml", 'memory:\n  h1_title: "Managed Instructions"\n')
    write(tmp_path / "sase" / "memory" / "zeta.md", short_note("# Zeta\n"))
    write(tmp_path / "sase" / "memory" / "alpha.md", short_note("# Alpha\n"))

    plan = plan_amd_memory_sync(tmp_path, generated_short_notes={})

    assert plan.blockers == ()
    assert plan.agents_content is not None
    parsed = parse_amd_agents_document(plan.agents_content)
    assert parsed.short_memory_paths == (
        "sase/memory/alpha.md",
        "sase/memory/zeta.md",
    )


def test_init_memory_rejects_invalid_memory_priority(
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
        'is_sase_managed: true\nmemory:\n  h1_title: "Managed Instructions"\n',
    )
    write(
        project_root / "sase" / "memory" / "bad.md",
        "---\ntype: core\nparent: AGENTS.md\npriority: true\n---\n# Bad\n",
    )

    assert run_handler() == 1
    err = capsys.readouterr().err
    assert "sase/memory/bad.md" in err
    assert "memory note priority must be a non-negative integer" in err


def test_init_memory_rejects_priority_on_reference_note(
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
        'is_sase_managed: true\nmemory:\n  h1_title: "Managed Instructions"\n',
    )
    write(
        project_root / "sase" / "memory" / "reference.md",
        "---\n"
        "type: reference\n"
        "parent: AGENTS.md\n"
        "priority: 5\n"
        "description: Reference.\n"
        "---\n"
        "# Reference\n",
    )

    assert run_handler() == 1
    err = capsys.readouterr().err
    assert "sase/memory/reference.md" in err
    assert "priority is only meaningful on core memory notes" in err


def test_init_memory_migrates_legacy_memory_note_types_idempotently(
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
        'is_sase_managed: true\nmemory:\n  h1_title: "Managed Instructions"\n',
    )

    assert run_handler() == 0

    legacy_core = project_root / "sase" / "memory" / "legacy_core.md"
    legacy_reference = project_root / "sase" / "memory" / "legacy_reference.md"
    canonical_core = project_root / "sase" / "memory" / "canonical_core.md"
    write(
        legacy_core,
        "---\n"
        "type: short\n"
        "parent: AGENTS.md\n"
        "priority: 5\n"
        "owner: preserved\n"
        "---\n"
        "# Legacy Core\n\n"
        "Core body.\n",
    )
    write(
        legacy_reference,
        "---\n"
        "type: long\n"
        "parent: AGENTS.md\n"
        "description: Legacy reference.\n"
        "owner: preserved\n"
        "---\n"
        "# Legacy Reference\n\n"
        "Reference body.\n",
    )
    write(
        canonical_core,
        "---\n"
        "type: core\n"
        "parent: AGENTS.md\n"
        "owner: preserved\n"
        "---\n"
        "# Canonical Core\n\n"
        "Core body.\n",
    )

    plan = plan_memory()
    frontmatter_actions = [
        action for action in plan.actions if action.detail == "memory note frontmatter"
    ]
    assert {(action.operation, action.path) for action in frontmatter_actions} == {
        ("update", legacy_core),
        ("update", legacy_reference),
    }
    assert canonical_core not in {action.path for action in frontmatter_actions}

    assert run_handler() == 0

    legacy_core_text = legacy_core.read_text(encoding="utf-8")
    legacy_reference_text = legacy_reference.read_text(encoding="utf-8")
    assert "type: core\n" in legacy_core_text
    assert "type: short\n" not in legacy_core_text
    assert "priority: 5\n" in legacy_core_text
    assert "owner: preserved\n" in legacy_core_text
    assert legacy_core_text.endswith("# Legacy Core\n\nCore body.\n")
    assert "type: reference\n" in legacy_reference_text
    assert "type: long\n" not in legacy_reference_text
    assert "description: Legacy reference.\n" in legacy_reference_text
    assert "owner: preserved\n" in legacy_reference_text
    assert legacy_reference_text.endswith("# Legacy Reference\n\nReference body.\n")
    assert [
        action
        for action in plan_memory().actions
        if action.detail == "memory note frontmatter"
    ] == []


def test_init_memory_rejects_short_memory_with_deep_heading(
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
        'is_sase_managed: true\nmemory:\n  h1_title: "Managed Instructions"\n',
    )
    # A core note with an H4 heading cannot be inlined and must block init.
    write(
        project_root / "sase" / "memory" / "bad.md",
        short_note("# Bad\n\n#### Too Deep\n"),
    )

    assert run_handler() == 1
    err = capsys.readouterr().err
    assert "sase/memory/bad.md" in err
    assert "deeper than H3" in err


def test_init_memory_rejects_missing_memory_parent(
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
    write(project_root / "AGENTS.md", "@sase/memory/sase.md\n")
    write(
        project_root / "sase" / "memory" / "orphan.md",
        "---\ntype: reference\nparent: sase/memory/ghost.md\ndescription: Orphan.\n---\n"
        "# Orphan\n",
    )

    assert run_handler() == 1
    err = capsys.readouterr().err
    assert "invalid memory parent for sase/memory/orphan.md" in err
    assert "sase/memory/ghost.md" in err
    assert "parent target does not exist" in err
    assert "sase/memory/orphan.md" in err


def test_tier2_section_heading_keeps_top_level_long_note_reachable(
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
        'is_sase_managed: true\nmemory:\n  h1_title: "Managed Instructions"\n',
    )
    write(
        project_root / "sase" / "memory" / "only.md",
        long_note("# Only\n", description="The only extra top-level long note."),
    )

    assert run_handler() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "### 3.1 `sase/memory/only.md`" in agents
    assert unreferenced_memory_files_for_init(project_root) == ()
