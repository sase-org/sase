"""Tests for the shared memory-note mutation engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.paths import sase_home
from sase.main.init_memory.root_rendering import generated_memory_note_relative_paths
from sase.memory.inventory_reachability import (
    memory_parent_blockers_for_init,
    unreferenced_memory_files_for_init,
)
from sase.memory.mutation import (
    MemoryConflictError,
    MemoryGeneratedNoteError,
    MemoryMutationError,
    MemoryMutationOutcome,
    MemoryScopeKind,
    MemoryValidationError,
    create_memory_note,
    delete_memory_note,
    memory_note_digest,
    memory_note_relative_path_for_stem,
    update_memory_note,
    validate_memory_note_draft,
)
from sase.memory.notes import (
    AGENTS_PARENT,
    apply_memory_frontmatter,
    discover_memory_notes,
    parse_memory_note_text,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _note_text(
    *,
    note_type: str = "long",
    parent: str = AGENTS_PARENT,
    description: str | None = "A note.",
    body: str = "# Body\n",
) -> str:
    return apply_memory_frontmatter(
        body,
        note_type=note_type,
        parent=parent,
        description=description,
    )


def _seed_scope(root: Path, *, hub: bool = False) -> None:
    agents = "@sase/memory/hub.md\n" if hub else "# Agents\n"
    _write(root / "AGENTS.md", agents)
    if hub:
        _write(
            root / "sase" / "memory" / "hub.md",
            _note_text(description="Hub note.", body="# Hub\n"),
        )


def _create(
    root: Path,
    stem: str,
    *,
    note_type: str = "long",
    parent: str = AGENTS_PARENT,
    description: str | None = "A note.",
    body: str = "",
    scope_key: str = "demo",
    scope_kind: MemoryScopeKind = "project",
) -> MemoryMutationOutcome:
    return create_memory_note(
        scope_key=scope_key,
        content_root=root,
        stem=stem,
        note_type=note_type,
        parent=parent,
        description=description,
        body=body,
        scope_kind=scope_kind,
    )


def test_generated_memory_note_relative_paths_match_private_helpers() -> None:
    assert tuple(
        path.as_posix()
        for path in generated_memory_note_relative_paths(include_project_memory=False)
    ) == (
        "sase/memory/sase.md",
        "sase/memory/task_types.md",
    )
    assert tuple(
        path.as_posix()
        for path in generated_memory_note_relative_paths(include_project_memory=True)
    ) == (
        "sase/memory/sase.md",
        "sase/memory/task_types.md",
        "sase/memory/sase_beads.md",
        "sase/memory/sase_sizes.md",
    )


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
            _note_text(note_type="short", description="Short.", body="# S\n"),
            "sase/memory/brief.md",
        ),
        parse_memory_note_text(
            _note_text(description="Hub.", body="# H\n"),
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
        _note_text(description="Parent.", body="# P\n"),
        "sase/memory/parent.md",
    )
    child = parse_memory_note_text(
        _note_text(parent="sase/memory/parent.md", description="Child.", body="# C\n"),
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
        _note_text(description="Hub.", body="# H\n"),
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
        _note_text(description="Parent.", body="# P\n"),
        "sase/memory/parent.md",
    )
    child = parse_memory_note_text(
        _note_text(parent="sase/memory/parent.md", description="Child.", body="# C\n"),
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


def test_create_writes_canonical_short_and_long_frontmatter(tmp_path: Path) -> None:
    _seed_scope(tmp_path)

    short_outcome = _create(
        tmp_path,
        "gotchas",
        note_type="short",
        description="Always-loaded context.",
        body="# Gotchas\n",
    )
    long_outcome = _create(
        tmp_path,
        "hub",
        note_type="long",
        description="Long-term hub.",
        body="# Hub\n",
    )

    short_path = tmp_path / "sase" / "memory" / "gotchas.md"
    long_path = tmp_path / "sase" / "memory" / "hub.md"
    assert short_path.read_text(encoding="utf-8") == apply_memory_frontmatter(
        "# Gotchas\n",
        note_type="short",
        parent=AGENTS_PARENT,
        description="Always-loaded context.",
    )
    assert long_path.read_text(encoding="utf-8") == apply_memory_frontmatter(
        "# Hub\n",
        note_type="long",
        parent=AGENTS_PARENT,
        description="Long-term hub.",
    )
    assert short_outcome.relative_path == "sase/memory/gotchas.md"
    assert long_outcome.relative_path == "sase/memory/hub.md"
    assert short_outcome.stem == "gotchas"
    assert short_outcome.type == "short"
    assert long_outcome.type == "long"


def test_create_child_note_uses_canonical_parent(tmp_path: Path) -> None:
    _seed_scope(tmp_path, hub=True)

    outcome = _create(
        tmp_path,
        "child",
        parent="hub",
        description="Child of the hub.",
        body="# Child\n",
    )

    path = tmp_path / "sase" / "memory" / "child.md"
    note = parse_memory_note_text(
        path.read_text(encoding="utf-8"), outcome.relative_path
    )
    assert note.parent == "sase/memory/hub.md"
    assert note.type == "long"
    assert note.description == "Child of the hub."


def test_update_preserves_body_and_rewrites_frontmatter(tmp_path: Path) -> None:
    _seed_scope(tmp_path, hub=True)
    body = "# Custom\n\nKeep this **exactly**.\n\n```\ncode\n```\n"
    created = _create(
        tmp_path,
        "child",
        parent="sase/memory/hub.md",
        description="Old description.",
        body=body,
    )
    path = tmp_path / "sase" / "memory" / "child.md"
    digest = memory_note_digest(path.read_bytes())

    outcome = update_memory_note(
        scope_key="demo",
        content_root=tmp_path,
        relative_path=created.relative_path,
        note_type="long",
        parent=AGENTS_PARENT,
        description="New description.",
        expected_digest=digest,
    )

    updated = path.read_text(encoding="utf-8")
    note = parse_memory_note_text(updated, created.relative_path)
    assert note.body == body
    assert note.parent == AGENTS_PARENT
    assert note.description == "New description."
    assert outcome.description == "New description."


def test_update_and_delete_raise_on_digest_conflict(tmp_path: Path) -> None:
    _seed_scope(tmp_path)
    created = _create(tmp_path, "hub", description="Hub.")
    path = tmp_path / "sase" / "memory" / "hub.md"
    stale = memory_note_digest(path.read_bytes())
    path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")

    with pytest.raises(MemoryConflictError, match="reload and retry"):
        update_memory_note(
            scope_key="demo",
            content_root=tmp_path,
            relative_path=created.relative_path,
            note_type="long",
            parent=AGENTS_PARENT,
            description="Hub.",
            expected_digest=stale,
        )
    assert "changed" in path.read_text(encoding="utf-8")

    with pytest.raises(MemoryConflictError, match="reload and retry"):
        delete_memory_note(
            scope_key="demo",
            content_root=tmp_path,
            relative_path=created.relative_path,
            expected_digest=stale,
        )
    assert path.is_file()


def test_generated_notes_are_refused_for_create_update_and_delete(
    tmp_path: Path,
) -> None:
    _seed_scope(tmp_path)
    generated = tmp_path / "sase" / "memory" / "sase.md"
    _write(generated, _note_text(note_type="short", description="Generated."))
    digest = memory_note_digest(generated.read_bytes())

    with pytest.raises(MemoryGeneratedNoteError, match="sase/memory/sase.md"):
        _create(tmp_path, "sase", note_type="short", description="Nope.")
    with pytest.raises(MemoryGeneratedNoteError, match="sase/memory/sase.md"):
        update_memory_note(
            scope_key="demo",
            content_root=tmp_path,
            relative_path="sase/memory/sase.md",
            note_type="short",
            parent=AGENTS_PARENT,
            description="Nope.",
            expected_digest=digest,
        )
    with pytest.raises(MemoryGeneratedNoteError, match="sase/memory/sase.md"):
        delete_memory_note(
            scope_key="demo",
            content_root=tmp_path,
            relative_path="sase/memory/sase.md",
            expected_digest=digest,
        )
    assert generated.is_file()

    with pytest.raises(MemoryGeneratedNoteError, match="sase_beads"):
        _create(tmp_path, "sase_beads", description="Project generated.")


def test_home_scope_allows_project_only_generated_names(tmp_path: Path) -> None:
    _seed_scope(tmp_path)
    outcome = _create(
        tmp_path,
        "sase_beads",
        description="Home-authored beads note.",
        scope_key="home",
        scope_kind="home",
    )
    assert outcome.relative_path == "sase/memory/sase_beads.md"
    assert (tmp_path / "sase" / "memory" / "sase_beads.md").is_file()


def test_delete_refuses_notes_with_children(tmp_path: Path) -> None:
    _seed_scope(tmp_path, hub=True)
    _create(
        tmp_path,
        "child",
        parent="sase/memory/hub.md",
        description="Child.",
    )
    hub = tmp_path / "sase" / "memory" / "hub.md"

    with pytest.raises(MemoryMutationError, match="reparent children first"):
        delete_memory_note(
            scope_key="demo",
            content_root=tmp_path,
            relative_path="sase/memory/hub.md",
            expected_digest=memory_note_digest(hub.read_bytes()),
        )
    assert hub.is_file()
    assert (tmp_path / "sase" / "memory" / "child.md").is_file()


def test_delete_writes_timestamped_backup_then_unlinks(tmp_path: Path) -> None:
    _seed_scope(tmp_path)
    created = _create(tmp_path, "hub", description="To delete.", body="# Keep\n")
    path = tmp_path / "sase" / "memory" / "hub.md"
    original = path.read_bytes()

    outcome = delete_memory_note(
        scope_key="demo",
        content_root=tmp_path,
        relative_path=created.relative_path,
        expected_digest=memory_note_digest(original),
    )

    assert not path.exists()
    assert outcome.backup_path is not None
    assert outcome.backup_path.is_file()
    assert outcome.backup_path.read_bytes() == original
    assert outcome.backup_path.parent == tmp_path / ".sase" / "memory-backups"
    assert outcome.backup_path.name.startswith("hub-")
    assert outcome.backup_path.suffix == ".md"


def test_home_delete_backs_up_under_sase_home(tmp_path: Path) -> None:
    _seed_scope(tmp_path)
    created = _create(
        tmp_path,
        "hub",
        description="Home note.",
        scope_key="home",
        scope_kind="home",
    )
    path = tmp_path / "sase" / "memory" / "hub.md"

    outcome = delete_memory_note(
        scope_key="home",
        content_root=tmp_path,
        relative_path=created.relative_path,
        expected_digest=memory_note_digest(path.read_bytes()),
        scope_kind="home",
    )

    assert outcome.backup_path is not None
    assert outcome.backup_path.is_relative_to(sase_home() / "memory-backups" / "home")
    assert not (tmp_path / ".sase" / "memory-backups").exists()


def test_refuses_traversal_and_non_flat_paths(tmp_path: Path) -> None:
    _seed_scope(tmp_path)
    _create(tmp_path, "hub", description="Hub.")

    with pytest.raises(MemoryValidationError, match="traversal|flat"):
        _create(tmp_path, "../escape", description="Nope.")
    with pytest.raises(MemoryMutationError, match="flat note"):
        update_memory_note(
            scope_key="demo",
            content_root=tmp_path,
            relative_path="sase/memory/../hub.md",
            note_type="long",
            parent=AGENTS_PARENT,
            description="Hub.",
            expected_digest="0" * 64,
        )
    with pytest.raises(MemoryMutationError, match="flat note"):
        delete_memory_note(
            scope_key="demo",
            content_root=tmp_path,
            relative_path="memory/nested/hub.md",
            expected_digest="0" * 64,
        )


def test_create_refuses_to_overwrite_existing_file(tmp_path: Path) -> None:
    _seed_scope(tmp_path)
    _create(tmp_path, "hub", description="First.")

    with pytest.raises(MemoryValidationError, match="already exists"):
        _create(tmp_path, "hub", description="Second.")


def test_failed_atomic_create_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    _seed_scope(tmp_path)

    def boom(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError("link failed")

    monkeypatch.setattr(os, "link", boom)
    with pytest.raises(OSError, match="link failed"):
        _create(tmp_path, "fresh", description="Fresh.")

    write_root = tmp_path / "sase" / "memory"
    assert not (write_root / "fresh.md").exists()
    assert list(write_root.glob(".fresh.md.*.tmp")) == []


def test_create_round_trip_passes_init_reachability(tmp_path: Path) -> None:
    _seed_scope(tmp_path)
    _create(
        tmp_path,
        "gotchas",
        note_type="short",
        description="Always loaded.",
        body="# Gotchas\n",
    )
    _create(tmp_path, "hub", description="Reachable hub.", body="# Hub\n")
    (tmp_path / "AGENTS.md").write_text(
        "@sase/memory/hub.md\n",
        encoding="utf-8",
    )
    _create(
        tmp_path,
        "child",
        parent="sase/memory/hub.md",
        description="Reachable child.",
        body="# Child\n",
    )

    assert memory_parent_blockers_for_init(tmp_path) == ()
    assert unreferenced_memory_files_for_init(tmp_path) == ()
    notes = discover_memory_notes(tmp_path)
    assert {note.relative_path for note in notes} == {
        "sase/memory/gotchas.md",
        "sase/memory/hub.md",
        "sase/memory/child.md",
    }


def test_update_legacy_source_preserves_legacy_path(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "# Agents\n")
    _write(
        tmp_path / "memory" / "legacy.md",
        _note_text(description="Legacy note.", body="# Legacy\n"),
    )
    path = tmp_path / "memory" / "legacy.md"
    digest = memory_note_digest(path.read_bytes())

    update_memory_note(
        scope_key="demo",
        content_root=tmp_path,
        relative_path="sase/memory/legacy.md",
        note_type="long",
        parent=AGENTS_PARENT,
        description="Updated legacy.",
        expected_digest=digest,
    )

    assert path.is_file()
    assert not (tmp_path / "sase" / "memory" / "legacy.md").exists()
    note = parse_memory_note_text(
        path.read_text(encoding="utf-8"), "sase/memory/legacy.md"
    )
    assert note.description == "Updated legacy."
    assert note.body == "# Legacy\n"


def test_memory_note_relative_path_for_stem() -> None:
    assert memory_note_relative_path_for_stem("gotchas") == "sase/memory/gotchas.md"
