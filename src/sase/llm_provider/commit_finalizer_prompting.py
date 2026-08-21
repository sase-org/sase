"""Prompt and response helpers for commit finalization."""

from __future__ import annotations

import os

from sase.commit_instructions import (
    build_commit_instruction_message,
    build_name_instruction_text,
)

from .commit_finalizer_types import DirtyRepo, DirtyState


def build_dirty_details(
    *,
    main_details: str,
    main_instruction: str,
    main_repo: DirtyRepo | None,
    sibling_repos: tuple[DirtyRepo, ...],
    external_repos: tuple[DirtyRepo, ...] = (),
    sdd_repos: tuple[DirtyRepo, ...] = (),
) -> str:
    if (
        main_repo is not None
        and not sibling_repos
        and not external_repos
        and not sdd_repos
        and main_details
    ):
        return main_details

    repos: list[DirtyRepo] = []
    if main_repo is not None:
        repos.append(main_repo)
    repos.extend(sibling_repos)
    repos.extend(external_repos)
    repos.extend(sdd_repos)
    if not repos:
        return ""

    lines: list[str] = []
    if repos:
        lines.append("Uncommitted changes detected in repositories:")
        for repo in repos:
            lines.append(f"- {_repo_label(repo)}: {repo.path}")
            lines.extend(f"  - {path}" for path in repo.changed_files[:20])
            if len(repo.changed_files) > 20:
                lines.append(f"  - ... ({len(repo.changed_files)} total)")

    if main_repo is not None and main_instruction:
        lines.extend(["", "Main workspace commit instructions:", main_instruction])

    non_primary_repos = (*sibling_repos, *external_repos, *sdd_repos)
    if non_primary_repos:
        lines.extend(
            [
                "",
                "External repository commit instructions:",
                _sibling_commit_instruction(),
            ]
        )

    if non_primary_repos:
        for repo in non_primary_repos:
            lines.append(
                f"- For `{repo.name}`, run `cd {repo.path}` before using "
                "your /sase_git_commit skill."
            )
        lines.append(
            "After each external-repo commit, run `git status --short --branch` in "
            "that repository and make sure it is clean before continuing."
        )

    return "\n".join(lines)


def _repo_label(repo: DirtyRepo) -> str:
    if repo.kind == "main":
        return "main workspace"
    if repo.kind == "sibling":
        return f"linked repo {repo.name}"
    if repo.kind == "external":
        return f"external repo `{repo.name}`"
    return f"SDD sidecar repo {repo.name}"


def build_pre_existing_details(
    details: str,
    pre_existing_repos: tuple[DirtyRepo, ...],
) -> str:
    """Append a report of paths dirty before this run started to *details*.

    These paths are excluded from the must-commit set built into *details*
    (see ``build_dirty_details``); listing them here tells the agent they
    are not its responsibility instead of leaving it to guess, the fix for
    the incident where a finalizer pass told an agent it had to commit
    another agent's in-flight edit.
    """
    if not pre_existing_repos:
        return details

    lines = [
        "Pre-existing changes detected before this run started "
        "(not from this run — do not commit these):",
    ]
    for repo in pre_existing_repos:
        lines.append(f"- {_repo_label(repo)}: {repo.path}")
        lines.extend(f"  - {path}" for path in repo.changed_files[:20])
        if len(repo.changed_files) > 20:
            lines.append(f"  - ... ({len(repo.changed_files)} total)")

    section = "\n".join(lines)
    return f"{details}\n\n{section}" if details else section


def _sibling_commit_instruction() -> str:
    method = os.environ.get("SASE_COMMIT_METHOD", "")
    instruction = build_commit_instruction_message(
        "/sase_git_commit", method, os.environ.get("SASE_BEAD_ID")
    )
    name_instruction = build_name_instruction_text()
    if name_instruction:
        instruction += " " + name_instruction
    return instruction


def _result_changed_files(dirty_state: DirtyState) -> list[str]:
    if len(dirty_state.repos) == 1 and dirty_state.repos[0].kind == "main":
        return list(dirty_state.repos[0].changed_files)

    changed: list[str] = []
    for repo in dirty_state.repos:
        changed.extend(f"{repo.name}:{path}" for path in repo.changed_files)
    return changed


def append_response(existing: str, new: str) -> str:
    return (existing + "\n\n" + new.strip()).strip()


def merge_usage(
    first: dict[str, int] | None,
    second: dict[str, int] | None,
) -> dict[str, int] | None:
    if first is None:
        return dict(second) if second is not None else None
    if second is None:
        return dict(first)
    merged = dict(first)
    for key, value in second.items():
        merged[key] = merged.get(key, 0) + value
    return merged


def failure_message(
    dirty_state: DirtyState,
    max_passes: int,
    no_progress_passes: int = 0,
) -> str:
    changed_files = _result_changed_files(dirty_state)
    listed_files = ", ".join(changed_files[:10]) or "(unable to list changed files)"
    if len(changed_files) > 10:
        listed_files += f", ... ({len(changed_files)} total)"
    repo_paths = ", ".join(f"{repo.name}={repo.path}" for repo in dirty_state.repos)
    message = (
        "Commit finalizer failed: uncommitted changes remain after "
        f"{max_passes} finalizer pass(es) in {repo_paths}: {listed_files}."
    )
    if max_passes > 0 and no_progress_passes >= max_passes:
        message += (
            " No pass produced a commit or a working-tree change, which "
            "indicates the agent ended each pass without committing."
        )
    return message
