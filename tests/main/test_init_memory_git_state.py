"""Tests for ``sase memory init`` git-state helpers."""

from __future__ import annotations

from sase.main.init_memory.git_state import classify, dirty_path_label, parse_status_z


def test_parse_status_z_handles_common_statuses() -> None:
    entries = parse_status_z(
        b" M memory/obsidian.md\0"
        b"A  memory/new.md\0"
        b"D  memory/old.md\0"
        b"?? memory/untracked.md\0"
        b" M memory/space name.md\0"
    )

    assert [(entry.status, entry.path, entry.original_path) for entry in entries] == [
        (" M", "memory/obsidian.md", None),
        ("A ", "memory/new.md", None),
        ("D ", "memory/old.md", None),
        ("??", "memory/untracked.md", None),
        (" M", "memory/space name.md", None),
    ]


def test_parse_status_z_handles_renames_and_copies() -> None:
    entries = parse_status_z(
        b"R  memory/new.md\0memory/old.md\0C  memory/copied.md\0memory/source.md\0"
    )

    assert [(entry.status, entry.path, entry.original_path) for entry in entries] == [
        ("R ", "memory/new.md", "memory/old.md"),
        ("C ", "memory/copied.md", "memory/source.md"),
    ]


def test_classify_partitions_memory_and_other_paths() -> None:
    entries = parse_status_z(
        b" M memory/obsidian.md\0?? memory/new_note.md\0 M src/sase/foo.py\0"
    )

    memory_dirty, other_dirty = classify(entries, "memory")

    assert [dirty.path for dirty in memory_dirty] == [
        "memory/obsidian.md",
        "memory/new_note.md",
    ]
    assert [dirty.path for dirty in other_dirty] == ["src/sase/foo.py"]


def test_classify_renames_include_both_paths() -> None:
    entries = parse_status_z(
        b"R  memory/new.md\0memory/old.md\0"
        b"R  memory/from_src.md\0src/source.md\0"
        b"R  src/new.md\0memory/was.md\0"
    )

    memory_dirty, other_dirty = classify(entries, "memory")

    assert [dirty.path for dirty in memory_dirty] == [
        "memory/new.md",
        "memory/old.md",
        "memory/from_src.md",
        "memory/was.md",
    ]
    assert [dirty.path for dirty in other_dirty] == [
        "src/source.md",
        "src/new.md",
    ]


def test_classify_matches_only_explicit_generated_source_paths() -> None:
    entries = parse_status_z(
        b" M AGENTS.md\0 M demos/tapes/AGENTS.md\0 M docs/AGENTS.md\0 M AGENTS.md.bak\0"
    )

    fold_dirty, other_dirty = classify(
        entries,
        "memory",
        source_paths=("AGENTS.md", "demos/tapes/AGENTS.md"),
    )

    assert [dirty.path for dirty in fold_dirty] == [
        "AGENTS.md",
        "demos/tapes/AGENTS.md",
    ]
    assert [dirty.path for dirty in other_dirty] == [
        "docs/AGENTS.md",
        "AGENTS.md.bak",
    ]


def test_classify_rename_and_copy_source_boundaries_remain_all_or_nothing() -> None:
    entries = parse_status_z(
        b"R  AGENTS.md\0old-AGENTS.md\0C  demos/AGENTS.md\0templates/AGENTS.md\0"
    )

    fold_dirty, other_dirty = classify(
        entries,
        "memory",
        source_paths=("AGENTS.md", "demos/AGENTS.md"),
    )

    assert [dirty.path for dirty in fold_dirty] == ["AGENTS.md", "demos/AGENTS.md"]
    assert [dirty.path for dirty in other_dirty] == [
        "old-AGENTS.md",
        "templates/AGENTS.md",
    ]


def test_dirty_path_label() -> None:
    assert dirty_path_label("??") == "new"
    assert dirty_path_label("A ") == "new"
    assert dirty_path_label(" M") == "modified"
    assert dirty_path_label("D ") == "deleted"
    assert dirty_path_label("R ") == "renamed"
    assert dirty_path_label("UU") == "conflicted"
