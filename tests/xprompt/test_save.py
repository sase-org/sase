from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from sase.xprompt.config_yaml import insert_xprompt_into_config
from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.loader_sources import load_xprompt_from_file
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import (
    SkillPlacementError,
    save_config_xprompt,
    save_markdown_document,
    save_markdown_xprompt,
)
from sase.xprompt.tags import XPromptTag


def _frontmatter(*, skill: bool | list[str] | None = None) -> PromptFrontmatter:
    return PromptFrontmatter(
        name="draft",
        description="Reusable review prompt.",
        tags=["vcs", "mentor"],
        inputs=[
            InputArg(
                name="topic",
                type=InputType.WORD,
                description="Topic to review.",
            )
        ],
        xprompts={"_rules": XPrompt(name="_rules", content="Be precise.")},
        skill=skill,
        snippet="review",
    )


def _home_skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``$HOME`` at *tmp_path* and return its canonical skill directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sase.xprompt.skill_locations.get_use_chezmoi", lambda: False)
    monkeypatch.setattr("sase.xprompt.skill_locations.detect_project", lambda: None)
    skills = tmp_path / "sase" / "skills"
    skills.mkdir(parents=True)
    return skills


def test_markdown_save_round_trips_full_frontmatter(tmp_path: Path) -> None:
    body = "First pane\n---\nSecond pane"
    path = tmp_path / "draft.md"

    save_markdown_xprompt(path, _frontmatter(), body)

    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\nname: draft\n")
    assert text.endswith("First pane\n---\nSecond pane\n")

    loaded = load_xprompt_from_file(path)
    assert loaded is not None
    assert loaded.name == "draft"
    assert loaded.content.rstrip("\n") == body
    assert loaded.description == "Reusable review prompt."
    assert loaded.tags == frozenset({XPromptTag.vcs, XPromptTag.mentor})
    assert loaded.inputs[0].name == "topic"
    assert loaded.inputs[0].description == "Topic to review."
    assert loaded.local_xprompts["_rules"].content == "Be precise."
    assert loaded.skill is None
    assert loaded.snippet == "review"


def test_markdown_skill_saves_into_a_canonical_skill_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills = _home_skills_dir(tmp_path, monkeypatch)
    path = skills / "draft.md"

    save_markdown_xprompt(path, _frontmatter(skill=["codex"]), "Review it")

    loaded = load_xprompt_from_file(path)
    assert loaded is not None
    assert loaded.skill == ["codex"]


def test_markdown_save_refuses_a_skill_outside_a_skill_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _home_skills_dir(tmp_path, monkeypatch)
    path = tmp_path / "sase" / "xprompts" / "draft.md"
    path.parent.mkdir(parents=True)

    with pytest.raises(SkillPlacementError) as exc_info:
        save_markdown_xprompt(path, _frontmatter(skill=True), "Review it")

    assert "sase/skills/" in str(exc_info.value)
    assert not path.exists()


def test_markdown_document_save_refuses_a_smuggled_skill_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _home_skills_dir(tmp_path, monkeypatch)
    path = tmp_path / "sase" / "xprompts" / "draft.md"
    path.parent.mkdir(parents=True)

    with pytest.raises(SkillPlacementError):
        save_markdown_document(path, "---\nname: draft\nskill: true\n---\n\nBody\n")

    assert not path.exists()


def test_config_save_round_trips_full_frontmatter_and_orders_entries(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text(
        "xprompts:\n  alpha: |\n    Alpha\n\n  zulu: |\n    Zulu\n",
        encoding="utf-8",
    )

    body = "First pane\n---\nSecond pane"
    assert save_config_xprompt(config, "bravo", _frontmatter(), body) is True

    text = config.read_text(encoding="utf-8")
    assert text.index("alpha:") < text.index("bravo:") < text.index("zulu:")
    assert "    description: Reusable review prompt." in text
    assert "    content: |-" in text
    assert "      ---" in text

    data = yaml.safe_load(text)
    entries = data["xprompts"]
    parsed = parse_xprompt_entries(entries, "config")
    loaded = parsed["bravo"]
    # ``|-`` strips the trailing newline, so the submitted body round-trips
    # exactly without needing ``rstrip("\n")``.
    assert loaded.content == body
    assert loaded.description == "Reusable review prompt."
    assert loaded.tags == frozenset({XPromptTag.vcs, XPromptTag.mentor})
    assert loaded.inputs[0].name == "topic"
    assert loaded.local_xprompts["_rules"].content == "Be precise."
    assert loaded.snippet == "review"


def test_config_save_refuses_a_skill_entry(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("xprompts:\n  alpha: |\n    Alpha\n", encoding="utf-8")

    # A config entry can never be a skill: generation needs a Markdown source
    # in a canonical skill directory to render from.
    with pytest.raises(SkillPlacementError) as exc_info:
        save_config_xprompt(config, "bravo", _frontmatter(skill=True), "Body")

    assert "sase/skills/" in str(exc_info.value)
    assert "bravo" not in config.read_text(encoding="utf-8")


def test_config_insert_overwrites_existing_name(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    config.write_text(
        "xprompts:\n  alpha: |\n    Old\n\n  beta: |\n    Keep\n",
        encoding="utf-8",
    )

    result = insert_xprompt_into_config(
        str(config),
        "alpha",
        [],
        "New",
        frontmatter=PromptFrontmatter(description="Updated"),
    )

    assert result is True
    text = config.read_text(encoding="utf-8")
    assert "Old" not in text
    assert text.count("  alpha:") == 1
    assert "    description: Updated" in text
    assert "      New" in text
