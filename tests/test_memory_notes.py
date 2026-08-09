from __future__ import annotations

from pathlib import Path

from sase.memory.notes import (
    AGENTS_PARENT,
    MemoryNote,
    _children_of,
    apply_memory_frontmatter,
    discover_memory_notes,
    parse_memory_note_text,
    render_children_section,
    render_memory_note_references,
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


def test_parse_note_without_frontmatter_marks_required_fields_missing() -> None:
    note = parse_memory_note_text(
        "# Build\n\nBody stays exact.\n",
        "sase/memory/build_and_run.md",
    )

    assert note.path == Path("sase/memory/build_and_run.md")
    assert note.relative_path == "sase/memory/build_and_run.md"
    assert note.type is None
    assert note.type_source == "missing"
    assert note.parent == AGENTS_PARENT
    assert note.parent_source == "missing"
    assert note.description is None
    assert note.body == "# Build\n\nBody stays exact.\n"


def test_parse_flat_note_strips_frontmatter_and_normalizes_description() -> None:
    note = parse_memory_note_text(
        "---\n"
        "type: long\n"
        "parent: sase/memory/hub.md\n"
        "description: |\n"
        "  Child note\n"
        "  details.\n"
        "---\n"
        "# Child\n",
        "sase/memory/child.md",
    )

    assert note.type == "long"
    assert note.type_source == "frontmatter"
    assert note.parent == "sase/memory/hub.md"
    assert note.parent_source == "frontmatter"
    assert note.description == "Child note details."
    assert note.body == "# Child\n"


def test_apply_memory_frontmatter_drops_keywords_and_preserves_other_extra() -> None:
    content = apply_memory_frontmatter(
        "---\nkeywords: [skills]\ndescription: Old description.\n---\n# Body\n",
        note_type="long",
        parent=AGENTS_PARENT,
        description="New description.",
        extra={"keywords": ["replacement"], "owner": "docs"},
    )

    assert content == (
        "---\n"
        "type: long\n"
        "parent: AGENTS.md\n"
        "description: New description.\n"
        "owner: docs\n"
        "---\n"
        "\n"
        "# Body\n"
    )


def test_discover_memory_notes_reads_flat_layout_only(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "README.md", "# Memory\n")
    _write(
        tmp_path / "sase" / "memory" / "flat.md",
        "---\ntype: long\nparent: AGENTS.md\ndescription: Flat note.\n---\n# Flat\n",
    )
    _write(tmp_path / "sase" / "memory" / "short" / "base.md", "# Base\n")
    _write(tmp_path / "sase" / "memory" / "long" / "nested" / "detail.md", "# Detail\n")

    notes = discover_memory_notes(tmp_path)

    assert tuple(note.relative_path for note in notes) == ("sase/memory/flat.md",)
    assert tuple(note.type for note in notes) == ("long",)


def test_discover_memory_notes_reads_legacy_tree_with_canonical_references(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "memory" / "child.md",
        "---\n"
        "type: long\n"
        "parent: memory/parent.md\n"
        "description: Legacy child.\n"
        "---\n"
        "# Child\n",
    )

    (note,) = discover_memory_notes(tmp_path)

    assert note.relative_path == "sase/memory/child.md"
    assert note.source_relative_path == Path("memory/child.md")
    assert note.parent == "sase/memory/parent.md"


def test_children_and_reference_rendering_match_agents_shape() -> None:
    hub = _note("sase/memory/hub.md", description="Hub.")
    child_b = _note(
        "sase/memory/child_b.md",
        parent="sase/memory/hub.md",
        description="Beta child.",
    )
    child_a = _note(
        "sase/memory/child_a.md",
        parent="sase/memory/hub.md",
        description="Alpha child.",
    )
    short_child = _note(
        "sase/memory/short_child.md",
        note_type="short",
        parent="sase/memory/hub.md",
        description=None,
    )

    children = _children_of((child_b, hub, short_child, child_a), hub)

    assert tuple(note.relative_path for note in children) == (
        "sase/memory/child_a.md",
        "sase/memory/child_b.md",
    )
    assert render_memory_note_references(children) == (
        "**`sase/memory/child_a.md`**  \n"
        "Alpha child.\n\n"
        "**`sase/memory/child_b.md`**  \n"
        "Beta child."
    )
    assert render_children_section((child_b, hub, short_child, child_a), hub) == (
        "## Children\n\n"
        "The below files contain detailed reference material. When working in their "
        "domain, you\n"
        "MUST use your `/sase_memory_read` skill to review their contents. Do not "
        "read canonical\n"
        "memory files directly.\n\n"
        "**`sase/memory/child_a.md`**  \n"
        "Alpha child.\n\n"
        "**`sase/memory/child_b.md`**  \n"
        "Beta child.\n"
    )
