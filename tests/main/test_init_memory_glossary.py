"""Tests for the generated glossary Tier 1 note during ``sase memory init``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.amd.constants import PROVIDER_SHIM_FILES
from sase.main.init_memory.formatting import format_generated_memory_markdown
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
    project_config: str,
    home_config: str | None = None,
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
    if home_config is not None:
        write(config_dir / "sase.yml", home_config)
    return project_root, home_root, config_dir


def _tier1_memory(agents: str) -> str:
    return agents.split("## 1. Tier 1 (short-term) Memory", 1)[1].split(
        "## 2. Tier 2 (long-term) Memory", 1
    )[0]


def _tier2_memory(agents: str) -> str:
    return agents.split("## 2. Tier 2 (long-term) Memory", 1)[1]


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _glossary_section(text: str) -> str:
    marker = "Glossary Terms"
    start = text.index(marker)
    heading_start = text.rfind("\n", 0, start)
    heading_start = 0 if heading_start == -1 else heading_start + 1
    lines = text[heading_start:].splitlines(keepends=True)
    collected = [lines[0]]
    for line in lines[1:]:
        if line.startswith("### "):
            break
        collected.append(line)
    return "".join(collected)


def _glossary_note_path(project_root: Path) -> Path:
    return project_root / "sase" / "memory" / "glossary.md"


def _marked_glossary_note(*, note_type: str = "long") -> str:
    return (
        "---\n"
        f"type: {note_type}\n"
        "parent: AGENTS.md\n"
        "description: Project-local glossary generated from sase.yml.\n"
        "sase_generated: glossary\n"
        "---\n\n"
        "# Glossary of Terms\n\n"
        "## Workspace\n\n"
        "A stale generated definition.\n"
    )


def _unmarked_glossary_note() -> str:
    return (
        "---\n"
        "type: long\n"
        "parent: AGENTS.md\n"
        "description: Human glossary note.\n"
        "---\n\n"
        "# Glossary\n\n"
        "Human note.\n"
    )


def test_memory_plan_generates_glossary_note_in_tier1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Agent Clan:
      aliases:
        - agent clans
        - clan
      definition: >-
        A named, rootless container for agents that run in parallel.
    Workspace:
      definition: A numbered project checkout.
""",
    )

    plan = plan_memory()

    assert plan.blockers == ()
    action_by_path = {action.path: action for action in plan.actions}
    note_path = _glossary_note_path(project_root)
    assert note_path in action_by_path
    note = str(action_by_path[note_path].new_content)
    assert note.startswith("---\ntype: short\nparent: AGENTS.md\n")
    assert "sase_generated: glossary" in note
    assert "# Glossary Terms" in note
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    tier1 = _tier1_memory(agents)
    tier2 = _tier2_memory(agents)

    assert "Glossary Terms (glossary)" in tier1
    assert "A named, rootless container" not in agents
    assert "Glossary Terms" not in tier2
    assert "GLOSSARY TERMS" not in tier2
    assert '`sase glossary read <term> [<term> ...] -r "<why>"`' in tier1
    assert "in one command" in tier1
    assert (
        "Terms are separated by semicolons; aliases follow in parentheses."
        in _normalized(tier1)
    )
    assert "**GLOSSARY TERMS:** Agent Clan (clan); Workspace" in _normalized(tier1)
    assert "**GLOSSARY TERMS:** Agent Clan (clan); Workspace" in _normalized(note)
    assert "agent clans" not in tier1
    assert "agent clans" not in note
    assert not any(
        line.startswith("- ") for line in _glossary_section(tier1).splitlines()
    )
    readme = str(
        action_by_path[project_root / "sase" / "memory" / "README.md"].new_content
    )
    glossary_heading = "### `sase/memory/glossary.md`"
    assert glossary_heading in readme
    heading_index = readme.index(glossary_heading)
    next_heading = readme.find("\n### ", heading_index + 1)
    glossary_row = readme[heading_index : next_heading if next_heading != -1 else None]
    assert "- Type: `short`" in glossary_row


