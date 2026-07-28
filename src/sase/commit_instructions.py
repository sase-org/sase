"""Shared commit-enforcement instruction helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path
from collections.abc import Callable

from sase.diff_paths import changed_files_from_diff
from sase.vcs_provider import get_vcs_provider
from sase.vcs_provider._registry import detect_vcs

ChangedFilesFn = Callable[[str], tuple[bool, list[str]]]
CommitSkillFn = Callable[[str], str]
NameInstructionFn = Callable[[], str | None]


def build_commit_details(
    project_dir: str,
    *,
    commit_method: str | None = None,
    bead_id: str | None = None,
    get_changed_files: ChangedFilesFn | None = None,
    resolve_commit_skill: CommitSkillFn | None = None,
    build_name_instruction: NameInstructionFn | None = None,
) -> tuple[bool, list[str], str, str]:
    """Return (has_changes, changed_files, commit_instruction, details).

    ``commit_instruction`` is the trailing instruction sentence(s), and
    ``details`` is the full block (file list + instruction). When the worktree
    is clean, both strings are empty.
    """
    changed_files_fn = get_changed_files or _get_changed_files_for_commit
    commit_skill_fn = resolve_commit_skill or _resolve_commit_skill_name
    name_instruction_fn = build_name_instruction or build_name_instruction_text

    has_changes, changed_files = changed_files_fn(project_dir)
    if not has_changes:
        return (False, [], "", "")

    skill = commit_skill_fn(project_dir)
    method = (
        commit_method
        if commit_method is not None
        else os.environ.get("SASE_COMMIT_METHOD", "")
    )
    resolved_bead = bead_id if bead_id is not None else os.environ.get("SASE_BEAD_ID")
    commit_instruction = build_commit_instruction_message(skill, method, resolved_bead)
    name_instruction = name_instruction_fn()
    if name_instruction:
        commit_instruction += " " + name_instruction

    details = (
        "Uncommitted changes detected:\n"
        + "\n".join(changed_files)
        + f"\n\n{commit_instruction}"
    )
    return (True, changed_files, commit_instruction, details)


def _normalize_provider_token(provider: str | None) -> str:
    raw = (provider or "").strip().lower()
    if raw in {"", "auto"}:
        return "git"
    if raw in {"github", "bare_git", "git"}:
        return "git"
    if raw in {"google", "hg"}:
        return "hg"

    token = re.sub(r"[^a-z0-9_]", "_", raw)
    token = re.sub(r"_+", "_", token).strip("_")
    return token or "git"


def build_name_instruction_text() -> str | None:
    # Only PRs are named, since we need a branch name to associated with them.
    if os.environ.get("SASE_COMMIT_METHOD") != "create_pull_request":
        return None

    sase_name = os.environ.get("SASE_PR_NAME")
    sase_pr_name_is_set = True
    if not sase_name or sase_name == "None":
        sase_name = "<name>"
        sase_pr_name_is_set = False
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE", "")
    project = Path(project_file).stem if project_file else ""
    full_sase_name = sase_name
    if project and sase_pr_name_is_set:
        full_sase_name = f"{project}_{sase_name}"
    parts = [
        f'You MUST include `"name": "{full_sase_name}"` in your commit JSON payload.'
    ]
    if not sase_pr_name_is_set:
        parts.append(
            f"You should decide on what name to use for `{sase_name}` but it should be"
            ' short, descriptive, and consist" of lowercase letters and underscores.'
        )
        if project:
            parts.append(
                f'Also, one more requirement: `{sase_name}` MUST start with "{project}_".'
            )
    return " ".join(parts)


def build_commit_instruction_message(
    skill: str, commit_method: str, bead_id: str | None = None
) -> str:
    method = commit_method or "create_commit"
    resolved_bead_id = (bead_id or "").strip()
    parts = [
        "A post-completion finalizer has detected uncommitted changes.",
        "First decide whether the listed uncommitted changes were made by you in this session.",
        "If you did NOT make these changes, ignore this warning for the session; it will not appear again.",
    ]
    if resolved_bead_id:
        parts.append(
            f"If you DID make these changes, run `sase bead close {resolved_bead_id} "
            f'--note "<what you verified>"` and verify bead `{resolved_bead_id}` is '
            "closed before invoking the commit skill."
        )
        parts.append(
            f"Then commit the changes using your {skill} skill before continuing."
        )
    else:
        parts.append(
            f"If you DID make these changes, commit them using your {skill} skill before continuing."
        )
    parts.append(f"The commit method type is `{method}`.")
    parts.append(
        "When invoking the commit skill, include a separate `-f` flag for each listed file you intend to commit, "
        "including newly created untracked files."
    )
    parts.append(
        "Omit `-f` only when you intentionally want to stage every change in that repository."
    )
    parts.append(
        "Do not preemptively stash, pull, fast-forward, or hand-sync before invoking "
        "the commit skill; the git commit workflow commits first and rebases safely."
    )
    if method != "create_pull_request":
        parts.append(
            "When constructing the commit message, describe only the changes in this commit."
        )
        parts.append(
            "Do NOT describe the entire pull request or unrelated planned work."
        )
    parts.append(
        f"You MUST use `--type {method}` or omit --type entirely to let the"
        " environment decide. Do NOT pass a --type value that conflicts with"
        " the stated method."
    )
    return " ".join(parts)


def _resolve_commit_skill_name(project_dir: str) -> str:
    explicit = os.environ.get("SASE_COMMIT_SKILL")
    if explicit:
        return explicit

    provider = os.environ.get("SASE_VCS_PROVIDER")
    if not provider or provider == "auto":
        provider = detect_vcs(project_dir)
    provider_token = _normalize_provider_token(provider)
    return f"/sase_{provider_token}_commit"


def _get_changed_files_for_commit(project_dir: str) -> tuple[bool, list[str]]:
    try:
        provider = get_vcs_provider(project_dir)
    except Exception:
        return (False, [])

    diff_text: str | None = None
    try:
        ok, diff_text = provider.diff_with_untracked(project_dir, timeout=20)
        if not ok:
            diff_text = None
    except NotImplementedError:
        ok, diff_text = provider.diff(project_dir)
        if not ok:
            diff_text = None
    except Exception:
        diff_text = None

    changed_files = changed_files_from_diff(diff_text or "")
    if changed_files:
        return (True, changed_files)

    try:
        ok, value = provider.has_local_changes(project_dir)
        if ok and (value or "").strip().lower() == "true":
            return (True, ["(unable to list changed files for this VCS provider)"])
    except NotImplementedError:
        pass
    except Exception:
        pass

    return (False, [])
