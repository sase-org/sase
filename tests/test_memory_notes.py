from __future__ import annotations

from pathlib import Path

from sase.memory.notes import (
    AGENTS_PARENT,
    DEFAULT_MEMORY_PRIORITY,
    MemoryNote,
    _children_of,
    _prettier_stable_frontmatter,
    apply_memory_frontmatter,
    collapse_description,
    discover_memory_notes,
    parse_memory_note_text,
    _render_memory_note_references,
    render_children_section,
    render_long_memory_sections,
)
from sase.memory.text_filter import filter_memory_notes


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _note(
    path: str,
    *,
    note_type: str = "reference",
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
        "type: reference\n"
        "parent: sase/memory/hub.md\n"
        "description: |\n"
        "  Child note\n"
        "  details.\n"
        "---\n"
        "# Child\n",
        "sase/memory/child.md",
    )

    assert note.type == "reference"
    assert note.type_source == "frontmatter"
    assert note.parent == "sase/memory/hub.md"
    assert note.parent_source == "frontmatter"
    assert note.description == "Child note\ndetails."
    assert note.body == "# Child\n"


def test_parse_memory_note_priority_defaults_to_missing() -> None:
    note = parse_memory_note_text(
        "---\ntype: core\nparent: AGENTS.md\n---\n# Core\n",
        "sase/memory/core.md",
    )

    assert note.priority == DEFAULT_MEMORY_PRIORITY
    assert note.priority_source == "missing"


def test_parse_memory_note_priority_accepts_non_negative_integer() -> None:
    note = parse_memory_note_text(
        "---\ntype: core\nparent: AGENTS.md\npriority: 0\n---\n# Core\n",
        "sase/memory/core.md",
    )

    assert note.priority == 0
    assert note.priority_source == "frontmatter"


def test_parse_memory_note_priority_rejects_bool_and_non_integer_values() -> None:
    for raw_value in ("true", '"5"', "5.5", "-1", "null"):
        note = parse_memory_note_text(
            f"---\ntype: core\nparent: AGENTS.md\npriority: {raw_value}\n---\n# Core\n",
            "sase/memory/core.md",
        )
        assert note.priority == DEFAULT_MEMORY_PRIORITY
        assert note.priority_source == "invalid"


def test_apply_memory_frontmatter_renders_priority_only_when_non_default() -> None:
    default_priority = apply_memory_frontmatter(
        "# Core\n",
        note_type="core",
        priority=DEFAULT_MEMORY_PRIORITY,
    )
    explicit_priority = apply_memory_frontmatter(
        "# Core\n",
        note_type="core",
        priority=5,
        description="Core note.",
    )

    assert "priority:" not in default_priority
    assert explicit_priority.startswith(
        "---\n"
        "type: core\n"
        "parent: AGENTS.md\n"
        "priority: 5\n"
        "description: Core note.\n"
        "---\n"
    )


def test_apply_memory_frontmatter_preserves_priority_on_unrelated_rewrite() -> None:
    original = (
        "---\n"
        "type: reference\n"
        "parent: AGENTS.md\n"
        "priority: 5\n"
        "description: Old.\n"
        "---\n"
        "# Body\n"
    )

    rewritten = apply_memory_frontmatter(
        original,
        note_type="reference",
        parent=AGENTS_PARENT,
        description="New.",
    )

    assert rewritten.startswith(
        "---\ntype: reference\nparent: AGENTS.md\npriority: 5\ndescription: New.\n---\n"
    )
    assert parse_memory_note_text(rewritten, "sase/memory/ref.md").priority == 5


def test_parse_memory_note_text_normalizes_legacy_types() -> None:
    short_note = parse_memory_note_text(
        "---\ntype: short\nparent: AGENTS.md\n---\n# Core\n",
        "sase/memory/core.md",
    )
    long_note = parse_memory_note_text(
        "---\ntype: long\nparent: AGENTS.md\ndescription: Detail.\n---\n# Ref\n",
        "sase/memory/ref.md",
    )
    core_note = parse_memory_note_text(
        "---\ntype: core\nparent: AGENTS.md\n---\n# Core\n",
        "sase/memory/core2.md",
    )
    reference_note = parse_memory_note_text(
        "---\ntype: reference\nparent: AGENTS.md\ndescription: Detail.\n---\n# Ref\n",
        "sase/memory/ref2.md",
    )
    bogus_note = parse_memory_note_text(
        "---\ntype: bogus\nparent: AGENTS.md\n---\n# Bogus\n",
        "sase/memory/bogus.md",
    )

    assert short_note.type == "core"
    assert short_note.type_source == "frontmatter"
    assert long_note.type == "reference"
    assert long_note.type_source == "frontmatter"
    assert core_note.type == "core"
    assert reference_note.type == "reference"
    assert bogus_note.type == "bogus"
    assert bogus_note.type_source == "invalid"


def test_multiline_description_round_trips_as_literal_block() -> None:
    description = "Lead paragraph.\n\n- One\n- Two\n\nTrailer."

    content = apply_memory_frontmatter(
        "# Body\n",
        note_type="reference",
        parent=AGENTS_PARENT,
        description=description,
    )

    assert (
        "description: |-\n  Lead paragraph.\n\n  - One\n  - Two\n\n  Trailer.\n"
    ) in content
    note = parse_memory_note_text(content, "sase/memory/block.md")
    assert note.description == description
    assert (
        apply_memory_frontmatter(
            content,
            note_type="reference",
            parent=AGENTS_PARENT,
            description=note.description,
        )
        == content
    )