def test_memory_plan_omits_parens_when_only_alias_is_term_plural(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Patch:
      aliases:
        - patches
      definition: A tracked unit of change.
""",
    )

    plan = plan_memory()

    assert plan.blockers == ()
    action_by_path = {action.path: action for action in plan.actions}
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    note = str(action_by_path[_glossary_note_path(project_root)].new_content)
    tier1 = _tier1_memory(agents)
    assert "**GLOSSARY TERMS:** Patch" in _normalized(tier1)
    assert "**GLOSSARY TERMS:** Patch" in _normalized(note)
    assert "Patch (patches)" not in tier1
    assert "Patch (patches)" not in note
    assert "patches" not in tier1
    assert "patches" not in note


def test_memory_plan_glossary_block_terms_are_semicolon_separated_and_format_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Agent Clan:
      aliases:
        - hood
        - agent neighborhood
      definition: A named, rootless container.
    Artifact Reference:
      aliases:
        - artifact references
        - ref
      definition: A typed citation in an agent prompt.
""",
    )

    plan = plan_memory()

    assert plan.blockers == ()
    action_by_path = {action.path: action for action in plan.actions}
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    note = str(action_by_path[_glossary_note_path(project_root)].new_content)
    expected = (
        "**GLOSSARY TERMS:** Agent Clan (hood, agent neighborhood); "
        "Artifact Reference (ref)"
    )
    assert expected in _normalized(_tier1_memory(agents))
    assert expected in _normalized(note)
    assert "artifact references" not in agents
    assert "artifact references" not in note
    assert format_generated_memory_markdown(agents) == agents
    assert format_generated_memory_markdown(note) == note


def test_memory_plan_glossary_terms_section_stays_compact_as_term_count_grows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terms = (
        "Agent Clan",
        "Agent Family",
        "Agent Hood",
        "Agent Instruction File",
        "Artifact Reference",
        "Current Project",
        "Feature Flag",
        "Sase Workspace",
        "Xprompt Memory",
        "Xprompt Workflow",
    )
    glossary_yaml = "\n".join(
        f"    {term}:\n      definition: Definition of {term}." for term in terms
    )
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config=f"""
is_sase_managed: true
memory:
  glossary:
{glossary_yaml}
""",
    )

    plan = plan_memory()

    assert plan.blockers == ()
    action_by_path = {action.path: action for action in plan.actions}
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    note = str(action_by_path[_glossary_note_path(project_root)].new_content)
    section = _glossary_section(_tier1_memory(agents))
    section_lines = section.splitlines()
    terms_paragraph = section.split("**GLOSSARY TERMS:**", 1)[1]
    terms_paragraph_lines = [line for line in terms_paragraph.splitlines() if line]
    normalized = _normalized(section)

    assert not any(line.startswith("- ") for line in section_lines)
    assert "**GLOSSARY TERMS:**" in section
    assert len(terms_paragraph_lines) < len(terms)
    assert normalized.count("**GLOSSARY TERMS:**") == 1
    for term in terms:
        assert normalized.count(term) == 1
    assert format_generated_memory_markdown(note) == note
    assert format_generated_memory_markdown(agents) == agents
    assert "\n" in note.split("**GLOSSARY TERMS:**", 1)[1]


def test_memory_apply_generates_glossary_note_idempotently_and_copies_provider_shims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Workspace:
      aliases:
        - workspaces
      definition: A numbered project checkout.
""",
    )

    assert run_memory() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    note = _glossary_note_path(project_root).read_text(encoding="utf-8")
    assert "Glossary Terms (glossary)" in _tier1_memory(agents)
    assert "Glossary Terms" not in _tier2_memory(agents)
    assert "GLOSSARY TERMS" not in _tier2_memory(agents)
    assert "**GLOSSARY TERMS:** Workspace" in _normalized(_tier1_memory(agents))
    assert "type: short" in note
    assert "sase_generated: glossary" in note
    for filename in PROVIDER_SHIM_FILES:
        assert (project_root / filename).read_text(encoding="utf-8") == agents

    assert run_memory(check=True) == 0
    assert plan_memory().actions == ()


def test_memory_init_overwrites_marked_glossary_note_when_terms_are_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Workspace:
      definition: A numbered project checkout.
""",
    )
    write(_glossary_note_path(project_root), _marked_glossary_note(note_type="short"))

    assert run_memory() == 0

    note = _glossary_note_path(project_root).read_text(encoding="utf-8")
    assert "type: short" in note
    assert "sase_generated: glossary" in note
    assert "A stale generated definition" not in note
    assert "**GLOSSARY TERMS:** Workspace" in _normalized(note)
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Glossary Terms (glossary)" in _tier1_memory(agents)
    assert "Glossary Terms" not in _tier2_memory(agents)

    assert run_memory(check=True) == 0


