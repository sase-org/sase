"""Create, update, and delete tests for the memory-note mutation engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.paths import sase_home
from sase.memory.inventory_reachability import (
    memory_parent_blockers_for_init,
    unreferenced_memory_files_for_init,
)
from sase.memory.mutation import (
    MemoryConflictError,
    MemoryMutationError,
    MemoryValidationError,
    delete_memory_note,
    memory_note_digest,
    update_memory_note,
)
from sase.memory.notes import (
    AGENTS_PARENT,
    apply_memory_frontmatter,
    discover_memory_notes,
    parse_memory_note_text,
)

from .helpers import create_note, note_text, seed_scope, write_file


def test_create_writes_canonical_short_and_long_frontmatter(tmp_path: Path) -> None:
    seed_scope(tmp_path)

    short_outcome = create_note(
        tmp_path,
        "gotchas",
        note_type="core",
        description="Always-loaded context.",
        body="# Gotchas\n",
    )
    long_outcome = create_note(
        tmp_path,
        "hub",
        note_type="reference",
        description="Long-term hub.",
        body="# Hub\n",
    )

    short_path = tmp_path / "sase" / "memory" / "gotchas.md"
    long_path = tmp_path / "sase" / "memory" / "hub.md"
    assert short_path.read_text(encoding="utf-8") == apply_memory_frontmatter(
        "# Gotchas\n",
        note_type="core",
        parent=AGENTS_PARENT,
        description="Always-loaded context.",
    )
    assert long_path.read_text(encoding="utf-8") == apply_memory_frontmatter(
        "# Hub\n",
        note_type="reference",
        parent=AGENTS_PARENT,
        description="Long-term hub.",
    )
    assert short_outcome.relative_path == "sase/memory/gotchas.md"
    assert long_outcome.relative_path == "sase/memory/hub.md"
    assert short_outcome.stem == "gotchas"
    assert short_outcome.type == "core"
    assert long_outcome.type == "reference"


def test_create_child_note_uses_canonical_parent(tmp_path: Path) -> None:
    seed_scope(tmp_path, hub=True)

    outcome = create_note(
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
    assert note.type == "reference"
    assert note.description == "Child of the hub."


def test_update_preserves_body_and_rewrites_frontmatter(tmp_path: Path) -> None:
    seed_scope(tmp_path, hub=True)
    body = "# Custom\n\nKeep this **exactly**.\n\n```\ncode\n```\n"
    created = create_note(
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
        note_type="reference",
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


def test_update_preserves_priority_while_rewriting_frontmatter(tmp_path: Path) -> None:
    seed_scope(tmp_path)
    path = tmp_path / "sase" / "memory" / "core.md"
    write_file(
        path,
        "---\ntype: core\nparent: AGENTS.md\npriority: 5\n---\n# Core\n",
    )
    digest = memory_note_digest(path.read_bytes())

    update_memory_note(
        scope_key="demo",
        content_root=tmp_path,
        relative_path="sase/memory/core.md",
        note_type="core",
        parent=AGENTS_PARENT,
        description="New description.",
        expected_digest=digest,
    )

    updated = path.read_text(encoding="utf-8")
    note = parse_memory_note_text(updated, "sase/memory/core.md")
    assert note.priority == 5
    assert "priority: 5\n" in updated
    assert "description: New description.\n" in updated


def test_update_and_delete_raise_on_digest_conflict(tmp_path: Path) -> None:
    seed_scope(tmp_path)
    created = create_note(tmp_path, "hub", description="Hub.")
    path = tmp_path / "sase" / "memory" / "hub.md"
    stale = memory_note_digest(path.read_bytes())
    path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")

    with pytest.raises(MemoryConflictError, match="reload and retry"):
        update_memory_note(
            scope_key="demo",
            content_root=tmp_path,
            relative_path=created.relative_path,
            note_type="reference",
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


def test_delete_refuses_notes_with_children(tmp_path: Path) -> None:
    seed_scope(tmp_path, hub=True)
    create_note(
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
    seed_scope(tmp_path)
    created = create_note(tmp_path, "hub", description="To delete.", body="# Keep\n")
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
    seed_scope(tmp_path)
    created = create_note(
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
    seed_scope(tmp_path)
    create_note(tmp_path, "hub", description="Hub.")

    with pytest.raises(MemoryValidationError, match="traversal|flat"):
        create_note(tmp_path, "../escape", description="Nope.")
    with pytest.raises(MemoryMutationError, match="flat note"):
        update_memory_note(
            scope_key="demo",
            content_root=tmp_path,
            relative_path="sase/memory/../hub.md",
            note_type="reference",
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
    seed_scope(tmp_path)
    create_note(tmp_path, "hub", description="First.")

    with pytest.raises(MemoryValidationError, match="already exists"):
        create_note(tmp_path, "hub", description="Second.")


def test_failed_atomic_create_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    seed_scope(tmp_path)

    def boom(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError("link failed")

    monkeypatch.setattr(os, "link", boom)
    with pytest.raises(OSError, match="link failed"):
        create_note(tmp_path, "fresh", description="Fresh.")

    write_root = tmp_path / "sase" / "memory"
    assert not (write_root / "fresh.md").exists()
    assert list(write_root.glob(".fresh.md.*.tmp")) == []


def test_create_round_trip_passes_init_reachability(tmp_path: Path) -> None:
    seed_scope(tmp_path)
    create_note(
        tmp_path,
        "gotchas",
        note_type="core",
        description="Always loaded.",
        body="# Gotchas\n",
    )
    create_note(tmp_path, "hub", description="Reachable hub.", body="# Hub\n")
    (tmp_path / "AGENTS.md").write_text(
        "@sase/memory/hub.md\n",
        encoding="utf-8",
    )
    create_note(
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
    write_file(tmp_path / "AGENTS.md", "# Agents\n")
    write_file(
        tmp_path / "memory" / "legacy.md",
        note_text(description="Legacy note.", body="# Legacy\n"),
    )
    path = tmp_path / "memory" / "legacy.md"
    digest = memory_note_digest(path.read_bytes())

    update_memory_note(
        scope_key="demo",
        content_root=tmp_path,
        relative_path="sase/memory/legacy.md",
        note_type="reference",
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
