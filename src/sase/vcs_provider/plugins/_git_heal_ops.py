"""Git self-heal operations mixin.

Provides the git operations behind the workspace-preparation self-heal
ladder (inspect, abort in-progress operations, forced checkout, split
fetch/rebase, hard reset). Shared across all git-based VCS plugins through
:class:`GitCommon`; providers without these hooks raise
``NotImplementedError`` and preparation skips the heal rungs.
"""

import os
from pathlib import Path

from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import hookimpl
from sase.vcs_provider._types import CheckoutInspection
from sase.workspace_provider.utils import (
    abort_in_progress_git_operations,
    in_progress_git_operations,
)


class GitHealOpsMixin(CommandRunner):
    """Git self-heal operations for workspace preparation."""

    @hookimpl
    def vcs_inspect_checkout(self, cwd: str) -> CheckoutInspection:
        from sase.core.git_query_facade import parse_git_conflicted_files

        git_dir = self._heal_git_dir(cwd)
        operations = in_progress_git_operations(git_dir) if git_dir is not None else []
        conflicted_out = self._run(
            ["git", "diff", "--name-only", "--diff-filter=U"], cwd
        )
        unmerged = (
            parse_git_conflicted_files(conflicted_out.stdout)
            if conflicted_out.success
            else []
        )
        branch_out = self._run(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd
        )
        branch = branch_out.stdout.strip() or None if branch_out.success else None
        head_out = self._run(["git", "rev-parse", "--verify", "HEAD"], cwd)
        head = head_out.stdout.strip() or None if head_out.success else None
        status_out = self._run(["git", "status", "--porcelain"], cwd)
        dirty = bool(status_out.stdout.strip()) if status_out.success else False
        return CheckoutInspection(
            operations=tuple(operations),
            unmerged_paths=tuple(unmerged),
            branch=branch,
            head=head,
            dirty=dirty,
            detached_orphan=self._is_detached_orphan(cwd, branch, head),
        )

    @hookimpl
    def vcs_in_progress_operations(self, cwd: str) -> list[str]:
        git_dir = self._heal_git_dir(cwd)
        if git_dir is None:
            return []
        return in_progress_git_operations(git_dir)

    @hookimpl
    def vcs_abort_in_progress_operations(self, cwd: str) -> tuple[bool, str | None]:
        git_dir_result = self._run(["git", "rev-parse", "--git-dir"], cwd)
        if not git_dir_result.success or not git_dir_result.stdout.strip():
            detail = (
                git_dir_result.stderr.strip()
                or git_dir_result.stdout.strip()
                or "git rev-parse --git-dir failed"
            )
            return (False, f"could not resolve the Git directory: {detail}")
        raw = git_dir_result.stdout.strip()
        git_dir = Path(raw) if os.path.isabs(raw) else Path(cwd) / raw

        def _run(argv: list[str]) -> tuple[int, str]:
            out = self._run(argv, cwd)
            return out.returncode, (out.stderr or out.stdout or "").strip()

        error = abort_in_progress_git_operations(Path(cwd), git_dir, _run)
        if error is not None:
            return (False, error)
        return (True, None)

    @hookimpl
    def vcs_force_checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        if revision.startswith("origin/"):
            revision = revision[len("origin/") :]
        out = self._run(["git", "checkout", "-f", revision], cwd)
        return self._to_result(out, "git checkout -f")

    @hookimpl
    def vcs_recreate_branch_from_remote(
        self, branch: str, remote_ref: str, cwd: str
    ) -> tuple[bool, str | None]:
        out = self._run(["git", "checkout", "-B", branch, remote_ref], cwd)
        return self._to_result(out, "git checkout -B")

    @hookimpl
    def vcs_fetch_origin(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "fetch", "origin"], cwd, timeout=600)
        return self._to_result(out, "git fetch origin")

    @hookimpl
    def vcs_rebase_onto(self, remote_ref: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "rebase", remote_ref], cwd, timeout=600)
        return self._to_result(out, "git rebase")

    @hookimpl
    def vcs_reset_to_remote(self, remote_ref: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "reset", "--hard", remote_ref], cwd)
        return self._to_result(out, "git reset --hard")

    # --- Helpers ---

    def _heal_git_dir(self, cwd: str) -> Path | None:
        """Resolve *cwd*'s git dir, or return None when it cannot be resolved."""
        out = self._run(["git", "rev-parse", "--git-dir"], cwd)
        if not out.success or not out.stdout.strip():
            return None
        raw = out.stdout.strip()
        return Path(raw) if os.path.isabs(raw) else Path(cwd) / raw

    def _is_detached_orphan(
        self, cwd: str, branch: str | None, head: str | None
    ) -> bool:
        """Whether a detached HEAD holds commits no local branch or tag has.

        Uses ``for-each-ref``, which lists only real refs: ``git branch
        --contains`` also prints a ``* (HEAD detached ...)`` pseudo-entry
        while detached, which would hide every genuine orphan.
        """
        if branch is not None or not head:
            return False
        out = self._run(
            [
                "git",
                "for-each-ref",
                "--format=%(refname:short)",
                "--contains",
                head,
                "refs/heads",
                "refs/tags",
            ],
            cwd,
        )
        return out.success and not out.stdout.strip()
