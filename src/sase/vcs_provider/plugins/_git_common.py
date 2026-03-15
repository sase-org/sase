"""Shared git methods for git-based VCS plugins.

Common git operations (checkout, diff, commit, rebase, etc.) are
identical across different git-based plugins.  This mixin centralises
them so plugin classes only override the handful of methods that differ.
"""

import os

from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import hookimpl


class GitCommon(CommandRunner):
    """Mixin with shared ``@hookimpl`` methods for git-based plugins."""

    # --- Core operations ---

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

    @hookimpl
    def vcs_commit(self, name: str, logfile: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "commit", "-F", logfile], cwd)
        return self._to_result(out, "git commit")

    @hookimpl
    def vcs_amend(
        self, note: str, cwd: str, no_upload: bool
    ) -> tuple[bool, str | None]:
        out = self._run(["git", "commit", "--amend", "-m", note], cwd)
        return self._to_result(out, "git commit --amend")

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
        out = self._run(["git", "branch", "-D", revision], cwd)
        return self._to_result(out, "git branch -D")

    @hookimpl
    def vcs_stash_and_clean(
        self, diff_name: str, cwd: str, timeout: int
    ) -> tuple[bool, str | None]:
        diff_out = self._run(["git", "diff", "HEAD"], cwd, timeout=timeout)
        if not diff_out.success:
            error_msg = (
                diff_out.stderr.strip() or diff_out.stdout.strip() or "no error output"
            )
            return (False, error_msg)
        try:
            with open(diff_name, "w") as f:
                f.write(diff_out.stdout)
                if not diff_out.stdout.endswith("\n"):
                    f.write("\n")
        except OSError as e:
            return (False, f"Failed to write diff file: {e}")
        reset_out = self._run(["git", "reset", "--hard", "HEAD"], cwd, timeout=timeout)
        if not reset_out.success:
            return (False, f"git reset --hard failed: {reset_out.stderr.strip()}")
        clean_out = self._run(["git", "clean", "-fd"], cwd, timeout=timeout)
        if not clean_out.success:
            return (False, f"git clean -fd failed: {clean_out.stderr.strip()}")
        return (True, None)

    # --- Optional core operations ---

    @hookimpl
    def vcs_resolve_revision(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str:
        from sase.sase_utils import (
            changespec_name_to_branch,
            changespec_name_to_branch_with_suffix,
        )

        branch_with_suffix = changespec_name_to_branch_with_suffix(
            changespec_name, project_basename
        )
        branch_without_suffix = changespec_name_to_branch(
            changespec_name, project_basename
        )

        # Also try prefix-stripped name with underscores preserved — branches
        # may have been created without underscore-to-hyphen conversion.
        prefix = f"{project_basename}_"
        prefix_stripped = (
            changespec_name[len(prefix) :]
            if changespec_name.startswith(prefix)
            else None
        )

        candidates = [changespec_name, branch_with_suffix, branch_without_suffix]
        if prefix_stripped and prefix_stripped not in candidates:
            candidates.append(prefix_stripped)

        # Try each candidate against local refs
        for candidate in candidates:
            out = self._run(["git", "rev-parse", "--verify", "--quiet", candidate], cwd)
            if out.success:
                return candidate

        # No local match — fetch from remote and retry against both local
        # and remote-tracking refs (rev-parse only finds local refs, but
        # git checkout can DWIM-create from origin/<branch>).
        self._run(["git", "fetch", "origin"], cwd, timeout=600)
        for candidate in candidates:
            out = self._run(["git", "rev-parse", "--verify", "--quiet", candidate], cwd)
            if out.success:
                return candidate
            # Check remote-tracking ref — vcs_checkout strips "origin/" and
            # git's DWIM creates a local tracking branch automatically.
            remote_ref = f"origin/{candidate}"
            out = self._run(
                ["git", "rev-parse", "--verify", "--quiet", remote_ref], cwd
            )
            if out.success:
                return remote_ref

        # Fall back to branch without suffix (may fail at checkout)
        return branch_without_suffix

    @hookimpl
    def vcs_show_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "show", "--format=", "--patch", revision], cwd)
        if not out.success:
            return (False, f"git show failed: {out.stderr.strip()}")
        return (True, out.stdout)

    @hookimpl
    def vcs_diff_with_untracked(
        self, cwd: str, timeout: int
    ) -> tuple[bool, str | None]:
        tracked = self._run(["git", "diff", "HEAD"], cwd, timeout=timeout)
        tracked_diff = tracked.stdout if tracked.success else ""

        ls_out = self._run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd,
            timeout=timeout,
        )
        untracked_diff = ""
        if ls_out.success and ls_out.stdout:
            files = [f for f in ls_out.stdout.split("\0") if f]
            for f in files[:100]:
                # git diff --no-index exits 1 when files differ (expected)
                result = self._run(
                    ["git", "diff", "--no-index", "/dev/null", f],
                    cwd,
                    timeout=timeout,
                )
                if result.stdout:
                    untracked_diff += result.stdout

        combined = tracked_diff + untracked_diff
        return (True, combined if combined.strip() else None)

    @hookimpl
    def vcs_committed_diff(self, cwd: str, timeout: int) -> tuple[bool, str | None]:
        out = self._run(["git", "diff", "HEAD~1..HEAD"], cwd, timeout=timeout)
        if not out.success:
            return (True, None)
        text = out.stdout.strip()
        return (True, text if text else None)

    def _get_default_branch(self, cwd: str) -> str:
        """Detect the default branch name (e.g. ``main`` or ``master``)."""
        branch_out = self._run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd)
        default_branch = "main"
        if branch_out.success:
            ref = branch_out.stdout.strip()
            if ref:
                default_branch = ref.rsplit("/", 1)[-1]
        return default_branch

    @hookimpl
    def vcs_get_default_parent_revision(self, cwd: str) -> str:
        return f"origin/{self._get_default_branch(cwd)}"

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
        return [line for line in out.stdout.split("\n") if line.strip()]

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

    # --- VCS-agnostic / Google-internal operations ---

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

    @hookimpl
    def vcs_get_description(
        self, revision: str, cwd: str, short: bool
    ) -> tuple[bool, str | None]:
        fmt = "%s" if short else "%B"
        out = self._run(["git", "log", f"--format={fmt}", "-n1", revision], cwd)
        if not out.success:
            return (False, out.stderr.strip() or "git log failed")
        return (True, out.stdout)

    @hookimpl
    def vcs_get_branch_name(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
        if not out.success:
            return (False, "git rev-parse --abbrev-ref HEAD failed")
        name = out.stdout.strip()
        if not name or name == "HEAD":
            return (True, None)
        return (True, name)

    @hookimpl
    def vcs_get_workspace_name(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "config", "--get", "remote.origin.url"], cwd)
        if out.success and out.stdout.strip():
            url = out.stdout.strip()
            name = os.path.basename(url)
            if name.endswith(".git"):
                name = name[:-4]
            return (True, name) if name else (True, None)
        root_out = self._run(["git", "rev-parse", "--show-toplevel"], cwd)
        if root_out.success and root_out.stdout.strip():
            name = os.path.basename(root_out.stdout.strip())
            return (True, name) if name else (True, None)
        return (False, "Could not determine workspace name")

    @hookimpl
    def vcs_has_local_changes(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "status", "--porcelain"], cwd)
        if not out.success:
            return (False, out.stderr.strip() or "git status failed")
        text = out.stdout.strip()
        return (True, text if text else None)

    @hookimpl
    def vcs_get_bug_number(self, cwd: str) -> tuple[bool, str | None]:
        return (True, "")

    @hookimpl
    def vcs_fix(self, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    @hookimpl
    def vcs_upload(self, cwd: str) -> tuple[bool, str | None]:
        return (True, None)
