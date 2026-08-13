"""Tests for ``sase memory agent-docs list`` inventory and rendering."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

from sase.amd.constants import (
    HOME_PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_FILES,
)
from sase.amd._agents_doc import parse_amd_agents_document
from sase.amd.inventory import _render_amd_inventory, _build_amd_inventory

_LEGACY_MARKER_PREFIX = "sase-" + "amd"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_shims(
    root: Path,
    filenames: tuple[str, ...] = PROVIDER_SHIM_FILES,
    *,
    content: str = PROVIDER_SHIM_CONTENT,
) -> None:
    for filename in filenames:
        write(root / filename, content)


def legacy_marker(name: str) -> str:
    return f"<!-- {_LEGACY_MARKER_PREFIX}:{name} -->"


def managed_agents(
    title: str = "Managed Instructions",
    *,
    markered: bool = False,
    numbered: bool = False,
) -> str:
    short_markers = ([legacy_marker("short-memory:start")] if markered else []) + (
        [legacy_marker("short-memory:end")] if markered else []
    )
    long_markers = ([legacy_marker("long-memory:start")] if markered else []) + (
        [legacy_marker("long-memory:end")] if markered else []
    )
    tier1_heading = (
        "## 1. Tier 1 (short-term) Memory"
        if numbered
        else "## Tier 1 (short-term) Memory"
    )
    tier2_heading = (
        "## 2. Tier 2 (long-term) Memory"
        if numbered
        else "## Tier 2 (long-term) Memory"
    )
    first_short = "### 1.1 Extra (extra)" if numbered else "### 1. Extra (extra)"
    second_short = (
        "### 1.2 SASE = Structured Agentic Software Engineering (sase)"
        if numbered
        else "### 2. SASE = Structured Agentic Software Engineering (sase)"
    )
    return "\n".join(
        [
            f"# {title}",
            "",
            tier1_heading,
            "",
            "The following memory files contain core context.",
            "",
            *short_markers[:1],
            first_short,
            "",
            second_short,
            *short_markers[1:],
            "",
            tier2_heading,
            "",
            "Prose mentions @sase/memory/prose.md and sase/memory/prose.md.",
            "",
            *long_markers[:1],
            "**`sase/memory/generated_skills.md`**  ",
            "Skill pipeline notes.",
            *long_markers[1:],
            "",
        ]
    )


def test_amd_parser_accepts_numbered_and_unnumbered_tier_headings() -> None:
    unnumbered = parse_amd_agents_document(managed_agents())
    numbered = parse_amd_agents_document(managed_agents(numbered=True))

    for parsed in (unnumbered, numbered):
        assert parsed.has_short_section
        assert parsed.has_long_section
        assert parsed.short_memory_paths == (
            "sase/memory/extra.md",
            "sase/memory/sase.md",
        )
        assert tuple(entry.path for entry in parsed.long_memory_entries) == (
            "sase/memory/generated_skills.md",
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
    root_agents = managed_agents("Root Instructions")
    write(project / "AGENTS.md", root_agents)
    write_shims(project, content=root_agents)
    write(
        project / "tools" / "AGENTS.md",
        "# Tools Instructions\n\n@sase/memory/tools.md\n",
    )
    write_shims(project / "tools", ("CLAUDE.md", "GEMINI.md"))
    write(project / ".sase" / "AGENTS.md", "# Ignored\n")
    write(project / "node_modules" / "AGENTS.md", "# Ignored\n")
    write(project / "__pycache__" / "AGENTS.md", "# Ignored\n")
    write(project / "sase" / "repos" / "linked" / "AGENTS.md", "# Ignored\n")
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


def test_build_inventory_uses_home_specific_provider_shim_status(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    home = tmp_path / "home"
    (project / ".git").mkdir(parents=True)
    write(project / "AGENTS.md", "# Project Instructions\n")
    write(home / "AGENTS.md", "# Home Instructions\n")
    # A full copy of ``AGENTS.md`` is the canonical exact shim; a legacy
    # ``@AGENTS.md`` import is still recognized as a (migratable) shim.
    write(home / "CLAUDE.md", "# Home Instructions\n")
    write(home / "GEMINI.md", PROVIDER_SHIM_CONTENT)

    inventory = _build_amd_inventory(
        root=project,
        home_root=home,
        chezmoi_root=tmp_path / "chezmoi",
        include_chezmoi=False,
    )

    home_entry = entry_by_path("~/AGENTS.md", inventory.entries)

    assert [(shim.filename, shim.state) for shim in home_entry.provider_shims] == [
        ("CLAUDE.md", "exact_shim"),
        ("GEMINI.md", "shim"),
        ("QWEN.md", "missing"),
        ("OPENCODE.md", "missing"),
    ]


def test_build_inventory_uses_chezmoi_home_provider_shim_status(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    home = tmp_path / "home"
    chezmoi = tmp_path / "chezmoi" / "home"
    (project / ".git").mkdir(parents=True)
    write(project / "AGENTS.md", "# Project Instructions\n")
    write(chezmoi / "AGENTS.md", "# Chezmoi Instructions\n")
    # Chezmoi home now writes static provider copies (no ``.tmpl``); a full copy
    # of ``AGENTS.md`` is the canonical exact shim.
    write_shims(chezmoi, content="# Chezmoi Instructions\n")

    inventory = _build_amd_inventory(
        root=project,
        home_root=home,
        chezmoi_root=chezmoi,
        include_chezmoi=True,
    )

    chezmoi_entry = next(
        entry for entry in inventory.entries if entry.scope == "chezmoi"
    )

    assert {shim.state for shim in chezmoi_entry.provider_shims} == {"exact_shim"}


def test_build_inventory_reports_legacy_chezmoi_plain_shim_status(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    home = tmp_path / "home"
    chezmoi = tmp_path / "chezmoi" / "home"
    (project / ".git").mkdir(parents=True)
    write(project / "AGENTS.md", "# Project Instructions\n")
    write(chezmoi / "AGENTS.md", "# Chezmoi Instructions\n")
    write(chezmoi / "CLAUDE.md", HOME_PROVIDER_SHIM_CONTENT)

    inventory = _build_amd_inventory(
        root=project,
        home_root=home,
        chezmoi_root=chezmoi,
        include_chezmoi=True,
    )

    chezmoi_entry = next(
        entry for entry in inventory.entries if entry.scope == "chezmoi"
    )

    assert [(shim.filename, shim.state) for shim in chezmoi_entry.provider_shims] == [
        ("CLAUDE.md", "shim"),
        ("GEMINI.md", "missing"),
        ("QWEN.md", "missing"),
        ("OPENCODE.md", "missing"),
    ]


def test_build_inventory_treats_markered_current_structure_as_managed(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    write(project / "AGENTS.md", managed_agents(markered=True))

    inventory = _build_amd_inventory(
        root=project,
        home_root=tmp_path / "home",
        chezmoi_root=tmp_path / "chezmoi",
        include_chezmoi=False,
    )

    entry = entry_by_path("AGENTS.md", inventory.entries)
    assert entry.management == "managed"
    assert entry.short_memory_refs == 2
    assert entry.long_memory_refs == 1


def test_build_inventory_treats_numbered_current_structure_as_managed(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    write(project / "AGENTS.md", managed_agents(numbered=True))

    inventory = _build_amd_inventory(
        root=project,
        home_root=tmp_path / "home",
        chezmoi_root=tmp_path / "chezmoi",
        include_chezmoi=False,
    )

    entry = entry_by_path("AGENTS.md", inventory.entries)
    assert entry.management == "managed"
    assert entry.short_memory_refs == 2
    assert entry.long_memory_refs == 1


def test_build_inventory_counts_inlined_short_memory_headers(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    write(
        project / "AGENTS.md",
        "\n".join(
            [
                "# Managed Instructions",
                "",
                "## Tier 1 (short-term) Memory",
                "",
                "The following memories contain core (always loaded) context:",
                "",
                "### 1. Extra (draft) (extra)",
                "",
                "#### A Section",
                "",
                "body",
                "",
                "### 2. SASE = Structured Agentic Software Engineering (sase)",
                "",
                "#### Workspace",
                "",
                "more body",
                "",
                "## Tier 2 (long-term) Memory",
                "",
                "**`sase/memory/generated_skills.md`**  ",
                "Skill pipeline notes.",
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
    assert entry.management == "managed"
    # The two numbered ``### Title (file)`` headers count; the inlined ``####``
    # body headings must not be miscounted as short memory.
    assert entry.short_memory_refs == 2
    assert entry.long_memory_refs == 1


def test_build_inventory_reports_partial_visible_amd_structure(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    write(
        project / "AGENTS.md",
        "\n".join(
            [
                "# Partial Managed Instructions",
                "",
                "## Tier 1 (short-term) Memory",
                "",
                "- @sase/memory/sase.md",
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
    assert entry.management == "incomplete managed structure"
    assert entry.short_memory_refs == 1
    assert entry.long_memory_refs == 0


def test_build_inventory_uses_broad_memory_counts_for_custom_documents(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    write(
        project / "AGENTS.md",
        "# Custom Instructions\n\n@sase/memory/base.md\nsase/memory/detail.md\n",
    )

    inventory = _build_amd_inventory(
        root=project,
        home_root=tmp_path / "home",
        chezmoi_root=tmp_path / "chezmoi",
        include_chezmoi=False,
    )

    entry = entry_by_path("AGENTS.md", inventory.entries)
    assert entry.management == "custom"
    assert entry.short_memory_refs == 1
    assert entry.long_memory_refs == 1


def test_render_agent_docs_inventory_outputs_compact_rich_table(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    root_agents = managed_agents("Root Instructions")
    write(project / "AGENTS.md", root_agents)
    write_shims(project, content=root_agents)
    tools_agents = "# Tools Instructions\n\n@sase/memory/tools.md\n"
    write(project / "tools" / "AGENTS.md", tools_agents)
    write_shims(project / "tools", ("CLAUDE.md", "GEMINI.md"), content=tools_agents)
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
    assert "Agent Documents" in output
    assert "Agent Markdown Documents" in output
    assert "AGENTS.md" in output
    assert "tools/AGENTS.md" in output
    assert "Root Instructions" in output
    assert "managed" in output
    assert "custom" in output
    assert "short 2 / long 1" in output
    assert "missing: QWEN.md, OPENCODE.md" in output
