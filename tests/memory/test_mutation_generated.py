"""Generated-note contract tests for the memory-note mutation engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.init_memory.root_rendering import (
    generated_glossary_memory_relative_path,
    generated_memory_note_relative_paths,
    generated_short_notes,
    render_generated_project_long_memory_contents,
)
from sase.memory.mutation import (
    MemoryGeneratedNoteError,
    delete_memory_note,
    memory_note_digest,
    update_memory_note,
)
from sase.memory.notes import AGENTS_PARENT

from .helpers import create_note, note_text, seed_scope, write_file


def test_generated_memory_note_relative_paths_match_private_helpers() -> None:
    assert tuple(
        path.as_posix()
        for path in generated_memory_note_relative_paths(include_project_memory=False)
    ) == ("sase/memory/sase.md",)
    assert tuple(
        path.as_posix()
        for path in generated_memory_note_relative_paths(include_project_memory=True)
    ) == (
        "sase/memory/sase.md",
        "sase/memory/task_types.md",
        "sase/memory/artifact_relations.md",
        "sase/memory/glossary.md",
        "sase/memory/sase_artifacts.md",
        "sase/memory/sase_beads.md",
        "sase/memory/sase_sizes.md",
    )


def test_generated_paths_cover_every_note_sase_memory_init_generates() -> None:
    """Guard the panel's read-only contract against a new generated note.

    A note added to ``sase memory init`` but not to this set would show up in
    the Memory panel as an ordinary, editable note whose next publish silently
    overwrites the edit.
    """
    long_contents, error = render_generated_project_long_memory_contents()
    assert error is None
    written = {
        *generated_short_notes(
            "generated sase body",
            "generated artifact relations body",
            "generated glossary body",
        ),
        *long_contents,
    }
    contract = {
        path.as_posix()
        for path in generated_memory_note_relative_paths(include_project_memory=True)
    }
    assert written <= contract


def test_generated_glossary_note_is_project_only_and_matches_its_helper() -> None:
    assert generated_glossary_memory_relative_path().as_posix() == (
        "sase/memory/glossary.md"
    )
    assert generated_glossary_memory_relative_path() in (
        generated_memory_note_relative_paths(include_project_memory=True)
    )
    assert generated_glossary_memory_relative_path() not in (
        generated_memory_note_relative_paths(include_project_memory=False)
    )


def test_generated_notes_are_refused_for_create_update_and_delete(
    tmp_path: Path,
) -> None:
    seed_scope(tmp_path)
    generated = tmp_path / "sase" / "memory" / "sase.md"
    write_file(generated, note_text(note_type="core", description="Generated."))
    digest = memory_note_digest(generated.read_bytes())

    with pytest.raises(MemoryGeneratedNoteError, match="sase/memory/sase.md"):
        create_note(tmp_path, "sase", note_type="core", description="Nope.")
    with pytest.raises(MemoryGeneratedNoteError, match="sase/memory/sase.md"):
        update_memory_note(
            scope_key="demo",
            content_root=tmp_path,
            relative_path="sase/memory/sase.md",
            note_type="core",
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
        create_note(tmp_path, "sase_beads", description="Project generated.")
    with pytest.raises(MemoryGeneratedNoteError, match="sase_artifacts"):
        create_note(tmp_path, "sase_artifacts", description="Project generated.")


def test_generated_glossary_note_is_refused_in_a_project_scope(tmp_path: Path) -> None:
    seed_scope(tmp_path)
    glossary = tmp_path / "sase" / "memory" / "glossary.md"
    write_file(glossary, note_text(note_type="core", description="Generated glossary."))
    digest = memory_note_digest(glossary.read_bytes())

    with pytest.raises(MemoryGeneratedNoteError, match="sase/memory/glossary.md"):
        create_note(tmp_path, "glossary", note_type="core", description="Nope.")
    with pytest.raises(MemoryGeneratedNoteError, match="sase/memory/glossary.md"):
        update_memory_note(
            scope_key="demo",
            content_root=tmp_path,
            relative_path="sase/memory/glossary.md",
            note_type="core",
            parent=AGENTS_PARENT,
            description="Nope.",
            expected_digest=digest,
        )
    with pytest.raises(MemoryGeneratedNoteError, match="sase/memory/glossary.md"):
        delete_memory_note(
            scope_key="demo",
            content_root=tmp_path,
            relative_path="sase/memory/glossary.md",
            expected_digest=digest,
        )
    assert glossary.is_file()


def test_home_scope_allows_the_project_only_task_types_name(tmp_path: Path) -> None:
    seed_scope(tmp_path)
    outcome = create_note(
        tmp_path,
        "task_types",
        note_type="core",
        description="Home-authored task types.",
        scope_key="home",
        scope_kind="home",
    )
    assert outcome.relative_path == "sase/memory/task_types.md"
    assert (tmp_path / "sase" / "memory" / "task_types.md").is_file()


def test_home_scope_allows_the_project_only_glossary_name(tmp_path: Path) -> None:
    seed_scope(tmp_path)
    outcome = create_note(
        tmp_path,
        "glossary",
        note_type="core",
        description="Home-authored glossary note.",
        scope_key="home",
        scope_kind="home",
    )
    assert outcome.relative_path == "sase/memory/glossary.md"
    assert (tmp_path / "sase" / "memory" / "glossary.md").is_file()


def test_home_scope_allows_project_only_generated_names(tmp_path: Path) -> None:
    seed_scope(tmp_path)
    outcome = create_note(
        tmp_path,
        "sase_beads",
        description="Home-authored beads note.",
        scope_key="home",
        scope_kind="home",
    )
    assert outcome.relative_path == "sase/memory/sase_beads.md"
    assert (tmp_path / "sase" / "memory" / "sase_beads.md").is_file()

    artifact_outcome = create_note(
        tmp_path,
        "sase_artifacts",
        description="Home-authored artifacts note.",
        scope_key="home",
        scope_kind="home",
    )
    assert artifact_outcome.relative_path == "sase/memory/sase_artifacts.md"
    assert (tmp_path / "sase" / "memory" / "sase_artifacts.md").is_file()
