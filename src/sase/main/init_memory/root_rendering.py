"""Rendering helpers for memory root initialization."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from sase.amd.init import AmdMemorySyncPlan
from sase.memory.inventory import MemoryStats, stats_for_text
from sase.memory.notes import (
    AGENTS_PARENT,
    MemoryNote,
    apply_memory_frontmatter,
    discover_memory_notes,
    parse_memory_note_text,
)

from .formatting import format_generated_memory_markdown
from .models import LinkedRepoMemoryEntry, MemoryExpectedFile

MEMORY_DIRECTORY_MAP_FILENAME = "memory-directory-map.png"
MEMORY_DIRECTORY_MAP_RELATIVE_PATH = (
    Path("memory") / "assets" / MEMORY_DIRECTORY_MAP_FILENAME
)


@dataclass(frozen=True)
class _MemoryReadmeNote:
    note: MemoryNote
    stats: MemoryStats


def _extend_workspace_section(lines: list[str], project_name: str) -> None:
    lines.extend(
        [
            f"## Ephemeral `{project_name}_<N>` Workspace Directories",
            "",
            "SASE runs agents (like you) from ephemeral workspace directories, which are full clones of the "
            f"{project_name} repo. These",
            f"directories are named `{project_name}_<N>` where `<N>` is some integer. You need to be mindful not to run commands",
            "outside of these workspace directories, since they have their own isolated virtual environments.",
            "",
            "IMPORTANT: Do NOT mention your workspace directory (or any sibling workspace directory) in any plan files "
            "that you generate using your `/sase_plan` skill. The agent(s) that implement the plan might not run in the "
            "same workspace directory as you!",
            "",
        ]
    )


def _linked_repo_list_item(entry: LinkedRepoMemoryEntry) -> str:
    return f"- `{entry.name}`: {entry.description}"


def _extend_linked_repository_section(
    lines: list[str], entries: Iterable[LinkedRepoMemoryEntry]
) -> None:
    lines.extend(
        [
            "## Linked Repositories",
            "",
        ]
    )
    entries = tuple(entries)
    if entries:
        lines.append("Configured linked repositories for this context:")
        lines.append("")
        for entry in entries:
            lines.append(_linked_repo_list_item(entry))
    else:
        lines.append("No linked repositories are configured for this context.")
        lines.append("")
        return

    lines.extend(
        [
            "",
            "When you need to make changes to files in a numbered-workspace linked repo or need to review numbered-workspace linked repo code, agents MUST run:",
            "",
            "```bash",
            'sase workspace open -p <linked_repo> -r "<reason>" <workspace_num>',
            "```",
            "",
            "`<workspace_num>` must be the workspace number assigned to the primary repo "
            "(check what directory you were started in to figure this out). Use the path printed by",
            "`sase workspace open` as the only linked repo path for numbered-workspace linked reads/writes.",
            "",
            "IMPORTANT REMINDER: Do NOT attempt to look for a linked repo in any other way than by using `sase workspace open`!",
            "",
        ]
    )


def _render_sase_memory(
    entries: Iterable[LinkedRepoMemoryEntry], *, project_name: str | None = None
) -> str:
    lines = ["# SASE = Structured Agentic Software Engineering", ""]
    if project_name is not None:
        _extend_workspace_section(lines, project_name)

    _extend_linked_repository_section(lines, entries)
    return "\n".join(lines)


def _generated_sase_memory_relative_path() -> Path:
    return Path("memory") / "sase.md"


def generated_sase_memory_body(
    entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
) -> str:
    """Return the prettier-stable ``memory/sase.md`` body (no frontmatter)."""
    return format_generated_memory_markdown(
        _render_sase_memory(entries, project_name=project_name)
    )


def _generated_sase_memory_content(generated_sase_body: str) -> str:
    return apply_memory_frontmatter(
        generated_sase_body,
        note_type="short",
        parent=AGENTS_PARENT,
    )


def read_memory_directory_map_bytes() -> bytes:
    source = resources.files("sase.memory").joinpath(
        "assets",
        MEMORY_DIRECTORY_MAP_FILENAME,
    )
    with resources.as_file(source) as source_path:
        return source_path.read_bytes()


def _memory_note_overlay_by_relative_path(
    root: Path,
    overlay: dict[Path, str],
) -> dict[str, str]:
    root_resolved = root.resolve(strict=False)
    result: dict[str, str] = {}
    for path, content in overlay.items():
        resolved = path.resolve(strict=False)
        try:
            relative = resolved.relative_to(root_resolved)
        except ValueError:
            relative = path
        result[relative.as_posix()] = content
    return result


def _read_memory_note_text(root: Path, relative_path: str) -> str | None:
    try:
        return (root / relative_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _discover_memory_readme_notes(
    root: Path,
    *,
    overlay: dict[Path, str],
) -> tuple[_MemoryReadmeNote, ...]:
    text_by_relative_path = {
        note.relative_path: _read_memory_note_text(root, note.relative_path)
        for note in discover_memory_notes(root)
    }
    text_by_relative_path.update(_memory_note_overlay_by_relative_path(root, overlay))

    rows: list[_MemoryReadmeNote] = []
    for relative_path, text in text_by_relative_path.items():
        if text is None:
            continue
        note = parse_memory_note_text(text, relative_path)
        rows.append(_MemoryReadmeNote(note=note, stats=stats_for_text(text)))

    rows.sort(
        key=lambda row: (
            {"short": 0, "long": 1}.get(row.note.type or "", 2),
            row.note.relative_path,
        )
    )
    return tuple(rows)


def _note_description(note: MemoryNote) -> str:
    return note.description or "No description set."


def _note_type(note: MemoryNote) -> str:
    return note.type or "missing"


def _extend_memory_notes_section(
    lines: list[str],
    note_rows: tuple[_MemoryReadmeNote, ...],
) -> None:
    lines.extend(["## Memory Notes", ""])
    if not note_rows:
        lines.extend(
            [
                "No memory notes exist yet. Run `sase memory init` to create the generated `memory/sase.md` note.",
                "",
            ]
        )
        return

    for index, row in enumerate(note_rows):
        if index:
            lines.append("")
        note = row.note
        lines.extend(
            [
                f"### `{note.relative_path}`",
                "",
                f"- Type: `{_note_type(note)}`",
                f"- Description: {_note_description(note)}",
                f"- Parent: `{note.parent}`",
                f"- Lines: {row.stats.line_count}",
                f"- Approx. tokens: {row.stats.approx_token_count}",
            ]
        )
    lines.append("")


def _extend_memory_statistics_section(
    lines: list[str],
    note_rows: tuple[_MemoryReadmeNote, ...],
) -> None:
    short_count = sum(1 for row in note_rows if row.note.type == "short")
    long_count = sum(1 for row in note_rows if row.note.type == "long")
    total_lines = sum(row.stats.line_count for row in note_rows)
    total_tokens = sum(row.stats.approx_token_count for row in note_rows)
    lines.extend(
        [
            "## Statistics",
            "",
            f"- Total notes: {len(note_rows)}",
            f"- Short notes: {short_count}",
            f"- Long notes: {long_count}",
            f"- Total lines: {total_lines}",
            f"- Total approx. tokens: {total_tokens}",
            "",
        ]
    )


def _render_memory_readme(
    root: Path,
    *,
    overlay: dict[Path, str] | None = None,
) -> str:
    note_rows = _discover_memory_readme_notes(root, overlay=overlay or {})
    lines = [
        "# SASE Memory",
        "",
        "The `memory/` directory holds agent-facing project context. It separates compact, always-loaded notes from detailed reference notes that agents read only when relevant.",
        "",
        "![How SASE memory files are used](assets/memory-directory-map.png)",
        "",
        "## How Memory Files Are Used",
        "",
        "- Non-README Markdown files live directly under `memory/` and use YAML frontmatter for `type`, `parent`, and `description`.",
        "- `type: short` notes are Tier 1 context. `sase memory init` inlines them into `AGENTS.md`, then copies that exact content to each provider instruction shim.",
        "- `type: long` notes are detailed reference material for Tier 2. They require a `description` and are fetched explicitly with audited `sase memory read` calls.",
        "- `memory/sase.md` is generated from SASE configuration and captures linked repositories plus workspace rules.",
        "- `memory/README.md` is generated from the notes themselves, including the statistics below.",
        "",
        "### Frontmatter Schema",
        "",
        "- `type`: `short` for always-loaded notes or `long` for read-on-demand reference notes.",
        "- `parent`: `AGENTS.md` for top-level notes, or `memory/<note>.md` when a long note belongs under another long note.",
        "- `description`: required for long notes and used in generated agent instructions and this README.",
        "- `keywords`: optional extra metadata preserved by memory tooling when present.",
        "",
        "### Linking",
        "",
        "- `@memory/<note>.md` loads a note into agent context when the root instruction file is read.",
        "- Plain `memory/<note>.md` mentions keep a note discoverable without loading it automatically.",
        "- Long notes parented under another long note are reachable through that parent for validation.",
        "",
    ]
    _extend_memory_notes_section(lines, note_rows)
    _extend_memory_statistics_section(lines, note_rows)
    lines.extend(
        [
            "## Commands",
            "",
            "- `sase memory list` shows loaded, referenced, available, and missing memory files.",
            "- `sase memory init` creates or refreshes generated memory files, renders `AGENTS.md` and provider shims from `AGENTS.template.md`, and refreshes this asset-backed README.",
            "- Set `amd_agents_template` (or `amd_agents_minimal_template`) to a root-relative project template in `sase.yml`; home roots can instead use `AGENTS.template.md` (or `AGENTS.minimal.template.md`) in the SASE user config directory.",
            "- `sase memory init --check` reports drift without writing files.",
            "- `sase memory read <note>.md --reason <reason>` reads a long note and records an audited access event.",
            "- `sase memory write` proposes a new long-term memory note for review.",
            "- `sase memory review` reviews pending memory proposals.",
            "- `sase memory log` summarizes audited long-memory reads.",
            "",
        ]
    )
    return "\n".join(lines)


def render_expected_memory_files(
    root: Path,
    linked_entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
    amd_sync: AmdMemorySyncPlan | None = None,
    generated_sase_body: str | None = None,
) -> tuple[MemoryExpectedFile, ...]:
    if generated_sase_body is None:
        generated_sase_body = generated_sase_memory_body(
            linked_entries, project_name=project_name
        )
    generated_sase_path = root / _generated_sase_memory_relative_path()
    generated_sase_content = _generated_sase_memory_content(generated_sase_body)
    note_overlay = {generated_sase_path: generated_sase_content}
    if amd_sync is not None:
        note_overlay.update(
            {update.path: update.content for update in amd_sync.description_updates}
        )
    expected: list[MemoryExpectedFile] = [
        MemoryExpectedFile(
            path=generated_sase_path,
            content=generated_sase_content,
            detail="generated SASE memory",
        ),
        MemoryExpectedFile(
            path=root / "memory" / "README.md",
            content=format_generated_memory_markdown(
                _render_memory_readme(root, overlay=note_overlay)
            ),
            detail="memory README",
        ),
        MemoryExpectedFile(
            path=root / MEMORY_DIRECTORY_MAP_RELATIVE_PATH,
            content=read_memory_directory_map_bytes(),
            detail="memory directory map asset",
        ),
    ]
    if amd_sync is not None and amd_sync.agents_content is not None:
        expected.extend(
            MemoryExpectedFile(
                path=update.path,
                content=update.content,
                detail="long-memory description frontmatter",
                stale_operation="update",
            )
            for update in amd_sync.description_updates
        )
        expected.append(
            MemoryExpectedFile(
                path=root / "AGENTS.md",
                content=format_generated_memory_markdown(amd_sync.agents_content),
                detail="managed AGENTS.md",
                stale_operation="overwrite",
            )
        )
    elif amd_sync is not None and amd_sync.fallback_agents_content is not None:
        expected.append(
            MemoryExpectedFile(
                path=root / "AGENTS.md",
                content=format_generated_memory_markdown(
                    amd_sync.fallback_agents_content
                ),
                detail="agent instruction file",
                write_policy="create_if_missing",
            )
        )
    return tuple(expected)


def generated_short_notes(generated_sase_body: str) -> dict[str, str]:
    """Return the freshly generated short-note bodies keyed by relative path."""
    return {_generated_sase_memory_relative_path().as_posix(): generated_sase_body}
