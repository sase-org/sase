"""Tests for the generated glossary Tier 2 block during ``sase memory init``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.amd.constants import PROVIDER_SHIM_FILES
from sase.main.init_memory.formatting import format_generated_memory_markdown
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_memory,
    single_line,
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


def _glossary_section(tier2: str) -> str:
    heading = "### "
    marker = "Glossary Terms"
    start = tier2.index(marker)
    heading_start = tier2.rfind(heading, 0, start)
    return tier2[heading_start:]


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


def test_memory_plan_never_generates_a_glossary_note(
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
    assert _glossary_note_path(project_root) not in {
        action.path for action in plan.actions
    }
    action_by_path = {action.path: action for action in plan.actions}
    readme = str(
        action_by_path[project_root / "sase" / "memory" / "README.md"].new_content
    )
    assert "glossary.md" not in readme


def test_memory_plan_renders_glossary_terms_block_in_tier2(
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
    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    tier1 = _tier1_memory(agents)
    tier2 = _tier2_memory(agents)

    assert "Glossary Terms" not in tier1
    assert "A named, rootless container" not in agents
    assert "### 2.1 Long-Term Memory Files" in tier2
    assert "### 2.2 Glossary Terms" in tier2
    files_index = tier2.index("### 2.1 Long-Term Memory Files")
    intro_index = tier2.index("The below files contain detailed reference material")
    note_index = tier2.index("#### 2.1.")
    glossary_index = tier2.index("### 2.2 Glossary Terms")
    assert files_index < intro_index < note_index < glossary_index
    assert '`sase glossary read <term> [<term> ...] -r "<why>"`' in tier2
    assert "in one command" in tier2
    assert (
        "Terms are separated by semicolons; aliases follow in parentheses."
        in _normalized(tier2)
    )
    assert "**GLOSSARY TERMS:**" in agents
    assert "**GLOSSARY TERMS:** Agent Clan (clan); Workspace" in _normalized(tier2)
    assert "agent clans" not in tier2
    assert not any(
        line.startswith("- ") for line in _glossary_section(tier2).splitlines()
    )


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
    tier2 = _tier2_memory(str(action_by_path[project_root / "AGENTS.md"].new_content))
    assert "**GLOSSARY TERMS:** Patch" in _normalized(tier2)
    assert "Patch (patches)" not in tier2
    assert "patches" not in tier2


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
    tier2 = _tier2_memory(agents)

    assert (
        "**GLOSSARY TERMS:** Agent Clan (hood, agent neighborhood); "
        "Artifact Reference (ref)" in _normalized(tier2)
    )
    assert "artifact references" not in tier2
    assert format_generated_memory_markdown(agents) == agents


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
    _setup_project(
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
    agents = str(action_by_path[tmp_path / "project" / "AGENTS.md"].new_content)
    tier2 = _tier2_memory(agents)
    section = _glossary_section(tier2)
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


def test_memory_apply_generates_glossary_block_idempotently_and_copies_provider_shims(
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
    assert "Glossary Terms" not in _tier1_memory(agents)
    assert "### 2.2 Glossary Terms" in _tier2_memory(agents)
    assert "**GLOSSARY TERMS:** Workspace" in _normalized(_tier2_memory(agents))
    assert not _glossary_note_path(project_root).exists()
    for filename in PROVIDER_SHIM_FILES:
        assert (project_root / filename).read_text(encoding="utf-8") == agents

    assert run_memory(check=True) == 0
    assert plan_memory().actions == ()


def test_memory_init_deletes_stale_generated_glossary_note_even_with_configured_terms(
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

    assert not _glossary_note_path(project_root).exists()
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "### 2.2 Glossary Terms" in _tier2_memory(agents)

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


def test_memory_plan_preserves_unmarked_glossary_note_as_ordinary_long_note(
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
        _glossary_note_path(project_root),
        "---\ntype: long\nparent: AGENTS.md\ndescription: Human glossary note.\n"
        "---\n\n# Glossary\n\nHuman note.\n",
    )

    plan = plan_memory()

    assert plan.blockers == ()
    assert _glossary_note_path(project_root) not in {
        action.path for action in plan.actions
    }
    action_by_path = {action.path: action for action in plan.actions}
    tier2 = _tier2_memory(str(action_by_path[project_root / "AGENTS.md"].new_content))
    assert "`sase/memory/glossary.md`" in tier2
    assert "### 2.2 Glossary Terms" in tier2


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
