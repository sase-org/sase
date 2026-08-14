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


_SINGLE_TURN_CONTRACT = (
    "--- Single-Turn Execution Contract ---\n"
    "This is a non-interactive, single-turn invocation: once this response ends, "
    "the process exits immediately. There is no later turn, no notification "
    "delivery, and no scheduled wake-up. Background work does not survive the "
    "end of this turn, and identifiers for background work started in a "
    "previous pass are not resolvable in this one.\n"
    "Never end this response in order to wait for something to finish, to be "
    "notified, or to be resumed. If you need to verify something, do it now:\n"
    "1. Split verification into slices that each fit inside the command-timeout "
    "ceiling and run them in sequence within this turn; or\n"
    "2. if work is already running in the background, block on it within this "
    "same turn by polling until it finishes; or\n"
    "3. if verification still cannot be completed, commit the work anyway and "
    "state in your response exactly what was left unverified.\n"
    "Committing the listed changes is the only outcome that ends the finalizer "
    "successfully."
)


def build_follow_up_prompt(
    *,
    original_prompt: str,
    accumulated_response: str,
    details: str,
    pass_number: int,
    max_passes: int,
    previous_pass_stalled: bool = False,
    is_final_pass: bool = False,
) -> str:
    escalation_lines: list[str] = []
    if previous_pass_stalled:
        escalation_lines.append(
            "The previous pass ended without committing and without changing "
            "the working tree at all: it made no progress."
        )
    if is_final_pass:
        escalation_lines.append(
            "This is the final finalizer pass. If you do not commit the "
            "listed changes now, the run fails."
        )
    escalation = ("\n" + "\n".join(escalation_lines) + "\n") if escalation_lines else ""

    return (
        f"{original_prompt}\n\n"
        "--- Prior, Already-Terminated Output (do not resume or continue it) ---\n"
        f"{accumulated_response}\n\n"
        "Any intention recorded above to wait for, poll later, or be notified "
        "about background work already failed and must not be repeated.\n\n"
        f"{_SINGLE_TURN_CONTRACT}\n"
        f"{escalation}\n"
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
