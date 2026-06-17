from __future__ import annotations

from pathlib import Path

from sase.memory.notes import (
    AGENTS_PARENT,
    MemoryNote,
    MemoryNoteValidationError,
    apply_memory_frontmatter,
    children_of,
    discover_memory_notes,
    parse_memory_note_text,
    render_children_section,
    render_memory_note_references,
    validate_notes,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _note(
    path: str,
    *,
    note_type: str = "long",
    parent: str = AGENTS_PARENT,
    description: str | None = "Description.",
) -> MemoryNote:
    lines = [
        "---",
        f"type: {note_type}",
        f"parent: {parent}",
    ]
    if description is not None:
        lines.append(f"description: {description}")
    lines.extend(["---", f"# {Path(path).stem}", ""])
    return parse_memory_note_text("\n".join(lines), path)


def _messages(
    errors: tuple[MemoryNoteValidationError, ...], path: str
) -> tuple[str, ...]:
    return tuple(error.message for error in errors if error.path == path)


def test_parse_legacy_note_infers_type_and_default_parent() -> None:
    note = parse_memory_note_text(
        "# Build\n\nBody stays exact.\n",
        "memory/short/build_and_run.md",
    )

    assert note.path == Path("memory/short/build_and_run.md")
    assert note.relative_path == "memory/short/build_and_run.md"
    assert note.type == "short"
    assert note.type_source == "legacy_path"
    assert note.parent == AGENTS_PARENT
    assert note.parent_source == "default"
    assert note.description is None
    assert note.body == "# Build\n\nBody stays exact.\n"


def test_parse_flat_note_strips_frontmatter_and_normalizes_description() -> None:
    note = parse_memory_note_text(
        "---\n"
        "type: long\n"
        "parent: memory/hub.md\n"
        "description: |\n"
        "  Child note\n"
        "  details.\n"
        "---\n"
        "# Child\n",
        "memory/child.md",
    )

    assert note.type == "long"
    assert note.type_source == "frontmatter"
    assert note.parent == "memory/hub.md"
    assert note.parent_source == "frontmatter"
    assert note.description == "Child note details."
    assert note.body == "# Child\n"


def test_apply_memory_frontmatter_uses_canonical_key_order_and_preserves_extra() -> (
    None
):
    content = apply_memory_frontmatter(
        "---\nkeywords: [skills]\ndescription: Old description.\n---\n# Body\n",
        note_type="long",
        parent=AGENTS_PARENT,
        description="New description.",
        extra={"owner": "docs"},
    )

    assert content == (
        "---\n"
        "type: long\n"
        "parent: AGENTS.md\n"
        "description: New description.\n"
        "keywords:\n"
        "  - skills\n"
        "owner: docs\n"
        "---\n"
        "\n"
        "# Body\n"
    )


def test_discover_memory_notes_reads_flat_and_legacy_layouts(tmp_path: Path) -> None:
    _write(tmp_path / "memory" / "README.md", "# Memory\n")
    _write(
        tmp_path / "memory" / "flat.md",
        "---\ntype: long\nparent: AGENTS.md\ndescription: Flat note.\n---\n# Flat\n",
    )
    _write(tmp_path / "memory" / "short" / "base.md", "# Base\n")
    _write(tmp_path / "memory" / "long" / "nested" / "detail.md", "# Detail\n")

    notes = discover_memory_notes(tmp_path)

    assert tuple(note.relative_path for note in notes) == (
        "memory/flat.md",
        "memory/long/nested/detail.md",
        "memory/short/base.md",
    )
    assert tuple(note.type for note in notes) == ("long", "long", "short")


def test_children_and_reference_rendering_match_agents_shape() -> None:
    hub = _note("memory/hub.md", description="Hub.")
    child_b = _note(
        "memory/child_b.md",
        parent="memory/hub.md",
        description="Beta child.",
    )
    child_a = _note(
        "memory/child_a.md",
        parent="memory/hub.md",
        description="Alpha child.",
    )
    short_child = _note(
        "memory/short_child.md",
        note_type="short",
        parent="memory/hub.md",
        description=None,
    )

    children = children_of((child_b, hub, short_child, child_a), hub)

    assert tuple(note.relative_path for note in children) == (
        "memory/child_a.md",
        "memory/child_b.md",
    )
    assert render_memory_note_references(children) == (
        "**`memory/child_a.md`**  \n"
        "Alpha child.\n\n"
        "**`memory/child_b.md`**  \n"
        "Beta child."
    )
    assert render_children_section((child_b, hub, short_child, child_a), hub) == (
        "## Children\n\n"
        "**`memory/child_a.md`**  \n"
        "Alpha child.\n\n"
        "**`memory/child_b.md`**  \n"
        "Beta child.\n"
    )


def test_validate_notes_reports_required_frontmatter_errors() -> None:
    missing = parse_memory_note_text("# Missing\n", "memory/missing.md")
    invalid_type = parse_memory_note_text(
        "---\ntype: medium\nparent: AGENTS.md\ndescription: Bad type.\n---\n# Bad\n",
        "memory/invalid_type.md",
    )
    invalid_parent = parse_memory_note_text(
        "---\ntype: long\nparent: ../AGENTS.md\ndescription: Bad parent.\n---\n# Bad\n",
        "memory/invalid_parent.md",
    )
    missing_description = parse_memory_note_text(
        "---\ntype: long\nparent: AGENTS.md\n---\n# No description\n",
        "memory/no_description.md",
    )

    errors = validate_notes(
        (missing, invalid_type, invalid_parent, missing_description)
    )

    assert "missing type frontmatter" in _messages(errors, "memory/missing.md")
    assert "missing parent frontmatter" in _messages(errors, "memory/missing.md")
    assert "invalid memory note type" in _messages(errors, "memory/invalid_type.md")
    assert "invalid parent path" in _messages(errors, "memory/invalid_parent.md")
    assert "long memory notes require a description" in _messages(
        errors, "memory/no_description.md"
    )


def test_validate_notes_can_allow_transitional_legacy_frontmatter() -> None:
    short = parse_memory_note_text("# Short\n", "memory/short/base.md")
    long = parse_memory_note_text("# Long\n", "memory/long/detail.md")

    assert validate_notes((short, long), require_frontmatter=False) == ()


def test_validate_notes_reports_duplicate_flat_names_and_bad_parents() -> None:
    short_shared = _note(
        "memory/short/shared.md",
        note_type="short",
        description=None,
    )
    long_shared = _note("memory/long/shared.md", description="Shared.")
    short_parent = _note(
        "memory/short/hub.md",
        note_type="short",
        description=None,
    )
    long_under_short = _note(
        "memory/child.md",
        parent="memory/short/hub.md",
        description="Child.",
    )
    orphan = _note(
        "memory/orphan.md",
        parent="memory/missing.md",
        description="Orphan.",
    )
    short_nested = _note(
        "memory/short_nested.md",
        note_type="short",
        parent="memory/long/shared.md",
        description=None,
    )

    errors = validate_notes(
        (
            short_shared,
            long_shared,
            short_parent,
            long_under_short,
            orphan,
            short_nested,
        )
    )

    assert "duplicate flat memory filename: shared.md" in _messages(
        errors, "memory/short/shared.md"
    )
    assert "duplicate flat memory filename: shared.md" in _messages(
        errors, "memory/long/shared.md"
    )
    assert "parent must be AGENTS.md or a long memory note" in _messages(
        errors, "memory/child.md"
    )
    assert "parent memory note not found: memory/missing.md" in _messages(
        errors, "memory/orphan.md"
    )
    assert "short memory notes must use parent AGENTS.md" in _messages(
        errors, "memory/short_nested.md"
    )


def test_validate_notes_reports_parent_cycles() -> None:
    note_a = _note("memory/a.md", parent="memory/b.md", description="A.")
    note_b = _note("memory/b.md", parent="memory/c.md", description="B.")
    note_c = _note("memory/c.md", parent="memory/a.md", description="C.")

    errors = validate_notes((note_a, note_b, note_c))

    assert any(
        message.startswith("memory note parent cycle: ")
        for message in _messages(errors, "memory/a.md")
    )
    assert any(
        message.startswith("memory note parent cycle: ")
        for message in _messages(errors, "memory/b.md")
    )
    assert any(
        message.startswith("memory note parent cycle: ")
        for message in _messages(errors, "memory/c.md")
    )
