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


def test_inventory_tracks_transitive_loaded_references(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "@memory/short/base.md\n")
    _write(
        tmp_path / "memory" / "short" / "base.md",
        "# Base\n@memory/long/detail.md\n",
    )
    _write(tmp_path / "memory" / "long" / "detail.md", "# Detail\n")

    inventory = build_memory_inventory(tmp_path)

    assert inventory.entry_for("AGENTS.md").status == "loaded"
    assert inventory.entry_for("AGENTS.md").kind == "instruction"
    assert inventory.entry_for("memory/short/base.md").status == "loaded"
    assert inventory.entry_for("memory/long/detail.md").status == "loaded"
    assert inventory.loaded_count == 3
    assert inventory.loaded_stats.line_count == 4


def test_plain_memory_references_stay_referenced_only(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "@memory/short/base.md\n")
    _write(
        tmp_path / "memory" / "short" / "base.md",
        "# Base\nSee memory/long/index.md\n",
    )
    _write(
        tmp_path / "memory" / "long" / "index.md",
        "# Index\n@memory/long/detail.md\n",
    )
    _write(tmp_path / "memory" / "long" / "detail.md", "# Detail\n")

    inventory = build_memory_inventory(tmp_path)

    assert inventory.entry_for("memory/short/base.md").status == "loaded"
    assert inventory.entry_for("memory/long/index.md").status == "referenced"
    assert inventory.entry_for("memory/long/detail.md").status == "available"


def test_duplicate_instruction_roots_count_loaded_memory_once(
    tmp_path: Path,
) -> None:
    for filename in INSTRUCTION_ROOT_FILENAMES:
        if filename == "AGENTS.md":
            _write(tmp_path / filename, "@memory/short/base.md\n")
        else:
            _write(tmp_path / filename, "@AGENTS.md\n")
    _write(tmp_path / "memory" / "short" / "base.md", "# Base\n")

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
        "@memory/short/base.md\nmemory/long/missing.md\n",
    )
    _write(tmp_path / "memory" / "short" / "base.md", "# Base\n")

    inventory = build_memory_inventory(tmp_path)
    missing = inventory.entry_for("memory/long/missing.md")

    assert missing.status == "missing"
    assert missing.stats is None
    assert len(missing.references) == 1
    reference = missing.references[0]
    assert reference.kind == "plain"
    assert reference.exists is False
    assert reference.source == tmp_path / "AGENTS.md"


def test_inventory_includes_available_unreachable_memory_files(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "@memory/short/base.md\n")
    _write(tmp_path / "memory" / "short" / "base.md", "# Base\n")
    _write(tmp_path / "memory" / "long" / "orphan.md", "# Orphan\n")

    inventory = build_memory_inventory(tmp_path)

    assert inventory.entry_for("memory/short/base.md").status == "loaded"
    assert inventory.entry_for("memory/long/orphan.md").status == "available"


def test_outside_root_references_are_ignored(tmp_path: Path) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside.md"
    _write(outside, "# Outside\n")
    _write(
        root / "AGENTS.md",
        f"@memory/short/base.md\n@{outside}\n@../outside.md\n",
    )
    _write(root / "memory" / "short" / "base.md", "# Base\n")

    inventory = build_memory_inventory(root)

    assert tuple(entry.relative_path for entry in inventory.entries) == (
        "AGENTS.md",
        "memory/short/base.md",
    )
    assert inventory.entry_for("memory/short/base.md").status == "loaded"
    assert unreferenced_memory_files_for_init(root) == ()


def test_home_agents_and_memory_are_included_when_home_root_is_provided(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(home / "AGENTS.md", "@memory/short/home.md\n")
    _write(home / "memory" / "short" / "home.md", "# Home\n")

    inventory = build_memory_inventory(project, home_root=home)

    assert inventory.entry_for("~/AGENTS.md").status == "loaded"
    assert inventory.entry_for("~/AGENTS.md").kind == "instruction"
    assert inventory.entry_for("~/memory/short/home.md").status == "loaded"
    assert inventory.loaded_count == 2
    assert inventory.loaded_stats.line_count == 2


def test_project_and_home_memory_with_same_relative_path_are_unambiguous(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(project / "AGENTS.md", "@memory/short/shared.md\n")
    _write(project / "memory" / "short" / "shared.md", "# Project\n")
    _write(home / "AGENTS.md", "@memory/short/shared.md\n")
    _write(home / "memory" / "short" / "shared.md", "# Home\n")

    inventory = build_memory_inventory(project, home_root=home)

    assert inventory.entry_for("memory/short/shared.md").path == (
        project / "memory" / "short" / "shared.md"
    )
    assert inventory.entry_for("~/memory/short/shared.md").path == (
        home / "memory" / "short" / "shared.md"
    )
    assert {entry.relative_path for entry in inventory.entries} >= {
        "AGENTS.md",
        "memory/short/shared.md",
        "~/AGENTS.md",
        "~/memory/short/shared.md",
    }


def test_matching_project_and_home_root_are_not_counted_twice(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "@memory/short/base.md\n")
    _write(tmp_path / "memory" / "short" / "base.md", "# Base\n")

    inventory = build_memory_inventory(tmp_path, home_root=tmp_path)

    assert tuple(entry.relative_path for entry in inventory.entries) == (
        "AGENTS.md",
        "memory/short/base.md",
    )
    assert tuple(root.kind for root in inventory.context_roots) == ("project",)
    assert inventory.loaded_count == 2
    assert inventory.loaded_stats.line_count == 2


def test_init_reachability_still_traverses_plain_memory_references(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "AGENTS.md", "memory/long/index.md\n")
    _write(
        tmp_path / "memory" / "long" / "index.md",
        "# Index\n@memory/long/detail.md\n",
    )
    _write(tmp_path / "memory" / "long" / "detail.md", "# Detail\n")

    assert unreferenced_memory_files_for_init(tmp_path) == ()


def test_memory_relative_long_paths_reference_canonical_memory_files(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "AGENTS.md",
        'sase memory read long/index.md --reason "Need index context"\n',
    )
    _write(
        tmp_path / "memory" / "long" / "index.md",
        "# Index\n@memory/long/detail.md\n",
    )
    _write(tmp_path / "memory" / "long" / "detail.md", "# Detail\n")

    inventory = build_memory_inventory(tmp_path)
    index = inventory.entry_for("memory/long/index.md")

    assert index.status == "referenced"
    assert len(index.references) == 1
    assert index.references[0].kind == "plain"
    assert index.references[0].token == "long/index.md"
    assert unreferenced_memory_files_for_init(tmp_path) == ()


def test_inventory_tolerates_invalid_utf8_files(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "@memory/long/broken.md\n")
    broken = tmp_path / "memory" / "long" / "broken.md"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b"\xff")

    inventory = build_memory_inventory(tmp_path)
    entry = inventory.entry_for("memory/long/broken.md")

    assert entry.status == "loaded"
    assert entry.stats is None
    assert entry.references[0].exists is True
