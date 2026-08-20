"""Draft-validation tests for the memory-note mutation engine."""

from __future__ import annotations

import pytest

from sase.memory.mutation import (
    memory_note_relative_path_for_stem,
    validate_memory_note_draft,
)
from sase.memory.notes import (
    AGENTS_PARENT,
    parse_memory_note_text,
)

from .helpers import note_text


@pytest.mark.parametrize(
    ("stem", "field", "snippet"),
    [
        ("", "stem", "required"),
        ("   ", "stem", "required"),
        ("../secret", "stem", "traversal"),
        ("foo/bar", "stem", "flat"),
        ("README", "stem", "README"),
        ("readme.md", "stem", "README"),
        ("has space", "stem", "must match"),
        ("bad!", "stem", "must match"),
    ],
)
def test_validate_rejects_illegal_stems(stem: str, field: str, snippet: str) -> None:
    result = validate_memory_note_draft(
        stem=stem,
        note_type="long",
        parent=AGENTS_PARENT,
        description="Ok.",
    )

    assert snippet in " ".join(result.by_field[field])
    assert not result


def test_validate_strips_md_suffix_and_accepts_valid_stem() -> None:
    result = validate_memory_note_draft(
        stem="gotchas.md",
        note_type="short",
        parent=AGENTS_PARENT,
        description=None,
    )

    assert result
    assert result.draft is not None
    assert result.draft.stem == "gotchas"
    assert result.draft.relative_path == "sase/memory/gotchas.md"
    assert result.draft.note_type == "short"
    assert result.draft.parent == AGENTS_PARENT


def test_validate_rejects_invalid_type_and_empty_long_description() -> None:
    result = validate_memory_note_draft(
        stem="hub",
        note_type="medium",
        parent=AGENTS_PARENT,
        description="   ",
    )

    assert "short or long" in " ".join(result.by_field["type"])
    assert "description" not in result.by_field

    result = validate_memory_note_draft(
        stem="hub",
        note_type="long",
        parent=AGENTS_PARENT,
        description="\n\t\n",
    )
    assert "require a description" in " ".join(result.by_field["description"])


def test_validate_requires_short_notes_to_parent_agents() -> None:
    result = validate_memory_note_draft(
        stem="gotchas",
        note_type="short",
        parent="sase/memory/hub.md",
        description="Always loaded.",
    )

    assert "AGENTS.md" in " ".join(result.by_field["parent"])


def test_validate_parent_must_exist_and_be_long() -> None:
    notes = (
        parse_memory_note_text(
            note_text(note_type="short", description="Short.", body="# S\n"),
            "sase/memory/brief.md",
        ),
        parse_memory_note_text(
            note_text(description="Hub.", body="# H\n"),
            "sase/memory/hub.md",
        ),
    )

    missing = validate_memory_note_draft(
        stem="child",
        note_type="long",
        parent="sase/memory/missing.md",
        description="Child.",
        existing_notes=notes,
    )
    assert "does not exist" in " ".join(missing.by_field["parent"])

    short_parent = validate_memory_note_draft(
        stem="child",
        note_type="long",
        parent="brief",
        description="Child.",
        existing_notes=notes,
    )
    assert "short note" in " ".join(short_parent.by_field["parent"])

    ok = validate_memory_note_draft(
        stem="child",
        note_type="long",
        parent="hub.md",
        description="Child.",
        existing_notes=notes,
    )
    assert ok
    assert ok.draft is not None
    assert ok.draft.parent == "sase/memory/hub.md"


def test_validate_rejects_self_parent_and_cycles() -> None:
    parent = parse_memory_note_text(
        note_text(description="Parent.", body="# P\n"),
        "sase/memory/parent.md",
    )
    child = parse_memory_note_text(
        note_text(parent="sase/memory/parent.md", description="Child.", body="# C\n"),
        "sase/memory/child.md",
    )

    self_parent = validate_memory_note_draft(
        stem="parent",
        note_type="long",
        parent="sase/memory/parent.md",
        description="Parent.",
        existing_notes=(parent, child),
        current_relative_path="sase/memory/parent.md",
    )
    assert "itself" in " ".join(self_parent.by_field["parent"])

    cycle = validate_memory_note_draft(
        stem="parent",
        note_type="long",
        parent="sase/memory/child.md",
        description="Parent.",
        existing_notes=(parent, child),
        current_relative_path="sase/memory/parent.md",
    )
    assert "cycle" in " ".join(cycle.by_field["parent"])


def test_validate_rejects_collision_and_generated_stems() -> None:
    existing = parse_memory_note_text(
        note_text(description="Hub.", body="# H\n"),
        "sase/memory/hub.md",
    )
    collision = validate_memory_note_draft(
        stem="hub",
        note_type="long",
        parent=AGENTS_PARENT,
        description="Other.",
        existing_notes=(existing,),
    )
    assert "already exists" in " ".join(collision.by_field["stem"])

    generated = validate_memory_note_draft(
        stem="sase",
        note_type="short",
        parent=AGENTS_PARENT,
        description="Generated.",
        include_project_memory=True,
    )
    assert "read-only" in " ".join(generated.by_field["stem"])

    project_only = validate_memory_note_draft(
        stem="sase_beads",
        note_type="long",
        parent=AGENTS_PARENT,
        description="Beads.",
        include_project_memory=False,
    )
    assert "read-only" not in " ".join(project_only.by_field.get("stem", ()))


def test_validate_rejects_retyping_parent_with_children() -> None:
    parent = parse_memory_note_text(
        note_text(description="Parent.", body="# P\n"),
        "sase/memory/parent.md",
    )
    child = parse_memory_note_text(
        note_text(parent="sase/memory/parent.md", description="Child.", body="# C\n"),
        "sase/memory/child.md",
    )

    result = validate_memory_note_draft(
        stem="parent",
        note_type="short",
        parent=AGENTS_PARENT,
        description="Parent.",
        existing_notes=(parent, child),
        current_relative_path="sase/memory/parent.md",
    )
    assert "children exist" in " ".join(result.by_field["type"])


def test_memory_note_relative_path_for_stem() -> None:
    assert memory_note_relative_path_for_stem("gotchas") == "sase/memory/gotchas.md"
