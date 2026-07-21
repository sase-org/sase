"""Git workspace synchronization and commit reword operations."""

import os
from typing import TYPE_CHECKING

from sase.core.git_query_facade import parse_git_conflicted_files
from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import hookimpl


class GitSyncOpsMixin(CommandRunner):
    """Git workspace synchronization and commit reword operations."""

    if TYPE_CHECKING:
        # Provided by GitCoreOpsMixin in the composed class.
        def _get_default_branch(self, cwd: str) -> str: ...

    @hookimpl
    def vcs_sync_workspace(self, cwd: str) -> tuple[bool, str | None]:
        fetch_out = self._run(["git", "fetch", "origin"], cwd, timeout=600)
        if not fetch_out.success:
            return self._to_result(fetch_out, "git fetch origin")
        default_branch = self._get_default_branch(cwd)
        rebase_out = self._run(
            ["git", "rebase", f"origin/{default_branch}"], cwd, timeout=600
        )
        return self._to_result(rebase_out, "git rebase")

    @hookimpl
    def vcs_is_sync_in_progress(self, cwd: str) -> bool:
        out = self._run(["git", "rev-parse", "--git-dir"], cwd)
        if not out.success:
            return False
        git_dir = out.stdout.strip()
        if not os.path.isabs(git_dir):
            git_dir = os.path.join(cwd, git_dir)
        return os.path.isdir(os.path.join(git_dir, "rebase-merge")) or os.path.isdir(
            os.path.join(git_dir, "rebase-apply")
        )

    @hookimpl
    def vcs_get_conflicted_files(self, cwd: str) -> list[str]:
        out = self._run(["git", "diff", "--name-only", "--diff-filter=U"], cwd)
        if not out.success:
            return []
        return parse_git_conflicted_files(out.stdout)

    @hookimpl
    def vcs_continue_sync(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(
            ["git", "-c", "core.editor=true", "rebase", "--continue"],
            cwd,
            timeout=600,
        )
        return self._to_result(out, "git rebase --continue")

    @hookimpl
    def vcs_abort_sync(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "rebase", "--abort"], cwd)
        return self._to_result(out, "git rebase --abort")

    @hookimpl
    def vcs_reword(self, description: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "commit", "--amend", "-m", description], cwd)
        return self._to_result(out, "git commit --amend")

    @hookimpl
    def vcs_reword_add_tag(
        self, tag_name: str, tag_value: str, cwd: str
    ) -> tuple[bool, str | None]:
        out = self._run(["git", "log", "--format=%B", "-n1", "HEAD"], cwd)
        if not out.success:
            return (False, out.stderr.strip() or "git log failed")
        current_msg = out.stdout.rstrip("\n")
        new_msg = f"{current_msg}\n{tag_name}={tag_value}"
        amend_out = self._run(["git", "commit", "--amend", "-m", new_msg], cwd)
        return self._to_result(amend_out, "git commit --amend")
