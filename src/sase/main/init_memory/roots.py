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
from .models import (
    MemoryExpectedFile,
    MemoryFileChange,
    MemoryRootPlan,
    MemoryRootResult,
    SiblingMemoryEntry,
)


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
            "When you need to make changes to files in a sibling repository or need to review sibling repository code, agents MUST run:",
            "",
            "```bash",
            "sase workspace open -p <sibling_repo> <workspace_num>",
            "```",
            "",
            "`<workspace_num>` must be the workspace number assigned to the primary repo "
            "(check what directory you were started in to figure this out). Use the path printed by",
            "`sase workspace open` as the only repository path for sibling reads/writes.",
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
        "The `memory/` directory holds agent-facing project context. Use "
        "`sase memory list` to inspect what a launch would load or reference, "
        "and `sase memory init` to create or refresh generated memory files.\n\n"
        "- `memory/short/` contains short-term context that is loaded when an "
        "instruction root reaches it through an `@memory/...` reference.\n"
        "- `memory/long/` contains detailed long-term context. Plain "
        "`memory/...` mentions make files visible as references, but do not "
        "load file contents unless the file is also reached through an "
        "`@...` reference.\n"
        "- Dynamic memory files under `.sase/memory/` are prompt-dependent. "
        "They are generated only during agent launch when keyword-tagged "
        "long-term sources match the prompt, not by `sase memory list`.\n"
    )


def _render_expected_memory_files(
    root: Path,
    sibling_entries: Iterable[SiblingMemoryEntry],
    *,
    project_name: str | None = None,
) -> tuple[MemoryExpectedFile, ...]:
    expected: list[MemoryExpectedFile] = [
        MemoryExpectedFile(
            path=root / "memory" / "short" / "sase.md",
            content=_render_sase_memory(sibling_entries, project_name=project_name),
            detail="generated SASE memory",
        ),
        MemoryExpectedFile(
            path=root / "memory" / "README.md",
            content=_render_memory_readme(),
            detail="memory README",
        ),
        MemoryExpectedFile(
            path=root / "AGENTS.md",
            content=MINIMAL_AGENTS_CONTENT,
            detail="agent instruction file",
            write_policy="create_if_missing",
        ),
    ]
    expected.extend(
        MemoryExpectedFile(
            path=root / filename,
            content=PROVIDER_SHIM_CONTENT,
            detail="provider instruction shim",
            stale_operation="overwrite",
        )
        for filename in PROVIDER_SHIM_FILES
    )
    return tuple(expected)


def _compare_expected_memory_files(
    expected_files: Iterable[MemoryExpectedFile],
) -> tuple[MemoryFileChange, ...]:
    changes: list[MemoryFileChange] = []
    for expected in expected_files:
        if not expected.path.exists():
            changes.append(
                MemoryFileChange(
                    path=expected.path,
                    operation="create",
                    detail=expected.detail,
                )
            )
            continue
        if expected.write_policy == "create_if_missing":
            continue
        try:
            current = expected.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            changes.append(
                MemoryFileChange(
                    path=expected.path,
                    operation=expected.stale_operation,
                    detail=expected.detail,
                )
            )
            continue
        if current != expected.content:
            changes.append(
                MemoryFileChange(
                    path=expected.path,
                    operation=expected.stale_operation,
                    detail=expected.detail,
                )
            )
    return tuple(changes)


def _write_expected_file(expected: MemoryExpectedFile) -> bool:
    if expected.write_policy == "create_if_missing" and expected.path.exists():
        return False
    try:
        if (
            expected.path.exists()
            and expected.path.read_text(encoding="utf-8") == expected.content
        ):
            return False
    except OSError:
        pass
    expected.path.parent.mkdir(parents=True, exist_ok=True)
    expected.path.write_text(expected.content, encoding="utf-8")
    return True


def _apply_expected_memory_files(
    expected_files: Iterable[MemoryExpectedFile],
) -> tuple[Path, ...]:
    written: list[Path] = []
    for expected in expected_files:
        if _write_expected_file(expected):
            written.append(expected.path)
    return tuple(written)


def _is_memory_markdown_path(root: Path, path: Path) -> bool:
    root_resolved = root.resolve(strict=False)
    try:
        relative = path.resolve(strict=False).relative_to(root_resolved)
    except ValueError:
        return False
    return (
        len(relative.parts) >= 3
        and relative.parts[0] == "memory"
        and relative.parts[1] in {"short", "long"}
        and path.suffix == ".md"
    )


def _validation_overlay_for_expected_files(
    root: Path,
    expected_files: Iterable[MemoryExpectedFile],
) -> dict[Path, str]:
    overlay: dict[Path, str] = {}
    agents_path = (root / "AGENTS.md").resolve(strict=False)
    for expected in expected_files:
        resolved = expected.path.resolve(strict=False)
        if _is_memory_markdown_path(root, expected.path):
            overlay[resolved] = expected.content
            continue
        if (
            resolved == agents_path
            and expected.write_policy == "create_if_missing"
            and not expected.path.exists()
        ):
            overlay[resolved] = expected.content
    return overlay


def plan_memory_root(
    root: Path,
    sibling_entries: Iterable[SiblingMemoryEntry],
    *,
    project_name: str | None = None,
) -> MemoryRootPlan:
    expected_files = _render_expected_memory_files(
        root,
        sibling_entries,
        project_name=project_name,
    )
    overlay = _validation_overlay_for_expected_files(root, expected_files)
    return MemoryRootPlan(
        root=root,
        changes=_compare_expected_memory_files(expected_files),
        unreferenced=unreferenced_memory_files(root, overlay=overlay),
    )


def initialize_memory_root(
    root: Path,
    sibling_entries: Iterable[SiblingMemoryEntry],
    *,
    project_name: str | None = None,
) -> MemoryRootResult:
    expected_files = _render_expected_memory_files(
        root,
        sibling_entries,
        project_name=project_name,
    )
    written = _apply_expected_memory_files(expected_files)

    (root / "memory" / "long").mkdir(parents=True, exist_ok=True)

    return MemoryRootResult(
        root=root,
        written_paths=written,
        unreferenced=unreferenced_memory_files(root),
    )
