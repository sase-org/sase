"""Git query and sync operations mixin.

Provides git read/query operations (resolve revision, show, get info)
and sync operations (rebase, conflict resolution) shared across all
git-based VCS plugins.
"""

import os
from collections.abc import Sequence
from typing import TYPE_CHECKING

from sase.core.git_query_facade import (
    derive_git_workspace_name,
    parse_git_branch_name,
    parse_git_conflicted_files,
    parse_git_local_changes,
    parse_git_name_status_z,
    parse_git_numstat_z,
)
from sase.core.vcs_log_facade import VCS_LOG_GIT_FORMAT, parse_git_log
from sase.core.vcs_log_wire import VcsCommitWire
from sase.core.vcs_repo_stats_facade import build_vcs_repo_stats
from sase.core.vcs_repo_stats_wire import VcsRepoStatsWire
from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import hookimpl

#: Git filters ``--until`` by committer time, while SASE's commit wire uses
#: author time. Admit a conservative margin so ordinary rebases remain
#: candidates for SASE's exact author-time filter. Commits whose committer
#: dates trail their author dates by more than this, or which lie beyond a
#: saturated bounded candidate fetch, can still be absent.
GIT_AUTHOR_DATE_UNTIL_SLOP_SECONDS = 7 * 24 * 60 * 60


