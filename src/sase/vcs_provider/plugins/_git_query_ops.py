"""Git query operations and compatibility facade.

Provides git read/query operations and composes the focused revision and
sync mixins used by all git-based VCS plugins.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from sase.core.git_query_facade import (
    derive_git_workspace_name,
    parse_git_branch_name,
    parse_git_local_changes,
    parse_git_name_status_z,
    parse_git_numstat_z,
)
from sase.core.vcs_log_facade import VCS_LOG_GIT_FORMAT, parse_git_log
from sase.core.vcs_log_wire import VcsCommitWire
from sase.core.vcs_repo_stats_facade import build_vcs_repo_stats
from sase.core.vcs_repo_stats_wire import VcsRepoStatsWire
from sase.vcs_provider._hookspec import hookimpl
from sase.vcs_provider._types import MergeVisibility
from sase.vcs_provider.plugins._git_revision_ops import GitRevisionOpsMixin
from sase.vcs_provider.plugins._git_sync_ops import GitSyncOpsMixin

#: Git filters ``--until`` by committer time, while SASE's commit wire uses
#: author time. Admit a conservative margin so ordinary rebases remain
#: candidates for SASE's exact author-time filter. Commits whose committer
#: dates trail their author dates by more than this, or which lie beyond a
#: saturated bounded candidate fetch, can still be absent.
GIT_AUTHOR_DATE_UNTIL_SLOP_SECONDS = 7 * 24 * 60 * 60


def _merge_visibility_args(merges: MergeVisibility) -> tuple[str, ...]:
    match merges:
        case "hide":
            return ("--no-merges",)
        case "show":
            return ()
        case "only":
            return ("--merges",)
    raise ValueError(f"unknown merge visibility: {merges!r}")


class GitQueryOpsMixin(GitRevisionOpsMixin, GitSyncOpsMixin):
    """Git query operations composed with revision and sync operations."""

    if TYPE_CHECKING:
        # Provided by GitCoreOpsMixin in the composed class.
        def _get_default_branch(self, cwd: str) -> str: ...

    # --- Show / diff helpers ---

    @hookimpl
    def vcs_show_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        # Git show omits merge patches by default. --first-parent (git >= 2.31)
        # yields the changes introduced relative to the first parent and leaves
        # ordinary commit patches unchanged.
        out = self._run(
            ["git", "show", "--first-parent", "--format=", "--patch", revision], cwd
        )
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
    def vcs_resolve_remote_log_ref(self, cwd: str, ref_name: str | None) -> str | None:
        """Resolve the remote-tracking ref used for ``sase stitch log``."""
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
        self, cwd: str, refs: Sequence[str], timeout: int
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
        self,
        cwd: str,
        local_ref: str,
        remote_ref: str,
        merges: MergeVisibility,
    ) -> tuple[set[str], set[str]]:
        from sase.vcs_provider._errors import VCSOperationError

        merge_args = _merge_visibility_args(merges)
        ahead_out = self._run(
            ["git", "rev-list", *merge_args, local_ref, f"^{remote_ref}"],
            cwd,
        )
        if not ahead_out.success:
            raise VCSOperationError(
                "partition_commits",
                ahead_out.stderr.strip() or "git rev-list ahead failed",
            )
        behind_out = self._run(
            ["git", "rev-list", *merge_args, remote_ref, f"^{local_ref}"],
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
        since: int | None,
        until: int | None,
        authors: tuple[str, ...],
        revs: Sequence[str],
        merges: MergeVisibility,
    ) -> list[VcsCommitWire]:
        from sase.vcs_provider._errors import VCSOperationError

        args = ["git", "log"]
        if limit >= 1:
            args.extend(["-n", str(limit)])
        args.extend(_merge_visibility_args(merges))
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
    def vcs_revision_id(self, revision: str, cwd: str) -> str:
        out = self._run(["git", "rev-parse", "--verify", revision], cwd)
        if not out.success or not out.stdout.strip():
            from sase.vcs_provider._errors import VCSOperationError

            raise VCSOperationError(
                "revision_id",
                out.stderr.strip() or f"could not resolve revision {revision!r}",
            )
        return out.stdout.strip()

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


def _sha_set(stdout: str) -> set[str]:
    return {line.strip() for line in stdout.splitlines() if line.strip()}
