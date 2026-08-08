from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from sase.xprompt.config_yaml import insert_xprompt_into_config
from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.loader_sources import load_xprompt_from_file
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import save_config_xprompt, save_markdown_xprompt
from sase.xprompt.tags import XPromptTag


def _frontmatter() -> PromptFrontmatter:
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
        skill=["codex"],
        snippet="review",
    )


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
    assert loaded.skill == ["codex"]
    assert loaded.snippet == "review"


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
    # A config entry can never be a skill, so the ``skill`` key that survives
    # the YAML round trip is rejected on load rather than silently honored.
    entries = data["xprompts"]
    assert entries["bravo"]["skill"] == ["codex"]
    assert parse_xprompt_entries(entries, "config").get("bravo") is None

    del entries["bravo"]["skill"]
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
