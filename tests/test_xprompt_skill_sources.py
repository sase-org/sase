"""Canonical skill-source placement, naming, and precedence rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.content_layout import (
    resolve_skill_file_sources,
    skill_placement_issue,
    skill_reference_name,
)
from sase.main._init_skills_sources import select_skill_xprompts
from sase.xprompt.load_issues import collect_xprompt_load_issues
from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.loader_skills import (
    SKILL_FRAME_TEMPLATE_FILENAME,
    SKILL_PLACEMENT_ISSUE_KIND,
    load_project_skills,
    load_skills_from_files,
)
from sase.xprompt.loader_sources import load_xprompts_from_files
from sase.xprompt.models import XPrompt


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _skill_file(path: Path, name: str, *, skill: str = "true") -> None:
    _write(
        path,
        f"---\nname: {name}\ndescription: {name} desc\nskill: {skill}\n---\n\n{name} body\n",
    )


@pytest.fixture
def home_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every home-scoped layout lookup at an isolated directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def test_reference_name_splits_provider_name_from_xprompt_reference() -> None:
    assert skill_reference_name("foo") == "skills/foo"
    assert skill_reference_name("foo", "app") == "app/skills/foo"


def test_layout_orders_project_before_home_and_omits_legacy_paths(
    tmp_path: Path, home_root: Path
) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()

    sources = resolve_skill_file_sources(project_root=project_root, project="app")

    assert [source.id for source in sources] == [
        "project_skills",
        "home_skills",
        "home_project_skills",
    ]
    assert [source.path for source in sources] == [
        project_root / "sase" / "skills",
        home_root / "sase" / "skills",
        home_root / "sase" / "skills" / "app",
    ]
    assert sources[0].project_namespaced is True
    assert sources[1].project_namespaced is False


def test_home_skill_takes_the_skills_namespace(home_root: Path) -> None:
    _skill_file(home_root / "sase" / "skills" / "bob_query.md", "bob_query")

    skills = load_skills_from_files()

    assert set(skills) == {"skills/bob_query"}
    loaded = skills["skills/bob_query"]
    assert loaded.skill_name == "bob_query"
    assert loaded.skill is True


def test_project_skill_is_qualified_but_keeps_its_slash_name(
    tmp_path: Path, home_root: Path
) -> None:
    project_root = tmp_path / "workspace"
    _skill_file(project_root / "sase" / "skills" / "scoped.md", "scoped")

    skills = load_project_skills(project_root, "app")

    assert set(skills) == {"app/skills/scoped"}
    assert skills["app/skills/scoped"].skill_name == "scoped"


def test_project_skill_shadows_the_home_skill_of_the_same_name(
    tmp_path: Path, home_root: Path
) -> None:
    project_root = tmp_path / "workspace"
    _skill_file(home_root / "sase" / "skills" / "dup.md", "dup")
    _skill_file(project_root / "sase" / "skills" / "dup.md", "dup")

    skills = load_skills_from_files(project_root=project_root)

    # No project name, so both sources resolve to the same reference and the
    # higher-priority project source wins.
    assert set(skills) == {"skills/dup"}
    assert skills["skills/dup"].source_path == str(
        project_root / "sase" / "skills" / "dup.md"
    )


def test_skill_declaration_outside_a_skill_source_is_rejected(
    home_root: Path,
) -> None:
    _write(
        home_root / "sase" / "xprompts" / "stale.md",
        "---\nname: stale\nskill: true\n---\n\nbody\n",
    )

    with collect_xprompt_load_issues() as issues:
        xprompts = load_xprompts_from_files()

    assert "stale" not in xprompts
    placement = [i for i in issues if i.kind == SKILL_PLACEMENT_ISSUE_KIND]
    assert len(placement) == 1
    assert "declares `skill:` outside a canonical skill source" in placement[0].error
    assert str(home_root / "sase" / "skills") in placement[0].error


def test_non_skill_in_a_skill_source_is_rejected(home_root: Path) -> None:
    _write(
        home_root / "sase" / "skills" / "plain.md",
        "---\nname: plain\ndescription: not a skill\n---\n\nbody\n",
    )

    with collect_xprompt_load_issues() as issues:
        skills = load_skills_from_files()

    assert skills == {}
    placement = [i for i in issues if i.kind == SKILL_PLACEMENT_ISSUE_KIND]
    assert len(placement) == 1
    assert "declares no truthy `skill:` value" in placement[0].error
    assert str(home_root / "sase" / "xprompts") in placement[0].error


def test_falsey_skill_value_in_a_skill_source_is_rejected(home_root: Path) -> None:
    _skill_file(home_root / "sase" / "skills" / "off.md", "off", skill="false")

    with collect_xprompt_load_issues() as issues:
        skills = load_skills_from_files()

    assert skills == {}
    assert [i.kind for i in issues] == [SKILL_PLACEMENT_ISSUE_KIND]


def test_provider_list_is_a_truthy_skill_value(home_root: Path) -> None:
    _skill_file(
        home_root / "sase" / "skills" / "codex_only.md", "codex_only", skill="[codex]"
    )

    skills = load_skills_from_files()

    assert skills["skills/codex_only"].skill == ["codex"]


def test_config_defined_skill_is_rejected_with_a_migration_destination() -> None:
    with collect_xprompt_load_issues() as issues:
        parsed = parse_xprompt_entries(
            {
                "plain": "just a prompt",
                "gmail": {"content": "body", "skill": True},
            },
            "config_overlay:sase_athena.yml",
        )

    assert set(parsed) == {"plain"}
    placement = [i for i in issues if i.kind == SKILL_PLACEMENT_ISSUE_KIND]
    assert len(placement) == 1
    assert "config_overlay:sase_athena.yml:gmail" in placement[0].error
    assert "sase/skills/" in placement[0].error


def test_frame_template_is_not_loaded_as_a_skill(home_root: Path) -> None:
    _write(
        home_root / "sase" / "skills" / SKILL_FRAME_TEMPLATE_FILENAME,
        "{{ frontmatter }}\n\n{{ body }}\n",
    )

    with collect_xprompt_load_issues() as issues:
        skills = load_skills_from_files()

    assert skills == {}
    assert issues == []


def test_selection_uses_the_provider_skill_name_for_ordering() -> None:
    entries = {
        "skills/zulu": XPrompt(
            name="skills/zulu", content="", skill=True, skill_name="zulu"
        ),
        "app/skills/alpha": XPrompt(
            name="app/skills/alpha", content="", skill=True, skill_name="alpha"
        ),
        "plain": XPrompt(name="plain", content=""),
    }

    selected = select_skill_xprompts(entries)

    assert [xp.skill_name for xp in selected] == ["alpha", "zulu"]


def test_selection_ignores_a_skill_flag_without_a_canonical_source() -> None:
    """Defense in depth: a rejected definition can never reach generation."""
    entries = {"rogue": XPrompt(name="rogue", content="", skill=True)}

    assert select_skill_xprompts(entries) == []


@pytest.mark.parametrize(
    ("in_skill_source", "declares_skill"),
    [(True, True), (False, False)],
)
def test_valid_placement_reports_no_issue(
    in_skill_source: bool, declares_skill: bool
) -> None:
    assert (
        skill_placement_issue(
            "sase/skills/foo.md",
            in_skill_source=in_skill_source,
            declares_skill=declares_skill,
        )
        is None
    )
