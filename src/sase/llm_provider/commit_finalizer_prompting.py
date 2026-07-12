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
    sdd_repos: tuple[DirtyRepo, ...] = (),
) -> str:
    if main_repo is not None and not sibling_repos and not sdd_repos and main_details:
        return main_details

    repos: list[DirtyRepo] = []
    if main_repo is not None:
        repos.append(main_repo)
    repos.extend(sibling_repos)
    repos.extend(sdd_repos)
    if not repos:
        return ""

    lines: list[str] = []
    if repos:
        lines.append("Uncommitted changes detected in repositories:")
        for repo in repos:
            if repo.kind == "main":
                label = "main workspace"
            elif repo.kind == "sibling":
                label = f"linked repo {repo.name}"
            else:
                label = f"SDD companion repo {repo.name}"
            lines.append(f"- {label}: {repo.path}")
            lines.extend(f"  - {path}" for path in repo.changed_files[:20])
            if len(repo.changed_files) > 20:
                lines.append(f"  - ... ({len(repo.changed_files)} total)")

    if main_repo is not None and main_instruction:
        lines.extend(["", "Main workspace commit instructions:", main_instruction])

    external_repos = (*sibling_repos, *sdd_repos)
    if external_repos:
        lines.extend(
            [
                "",
                "External repository commit instructions:",
                _sibling_commit_instruction(),
            ]
        )

    if external_repos:
        for repo in external_repos:
            lines.append(
                f"- For `{repo.name}`, run `cd {repo.path}` before using "
                "your /sase_git_commit skill."
            )
        lines.append(
            "After each external-repo commit, run `git status --short --branch` in "
            "that repository and make sure it is clean before continuing."
        )

    return "\n".join(lines)


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


def build_follow_up_prompt(
    *,
    original_prompt: str,
    accumulated_response: str,
    details: str,
    pass_number: int,
    max_passes: int,
) -> str:
    return (
        f"{original_prompt}\n\n"
        f"--- Work So Far ---\n{accumulated_response}\n\n"
        f"--- Commit Finalizer Pass {pass_number} of {max_passes} ---\n"
        f"{details}\n\n"
        "After handling the commit requirement, respond with a "
        "concise summary of what you did."
    )


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
) -> str:
    changed_files = _result_changed_files(dirty_state)
    listed_files = ", ".join(changed_files[:10]) or "(unable to list changed files)"
    if len(changed_files) > 10:
        listed_files += f", ... ({len(changed_files)} total)"
    repo_paths = ", ".join(f"{repo.name}={repo.path}" for repo in dirty_state.repos)
    return (
        "Commit finalizer failed: uncommitted changes remain after "
        f"{max_passes} finalizer pass(es) in {repo_paths}: {listed_files}."
    )
