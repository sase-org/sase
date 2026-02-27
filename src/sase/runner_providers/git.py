"""Git runner provider — manages workspace lifecycle for git-based agent runs.

Migrates logic from ``xprompts/git.yml`` + ``sase.scripts.git_setup`` into
the :class:`RunnerProvider` protocol so it can be invoked via ``%git:ref``
directives.
"""

import logging
import os
import subprocess
import tempfile

from sase.runner_provider import PostAgentResult, RunnerContext, RunnerProvider
from sase.running_field import (
    claim_workspace,
    get_first_available_axe_workspace,
    release_workspace,
)
from sase.workspace_provider.plugins.bare_git_workspace import resolve_git_ref
from sase.workspace_utils import ensure_git_clone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_git(
    args: list[str],
    cwd: str,
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the completed process."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def allocate_workspace(
    ref: str,
    *,
    n: int | None = None,
    release: bool = True,
) -> RunnerContext:
    """Resolve *ref*, claim a workspace, and return a populated context.

    This is the shared allocation logic extracted from
    :func:`sase.scripts.git_setup.main`.
    """
    resolved = resolve_git_ref(ref)

    project_name = resolved.project_name
    project_file = resolved.project_file

    # Check if workspace was pre-allocated by the TUI
    if os.environ.get("SASE_GIT_PRE_ALLOCATED") == "1":
        workspace_num = int(os.environ["SASE_GIT_WORKSPACE_NUM"])
        workspace_dir = os.environ["SASE_GIT_WORKSPACE_DIR"]
    elif n is not None:
        workspace_num = n
        workspace_dir = ensure_git_clone(resolved.primary_workspace_dir, workspace_num)
    else:
        workspace_num = get_first_available_axe_workspace(project_file)
        workspace_dir = ensure_git_clone(resolved.primary_workspace_dir, workspace_num)

    pid = os.getpid()
    workflow_name = f"git-{ref}"
    claim_workspace(
        project_file,
        workspace_num,
        workflow_name,
        pid,
        None,
        pinned=not release,
    )

    return RunnerContext(
        project_name=project_name,
        project_file=project_file,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        checkout_target=resolved.checkout_target,
        primary_workspace_dir=resolved.primary_workspace_dir,
        should_release=release,
    )


def prepare_git_workspace(workspace_dir: str) -> str:
    """Prepare a git workspace for an agent run.

    Backs up dirty state, cleans the workspace, fetches, and pulls.

    Returns:
        The HEAD commit hash before the agent runs.
    """
    # Save diff backup if workspace is dirty
    result = _run_git(["diff", "--quiet", "HEAD"], cwd=workspace_dir)
    if result.returncode != 0:
        backup_fd, backup_path = tempfile.mkstemp(
            prefix="git-workspace-backup-", suffix=".patch", dir="/tmp"
        )
        os.close(backup_fd)
        diff_result = _run_git(["diff", "HEAD"], cwd=workspace_dir)
        with open(backup_path, "w") as f:
            f.write(diff_result.stdout)
        logger.debug("Backed up dirty workspace to %s", backup_path)

    # Clean workspace
    _run_git(["checkout", "."], cwd=workspace_dir, check=True)
    _run_git(["clean", "-fd"], cwd=workspace_dir, check=True)

    # Fetch and pull
    _run_git(["fetch", "--quiet"], cwd=workspace_dir)
    _run_git(["pull", "--rebase", "--quiet"], cwd=workspace_dir)  # tolerate failure

    # Capture HEAD before agent
    head_result = _run_git(["rev-parse", "HEAD"], cwd=workspace_dir, check=True)
    return head_result.stdout.strip()


def capture_git_diff(workspace_dir: str, head_before: str) -> str | None:
    """Capture the diff produced by the agent run.

    Compares *head_before* to the current state. If commits were made,
    shows the last commit diff; otherwise shows uncommitted changes
    including untracked files.

    Returns:
        Path to a temp file containing the diff, or ``None`` if empty.
    """
    if not head_before:
        return None

    head_now = _run_git(
        ["rev-parse", "HEAD"], cwd=workspace_dir, check=True
    ).stdout.strip()

    diff_fd, diff_path = tempfile.mkstemp(
        prefix="sase-git-", suffix=".diff", dir="/tmp"
    )
    os.close(diff_fd)

    if head_now != head_before:
        # Commits were made — show the last commit's diff
        result = _run_git(["diff", "HEAD~1", "HEAD"], cwd=workspace_dir)
        diff_content = result.stdout
    else:
        # No commits — show uncommitted changes
        result = _run_git(["diff", "HEAD"], cwd=workspace_dir)
        diff_content = result.stdout

        # Include untracked files
        ls_result = _run_git(
            ["ls-files", "--others", "--exclude-standard"],
            cwd=workspace_dir,
        )
        for fname in ls_result.stdout.splitlines():
            fname = fname.strip()
            if fname:
                no_index = _run_git(
                    ["diff", "--no-index", "/dev/null", fname],
                    cwd=workspace_dir,
                )
                diff_content += no_index.stdout

    if diff_content.strip():
        with open(diff_path, "w") as f:
            f.write(diff_content)
        return diff_path

    # Empty diff — clean up
    os.unlink(diff_path)
    return None


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------


class GitRunnerProvider(RunnerProvider):
    """Built-in runner provider for local git workspaces."""

    @property
    def name(self) -> str:
        return "git"

    def pre_agent(
        self,
        ref: str,
        *,
        n: int | None = None,
        release: bool = True,
    ) -> RunnerContext:
        ctx = allocate_workspace(ref, n=n, release=release)
        head_before = prepare_git_workspace(ctx.workspace_dir)
        ctx.head_before = head_before
        os.chdir(ctx.workspace_dir)
        return ctx

    def post_agent(self, ctx: RunnerContext) -> PostAgentResult:
        if ctx.should_release:
            workflow_name = f"git-{ctx.checkout_target}"
            release_workspace(
                ctx.project_file,
                ctx.workspace_num,
                workflow_name,
            )

        diff_path = capture_git_diff(ctx.workspace_dir, ctx.head_before)
        return PostAgentResult(
            diff_path=diff_path,
            meta={"meta_workspace": str(ctx.workspace_num)},
        )
