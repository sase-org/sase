"""Assemble injectable memory content for agent prompts."""

from __future__ import annotations

from pathlib import Path

from sase.memory.repo import get_filetree, get_repo_path, repo_exists


def _get_system_contents(project: str | None = None) -> list[tuple[str, str]]:
    """Return (relative_path, file_contents) for all system/ memory files.

    Collects files from ``global/system/`` and, if *project* is given,
    ``projects/<project>/system/``.  Results are sorted by relative path.
    """
    repo = get_repo_path()
    if not repo_exists():
        return []

    system_dirs: list[Path] = []
    global_sys = repo / "global" / "system"
    if global_sys.is_dir():
        system_dirs.append(global_sys)
    if project:
        proj_sys = repo / "projects" / project / "system"
        if proj_sys.is_dir():
            system_dirs.append(proj_sys)

    results: list[tuple[str, str]] = []
    for sys_dir in system_dirs:
        for md_file in sorted(sys_dir.rglob("*.md")):
            if md_file.name == ".gitkeep":
                continue
            rel = str(md_file.relative_to(repo))
            contents = md_file.read_text().strip()
            if contents:
                results.append((rel, contents))

    return results


def build_injection(
    project: str | None = None,
    *,
    max_system_tokens: int | None = None,
) -> str:
    """Build the full memory injection block for agent prompts.

    Produces a markdown block containing:
    1. A filetree overview of the memory repo (scoped to *project*).
    2. Full contents of all ``system/`` files (global + project).

    If *max_system_tokens* is set, the system contents section is
    truncated to fit within the approximate token budget (using a
    rough 1 token ≈ 4 characters heuristic).
    """
    if not repo_exists():
        return ""

    filetree = get_filetree(project=project)
    system_files = _get_system_contents(project=project)

    if not filetree and not system_files:
        return ""

    parts: list[str] = ["## Agent Memory"]

    if filetree:
        parts.append("")
        parts.append("### Filetree")
        parts.append("")
        parts.append("```")
        parts.append(filetree)
        parts.append("```")

    if system_files:
        parts.append("")
        parts.append("### System Context (Always Loaded)")

        char_budget = max_system_tokens * 4 if max_system_tokens else None
        chars_used = 0

        for rel_path, contents in system_files:
            entry = f"\n#### {rel_path}\n\n{contents}"
            entry_chars = len(entry)

            if char_budget is not None:
                if chars_used + entry_chars > char_budget:
                    remaining = char_budget - chars_used
                    if remaining > 100:
                        parts.append(f"\n#### {rel_path}")
                        parts.append("")
                        parts.append(contents[: remaining - 50])
                        parts.append("\n*(truncated — token budget reached)*")
                    else:
                        parts.append(
                            "\n*(remaining system files omitted — token budget reached)*"
                        )
                    break
                chars_used += entry_chars

            parts.append(f"\n#### {rel_path}")
            parts.append("")
            parts.append(contents)

    return "\n".join(parts)
