"""Abstract base class defining the VCS provider interface."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.core.vcs_log_wire import VcsCommitWire

    from ._types import (
        IssueListState,
        IssueState,
        IssueWire,
        MergeVisibility,
        PullRequestListState,
        PullRequestWire,
    )


class VCSProvider(ABC):
    """Abstract interface for version control system operations.

    All methods take an explicit ``cwd`` parameter and return
    ``tuple[bool, str | None]`` — ``(success, error_message)`` — matching
    the convention established by ``run_workspace_command()`` in
    ``sase_utils.py``.
    """

    # --- Core abstract methods (must be implemented by all providers) ---

    @abstractmethod
    def checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        """Check out a revision / bookmark / branch."""

    @abstractmethod
    def diff(self, cwd: str) -> tuple[bool, str | None]:
        """Return the current uncommitted diff text.

        Returns ``(True, diff_text)`` when there are changes, or
        ``(True, None)`` when the working directory is clean.
        """

    @abstractmethod
    def diff_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        """Return the diff for a specific revision.

        Returns ``(True, diff_text)`` on success.
        """

    @abstractmethod
    def apply_patch(self, patch_path: str, cwd: str) -> tuple[bool, str | None]:
        """Apply a single patch file without committing."""

    @abstractmethod
    def apply_patches(
        self, patch_paths: list[str], cwd: str
    ) -> tuple[bool, str | None]:
        """Apply multiple patch files without committing."""

    @abstractmethod
    def add_remove(self, cwd: str) -> tuple[bool, str | None]:
        """Stage new and deleted files (``hg addremove`` / ``git add -A``)."""

    @abstractmethod
    def clean_workspace(self, cwd: str) -> tuple[bool, str | None]:
        """Revert all tracked changes and remove untracked files."""

    @abstractmethod
    def commit(self, name: str, logfile: str, cwd: str) -> tuple[bool, str | None]:
        """Create a new commit."""

    @abstractmethod
    def amend(
        self, note: str, cwd: str, *, no_upload: bool = False
    ) -> tuple[bool, str | None]:
        """Amend the current commit."""

    @abstractmethod
    def rename_branch(self, new_name: str, cwd: str) -> tuple[bool, str | None]:
        """Rename the current bookmark / branch."""

    @abstractmethod
    def rebase(
        self, branch_name: str, new_parent: str, cwd: str
    ) -> tuple[bool, str | None]:
        """Rebase a branch onto a new parent."""

    @abstractmethod
    def archive(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        """Archive (hide) a revision."""

    @abstractmethod
    def prune(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        """Permanently delete a revision."""

    @abstractmethod
    def stash_and_clean(
        self, diff_name: str, cwd: str, *, timeout: int = 300
    ) -> tuple[bool, str | None]:
        """Stash uncommitted changes and clean the workspace."""

    # --- Optional core methods (default raises NotImplementedError) ---

    def derive_branch_name(self, changespec_name: str, project_basename: str) -> str:
        """Derive the branch name for a suffix-stripped Patch (Ready form).

        The default implementation calls ``patch_name_to_branch()`` which
        strips the project prefix, removes the suffix, and converts underscores
        to hyphens.  Git providers override this to keep the Patch name
        as-is (only stripping the suffix).
        """
        from sase.core.patch import patch_name_to_branch

        return patch_name_to_branch(changespec_name, project_basename)

    def derive_branch_name_with_suffix(
        self, changespec_name: str, project_basename: str
    ) -> str:
        """Derive the branch name preserving the ``_N`` suffix (Draft form).

        The default implementation calls ``patch_name_to_branch_with_suffix()``
        which strips the project prefix and converts underscores to hyphens while
        keeping the suffix.  Git providers override this to return the Patch
        name unchanged.
        """
        from sase.core.patch import patch_name_to_branch_with_suffix

        return patch_name_to_branch_with_suffix(changespec_name, project_basename)

    def can_rename_branch(self, cwd: str) -> bool:
        """Return whether the VCS provider can rename branches.

        The default is ``True``.  Providers where branches are immutable once
        pushed (e.g. GitHub with open PRs) should return ``False``.
        """
        return True

    def existing_branch_suffixes(self, base_name: str, cwd: str) -> set[int]:
        """Return the ``_<N>`` suffix numbers already taken on the remote.

        Returns the set of integers ``N`` for which a remote branch named
        ``<base_name>_<N>`` exists.  The commit workflow unions this with the
        Patch namespace when picking the next PR-branch suffix so the
        reserved Patch name never collides with an already-pushed branch.

        The default implementation returns an empty set (no remote namespace
        to consult).
        """
        return set()

    def resolve_revision(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str:
        """Resolve a Patch name to a valid VCS revision.

        The default implementation returns *changespec_name* unchanged,
        which is correct for VCS backends (like hg) where the bookmark
        name matches the Patch name.
        """
        return changespec_name

    def revision_id(self, revision: str, cwd: str) -> str:
        """Return the provider's canonical immutable identity for *revision*.

        Backends whose revision spelling is already immutable can use this
        default. Providers with symbolic refs should override it.
        """

        return revision

    def resolve_current_patch_head_ref(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str:
        """Resolve the current remote-visible head for DELTAS computation.

        DELTAS refreshes may run from a workspace that is not checked out on the
        target Patch branch.  Providers can override this to prefer a
        freshly fetched remote-tracking ref over a stale local branch, while
        still returning the checked-out branch when it is the requested branch.
        """
        return self.resolve_revision(changespec_name, project_basename, cwd)

    def show_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        """Show the patch content for a specific revision.

        Returns ``(True, patch_text)`` on success.
        """
        raise NotImplementedError("show_revision is not supported by this VCS provider")

    def diff_with_untracked(
        self, cwd: str, *, timeout: int = 10
    ) -> tuple[bool, str | None]:
        """Generate a combined diff including both tracked changes and untracked files.

        Returns ``(True, diff_text)`` when there are changes, or
        ``(True, None)`` when the working directory is clean.
        """
        raise NotImplementedError(
            "diff_with_untracked is not supported by this VCS provider"
        )

    def committed_diff(self, cwd: str, *, timeout: int = 10) -> tuple[bool, str | None]:
        """Get the diff from the most recent commit.

        Returns ``(True, diff_text)`` on success, or
        ``(True, None)`` when unavailable.
        """
        raise NotImplementedError(
            "committed_diff is not supported by this VCS provider"
        )

    def get_default_parent_revision(self, cwd: str) -> str:
        """Return the default parent revision for this VCS (e.g. p4head, origin/main)."""
        raise NotImplementedError(
            "get_default_parent_revision is not supported by this VCS provider"
        )

    def diff_name_status(
        self, parent_ref: str, head_ref: str, cwd: str
    ) -> list[tuple[str, str]]:
        """Return ``(status_letter, path)`` pairs between two refs.

        Status letters follow ``git diff --name-status`` conventions: ``A``
        (added), ``M`` (modified), ``D`` (deleted), ``R`` (renamed), ``C``
        (copied), ``T`` (type-changed), ``U`` (unmerged).  Renames/copies
        appear as ``R<score>`` / ``C<score>`` and the row carries both the
        old and new path; the caller is responsible for splitting renames
        and folding unknown letters.

        For renamed entries, the returned ``path`` is encoded as
        ``"<old>\\t<new>"`` so a single tuple carries both paths without
        introducing a richer return type.

        Raises:
            VCSOperationError: When the underlying VCS query fails.
        """
        raise NotImplementedError(
            "diff_name_status is not supported by this VCS provider"
        )

    def diff_line_stats(
        self, parent_ref: str, head_ref: str, cwd: str
    ) -> list[tuple[str, str, str]]:
        """Return raw line stats rows between two refs.

        Rows match ``git diff --numstat`` semantics:
        ``(raw_added, raw_removed, path)``. Binary files use ``"-"`` for
        added/removed counts. Rename/copy rows should carry the target path.
        """
        raise NotImplementedError(
            "diff_line_stats is not supported by this VCS provider"
        )

    def log(
        self,
        cwd: str,
        limit: int,
        *,
        since: int | None = None,
        until: int | None = None,
        authors: tuple[str, ...] = (),
        revs: Sequence[str] = ("HEAD",),
        merges: "MergeVisibility" = "hide",
    ) -> list["VcsCommitWire"]:
        """Return up to *limit* recent commits, newest-first.

        Each commit is a provider-agnostic :class:`VcsCommitWire`
        carrying the full/short id, author name/email, epoch author
        timestamp, parent ids, subject, and body. ``merges`` controls
        merge-commit visibility: ``"hide"`` excludes merge commits,
        ``"show"`` includes every traversed commit, and ``"only"`` returns
        merge commits alone. The default preserves the historical authored
        change-history timeline.

        ``since`` and ``until`` are optional epoch-second bounds. ``authors``
        are case-insensitive substrings matched against author identity with
        OR semantics. ``revs`` selects the revision tips to union. ``limit <= 0``
        means unbounded.

        Raises:
            VCSOperationError: When the underlying VCS query fails.
        """
        raise NotImplementedError("log is not supported by this VCS provider")

    def resolve_remote_log_ref(
        self, cwd: str, ref_name: str | None = None
    ) -> str | None:
        """Resolve the remote-tracking ref used by ``sase stitch list``.

        When *ref_name* is provided, providers should interpret it as an
        explicit remote branch/ref override. Returning ``None`` means no usable
        remote comparison is available, and callers should fall back to local
        history with unknown presence.
        """
        raise NotImplementedError(
            "resolve_remote_log_ref is not supported by this VCS provider"
        )

    def fetch_remote(
        self, cwd: str, refs: Sequence[str], *, timeout: int = 120
    ) -> tuple[bool, str | None]:
        """Fetch only the remote refs needed by ``sase stitch list``."""
        raise NotImplementedError("fetch_remote is not supported by this VCS provider")

    def partition_commits(
        self,
        cwd: str,
        *,
        local_ref: str,
        remote_ref: str,
        merges: "MergeVisibility" = "hide",
    ) -> tuple[set[str], set[str]]:
        """Return ``(ahead_ids, behind_ids)`` for two refs.

        ``merges`` uses the same three-valued contract as :meth:`log` so
        presence labels and ahead/behind counts describe the same slice of
        history as the displayed commits.
        """
        raise NotImplementedError(
            "partition_commits is not supported by this VCS provider"
        )

    def file_at_revision(
        self, revision: str, file_path: str, cwd: str
    ) -> tuple[bool, str | None]:
        """Read a single file's contents at a specific revision.

        Returns ``(True, file_content)`` on success, ``(False, error)`` on failure.
        The *file_path* should be relative to the repository root.
        """
        raise NotImplementedError(
            "file_at_revision is not supported by this VCS provider"
        )

    def sync_workspace(self, cwd: str) -> tuple[bool, str | None]:
        """Sync the workspace with the remote (fetch + rebase / hg sync)."""
        raise NotImplementedError(
            "sync_workspace is not supported by this VCS provider"
        )

    def is_sync_in_progress(self, cwd: str) -> bool:
        """Check whether a sync/rebase operation is currently in progress."""
        raise NotImplementedError(
            "is_sync_in_progress is not supported by this VCS provider"
        )

    def get_conflicted_files(self, cwd: str) -> list[str]:
        """Return a list of files with unresolved merge conflicts."""
        raise NotImplementedError(
            "get_conflicted_files is not supported by this VCS provider"
        )

    def continue_sync(self, cwd: str) -> tuple[bool, str | None]:
        """Continue a paused sync/rebase after conflicts have been resolved."""
        raise NotImplementedError("continue_sync is not supported by this VCS provider")

    def abort_sync(self, cwd: str) -> tuple[bool, str | None]:
        """Abort a sync/rebase in progress and restore the previous state."""
        raise NotImplementedError("abort_sync is not supported by this VCS provider")

    # --- Optional issue-tracker operations ---

    def list_issues(
        self,
        cwd: str,
        state: "IssueListState" = "open",
        limit: int = 100,
    ) -> list["IssueWire"]:
        """List tracker issues for the repository at *cwd*.

        ``state`` accepts ``"open"``, ``"closed"``, or ``"all"`` and
        ``limit <= 0`` means unbounded.
        """
        raise NotImplementedError("list_issues is not supported by this VCS provider")

    def get_issue(self, number: int, cwd: str) -> "IssueWire":
        """Return one tracker issue by repository-local number."""
        raise NotImplementedError("get_issue is not supported by this VCS provider")

    def create_issue(
        self,
        title: str,
        body: str,
        labels: Sequence[str],
        cwd: str,
    ) -> "IssueWire":
        """Create a tracker issue and return its normalized wire record."""
        raise NotImplementedError("create_issue is not supported by this VCS provider")

    def update_issue(
        self,
        number: int,
        cwd: str,
        *,
        title: str | None = None,
        body: str | None = None,
        state: "IssueState | None" = None,
        labels: Sequence[str] | None = None,
    ) -> "IssueWire":
        """Update supplied tracker fields and return the refreshed issue."""
        raise NotImplementedError("update_issue is not supported by this VCS provider")

    def get_issue_url(self, number: int, cwd: str) -> str:
        """Return the browser URL for an issue without fetching its details."""
        raise NotImplementedError("get_issue_url is not supported by this VCS provider")

    # --- Optional pull-request operations ---

    def list_pull_requests(
        self,
        cwd: str,
        state: "PullRequestListState" = "open",
        limit: int = 100,
    ) -> list["PullRequestWire"]:
        """List tracker pull requests for the repository at *cwd*.

        ``state`` accepts ``"open"``, ``"closed"``, or ``"all"`` and
        ``limit <= 0`` means unbounded.
        """
        raise NotImplementedError(
            "list_pull_requests is not supported by this VCS provider"
        )

    # --- Google-internal methods (default raises NotImplementedError) ---

    def reword(self, description: str, cwd: str) -> tuple[bool, str | None]:
        """Reword the current commit's description."""
        raise NotImplementedError("reword is not supported by this VCS provider")

    def reword_add_tag(
        self, tag_name: str, tag_value: str, cwd: str
    ) -> tuple[bool, str | None]:
        """Add a tag to the current commit's description."""
        raise NotImplementedError(
            "reword_add_tag is not supported by this VCS provider"
        )

    def get_description(
        self, revision: str, cwd: str, *, short: bool = False
    ) -> tuple[bool, str | None]:
        """Get the commit description for a revision."""
        raise NotImplementedError(
            "get_description is not supported by this VCS provider"
        )

    def get_branch_name(self, cwd: str) -> tuple[bool, str | None]:
        """Get the current branch / bookmark name."""
        raise NotImplementedError(
            "get_branch_name is not supported by this VCS provider"
        )

    def get_pr_number(self, cwd: str) -> tuple[bool, str | None]:
        """Get the PR / change number for the current branch."""
        raise NotImplementedError("get_pr_number is not supported by this VCS provider")

    def get_cl_number(self, cwd: str) -> tuple[bool, str | None]:
        """Legacy alias for :meth:`get_pr_number`."""
        return self.get_pr_number(cwd)

    def get_workspace_name(self, cwd: str) -> tuple[bool, str | None]:
        """Get the workspace / repository name."""
        raise NotImplementedError(
            "get_workspace_name is not supported by this VCS provider"
        )

    def has_local_changes(self, cwd: str) -> tuple[bool, str | None]:
        """Check whether the working directory has uncommitted changes.

        Returns ``(True, "true"/"false")`` on success.
        """
        raise NotImplementedError(
            "has_local_changes is not supported by this VCS provider"
        )

    def get_bug_number(self, cwd: str) -> tuple[bool, str | None]:
        """Get the bug number associated with the current branch."""
        raise NotImplementedError(
            "get_bug_number is not supported by this VCS provider"
        )

    def mail(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        """Mail / upload a PR for review."""
        raise NotImplementedError("mail is not supported by this VCS provider")

    def fix(self, cwd: str) -> tuple[bool, str | None]:
        """Run automatic code fixes (``hg fix``)."""
        raise NotImplementedError("fix is not supported by this VCS provider")

    def upload(self, cwd: str) -> tuple[bool, str | None]:
        """Upload the current change for review."""
        raise NotImplementedError("upload is not supported by this VCS provider")

    def find_reviewers(self, pr_number: str, cwd: str) -> tuple[bool, str | None]:
        """Find suggested reviewers for a PR/change number."""
        raise NotImplementedError(
            "find_reviewers is not supported by this VCS provider"
        )

    def rewind(self, diff_paths: list[str], cwd: str) -> tuple[bool, str | None]:
        """Rewind changes by importing diffs in reverse."""
        raise NotImplementedError("rewind is not supported by this VCS provider")

    # --- Commit dispatch ---

    def create_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        """Create a commit from a JSON payload."""
        raise NotImplementedError("create_commit is not supported by this VCS provider")

    def create_proposal(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        """Create a proposal from a JSON payload."""
        raise NotImplementedError(
            "create_proposal is not supported by this VCS provider"
        )

    def create_pull_request(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        """Create a pull request from a JSON payload."""
        raise NotImplementedError(
            "create_pull_request is not supported by this VCS provider"
        )

    def finalize_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        """Re-run idempotent post-commit operations after a resumed workflow."""
        raise NotImplementedError(
            "finalize_commit is not supported by this VCS provider"
        )

    def supports_commit_excludes(self) -> bool:
        """Return whether this provider can honor ``-x/--exclude`` on commit dispatch.

        The default is ``False`` so every existing and out-of-tree provider
        defaults to "not supported" without being forced to change. A
        provider that cannot honor excludes must refuse a commit with a
        non-empty exclude list rather than silently committing the excluded
        path.
        """
        return False

    # --- VCS-agnostic methods (default implementations) ---

    def abandon_change(
        self, cl: str, revision: str, cwd: str
    ) -> tuple[bool, str | None]:
        """Abandon/close the remote change (PR, Patch) associated with a revision.

        Called during revert/archive before the local revision is pruned.
        The default implementation is a no-op — providers that manage remote
        changes (PRs, Patches) should override this.

        Returns ``(True, None)`` on success or no-op.
        """
        return (True, None)

    def prepare_description_for_reword(self, description: str) -> str:
        """Prepare a description string for the provider's reword command.

        The default implementation returns the description unchanged.
        Providers that need escaping (e.g. hg's ``$'...'`` quoting) should
        override this method.
        """
        return description

    def normalize_bug_value(self, tag_value: str) -> str:
        """Normalize a BUG tag value for storage in a Patch.

        The default implementation returns the value unchanged.
        Providers with a canonical bug URL format (e.g. ``http://b/<id>``)
        should override this method.
        """
        return tag_value

    def get_change_url(self, cwd: str) -> tuple[bool, str | None]:
        """Get the URL for the current change (PR URL or PR URL).

        Returns ``(True, url)`` on success, ``(True, None)`` if no change
        exists yet (e.g. git branch with no PR).
        """
        raise NotImplementedError(
            "get_change_url is not supported by this VCS provider"
        )

    def get_change_body(self, change_ref: str, cwd: str) -> tuple[bool, str | None]:
        """Get the body/description of a change (PR body or change description).

        Args:
            change_ref: A change identifier (e.g. PR URL or PR number).
            cwd: Working directory inside the repository.

        Returns ``(True, body_text)`` on success, ``(False, error)`` on failure.
        """
        raise NotImplementedError(
            "get_change_body is not supported by this VCS provider"
        )
