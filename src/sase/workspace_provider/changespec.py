"""Create a ChangeSpec after an agent workflow pushes commits."""

import re
import subprocess

from sase.history.chat import save_chat_history
from sase.workflows.commit.changespec_operations import add_changespec_to_project_file
from sase.workspace_provider import get_change_label
from sase.core.paths import (
    ensure_sase_directory,
    make_safe_filename,
    shorten_path,
)
from sase.core.time import generate_timestamp
from sase.workflows.utils import get_initial_hooks_for_changespec

_CONVENTIONAL_PREFIXES = re.compile(
    r"^(feat|fix|chore|ref|docs|test|ci|build|perf|style)\s*:\s*",
    re.IGNORECASE,
)


def _get_commits_ahead(checkout_target: str, branch_name: str) -> list[str]:
    """Return commit subjects on *branch_name* not yet in *checkout_target*.

    Results are ordered oldest-first (chronological).
    """
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--format=%s",
                f"{checkout_target}..{branch_name}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        # git log outputs newest-first; reverse for chronological order
        return list(reversed(result.stdout.strip().splitlines()))
    except Exception:
        return []


def _derive_cl_name(project_name: str, commit_subjects: list[str]) -> str:
    """Build a snake_case ChangeSpec name from the first commit subject."""
    if not commit_subjects:
        return f"{project_name}_agent_changes"

    raw = _CONVENTIONAL_PREFIXES.sub("", commit_subjects[0])

    # Convert to snake_case
    name = raw.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = name.strip("_")

    if not name:
        return f"{project_name}_agent_changes"

    name = name[:50]
    return f"{project_name}_{name}"


def _build_description(commit_subjects: list[str]) -> str:
    """Build a human-readable description from commit subjects."""
    if not commit_subjects:
        return "Agent changes"
    if len(commit_subjects) == 1:
        return commit_subjects[0]
    return "\n".join(f"{i}. {subj}" for i, subj in enumerate(commit_subjects, start=1))


def _save_committed_diff(
    cl_name: str,
    checkout_target: str,
    branch_name: str,
    timestamp: str,
) -> str | None:
    """Save the diff between *checkout_target* and *branch_name* to disk."""
    diff_text: str | None = None

    # Try git diff first
    try:
        result = subprocess.run(
            ["git", "diff", f"{checkout_target}...{branch_name}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            diff_text = result.stdout
    except Exception:
        pass

    # Fall back to VCS provider's committed_diff()
    if diff_text is None:
        try:
            import os

            from sase.vcs_provider import get_vcs_provider

            provider = get_vcs_provider(os.getcwd())
            ok, provider_diff = provider.committed_diff(os.getcwd())
            if ok and provider_diff and provider_diff.strip():
                diff_text = provider_diff
        except Exception:
            pass

    if diff_text is None:
        return None

    diffs_dir = ensure_sase_directory("diffs")
    safe_name = make_safe_filename(cl_name)
    filename = f"{safe_name}-{timestamp}.diff"
    diff_path = f"{diffs_dir}/{filename}"

    with open(diff_path, "w", encoding="utf-8") as f:
        f.write(diff_text)
        if not diff_text.endswith("\n"):
            f.write("\n")

    return shorten_path(diff_path)


def create_changespec_for_workflow(
    project_name: str,
    project_file: str,
    checkout_target: str,
    branch_name: str,
    prompt: str,
    response: str,
    workflow_name: str,
    cl_url: str | None = None,
    cl_name: str | None = None,
    status: str = "Draft",
    commit_description: str | None = None,
    parent: str | None = None,
) -> str | None:
    """Create a ChangeSpec for commits produced by an agent workflow.

    Returns the suffixed ChangeSpec name on success, or ``None`` when the
    agent branch has no new commits relative to *checkout_target* and no
    *commit_description* fallback is provided.

    Args:
        commit_description: Fallback commit description for non-git VCS where
            ``git log`` is unavailable. When *_get_commits_ahead()* returns
            empty and this is provided, it is used as a single commit subject.
    """
    commits = _get_commits_ahead(checkout_target, branch_name)
    if not commits and commit_description:
        commits = [commit_description]
    if not commits:
        return None

    if cl_name is None:
        cl_name = _derive_cl_name(project_name, commits)
    description = _build_description(commits)
    ts = generate_timestamp()

    chat_path = save_chat_history(prompt, response, workflow_name, timestamp=ts)
    diff_path = _save_committed_diff(cl_name, checkout_target, branch_name, ts)
    hooks = get_initial_hooks_for_changespec(verbose=False)
    cl_label = get_change_label(project_file)

    result = add_changespec_to_project_file(
        project_name,
        cl_name,
        description,
        parent=parent,
        cl_url=cl_url,
        initial_hooks=hooks,
        initial_commits=[(1, "[run] Initial Commit", chat_path, diff_path)],
        cl_label=cl_label,
        status=status,
    )

    return result
