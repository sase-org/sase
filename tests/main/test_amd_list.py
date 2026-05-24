"""Tests for ``sase amd list`` inventory and rendering."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

from sase.amd.constants import (
    LONG_MEMORY_END_MARKER,
    LONG_MEMORY_START_MARKER,
    PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_FILES,
    SHORT_MEMORY_END_MARKER,
    SHORT_MEMORY_START_MARKER,
)
from sase.amd.inventory import _render_amd_inventory, _build_amd_inventory


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_shims(root: Path, filenames: tuple[str, ...] = PROVIDER_SHIM_FILES) -> None:
    for filename in filenames:
        write(root / filename, PROVIDER_SHIM_CONTENT)


def managed_agents(title: str = "Managed Instructions") -> str:
    return "\n".join(
        [
            f"# {title}",
            "",
            SHORT_MEMORY_START_MARKER,
            "- @memory/short/extra.md",
            "- @memory/short/sase.md",
            SHORT_MEMORY_END_MARKER,
            "",
            LONG_MEMORY_START_MARKER,
            "**`memory/long/generated_skills.md`**  ",
            "Skill pipeline notes.",
            LONG_MEMORY_END_MARKER,
            "",
        ]
    )


def entry_by_path(inventory_path: str, paths_to_entries):
    for entry in paths_to_entries:
        if entry.display_path == inventory_path:
            return entry
    raise AssertionError(f"missing inventory entry: {inventory_path}")


def test_build_inventory_scans_project_agents_from_vcs_root_and_prunes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "repo"
    nested = project / "src" / "pkg"
    nested.mkdir(parents=True)
    (project / ".git").mkdir()
    write(project / "AGENTS.md", managed_agents("Root Instructions"))
    write_shims(project)
    write(
        project / "tools" / "AGENTS.md",
        "# Tools Instructions\n\n@memory/short/tools.md\n",
    )
    write_shims(project / "tools", ("CLAUDE.md", "GEMINI.md"))
    write(project / ".sase" / "AGENTS.md", "# Ignored\n")
    write(project / "node_modules" / "AGENTS.md", "# Ignored\n")
    write(project / "__pycache__" / "AGENTS.md", "# Ignored\n")
    home = tmp_path / "home"

    monkeypatch.chdir(nested)

    inventory = _build_amd_inventory(
        home_root=home,
        chezmoi_root=tmp_path / "chezmoi",
        include_chezmoi=False,
    )

    assert inventory.project_root == project.resolve(strict=False)
    assert [entry.display_path for entry in inventory.entries] == [
        "AGENTS.md",
        "tools/AGENTS.md",
    ]

    root_entry = entry_by_path("AGENTS.md", inventory.entries)
    assert root_entry.scope == "project"
    assert root_entry.h1_title == "Root Instructions"
    assert root_entry.management == "managed"
    assert root_entry.short_memory_refs == 2
    assert root_entry.long_memory_refs == 1
    assert {shim.state for shim in root_entry.provider_shims} == {"exact_shim"}

    tools_entry = entry_by_path("tools/AGENTS.md", inventory.entries)
    assert tools_entry.scope == "project-subdir"
    assert tools_entry.h1_title == "Tools Instructions"
    assert tools_entry.management == "custom"
    assert tools_entry.short_memory_refs == 1
    assert tools_entry.long_memory_refs == 0
    assert [
        (shim.filename, shim.state)
        for shim in tools_entry.provider_shims
        if shim.state == "missing"
    ] == [("QWEN.md", "missing"), ("OPENCODE.md", "missing")]


def test_build_inventory_includes_live_home_and_chezmoi_source(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    home = tmp_path / "home"
    chezmoi = home / ".local" / "share" / "chezmoi" / "home"
    (project / ".git").mkdir(parents=True)
    write(project / "AGENTS.md", "# Project Instructions\n")
    write(home / "AGENTS.md", "# Home Instructions\n")
    write(chezmoi / "AGENTS.md", "# Chezmoi Instructions\n")

    inventory = _build_amd_inventory(
        root=project,
        home_root=home,
        chezmoi_root=chezmoi,
        include_chezmoi=True,
    )

    entries = {(entry.scope, entry.display_path): entry for entry in inventory.entries}
    assert ("project", "AGENTS.md") in entries
    assert ("home", "~/AGENTS.md") in entries
    assert ("chezmoi", "~/.local/share/chezmoi/home/AGENTS.md") in entries
    assert entries[("home", "~/AGENTS.md")].h1_title == "Home Instructions"
    assert (
        entries[("chezmoi", "~/.local/share/chezmoi/home/AGENTS.md")].h1_title
        == "Chezmoi Instructions"
    )


def test_build_inventory_reports_partial_marker_blocks(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    write(
        project / "AGENTS.md",
        "\n".join(
            [
                "# Partial Managed Instructions",
                "",
                SHORT_MEMORY_START_MARKER,
                "- @memory/short/sase.md",
                SHORT_MEMORY_END_MARKER,
                "",
            ]
        ),
    )

    inventory = _build_amd_inventory(
        root=project,
        home_root=tmp_path / "home",
        chezmoi_root=tmp_path / "chezmoi",
        include_chezmoi=False,
    )

    entry = entry_by_path("AGENTS.md", inventory.entries)
    assert entry.management == "missing marker blocks"
    assert entry.short_memory_refs == 1
    assert entry.long_memory_refs == 0


def test_render_amd_inventory_outputs_compact_rich_table(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    write(project / "AGENTS.md", managed_agents("Root Instructions"))
    write_shims(project)
    write(
        project / "tools" / "AGENTS.md",
        "# Tools Instructions\n\n@memory/short/tools.md\n",
    )
    write_shims(project / "tools", ("CLAUDE.md", "GEMINI.md"))
    inventory = _build_amd_inventory(
        root=project,
        home_root=tmp_path / "home",
        chezmoi_root=tmp_path / "chezmoi",
        include_chezmoi=False,
    )

    stream = StringIO()
    console = Console(file=stream, force_terminal=False, width=160)

    _render_amd_inventory(inventory, console=console)

    output = stream.getvalue()
    assert "AMD Inventory" in output
    assert "Agent Markdown Documents" in output
    assert "AGENTS.md" in output
    assert "tools/AGENTS.md" in output
    assert "Root Instructions" in output
    assert "managed" in output
    assert "custom" in output
    assert "short 2 / long 1" in output
    assert "missing: QWEN.md, OPENCODE.md" in output