def test_memory_init_migrates_marked_long_glossary_note_to_short(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Workspace:
      definition: A numbered project checkout.
""",
    )
    write(_glossary_note_path(project_root), _marked_glossary_note(note_type="long"))

    assert run_memory() == 0

    note = _glossary_note_path(project_root).read_text(encoding="utf-8")
    assert note.startswith("---\ntype: short\n")
    assert "sase_generated: glossary" in note
    assert "type: long" not in note
    assert "A stale generated definition" not in note
    assert run_memory(check=True) == 0


def test_memory_init_deletes_stale_generated_glossary_note_without_configured_terms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="is_sase_managed: true\n",
    )
    write(_glossary_note_path(project_root), _marked_glossary_note())

    plan = plan_memory()

    assert ("delete", _glossary_note_path(project_root)) in {
        (action.operation, action.path) for action in plan.actions
    }

    assert run_memory() == 0
    assert not _glossary_note_path(project_root).exists()
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "GLOSSARY TERMS" not in agents
    assert "Glossary Terms" not in agents


def test_memory_plan_blocks_invalid_project_glossary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Agent Clan:
      aliases:
        - workspace
      definition: A named container.
    Workspace:
      aliases:
        - workspace
      definition: A numbered checkout.
""",
    )

    plan = plan_memory()

    assert plan.actions == ()
    assert any(
        "glossary" in blocker.lower() and "workspace" in blocker.lower()
        for blocker in plan.blockers
    )


def test_memory_plan_blocks_unmarked_glossary_note_when_terms_are_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Workspace:
      definition: A numbered project checkout.
""",
    )
    write(_glossary_note_path(project_root), _unmarked_glossary_note())

    plan = plan_memory()

    assert any(
        "refusing to overwrite unmarked glossary memory note" in blocker
        and "glossary.md" in blocker
        for blocker in plan.blockers
    )
    assert _glossary_note_path(project_root) not in {
        action.path for action in plan.actions
    }


def test_memory_plan_preserves_unmarked_glossary_note_without_configured_terms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="is_sase_managed: true\n",
    )
    write(_glossary_note_path(project_root), _unmarked_glossary_note())

    plan = plan_memory()

    assert plan.blockers == ()
    action_by_path = {action.path: action for action in plan.actions}
    note_action = action_by_path.get(_glossary_note_path(project_root))
    if note_action is not None:
        assert note_action.operation == "update"
        assert "Human note." in str(note_action.new_content)
        assert "sase_generated:" not in str(note_action.new_content)
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    tier2 = _tier2_memory(agents)
    assert "`sase/memory/glossary.md`" in tier2
    assert "GLOSSARY TERMS" not in agents
    assert "Glossary Terms (glossary)" not in agents


def test_memory_init_ignores_home_glossary_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, home_root, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="is_sase_managed: true\n",
        home_config="""
memory:
  glossary:
    Home Term:
      definition: This must not become home memory.
""",
    )

    assert run_memory() == 0

    assert not _glossary_note_path(home_root).exists()
    home_agents = home_root / "AGENTS.md"
    if home_agents.exists():
        home_text = home_agents.read_text(encoding="utf-8")
        assert "GLOSSARY TERMS" not in home_text
        assert "Glossary Terms" not in home_text


def test_memory_plan_numbers_glossary_in_tier1_and_notes_in_tier2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Workspace:
      definition: A numbered project checkout.
""",
    )
    write(
        project_root / "sase" / "memory" / "aaa.md",
        "---\ntype: long\nparent: AGENTS.md\ndescription: First.\n---\n# First\n",
    )
    write(
        project_root / "sase" / "memory" / "bbb.md",
        "---\ntype: long\nparent: AGENTS.md\ndescription: Second.\n---\n# Second\n",
    )

    plan = plan_memory()

    assert plan.blockers == ()
    action_by_path = {action.path: action for action in plan.actions}
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    assert "### 1.1 Glossary Terms (glossary)" in agents
    assert "### 2.1 `sase/memory/aaa.md`" in agents
    assert "### 2.2 `sase/memory/bbb.md`" in agents
    assert "#### 2.1" not in agents
    assert "Long-Term Memory Files" not in agents
    assert "Glossary Terms" not in _tier2_memory(agents)
