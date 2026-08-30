"""Glossary memory-web coverage during ``sase memory init``."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sase.amd.constants import PROVIDER_SHIM_FILES
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_memory,
    write,
)


def _setup_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_config: str = "is_sase_managed: true\n",
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
    write(project_root / "sase.yml", project_config)
    return project_root, home_root, config_dir


_WEB_HEADING_RE = re.compile(r"^## (?:\d+\. )?Memory Webs$", re.MULTILINE)
_REFERENCE_HEADING_RE = re.compile(r"^## (?:\d+\. )?Reference Memory$", re.MULTILINE)


def _web_memory(agents: str) -> str:
    match = _WEB_HEADING_RE.search(agents)
    if match is None:
        raise AssertionError("Memory Webs heading not found")
    return agents[match.end() :]


def _reference_memory(agents: str) -> str:
    match = _REFERENCE_HEADING_RE.search(agents)
    if match is None:
        raise AssertionError("Reference Memory heading not found")
    start = match.end()
    web_match = _WEB_HEADING_RE.search(agents, start)
    end = web_match.start() if web_match else len(agents)
    return agents[start:end]


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _glossary_note_path(project_root: Path) -> Path:
    return project_root / "sase" / "memory" / "glossary.md"


def _write_glossary_web(project_root: Path) -> Path:
    descriptor = _glossary_note_path(project_root)
    write(
        descriptor,
        "---\n"
        "type: core\n"
        "parent: AGENTS.md\n"
        "web: true\n"
        "roster: inline\n"
        "roster_label: GLOSSARY TERMS\n"
        "strand_noun: term\n"
        "---\n\n"
        "# Glossary Terms\n\n"
        "Human-owned descriptor body.\n",
    )
    write(
        descriptor.parent / "glossary" / "agent-clan.md",
        "---\nkeyword: Agent Clan\naliases: [clan, agent clans]\n---\n\n"
        "A named, rootless container for agents that run in parallel.\n",
    )
    write(
        descriptor.parent / "glossary" / "workspace.md",
        "---\nkeyword: Workspace\n---\n\nA numbered project checkout.\n",
    )
    return descriptor


def _unmarked_glossary_note() -> str:
    return (
        "---\n"
        "type: reference\n"
        "parent: AGENTS.md\n"
        "description: Human glossary note.\n"
        "---\n\n"
        "# Glossary\n\n"
        "Human note.\n"
    )


def test_memory_plan_renders_glossary_web_roster_without_inlining_strands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(tmp_path, monkeypatch)
    descriptor = _write_glossary_web(project_root)

    plan = plan_memory()

    assert plan.blockers == ()
    action_by_path = {action.path: action for action in plan.actions}
    updated_descriptor = str(action_by_path[descriptor].new_content)
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    webs = _web_memory(agents)
    reference = _reference_memory(agents)

    assert "Glossary Terms (glossary)" in webs
    assert "Glossary Terms" not in reference
    assert "**GLOSSARY TERMS:** Agent Clan (clan); Workspace" in _normalized(webs)
    assert "**GLOSSARY TERMS:** Agent Clan (clan); Workspace" in _normalized(
        updated_descriptor
    )
    assert "agent clans" not in webs
    assert "A named, rootless container" not in agents
    assert "sase glossary read" not in agents


def test_memory_apply_preserves_glossary_descriptor_body_and_provider_shims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(tmp_path, monkeypatch)
    descriptor = _write_glossary_web(project_root)

    assert run_memory() == 0

    note = descriptor.read_text(encoding="utf-8")
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Human-owned descriptor body." in note
    assert "**GLOSSARY TERMS:** Agent Clan (clan); Workspace" in _normalized(note)
    assert "A named, rootless container" not in agents
    for filename in PROVIDER_SHIM_FILES:
        assert (project_root / filename).read_text(encoding="utf-8") == agents

    assert run_memory(check=True) == 0
    assert plan_memory().actions == ()


def test_memory_plan_preserves_plain_glossary_note_as_user_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(tmp_path, monkeypatch)
    write(_glossary_note_path(project_root), _unmarked_glossary_note())

    plan = plan_memory()

    assert plan.blockers == ()
    action_by_path = {action.path: action for action in plan.actions}
    note_action = action_by_path.get(_glossary_note_path(project_root))
    if note_action is not None:
        assert "Human note." in str(note_action.new_content)
        assert "web: true" not in str(note_action.new_content)
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    assert "`sase/memory/glossary.md`" in _reference_memory(agents)
    assert "GLOSSARY TERMS" not in agents
    assert "Glossary Terms (glossary)" not in agents