class GitQueryOpsMixin(CommandRunner):
    """Git query, info, and sync operations."""

    if TYPE_CHECKING:
        # Provided by GitCoreOpsMixin in the composed class.
        def _get_default_branch(self, cwd: str) -> str: ...

    def _revision_candidates(
        self, changespec_name: str, project_basename: str
    ) -> tuple[list[str], str, str]:
        from sase.core.branch_map import read_branch_map
        from sase.core.changespec import (
            changespec_name_to_branch,
            changespec_name_to_branch_with_suffix,
        )

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

        return candidates, old_branch_without_suffix, old_branch_with_suffix

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

    @hookimpl
    def vcs_existing_branch_suffixes(self, base_name: str, cwd: str) -> set[int]:
        """Return ``_<N>`` suffix numbers already taken by remote branches.

        Queries the remote for branches named ``<base_name>_<N>`` (exact
        numeric suffix only) so PR-branch suffix allocation can avoid names
        whose branch already exists on the remote.  Returns an empty set when
        there is no ``origin`` remote or the query fails.
        """
        import re

        remote_check = self._run(["git", "remote", "get-url", "origin"], cwd)
        if not remote_check.success:
            return set()

        out = self._run(
            ["git", "ls-remote", "--heads", "origin", f"{base_name}_*"],
            cwd,
            timeout=60,
        )
        if not out.success:
            return set()

        suffix_re = re.compile(re.escape(base_name) + r"_(\d+)$")
        suffixes: set[int] = set()
        for line in out.stdout.splitlines():
            # Each line is "<sha>\trefs/heads/<branch>".
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            branch = parts[1].strip().removeprefix("refs/heads/")
            match = suffix_re.match(branch)
            if match:
                suffixes.add(int(match.group(1)))
        return suffixes

    # --- Revision resolution ---

    @hookimpl
    def vcs_resolve_revision(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str:
        candidates, old_branch_without_suffix, old_branch_with_suffix = (
            self._revision_candidates(changespec_name, project_basename)
        )

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
        return self.vcs_derive_branch_name(changespec_name, project_basename)

    @hookimpl
    def vcs_resolve_current_changespec_head_ref(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str:
        """Resolve DELTAS head with current-PR semantics.

        If the workspace is already on the target branch, use that checked-out
        branch because it may contain local commits that have just been created.
        Otherwise fetch and prefer origin/<branch> so background DELTAS refreshes
        do not read a stale local branch tip.
        """
        from sase.vcs_provider._errors import VCSOperationError

        candidates, old_branch_without_suffix, old_branch_with_suffix = (
            self._revision_candidates(changespec_name, project_basename)
        )

        branch_out = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
        if branch_out.success:
            current_branch = parse_git_branch_name(branch_out.stdout)
            if current_branch in candidates:
                return current_branch

        fetch_out = self._run(["git", "fetch", "origin"], cwd, timeout=600)
        if not fetch_out.success:
            raise VCSOperationError(
                "resolve_current_changespec_head_ref",
                fetch_out.stderr.strip() or "git fetch origin failed",
            )

        for candidate in candidates:
            remote_ref = f"origin/{candidate}"
            out = self._run(
                ["git", "rev-parse", "--verify", "--quiet", remote_ref], cwd
            )
            if out.success:
                return remote_ref

        for candidate in candidates:
            out = self._run(["git", "rev-parse", "--verify", "--quiet", candidate], cwd)
            if out.success:
                return candidate

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

        return self.vcs_derive_branch_name(changespec_name, project_basename)

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
        if not tracked.success:
            return (False, None)
        tracked_diff = tracked.stdout if tracked.success else ""

        ls_out = self._run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd,
            timeout=timeout,
        )
        if not ls_out.success:
            return (False, None)
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
                elif not result.success:
                    return (False, None)

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
    def vcs_resolve_remote_log_ref(
        self, cwd: str, ref_name: str | None = None
    ) -> str | None:
        """Resolve the remote-tracking ref used for ``sase vcs log``."""
        remote_out = self._run(["git", "remote", "get-url", "origin"], cwd)
        if not remote_out.success or not remote_out.stdout.strip():
            return None

        if ref_name:
            return self._normalize_remote_log_ref(ref_name)

        upstream = self._run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
            cwd,
        )
        upstream_ref = upstream.stdout.strip() if upstream.success else ""
        if upstream_ref.startswith("origin/") and self._git_ref_exists(
            cwd, upstream_ref
        ):
            return upstream_ref

        branch_out = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
        current_branch = (
            parse_git_branch_name(branch_out.stdout) if branch_out.success else None
        )
        if current_branch:
            current_ref = f"origin/{current_branch}"
            if self._git_ref_exists(cwd, current_ref):
                return current_ref

        return f"origin/{self._get_default_branch(cwd)}"

    @hookimpl
    def vcs_fetch_remote(
        self, cwd: str, refs: Sequence[str], timeout: int = 120
    ) -> tuple[bool, str | None]:
        """Fetch only the remote branches needed for the log comparison."""
        branches = tuple(
            dict.fromkeys(self._remote_branch_from_ref(ref) for ref in refs)
        )
        branches = tuple(branch for branch in branches if branch)
        if not branches:
            return (True, None)

        refspecs = [
            f"+refs/heads/{branch}:refs/remotes/origin/{branch}" for branch in branches
        ]
        args = [
            "git",
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            "origin",
            *refspecs,
        ]
        out = self._run(args, cwd, timeout=timeout)
        if not out.success and "--no-write-fetch-head" in (out.stderr + out.stdout):
            out = self._run(
                ["git", "fetch", "--no-tags", "origin", *refspecs],
                cwd,
                timeout=timeout,
            )
        return self._to_result(out, "git fetch origin")

    @hookimpl
    def vcs_partition_commits(
        self, cwd: str, local_ref: str, remote_ref: str
    ) -> tuple[set[str], set[str]]:
        from sase.vcs_provider._errors import VCSOperationError

        ahead_out = self._run(
            ["git", "rev-list", "--no-merges", local_ref, f"^{remote_ref}"],
            cwd,
        )
        if not ahead_out.success:
            raise VCSOperationError(
                "partition_commits",
                ahead_out.stderr.strip() or "git rev-list ahead failed",
            )
        behind_out = self._run(
            ["git", "rev-list", "--no-merges", remote_ref, f"^{local_ref}"],
            cwd,
        )
        if not behind_out.success:
            raise VCSOperationError(
                "partition_commits",
                behind_out.stderr.strip() or "git rev-list behind failed",
            )
        return (_sha_set(ahead_out.stdout), _sha_set(behind_out.stdout))

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
                f"{parent_ref}...{head_ref}",
            ],
            cwd,
        )
        if not out.success:
            raise VCSOperationError(
                "diff_name_status",
                out.stderr.strip() or "git diff --name-status failed",
            )
        return parse_git_name_status_z(out.stdout)

    @hookimpl
    def vcs_diff_line_stats(
        self, parent_ref: str, head_ref: str, cwd: str
    ) -> list[tuple[str, str, str]]:
        from sase.vcs_provider._errors import VCSOperationError

        out = self._run(
            [
                "git",
                "diff",
                "--numstat",
                "-z",
                f"{parent_ref}...{head_ref}",
            ],
            cwd,
        )
        if not out.success:
            raise VCSOperationError(
                "diff_line_stats",
                out.stderr.strip() or "git diff --numstat failed",
            )
        return parse_git_numstat_z(out.stdout)

    @hookimpl
    def vcs_log(
        self,
        cwd: str,
        limit: int,
        *,
        since: int | None = None,
        until: int | None = None,
        authors: tuple[str, ...] = (),
        revs: Sequence[str] = ("HEAD",),
    ) -> list[VcsCommitWire]:
        from sase.vcs_provider._errors import VCSOperationError

        args = ["git", "log"]
        if limit >= 1:
            args.extend(["-n", str(limit)])
        args.append("--no-merges")
        if since is not None:
            args.append(f"--since=@{since}")
        if until is not None:
            args.append(f"--until=@{until + GIT_AUTHOR_DATE_UNTIL_SLOP_SECONDS}")
        if authors:
            args.extend(["--fixed-strings", "--regexp-ignore-case"])
            args.extend(f"--author={author}" for author in authors)
        args.extend(revs or ("HEAD",))
        args.append(f"--format={VCS_LOG_GIT_FORMAT}")

        out = self._run(args, cwd)
        if not out.success:
            raise VCSOperationError("log", out.stderr.strip() or "git log failed")
        return parse_git_log(out.stdout)

    @hookimpl
    def vcs_repo_stats(self, cwd: str) -> VcsRepoStatsWire:
        from sase.vcs_provider._errors import VCSOperationError

        branch_out = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
        status_out = self._run(["git", "status", "--porcelain"], cwd)
        if not status_out.success:
            raise VCSOperationError(
                "repo_stats", status_out.stderr.strip() or "git status failed"
            )

        head_out = self._run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd)
        if not head_out.success:
            return build_vcs_repo_stats(
                total_commits_stdout="0\n",
                contributors_stdout="",
                last_commit_stdout="",
                branch_stdout=branch_out.stdout if branch_out.success else "",
                status_stdout=status_out.stdout,
            )

        count_out = self._run(["git", "rev-list", "--count", "HEAD"], cwd)
        if not count_out.success:
            raise VCSOperationError(
                "repo_stats", count_out.stderr.strip() or "git rev-list failed"
            )

        contributors_out = self._run(["git", "shortlog", "-sne", "HEAD"], cwd)
        if not contributors_out.success:
            raise VCSOperationError(
                "repo_stats",
                contributors_out.stderr.strip() or "git shortlog failed",
            )

        last_commit_out = self._run(
            ["git", "log", "-1", f"--format={VCS_LOG_GIT_FORMAT}"], cwd
        )
        if not last_commit_out.success:
            raise VCSOperationError(
                "repo_stats", last_commit_out.stderr.strip() or "git log failed"
            )

        return build_vcs_repo_stats(
            total_commits_stdout=count_out.stdout,
            contributors_stdout=contributors_out.stdout,
            last_commit_stdout=last_commit_out.stdout,
            branch_stdout=branch_out.stdout if branch_out.success else "",
            status_stdout=status_out.stdout,
        )

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
        return (True, parse_git_branch_name(out.stdout))

    @hookimpl
    def vcs_get_workspace_name(self, cwd: str) -> tuple[bool, str | None]:
        remote_out = self._run(["git", "config", "--get", "remote.origin.url"], cwd)
        remote_url = (
            remote_out.stdout
            if remote_out.success and remote_out.stdout.strip()
            else None
        )
        if remote_url is not None:
            return (True, derive_git_workspace_name(remote_url, None))
        root_out = self._run(["git", "rev-parse", "--show-toplevel"], cwd)
        if root_out.success and root_out.stdout.strip():
            return (True, derive_git_workspace_name(None, root_out.stdout))
        return (False, "Could not determine workspace name")

    @hookimpl
    def vcs_has_local_changes(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "status", "--porcelain"], cwd)
        if not out.success:
            return (False, out.stderr.strip() or "git status failed")
        return (True, parse_git_local_changes(out.stdout))

    @hookimpl
    def vcs_get_bug_number(self, cwd: str) -> tuple[bool, str | None]:
        return (True, "")

    @hookimpl
    def vcs_fix(self, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    @hookimpl
    def vcs_upload(self, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    def _git_ref_exists(self, cwd: str, ref: str) -> bool:
        out = self._run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd,
        )
        return out.success

    def _normalize_remote_log_ref(self, ref_name: str) -> str:
        ref = ref_name.strip()
        if ref.startswith("refs/remotes/"):
            return ref.removeprefix("refs/remotes/")
        if ref.startswith("refs/heads/"):
            return f"origin/{ref.removeprefix('refs/heads/')}"
        if ref.startswith("origin/"):
            return ref
        return f"origin/{ref}"

    def _remote_branch_from_ref(self, ref: str | None) -> str:
        if not ref:
            return ""
        if ref.startswith("refs/remotes/origin/"):
            return ref.removeprefix("refs/remotes/origin/")
        if ref.startswith("refs/heads/"):
            return ref.removeprefix("refs/heads/")
        if ref.startswith("origin/"):
            return ref.removeprefix("origin/")
        return ref

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


def _sha_set(stdout: str) -> set[str]:
    return {line.strip() for line in stdout.splitlines() if line.strip()}
