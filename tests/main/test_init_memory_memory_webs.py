"""Memory-init coverage for memory webs."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.amd._agents_doc import parse_amd_agents_document
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_memory,
    write,
)


def _descriptor(body: str = "# Terms\n\nDescriptor body.\n") -> str:
    return (
        "---\n"
        "type: core\n"
        "parent: AGENTS.md\n"
        "web: true\n"
        "roster_label: TERMS\n"
        "---\n\n"
        f"{body}"
    )


def _strand(body: str = "Hidden strand body.\n") -> str:
    return f"---\nkeyword: Alpha Term\naliases: [alpha]\n---\n\n{body}"


def _setup_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
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
    return project_root, home_root, config_dir


def test_memory_web_updates_roster_without_inlining_strand_bodies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _setup_roots(tmp_path, monkeypatch)
    descriptor = project_root / "sase" / "memory" / "terms.md"
    write(descriptor, _descriptor())
    write(project_root / "sase" / "memory" / "terms" / "alpha.md", _strand())

    plan = plan_memory()

    action_by_path = {action.path: action for action in plan.actions}
    updated_descriptor = str(action_by_path[descriptor].new_content)
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    assert "**TERMS:** Alpha Term (alpha)" in updated_descriptor
    assert "**TERMS:** Alpha Term (alpha)" in agents
    assert "Hidden strand body." not in agents


def test_core_memory_web_priority_orders_tier1_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _setup_roots(tmp_path, monkeypatch)
    write(
        project_root / "sase.yml",
        'is_sase_managed: true\nmemory:\n  h1_title: "Managed Instructions"\n',
    )
    descriptor = project_root / "sase" / "memory" / "terms.md"
    write(
        descriptor,
        _descriptor().replace("web: true\n", "web: true\npriority: 5\n"),
    )
    write(project_root / "sase" / "memory" / "terms" / "alpha.md", _strand())

    plan = plan_memory()

    action_by_path = {action.path: action for action in plan.actions}
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    parsed = parse_amd_agents_document(agents)
    assert parsed.short_memory_paths[:2] == (
        "sase/memory/terms.md",
        "sase/memory/sase.md",
    )


def test_memory_web_blocks_invalid_webs_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _setup_roots(tmp_path, monkeypatch)
    write(project_root / "sase" / "memory" / "terms.md", _descriptor())
    write(
        project_root / "sase" / "memory" / "terms" / "alpha.md",
        "---\ntype: core\n---\n\nBody.\n",
    )

    plan = plan_memory()
    exit_code = run_memory(check=True)

    assert exit_code == 1
    assert any("must not declare type" in blocker for blocker in plan.blockers)
