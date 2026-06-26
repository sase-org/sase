"""Memory root rendering and initialization helpers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import cast

from sase.amd.init import AmdMemorySyncPlan, plan_amd_memory_sync
from sase.amd.inline_memory import inline_memory_section
from sase.amd._shared import (
    ProviderShimPlan,
    apply_planned_delete,
    provider_shim_plan,
)
from sase.memory.notes import (
    AGENTS_PARENT,
    apply_memory_frontmatter,
)
from .formatting import format_generated_memory_markdown
from .inventory import unreferenced_memory_files
from .models import (
    MemoryExpectedFile,
    MemoryFileChange,
    MemoryRootPlan,
    MemoryRootResult,
    LinkedRepoMemoryEntry,
    MemoryChangeOperation,
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
            "IMPORTANT: Do NOT mention your workspace directory (or any sibling workspace directory) in any plan files "
            "that you generate using your `/sase_plan` skill. The agent(s) that implement the plan might not run in the "
            "same workspace directory as you!",
            "",
        ]
    )


def _static_linked_repo_display_path(entry: LinkedRepoMemoryEntry) -> str:
    display_path = entry.path
    if not display_path.endswith("/"):
        display_path = f"{display_path}/"
    return display_path


def _linked_repo_list_item(entry: LinkedRepoMemoryEntry) -> str:
    text = f"- `{entry.name}`: {entry.description}"
    if entry.workspace_strategy == "none":
        text += (
            " This repo is defined in the "
            f"`{_static_linked_repo_display_path(entry)}` directory."
        )
    return text


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

    numbered_entries = tuple(
        entry for entry in entries if entry.workspace_strategy != "none"
    )

    if numbered_entries:
        lines.extend(
            [
                "",
                "When you need to make changes to files in a numbered-workspace linked repository or need to review numbered-workspace linked repository code, agents MUST run:",
                "",
                "```bash",
                'sase workspace open -p <linked_repo> -r "<reason>" <workspace_num>',
                "```",
                "",
                "`<workspace_num>` must be the workspace number assigned to the primary repo "
                "(check what directory you were started in to figure this out). Use the path printed by",
                "`sase workspace open` as the only repository path for numbered-workspace linked reads/writes.",
                "",
            ]
        )
    else:
        lines.append("")


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


def _generated_sase_memory_body(
    entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
) -> str:
    """Return the prettier-stable ``memory/sase.md`` body (no frontmatter)."""
    return format_generated_memory_markdown(
        _render_sase_memory(entries, project_name=project_name)
    )


def _render_memory_readme() -> str:
    return (
        "# SASE Memory\n\n"
        "The `memory/` directory holds agent-facing project context. Use "
        "`sase memory list` to inspect what a launch would load or reference, "
        "and `sase memory init` to create or refresh generated memory files.\n\n"
        "- Non-README Markdown files live directly under `memory/` and use "
        "YAML frontmatter for `type` and `parent`.\n"
        "- `type: short` notes are always-loaded context when reached through "
        "an `@memory/...` reference.\n"
        "- `type: long` notes are detailed reference material. They require a "
        "`description` and are read with `sase memory read`.\n"
        "- Long notes can set `parent: memory/<note>.md` to appear in that "
        "parent note's `## Children` section.\n"
    )


def _minimal_agents_content(generated_sase_body: str) -> str:
    """Return a self-contained minimal ``AGENTS.md`` with ``sase.md`` inlined."""
    section = inline_memory_section(
        _generated_sase_memory_relative_path().as_posix(),
        generated_sase_body,
    )
    return f"# Agent Instructions\n\n{section}"


def _render_expected_memory_files(
    root: Path,
    linked_entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
    amd_sync: AmdMemorySyncPlan | None = None,
    generated_sase_body: str | None = None,
) -> tuple[MemoryExpectedFile, ...]:
    if generated_sase_body is None:
        generated_sase_body = _generated_sase_memory_body(
            linked_entries, project_name=project_name
        )
    expected: list[MemoryExpectedFile] = [
        MemoryExpectedFile(
            path=root / _generated_sase_memory_relative_path(),
            content=apply_memory_frontmatter(
                generated_sase_body,
                note_type="short",
                parent=AGENTS_PARENT,
            ),
            detail="generated SASE memory",
        ),
        MemoryExpectedFile(
            path=root / "memory" / "README.md",
            content=format_generated_memory_markdown(_render_memory_readme()),
            detail="memory README",
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
                content=amd_sync.agents_content,
                detail="managed AGENTS.md",
                stale_operation="overwrite",
            )
        )
    else:
        expected.append(
            MemoryExpectedFile(
                path=root / "AGENTS.md",
                content=_minimal_agents_content(generated_sase_body),
                detail="agent instruction file",
                write_policy="create_if_missing",
            )
        )
    return tuple(expected)


def _generated_short_notes(generated_sase_body: str) -> dict[str, str]:
    """Return the freshly generated short-note bodies keyed by relative path."""
    return {_generated_sase_memory_relative_path().as_posix(): generated_sase_body}


def _amd_sync_plan(
    root: Path,
    *,
    enable_amd: bool,
    generated_short_notes: dict[str, str],
) -> AmdMemorySyncPlan | None:
    if not enable_amd:
        return None
    # The onboarding fallback (derive a managed title when memory exists but
    # none is configured) is scoped to project roots inside
    # ``resolve_amd_h1_title`` via its home-root check, so home/chezmoi roots
    # only get a managed AGENTS.md when a title is explicitly configured.
    return plan_amd_memory_sync(
        root,
        onboarding=True,
        generated_short_notes=generated_short_notes,
    )


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


def _provider_shim_changes(plan: ProviderShimPlan) -> tuple[MemoryFileChange, ...]:
    changes: list[MemoryFileChange] = []
    for write in plan.writes:
        if write.action.operation not in {"create", "overwrite"}:
            raise AssertionError(
                f"unexpected memory init operation: {write.action.operation}"
            )
        changes.append(
            MemoryFileChange(
                path=write.path,
                operation=cast(MemoryChangeOperation, write.action.operation),
                detail=write.action.detail,
            )
        )
    for delete in plan.deletes:
        changes.append(
            MemoryFileChange(
                path=delete.path,
                operation="delete",
                detail=delete.action.detail,
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


def _apply_provider_shim_plan(plan: ProviderShimPlan) -> tuple[Path, ...]:
    written: list[Path] = []
    for write in plan.writes:
        write.path.parent.mkdir(parents=True, exist_ok=True)
        write.path.write_text(write.content, encoding="utf-8")
        written.append(write.path)
    return tuple(written)


def _delete_provider_shim_paths(plan: ProviderShimPlan) -> tuple[Path, ...]:
    deleted: list[Path] = []
    for delete in plan.deletes:
        did_delete, delete_error = apply_planned_delete(delete)
        if delete_error is not None:
            raise OSError(delete_error)
        if did_delete:
            deleted.append(delete.path)
    return tuple(deleted)


def _is_memory_markdown_path(root: Path, path: Path) -> bool:
    root_resolved = root.resolve(strict=False)
    try:
        relative = path.resolve(strict=False).relative_to(root_resolved)
    except ValueError:
        return False
    if path.suffix != ".md" or not relative.parts or relative.parts[0] != "memory":
        return False
    return len(relative.parts) == 2 and relative.name != "README.md"


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
        if resolved == agents_path and (
            expected.write_policy == "overwrite"
            or (
                expected.write_policy == "create_if_missing"
                and not expected.path.exists()
            )
        ):
            overlay[resolved] = expected.content
    return overlay


def _final_agents_content(
    root: Path, expected_files: Iterable[MemoryExpectedFile]
) -> str:
    """Return the root's final ``AGENTS.md`` content for provider copies.

    Provider files are byte-for-byte copies of ``AGENTS.md``. The final content
    is the managed render (or rendered minimal template) whenever ``AGENTS.md``
    is (re)written, and the existing on-disk content when the minimal template is
    ``create_if_missing`` and the file already exists (so we never copy a stale
    render over an untouched user file).
    """
    agents_path = root / "AGENTS.md"
    for expected in expected_files:
        if expected.path != agents_path:
            continue
        if expected.write_policy == "create_if_missing" and expected.path.exists():
            try:
                return expected.path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return expected.content
        return expected.content
    return ""


def plan_memory_root(
    root: Path,
    linked_entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
    enable_amd: bool = False,
    chezmoi_home_roots: Iterable[Path] = (),
) -> MemoryRootPlan:
    generated_sase_body = _generated_sase_memory_body(
        linked_entries, project_name=project_name
    )
    amd_sync = _amd_sync_plan(
        root,
        enable_amd=enable_amd,
        generated_short_notes=_generated_short_notes(generated_sase_body),
    )
    expected_files = _render_expected_memory_files(
        root,
        linked_entries,
        project_name=project_name,
        amd_sync=amd_sync,
        generated_sase_body=generated_sase_body,
    )
    shim_plan = provider_shim_plan(
        root,
        agents_content=_final_agents_content(root, expected_files),
        chezmoi_home_roots=chezmoi_home_roots,
    )
    overlay = _validation_overlay_for_expected_files(root, expected_files)
    return MemoryRootPlan(
        root=root,
        changes=(
            _compare_expected_memory_files(expected_files)
            + _provider_shim_changes(shim_plan)
        ),
        unreferenced=unreferenced_memory_files(root, overlay=overlay),
        blockers=((() if amd_sync is None else amd_sync.blockers) + shim_plan.blockers),
    )


def initialize_memory_root(
    root: Path,
    linked_entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
    enable_amd: bool = False,
    chezmoi_home_roots: Iterable[Path] = (),
) -> MemoryRootResult:
    generated_sase_body = _generated_sase_memory_body(
        linked_entries, project_name=project_name
    )
    amd_sync = _amd_sync_plan(
        root,
        enable_amd=enable_amd,
        generated_short_notes=_generated_short_notes(generated_sase_body),
    )
    expected_files = _render_expected_memory_files(
        root,
        linked_entries,
        project_name=project_name,
        amd_sync=amd_sync,
        generated_sase_body=generated_sase_body,
    )
    shim_plan = provider_shim_plan(
        root,
        agents_content=_final_agents_content(root, expected_files),
        chezmoi_home_roots=chezmoi_home_roots,
    )
    written = _apply_expected_memory_files(expected_files)
    written = (*written, *_apply_provider_shim_plan(shim_plan))
    deleted = _delete_provider_shim_paths(shim_plan)

    return MemoryRootResult(
        root=root,
        written_paths=written,
        unreferenced=unreferenced_memory_files(root),
        deleted_paths=deleted,
    )
