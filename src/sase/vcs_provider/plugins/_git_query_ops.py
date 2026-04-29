"""Git query and sync operations mixin.

Provides git read/query operations (resolve revision, show, get info)
and sync operations (rebase, conflict resolution) shared across all
git-based VCS plugins.
"""

import os
from typing import TYPE_CHECKING

from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import hookimpl


class GitQueryOpsMixin(CommandRunner):
    """Git query, info, and sync operations."""

    if TYPE_CHECKING:
        # Provided by GitCoreOpsMixin in the composed class.
        def _get_default_branch(self, cwd: str) -> str: ...

    # --- Branch name derivation ---

    @hookimpl
    def vcs_derive_branch_name(
        self, changespec_name: str, project_basename: str
    ) -> str:
        from sase.core.changespec import strip_reverted_suffix

        return strip_reverted_suffix(changespec_name)

    @hookimpl
    def vcs_derive_branch_name_with_suffix(
        self, changespec_name: str, project_basename: str
    ) -> str:
        return changespec_name

    @hookimpl
    def vcs_can_rename_branch(self, cwd: str) -> bool:
        return True

    # --- Revision resolution ---

    @hookimpl
    def vcs_resolve_revision(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str:
        from sase.core.branch_map import read_branch_map
        from sase.core.changespec import (
            changespec_name_to_branch,
            changespec_name_to_branch_with_suffix,
        )

        # --- Build candidate list ---
        # 1. Branch map alias (highest priority for immutable-branch providers)
        branch_map = read_branch_map(project_basename)
        mapped_branch = branch_map.get(changespec_name)

        # 2. New naming: derive_branch_name_with_suffix / derive_branch_name
        derived_with_suffix = self.vcs_derive_branch_name_with_suffix(
            changespec_name, project_basename
        )
        derived_without_suffix = self.vcs_derive_branch_name(
            changespec_name, project_basename
        )

        # 3. Old naming (backward compat): changespec_name_to_branch*
        old_branch_with_suffix = changespec_name_to_branch_with_suffix(
            changespec_name, project_basename
        )
        old_branch_without_suffix = changespec_name_to_branch(
            changespec_name, project_basename
        )

        # 4. Prefix-stripped with underscores preserved
        prefix = f"{project_basename}_"
        prefix_stripped = (
            changespec_name[len(prefix) :]
            if changespec_name.startswith(prefix)
            else None
        )

        # Deduplicate while preserving priority order
        seen: set[str] = set()
        candidates: list[str] = []
        for c in [
            mapped_branch,
            changespec_name,
            derived_with_suffix,
            derived_without_suffix,
            old_branch_with_suffix,
            old_branch_without_suffix,
            prefix_stripped,
        ]:
            if c and c not in seen:
                seen.add(c)
                candidates.append(c)

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

        # Last resort: if the changespec is a base name (no __N suffix),
        # look for a unique suffixed remote branch.  This handles the case
        # where a Ready changespec's branch was previously renamed with a
        # suffix (e.g. "feature-1") but the changespec name lost the suffix.
        if old_branch_without_suffix == old_branch_with_suffix:
            pattern = f"refs/remotes/origin/{old_branch_without_suffix}-*"
            ref_out = self._run(
                ["git", "for-each-ref", "--format=%(refname:short)", pattern], cwd
            )
            if ref_out.success and ref_out.stdout.strip():
                import re

                suffix_re = re.compile(
                    re.escape(f"origin/{old_branch_without_suffix}") + r"-\d+$"
                )
                matches = [
                    r for r in ref_out.stdout.strip().splitlines() if suffix_re.match(r)
                ]
                if len(matches) == 1:
                    return matches[0]

        # Fall back to derived name without suffix (may fail at checkout)
        return derived_without_suffix

    # --- Show / diff helpers ---

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

    # --- Info queries ---

    @hookimpl
    def vcs_get_default_parent_revision(self, cwd: str) -> str:
        return f"origin/{self._get_default_branch(cwd)}"

    @hookimpl
    def vcs_diff_name_status(
        self, parent_ref: str, head_ref: str, cwd: str
    ) -> list[tuple[str, str]]:
        from sase.vcs_provider._errors import VCSOperationError

        out = self._run(
            [
                "git",
                "diff",
                "--name-status",
                "-z",
                f"{parent_ref}..{head_ref}",
            ],
            cwd,
        )
        if not out.success:
            raise VCSOperationError(
                "diff_name_status",
                out.stderr.strip() or "git diff --name-status failed",
            )
        return _parse_git_name_status_z(out.stdout)

    @hookimpl
    def vcs_file_at_revision(
        self, revision: str, file_path: str, cwd: str
    ) -> tuple[bool, str | None]:
        out = self._run(["git", "show", f"{revision}:{file_path}"], cwd)
        if not out.success:
            return (False, f"git show failed: {out.stderr.strip()}")
        return (True, out.stdout)

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

    # --- Sync operations ---

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

    # --- Reword operations ---

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


def _parse_git_name_status_z(stdout: str) -> list[tuple[str, str]]:
    """Parse the NUL-delimited output of ``git diff --name-status -z``.

    The output is a stream of NUL-separated fields: a status letter (e.g.
    ``A``, ``M``, ``D``, ``R100``, ``C75``, ``T``, ``U``) followed by one
    or two paths.  Rename/copy entries (``R``/``C``) are followed by *two*
    paths (old, new); all other statuses are followed by exactly one.

    Returns a list of ``(status_letter, path)`` tuples.  For renames and
    copies the path is encoded as ``"<old>\\t<new>"`` so callers can split
    it apart and decide how to surface the rename.
    """
    if not stdout:
        return []
    # `git diff -z` ends every field with a NUL; trim a trailing empty token.
    parts = stdout.split("\0")
    if parts and parts[-1] == "":
        parts.pop()

    result: list[tuple[str, str]] = []
    i = 0
    while i < len(parts):
        status = parts[i]
        i += 1
        if not status:
            continue
        first_letter = status[0]
        if first_letter in ("R", "C") and i + 1 < len(parts):
            old_path = parts[i]
            new_path = parts[i + 1]
            i += 2
            result.append((status, f"{old_path}\t{new_path}"))
        elif i < len(parts):
            path = parts[i]
            i += 1
            result.append((status, path))
    return result
