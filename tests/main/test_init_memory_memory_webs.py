"""Memory-init coverage for memory webs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sase.amd._agents_doc import parse_amd_agents_document
from sase.memory.web import END_MARKER, START_MARKER
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
    assert START_MARKER in updated_descriptor
    assert END_MARKER in updated_descriptor
    assert "**TERMS:** Alpha Term (alpha)" in agents
    assert START_MARKER not in agents
    assert END_MARKER not in agents
    assert "Hidden strand body." not in agents


def test_memory_web_priority_orders_web_section(
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
    assert parsed.has_web_section
    assert parsed.short_memory_paths[0] == "sase/memory/sase.md"
    assert parsed.web_memory_paths[0] == "sase/memory/terms.md"
    assert "## 1. Core Memory" in agents
    assert "## 2. Reference Memory" in agents
    assert "## 3. Memory Webs" in agents
    core_index = agents.index("## 1. Core Memory")
    reference_index = agents.index("## 2. Reference Memory")
    web_index = agents.index("## 3. Memory Webs")
    assert core_index < reference_index < web_index
    assert "Terms (terms)" not in agents[:web_index]
    assert "### 3.1 Terms (terms)" in agents


def test_memory_web_blocks_invalid_descriptor_structure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _setup_roots(tmp_path, monkeypatch)
    write(
        project_root / "sase" / "memory" / "terms.md",
        _descriptor(body="## Not an H1\n\nDescriptor body.\n"),
    )
    write(project_root / "sase" / "memory" / "terms" / "alpha.md", _strand())

    plan = plan_memory()

    assert any(
        "sase/memory/terms.md" in blocker and "H1" in blocker
        for blocker in plan.blockers
    )


def test_project_root_renders_three_memory_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _setup_roots(tmp_path, monkeypatch)
    write(
        project_root / "sase.yml",
        'is_sase_managed: true\nmemory:\n  h1_title: "Managed Instructions"\n',
    )

    plan = plan_memory()
    action_by_path = {action.path: action for action in plan.actions}

    project_agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    assert "## 1. Core Memory" in project_agents
    assert "## 2. Reference Memory" in project_agents
    assert "## 3. Memory Webs" in project_agents
    parsed_project = parse_amd_agents_document(project_agents)
    assert parsed_project.has_web_section
    assert parsed_project.web_memory_paths == ("sase/memory/task_types.md",)
    core_index = project_agents.index("## 1. Core Memory")
    reference_index = project_agents.index("## 2. Reference Memory")
    web_index = project_agents.index("## 3. Memory Webs")
    assert core_index < reference_index < web_index
    assert "Task Bead Types" not in project_agents[:web_index]
    assert not re.search(r"\n## (?!#)", project_agents[web_index + 1 :])


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
