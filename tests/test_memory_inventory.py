from __future__ import annotations

from pathlib import Path

from sase.memory.inventory import (
    INSTRUCTION_ROOT_FILENAMES,
    build_memory_inventory,
    unreferenced_memory_files_for_init,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _long_note(*, parent: str = "AGENTS.md", title: str = "Note") -> str:
    return f"---\ntype: long\nparent: {parent}\ndescription: {title}.\n---\n# {title}\n"


def test_inventory_tracks_transitive_loaded_references(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "@sase/memory/base.md\n")
    _write(
        tmp_path / "sase" / "memory" / "base.md",
        "# Base\n@sase/memory/detail.md\n",
    )
    _write(tmp_path / "sase" / "memory" / "detail.md", "# Detail\n")

    inventory = build_memory_inventory(tmp_path)

    assert inventory.entry_for("AGENTS.md").status == "loaded"
    assert inventory.entry_for("AGENTS.md").kind == "instruction"
    assert inventory.entry_for("sase/memory/base.md").status == "loaded"
    assert inventory.entry_for("sase/memory/detail.md").status == "loaded"
    assert inventory.loaded_count == 3
    assert inventory.loaded_stats.line_count == 4


def test_plain_memory_references_stay_referenced_only(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "@sase/memory/base.md\n")
    _write(
        tmp_path / "sase" / "memory" / "base.md",
        "# Base\nSee sase/memory/index.md\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "index.md",
        "# Index\n@sase/memory/detail.md\n",
    )
    _write(tmp_path / "sase" / "memory" / "detail.md", "# Detail\n")

    inventory = build_memory_inventory(tmp_path)

    assert inventory.entry_for("sase/memory/base.md").status == "loaded"
    assert inventory.entry_for("sase/memory/index.md").status == "referenced"
    assert inventory.entry_for("sase/memory/detail.md").status == "available"


def test_duplicate_instruction_roots_count_loaded_memory_once(
    tmp_path: Path,
) -> None:
    for filename in INSTRUCTION_ROOT_FILENAMES:
        if filename == "AGENTS.md":
            _write(tmp_path / filename, "@sase/memory/base.md\n")
        else:
            _write(tmp_path / filename, "@AGENTS.md\n")
    _write(tmp_path / "sase" / "memory" / "base.md", "# Base\n")

    inventory = build_memory_inventory(tmp_path)

    assert tuple(path.name for path in inventory.instruction_roots) == (
        "CLAUDE.md",
        "GEMINI.md",
        "QWEN.md",
        "OPENCODE.md",
        "AGENTS.md",
    )
    assert inventory.loaded_count == 2
    assert inventory.loaded_stats.line_count == 2
    assert inventory.loaded_stats.approx_token_count == 8


def test_inventory_reports_missing_referenced_memory_files(tmp_path: Path) -> None:
    _write(
        tmp_path / "AGENTS.md",
        "@sase/memory/base.md\nsase/memory/missing.md\n",
    )
    _write(tmp_path / "sase" / "memory" / "base.md", "# Base\n")

    inventory = build_memory_inventory(tmp_path)
    missing = inventory.entry_for("sase/memory/missing.md")

    assert missing.status == "missing"
    assert missing.stats is None
    assert len(missing.references) == 1
    reference = missing.references[0]
    assert reference.kind == "plain"
    assert reference.exists is False
    assert reference.source == tmp_path / "AGENTS.md"


def test_inventory_includes_available_unreachable_memory_files(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "@sase/memory/base.md\n")
    _write(tmp_path / "sase" / "memory" / "base.md", "# Base\n")
    _write(tmp_path / "sase" / "memory" / "orphan.md", "# Orphan\n")

    inventory = build_memory_inventory(tmp_path)

    assert inventory.entry_for("sase/memory/base.md").status == "loaded"
    assert inventory.entry_for("sase/memory/orphan.md").status == "available"


def test_outside_root_references_are_ignored(tmp_path: Path) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside.md"
    _write(outside, "# Outside\n")
    _write(
        root / "AGENTS.md",
        f"@sase/memory/base.md\n@{outside}\n@../outside.md\n",
    )
    _write(root / "sase" / "memory" / "base.md", "# Base\n")

    inventory = build_memory_inventory(root)

    assert tuple(entry.relative_path for entry in inventory.entries) == (
        "AGENTS.md",
        "sase/memory/base.md",
    )
    assert inventory.entry_for("sase/memory/base.md").status == "loaded"
    assert unreferenced_memory_files_for_init(root) == ()


def test_home_agents_and_memory_are_included_when_home_root_is_provided(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(home / "AGENTS.md", "@sase/memory/home.md\n")
    _write(home / "sase" / "memory" / "home.md", "# Home\n")

    inventory = build_memory_inventory(project, home_root=home)

    assert inventory.entry_for("~/AGENTS.md").status == "loaded"
    assert inventory.entry_for("~/AGENTS.md").kind == "instruction"
    assert inventory.entry_for("~/sase/memory/home.md").status == "loaded"
    assert inventory.loaded_count == 2
    assert inventory.loaded_stats.line_count == 2


def test_project_and_home_memory_with_same_relative_path_are_unambiguous(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(project / "AGENTS.md", "@sase/memory/shared.md\n")
    _write(project / "sase" / "memory" / "shared.md", "# Project\n")
    _write(home / "AGENTS.md", "@sase/memory/shared.md\n")
    _write(home / "sase" / "memory" / "shared.md", "# Home\n")

    inventory = build_memory_inventory(project, home_root=home)

    assert inventory.entry_for("sase/memory/shared.md").path == (
        project / "sase" / "memory" / "shared.md"
    )
    assert inventory.entry_for("~/sase/memory/shared.md").path == (
        home / "sase" / "memory" / "shared.md"
    )
    assert {entry.relative_path for entry in inventory.entries} >= {
        "AGENTS.md",
        "sase/memory/shared.md",
        "~/AGENTS.md",
        "~/sase/memory/shared.md",
    }


def test_matching_project_and_home_root_are_not_counted_twice(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "@sase/memory/base.md\n")
    _write(tmp_path / "sase" / "memory" / "base.md", "# Base\n")

    inventory = build_memory_inventory(tmp_path, home_root=tmp_path)

    assert tuple(entry.relative_path for entry in inventory.entries) == (
        "AGENTS.md",
        "sase/memory/base.md",
    )
    assert tuple(root.kind for root in inventory.context_roots) == ("project",)
    assert inventory.loaded_count == 2
    assert inventory.loaded_stats.line_count == 2


def test_init_reachability_still_traverses_plain_memory_references(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "AGENTS.md", "sase/memory/index.md\n")
    _write(
        tmp_path / "sase" / "memory" / "index.md",
        "# Index\n@sase/memory/detail.md\n",
    )
    _write(tmp_path / "sase" / "memory" / "detail.md", "# Detail\n")

    assert unreferenced_memory_files_for_init(tmp_path) == ()


def test_init_reachability_treats_short_notes_as_inlined(tmp_path: Path) -> None:
    # Short notes are inlined into AGENTS.md rather than ``@``-imported, so they
    # are reachable even when AGENTS.md does not reference them at all.
    _write(tmp_path / "AGENTS.md", "# Title\n\n## Tier 1 (short-term) Memory\n")
    _write(
        tmp_path / "sase" / "memory" / "note.md",
        "---\ntype: short\nparent: AGENTS.md\n---\n# Note\n",
    )

    assert unreferenced_memory_files_for_init(tmp_path) == ()


def test_inlined_short_note_is_loaded_in_inventory(tmp_path: Path) -> None:
    _write(
        tmp_path / "AGENTS.md",
        "# Title\n\n## Tier 1 (short-term) Memory\n\n"
        "### 1. Note (draft) (note)\n\nInlined body.\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "note.md",
        "---\ntype: short\nparent: AGENTS.md\n---\n# Note (draft)\n\nInlined body.\n",
    )

    inventory = build_memory_inventory(tmp_path)

    assert inventory.entry_for("sase/memory/note.md").status == "loaded"


def test_init_reachability_follows_long_note_parent_metadata(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "AGENTS.md", "sase/memory/hub.md\n")
    _write(tmp_path / "sase" / "memory" / "hub.md", _long_note(title="Hub"))
    _write(
        tmp_path / "sase" / "memory" / "child.md",
        _long_note(parent="sase/memory/hub.md", title="Child"),
    )
    _write(
        tmp_path / "sase" / "memory" / "grandchild.md",
        _long_note(parent="sase/memory/child.md", title="Grandchild"),
    )

    assert unreferenced_memory_files_for_init(tmp_path) == ()


def test_init_reachability_follows_overlay_parent_metadata(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "AGENTS.md", "sase/memory/generated.md\n")
    _write(
        tmp_path / "sase" / "memory" / "child.md",
        _long_note(parent="sase/memory/generated.md", title="Child"),
    )

    unreferenced = unreferenced_memory_files_for_init(
        tmp_path,
        overlay={
            tmp_path / "sase" / "memory" / "generated.md": _long_note(
                title="Generated"
            ),
        },
    )

    assert unreferenced == ()


def test_ignored_paths_drop_unreferenced_note_from_result(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "@sase/memory/base.md\n")
    _write(tmp_path / "sase" / "memory" / "base.md", "# Base\n")
    _write(tmp_path / "sase" / "memory" / "orphan.md", "# Orphan\n")
    _write(tmp_path / "sase" / "memory" / "other_orphan.md", "# Other orphan\n")

    orphan = tmp_path / "sase" / "memory" / "orphan.md"
    other_orphan = tmp_path / "sase" / "memory" / "other_orphan.md"

    assert unreferenced_memory_files_for_init(tmp_path) == (orphan, other_orphan)
    assert unreferenced_memory_files_for_init(tmp_path, ignored_paths=(orphan,)) == (
        other_orphan,
    )
