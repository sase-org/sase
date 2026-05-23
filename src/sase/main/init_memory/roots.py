"""Memory root rendering and initialization helpers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .constants import (
    MINIMAL_AGENTS_CONTENT,
    PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_FILES,
)
from .inventory import unreferenced_memory_files
from .models import MemoryRootResult, SiblingMemoryEntry


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
        ]
    )


def _extend_sibling_repository_section(
    lines: list[str], entries: Iterable[SiblingMemoryEntry]
) -> None:
    lines.extend(
        [
            "## Sibling Repositories",
            "",
        ]
    )
    entries = tuple(entries)
    if entries:
        lines.append("Configured sibling repositories for this context:")
        lines.append("")
        for entry in entries:
            lines.append(f"- `{entry.name}`: {entry.description}")
    else:
        lines.append("No sibling repositories are configured for this context.")

    lines.extend(
        [
            "",
            "When a sibling repository needs changes, agents MUST run:",
            "",
            "```bash",
            "sase workspace open -p <sibling_repo> <workspace_num>",
            "```",
            "",
            "`<workspace_num>` must be the workspace number assigned to the primary repo "
            "(check what directory you were started in to figure this out). Use the path printed by",
            "`sase workspace open` as the only repository path for sibling edits.",
            "",
        ]
    )


def _render_sase_memory(
    entries: Iterable[SiblingMemoryEntry], *, project_name: str | None = None
) -> str:
    if project_name is None:
        lines = ["# SASE Memory", ""]
    else:
        lines = ["# SASE = Structured Agentic Software Engineering", ""]
        _extend_workspace_section(lines, project_name)

    _extend_sibling_repository_section(lines, entries)
    return "\n".join(lines)


def _render_memory_readme() -> str:
    return (
        "# SASE Memory\n\n"
        "The `memory/` directory holds agent-facing project context.\n\n"
        "- `memory/short/` contains always-loaded context referenced from "
        "`AGENTS.md`.\n"
        "- `memory/long/` contains detailed context that must be reachable "
        "from `AGENTS.md` directly or through another\n"
        "  referenced memory file.\n"
    )


def _write_text_if_changed(path: Path, content: str) -> bool:
    try:
        if path.exists() and path.read_text(encoding="utf-8") == content:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _ensure_agents_file(root: Path) -> Path | None:
    agents_path = root / "AGENTS.md"
    if agents_path.exists():
        return None
    agents_path.write_text(MINIMAL_AGENTS_CONTENT, encoding="utf-8")
    return agents_path


def _ensure_provider_shims(root: Path) -> list[Path]:
    written: list[Path] = []
    for filename in PROVIDER_SHIM_FILES:
        path = root / filename
        if _write_text_if_changed(path, PROVIDER_SHIM_CONTENT):
            written.append(path)
    return written


def initialize_memory_root(
    root: Path,
    sibling_entries: Iterable[SiblingMemoryEntry],
    *,
    project_name: str | None = None,
) -> MemoryRootResult:
    written: list[Path] = []

    (root / "memory" / "short").mkdir(parents=True, exist_ok=True)
    (root / "memory" / "long").mkdir(parents=True, exist_ok=True)

    memory_path = root / "memory" / "short" / "sase.md"
    if _write_text_if_changed(
        memory_path,
        _render_sase_memory(sibling_entries, project_name=project_name),
    ):
        written.append(memory_path)

    readme_path = root / "memory" / "README.md"
    if _write_text_if_changed(readme_path, _render_memory_readme()):
        written.append(readme_path)

    agents_path = _ensure_agents_file(root)
    if agents_path is not None:
        written.append(agents_path)
    written.extend(_ensure_provider_shims(root))

    return MemoryRootResult(
        root=root,
        written_paths=tuple(written),
        unreferenced=unreferenced_memory_files(root),
    )
