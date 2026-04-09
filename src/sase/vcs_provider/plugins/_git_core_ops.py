"""Core git operations mixin.

Provides basic git operations (checkout, diff, commit, etc.) that are
shared across all git-based VCS plugins.
"""

import os

from sase.telemetry.metrics import VCS_COMMITS, VCS_OPERATIONS
from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import hookimpl


class GitCoreOpsMixin(CommandRunner):
    """Core git operations: checkout, diff, commit, branch, rebase, etc."""

    _provider_name: str

    # --- Checkout / diff / apply ---

    @hookimpl
    def vcs_checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        # When asked to checkout a remote-tracking ref like origin/master,
        # always use the local branch name to leverage git's DWIM behavior.
        # If the local branch exists, git uses it directly; if not, git
        # auto-creates a local tracking branch from the remote-tracking ref.
        if revision.startswith("origin/"):
            revision = revision[len("origin/") :]
        out = self._run(["git", "checkout", revision], cwd)
        return self._to_result(out, "git checkout")

    @hookimpl
    def vcs_diff(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "diff", "HEAD"], cwd)
        if not out.success:
            out = self._run(["git", "diff"], cwd)
            if not out.success:
                return (False, f"git diff failed: {out.stderr.strip()}")
        text = out.stdout.strip()
        return (True, text if text else None)

    @hookimpl
    def vcs_diff_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        default_branch = self._get_default_branch(cwd)
        out = self._run(["git", "diff", f"origin/{default_branch}...{revision}"], cwd)
        if not out.success:
            out = self._run(["git", "diff", f"{revision}~1", revision], cwd)
        if not out.success:
            out = self._run(["git", "show", "--format=", "--patch", revision], cwd)
        if not out.success:
            return (False, f"git diff failed: {out.stderr.strip()}")
        return (True, out.stdout)

    @hookimpl
    def vcs_apply_patch(self, patch_path: str, cwd: str) -> tuple[bool, str | None]:
        expanded = os.path.expanduser(patch_path)
        if not os.path.exists(expanded):
            return (False, f"Diff file not found: {patch_path}")
        out = self._run(["git", "apply", expanded], cwd)
        if not out.success:
            return (False, out.stderr.strip() or "git apply failed")
        return (True, None)

    @hookimpl
    def vcs_apply_patches(
        self, patch_paths: list[str], cwd: str
    ) -> tuple[bool, str | None]:
        if not patch_paths:
            return (True, None)
        expanded: list[str] = []
        for p in patch_paths:
            ep = os.path.expanduser(p)
            if not os.path.exists(ep):
                return (False, f"Diff file not found: {p}")
            expanded.append(ep)
        out = self._run(["git", "apply"] + expanded, cwd)
        if not out.success:
            return (False, out.stderr.strip() or "git apply failed")
        return (True, None)

    # --- Stage / clean ---

    @hookimpl
    def vcs_add_remove(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "add", "-A"], cwd)
        return self._to_result(out, "git add -A")

    @hookimpl
    def vcs_clean_workspace(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "reset", "--hard", "HEAD"], cwd)
        if not out.success:
            return (False, f"git reset --hard failed: {out.stderr.strip()}")
        out = self._run(["git", "clean", "-fd"], cwd)
        if not out.success:
            return (False, f"git clean -fd failed: {out.stderr.strip()}")
        return (True, None)

    # --- Commit / amend ---

    @hookimpl
    def vcs_commit(self, name: str, logfile: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "commit", "-F", logfile], cwd)
        result = self._to_result(out, "git commit")
        status = "ok" if result[0] else "error"
        VCS_OPERATIONS.labels(
            provider=self._provider_name, operation="commit", status=status
        ).inc()
        if result[0]:
            VCS_COMMITS.labels(provider=self._provider_name, type="create").inc()
        return result

    @hookimpl
    def vcs_amend(
        self, note: str, cwd: str, no_upload: bool
    ) -> tuple[bool, str | None]:
        out = self._run(["git", "commit", "--amend", "-m", note], cwd)
        result = self._to_result(out, "git commit --amend")
        status = "ok" if result[0] else "error"
        VCS_OPERATIONS.labels(
            provider=self._provider_name, operation="amend", status=status
        ).inc()
        if result[0]:
            VCS_COMMITS.labels(provider=self._provider_name, type="amend").inc()
        return result

    # --- Branch / rebase / archive ---

    @hookimpl
    def vcs_rename_branch(self, new_name: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "branch", "-m", new_name], cwd)
        return self._to_result(out, "git branch -m")

    @hookimpl
    def vcs_rebase(
        self, branch_name: str, new_parent: str, cwd: str
    ) -> tuple[bool, str | None]:
        out = self._run(
            ["git", "rebase", "--onto", new_parent, branch_name], cwd, timeout=600
        )
        return self._to_result(out, "git rebase")

    @hookimpl
    def vcs_archive(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        tag_out = self._run(["git", "tag", f"archive/{revision}", revision], cwd)
        if not tag_out.success:
            return self._to_result(tag_out, "git tag")
        delete_out = self._run(["git", "branch", "-D", revision], cwd)
        if not delete_out.success:
            return self._to_result(delete_out, "git branch -D")
        return (True, None)

    @hookimpl
    def vcs_prune(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        # resolve_revision may return a remote-tracking ref (e.g.
        # "origin/branch") when no local branch exists.  git branch -D only
        # deletes local branches, so strip the remote prefix first.
        local_branch = revision.removeprefix("origin/")
        out = self._run(["git", "branch", "-D", local_branch], cwd)
        if not out.success and "not found" in out.stderr:
            # No local branch to delete — nothing to prune.
            return (True, None)
        return self._to_result(out, "git branch -D")

    @hookimpl
    def vcs_stash_and_clean(
        self, diff_name: str, cwd: str, timeout: int
    ) -> tuple[bool, str | None]:
        status_out = self._run(["git", "status", "--porcelain"], cwd, timeout=timeout)
        if not status_out.success:
            return (False, f"git status failed: {status_out.stderr.strip()}")
        if not status_out.stdout.strip():
            return (True, None)
        out = self._run(
            ["git", "stash", "push", "--include-untracked", "-m", diff_name],
            cwd,
            timeout=timeout,
        )
        if not out.success:
            return (False, f"git stash push failed: {out.stderr.strip()}")
        return (True, None)

    # --- Helpers ---

    def _get_default_branch(self, cwd: str) -> str:
        """Detect the default branch name (e.g. ``main`` or ``master``)."""
        branch_out = self._run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd)
        if branch_out.success:
            ref = branch_out.stdout.strip()
            if ref:
                return ref.rsplit("/", 1)[-1]
        # Probe for common default branch names
        for candidate in ("master", "main"):
            check = self._run(
                [
                    "git",
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/remotes/origin/{candidate}",
                ],
                cwd,
            )
            if check.success:
                return candidate
        return "main"
