"""Tests for ``sase memory init`` git-state helpers."""

from __future__ import annotations

from sase.main.init_memory.git_state import classify, dirty_path_label, parse_status_z


def test_parse_status_z_handles_common_statuses() -> None:
    entries = parse_status_z(
        b" M sase/memory/obsidian.md\0"
        b"A  sase/memory/new.md\0"
        b"D  sase/memory/old.md\0"
        b"?? sase/memory/untracked.md\0"
        b" M sase/memory/space name.md\0"
    )

    assert [(entry.status, entry.path, entry.original_path) for entry in entries] == [
        (" M", "sase/memory/obsidian.md", None),
        ("A ", "sase/memory/new.md", None),
        ("D ", "sase/memory/old.md", None),
        ("??", "sase/memory/untracked.md", None),
        (" M", "sase/memory/space name.md", None),
    ]


def test_parse_status_z_handles_renames_and_copies() -> None:
    entries = parse_status_z(
        b"R  sase/memory/new.md\0sase/memory/old.md\0C  sase/memory/copied.md\0sase/memory/source.md\0"
    )

    assert [(entry.status, entry.path, entry.original_path) for entry in entries] == [
        ("R ", "sase/memory/new.md", "sase/memory/old.md"),
        ("C ", "sase/memory/copied.md", "sase/memory/source.md"),
    ]


def test_classify_partitions_memory_and_other_paths() -> None:
    entries = parse_status_z(
        b" M sase/memory/obsidian.md\0?? sase/memory/new_note.md\0 M src/sase/foo.py\0"
    )

    memory_dirty, other_dirty = classify(entries, "sase/memory")

    assert [dirty.path for dirty in memory_dirty] == [
        "sase/memory/obsidian.md",
        "sase/memory/new_note.md",
    ]
    assert [dirty.path for dirty in other_dirty] == ["src/sase/foo.py"]


def test_classify_renames_include_both_paths() -> None:
    entries = parse_status_z(
        b"R  sase/memory/new.md\0sase/memory/old.md\0"
        b"R  sase/memory/from_src.md\0src/source.md\0"
        b"R  src/new.md\0sase/memory/was.md\0"
    )

    memory_dirty, other_dirty = classify(entries, "sase/memory")

    assert [dirty.path for dirty in memory_dirty] == [
        "sase/memory/new.md",
        "sase/memory/old.md",
        "sase/memory/from_src.md",
        "sase/memory/was.md",
    ]
    assert [dirty.path for dirty in other_dirty] == [
        "src/source.md",
        "src/new.md",
    ]


def test_classify_transition_includes_canonical_and_legacy_memory_paths() -> None:
    entries = parse_status_z(
        b" M sase/memory/new.md\0D  memory/old.md\0 M src/sase/foo.py\0"
    )

    memory_dirty, other_dirty = classify(
        entries,
        ("sase/memory", "memory"),
    )

    assert [dirty.path for dirty in memory_dirty] == [
        "sase/memory/new.md",
        "memory/old.md",
    ]
    assert [dirty.path for dirty in other_dirty] == ["src/sase/foo.py"]


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
