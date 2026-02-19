"""Create a ChangeSpec after an agent workflow pushes commits."""

import re
import subprocess

from sase.chat_history import save_chat_history
from sase.commit_workflow.changespec_operations import add_changespec_to_project_file
from sase.gh_workspace import get_cl_field_label
from sase.sase_utils import (
    ensure_sase_directory,
    generate_timestamp,
    make_safe_filename,
    shorten_path,
)
from sase.workflow_utils import get_initial_hooks_for_changespec

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
    try:
        result = subprocess.run(
            ["git", "diff", f"{checkout_target}...{branch_name}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
    except Exception:
        return None

    diffs_dir = ensure_sase_directory("diffs")
    safe_name = make_safe_filename(cl_name)
    filename = f"{safe_name}-{timestamp}.diff"
    diff_path = f"{diffs_dir}/{filename}"

    with open(diff_path, "w", encoding="utf-8") as f:
        f.write(result.stdout)

    return shorten_path(diff_path)


# pyvision: xprompts/pr.yml
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
) -> str | None:
    """Create a ChangeSpec for commits produced by an agent workflow.

    Returns the suffixed ChangeSpec name on success, or ``None`` when the
    agent branch has no new commits relative to *checkout_target*.
    """
    commits = _get_commits_ahead(checkout_target, branch_name)
    if not commits:
        return None

    if cl_name is None:
        cl_name = _derive_cl_name(project_name, commits)
    description = _build_description(commits)
    ts = generate_timestamp()

    chat_path = save_chat_history(prompt, response, workflow_name, timestamp=ts)
    diff_path = _save_committed_diff(cl_name, checkout_target, branch_name, ts)
    hooks = get_initial_hooks_for_changespec(verbose=False)
    cl_label = get_cl_field_label(project_file)

    result = add_changespec_to_project_file(
        project_name,
        cl_name,
        description,
        parent=None,
        cl_url=cl_url,
        initial_hooks=hooks,
        initial_commits=[(1, "[run] Initial Commit", chat_path, diff_path)],
        cl_label=cl_label,
    )

    return result