def test_multiline_description_with_frontmatter_marker_collapses_safely() -> None:
    content = apply_memory_frontmatter(
        "# Body\n",
        note_type="reference",
        parent=AGENTS_PARENT,
        description="Lead.\n---\nTrailer.",
    )

    assert "description: Lead. --- Trailer.\n" in content
    assert "description: |" not in content
    note = parse_memory_note_text(content, "sase/memory/unsafe.md")
    assert note.description == "Lead. --- Trailer."


def test_collapse_description_flattens_block_to_one_line() -> None:
    assert (
        collapse_description("Lead.\n\n- One\n  wrapped\n\nTrailer.")
        == "Lead. - One wrapped Trailer."
    )
    assert collapse_description(None) is None
    assert collapse_description(" \n\t ") is None


def test_prettier_stable_frontmatter_leaves_literal_block_scalar_untouched() -> None:
    dumped = "type: reference\nparent: AGENTS.md\ndescription: |-\n  Lead.\n\n  - One\n"

    assert _prettier_stable_frontmatter(dumped) == dumped.rstrip("\n")


def test_apply_memory_frontmatter_drops_keywords_and_preserves_other_extra() -> None:
    content = apply_memory_frontmatter(
        "---\nkeywords: [skills]\ndescription: Old description.\n---\n# Body\n",
        note_type="reference",
        parent=AGENTS_PARENT,
        description="New description.",
        extra={"keywords": ["replacement"], "owner": "docs"},
    )

    assert content == (
        "---\n"
        "type: reference\n"
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
        "---\ntype: reference\nparent: AGENTS.md\ndescription: Flat note.\n---\n# Flat\n",
    )
    _write(tmp_path / "sase" / "memory" / "short" / "base.md", "# Base\n")
    _write(tmp_path / "sase" / "memory" / "long" / "nested" / "detail.md", "# Detail\n")

    notes = discover_memory_notes(tmp_path)

    assert tuple(note.relative_path for note in notes) == ("sase/memory/flat.md",)
    assert tuple(note.type for note in notes) == ("reference",)


def test_discover_memory_notes_reads_legacy_tree_with_canonical_references(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "memory" / "child.md",
        "---\n"
        "type: reference\n"
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
        note_type="core",
        parent="sase/memory/hub.md",
        description=None,
    )

    children = _children_of((child_b, hub, short_child, child_a), hub)

    assert tuple(note.relative_path for note in children) == (
        "sase/memory/child_a.md",
        "sase/memory/child_b.md",
    )
    assert _render_memory_note_references(children) == (
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


def test_render_long_memory_sections_orders_and_filters_notes() -> None:
    short_note = _note(
        "sase/memory/aaa.md",
        note_type="core",
        description="Must not appear.",
    )
    later = _note("sase/memory/later.md", description="Later.")
    earlier = _note("sase/memory/earlier.md", description="Earlier.")

    assert render_long_memory_sections((later, short_note, earlier)) == (
        "### `sase/memory/earlier.md`\n"
        "\n"
        "Earlier.\n"
        "\n"
        "### `sase/memory/later.md`\n"
        "\n"
        "Later."
    )


def test_render_long_memory_sections_preserves_block_descriptions() -> None:
    note = MemoryNote(
        path=Path("sase/memory/block.md"),
        type="reference",
        parent=AGENTS_PARENT,
        description="Lead paragraph.\n\n- One\n- Two\n\nTrailer.",
        body="# Block\n",
        frontmatter={},
        type_source="frontmatter",
        parent_source="frontmatter",
    )

    assert render_long_memory_sections((note,)) == (
        "### `sase/memory/block.md`\n\nLead paragraph.\n\n- One\n- Two\n\nTrailer."
    )


def test_render_long_memory_sections_omits_empty_description_body() -> None:
    empty = MemoryNote(
        path=Path("sase/memory/empty.md"),
        type="reference",
        parent=AGENTS_PARENT,
        description="",
        body="",
        frontmatter={},
        type_source="frontmatter",
        parent_source="frontmatter",
    )
    missing = MemoryNote(
        path=Path("sase/memory/missing.md"),
        type="reference",
        parent=AGENTS_PARENT,
        description=None,
        body="",
        frontmatter={},
        type_source="frontmatter",
        parent_source="frontmatter",
    )

    assert render_long_memory_sections((empty, missing)) == (
        "### `sase/memory/empty.md`\n\n### `sase/memory/missing.md`"
    )


def test_filter_memory_notes_matches_stem_and_description_not_body_by_default() -> None:
    stem_hit = _note("sase/memory/alpha.md", description="Hub note.")
    description_hit = _note("sase/memory/beta.md", description="Mentions Alpha here.")
    body_only = parse_memory_note_text(
        "---\ntype: reference\nparent: AGENTS.md\ndescription: Other.\n---\n# Alpha in body\n",
        "sase/memory/gamma.md",
    )

    notes = (stem_hit, description_hit, body_only)
    matched = filter_memory_notes(notes, pattern="alpha", include_bodies=False)
    assert tuple(note.path.stem for note in matched) == ("alpha", "beta")

    with_bodies = filter_memory_notes(notes, pattern="alpha", include_bodies=True)
    assert tuple(note.path.stem for note in with_bodies) == ("alpha", "beta", "gamma")

    assert filter_memory_notes(notes, pattern=None, include_bodies=False) == notes
    assert filter_memory_notes(notes, pattern="", include_bodies=True) == notes
