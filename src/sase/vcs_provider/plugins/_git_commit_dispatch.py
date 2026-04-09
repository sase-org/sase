"""Git commit dispatch mixin.

Provides the high-level commit dispatch methods (create_commit,
create_proposal, create_pull_request) and their supporting helpers,
shared across all git-based VCS plugins.
"""

import os
from typing import TYPE_CHECKING

from sase.telemetry.metrics import VCS_COMMITS, VCS_OPERATIONS
from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import hookimpl


class GitCommitDispatchMixin(CommandRunner):
    """Commit dispatch: create_commit, create_proposal, create_pull_request."""

    _provider_name: str

    if TYPE_CHECKING:
        # Provided by GitCoreOpsMixin in the composed class.
        def _get_default_branch(self, cwd: str) -> str: ...

    # --- Helpers ---

    def _stage_bead_dirs(self, cwd: str) -> None:
        """Stage ``.sase_beads/`` if the directory has uncommitted changes."""
        bead_dir = os.path.join(cwd, ".sase_beads")
        if os.path.isdir(bead_dir):
            status = self._run(["git", "status", "--porcelain", ".sase_beads/"], cwd)
            if status.stdout.strip():
                self._run(["git", "add", ".sase_beads/"], cwd)

    def _stage_extra_paths(self, payload: dict, cwd: str) -> None:
        """Stage extra paths recorded in the payload (e.g. plan file)."""
        plan_path = payload.get("_plan_path", "")
        if plan_path:
            self._run(["git", "add", "--", plan_path], cwd)

    def _validate_staged(self, cwd: str) -> tuple[bool, str | None]:
        """Return failure when the index contains no staged changes."""
        check = self._run(["git", "diff", "--cached", "--quiet"], cwd)
        if check.success:  # exit 0 => nothing staged
            return (False, "No staged changes to commit")
        return (True, None)

    def _merge_with_master(self, cwd: str) -> tuple[bool, str | None]:
        """Fetch and merge ``origin/<default>`` to keep the branch current."""
        # Skip for detached HEAD
        branch_out = self._run(["git", "symbolic-ref", "--short", "HEAD"], cwd)
        if not branch_out.success:
            return (True, None)

        default_branch = self._get_default_branch(cwd)

        self._run(
            ["git", "fetch", "origin", default_branch, "--quiet"], cwd, timeout=600
        )

        # Stash staged changes (--keep-index preserves the index)
        stash_out = self._run(["git", "stash", "--quiet", "--keep-index"], cwd)
        stashed = stash_out.success

        merge_out = self._run(
            ["git", "merge", f"origin/{default_branch}", "--no-edit", "--quiet"], cwd
        )
        if not merge_out.success:
            self._run(["git", "merge", "--abort"], cwd)
            if stashed:
                self._run(["git", "stash", "pop", "--quiet"], cwd)
            return (
                False,
                f"Merge conflict syncing with origin/{default_branch}. "
                "Resolve manually and retry.",
            )

        if stashed:
            pop = self._run(["git", "stash", "pop", "--quiet"], cwd)
            if not pop.success:
                return (
                    False,
                    "Failed to restore staged changes after merge. "
                    "Run 'git stash pop' to recover.",
                )

        return (True, None)

    def _push_with_retry(
        self, cwd: str, push_args: list[str] | None = None
    ) -> tuple[bool, str | None]:
        """Push to origin; on failure pull-and-retry once."""
        remote_check = self._run(["git", "remote", "get-url", "origin"], cwd)
        if not remote_check.success:
            return (True, None)  # no remote -- skip

        if push_args is None:
            branch_out = self._run(["git", "symbolic-ref", "--short", "HEAD"], cwd)
            if not branch_out.success:
                return (True, None)  # detached HEAD -- skip
            push_args = ["origin", branch_out.stdout.strip()]

        push_out = self._run(["git", "push"] + push_args, cwd)
        if push_out.success:
            return (True, None)

        # Pull and retry
        pull_out = self._run(["git", "pull", "--no-edit"], cwd)
        if not pull_out.success:
            self._run(["git", "merge", "--abort"], cwd)
            err = pull_out.stderr.strip() or pull_out.stdout.strip()
            return (False, f"git push failed and pull could not resolve it: {err}")

        push2 = self._run(["git", "push"] + push_args, cwd)
        if not push2.success:
            err = push2.stderr.strip() or push2.stdout.strip()
            return (False, f"git push failed after pull: {err}")
        return (True, None)

    def _post_commit_bead_amend(self, payload: dict, cwd: str) -> None:
        """Add a COMMIT note to the bead and amend ``.sase_beads/`` into the commit."""
        bead_id = payload.get("bead_id")
        if not bead_id:
            return

        rev = self._run(["git", "rev-parse", "--short", "HEAD"], cwd)
        commit_hash = rev.stdout.strip() if rev.success else "unknown"

        self._run(
            ["sase", "bead", "update", bead_id, "--notes", f"COMMIT: {commit_hash}"],
            cwd,
        )

        # Fold bead tracking changes into the commit via amend
        bead_dir = os.path.join(cwd, ".sase_beads")
        if os.path.isdir(bead_dir):
            status = self._run(["git", "status", "--porcelain", ".sase_beads/"], cwd)
            if status.stdout.strip():
                self._run(["git", "add", ".sase_beads/"], cwd)
                self._run(["git", "commit", "--amend", "--no-edit", "--quiet"], cwd)

    # --- Dispatch ---

    @hookimpl
    def vcs_create_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        message = payload.get("message", "")
        files = payload.get("files", [])

        # Stage user files
        if files:
            out = self._run(["git", "add", "--"] + files, cwd)
        else:
            out = self._run(["git", "add", "-A"], cwd)
        if not out.success:
            return self._to_result(out, "git add")

        # Stage .sase_beads/ and extra paths (plan file)
        self._stage_bead_dirs(cwd)
        self._stage_extra_paths(payload, cwd)

        # Validate staged changes exist
        ok, err = self._validate_staged(cwd)
        if not ok:
            return (False, err)

        # Merge with origin/master to keep branch current
        ok, err = self._merge_with_master(cwd)
        if not ok:
            return (False, err)

        # Re-stage .sase_beads/ after merge (merge may modify tracked files)
        self._stage_bead_dirs(cwd)

        out = self._run(["git", "commit", "-m", message], cwd)
        if not out.success:
            return self._to_result(out, "git commit")

        # Post-commit bead note + amend (skip for create_proposal delegation)
        if not payload.get("_skip_bead_amend"):
            self._post_commit_bead_amend(payload, cwd)

        ok, err = self._push_with_retry(cwd)
        if not ok:
            return (False, err)

        rev = self._run(["git", "rev-parse", "--short", "HEAD"], cwd)
        commit_hash = rev.stdout.strip() if rev.success else None
        VCS_COMMITS.labels(provider=self._provider_name, type="create").inc()
        VCS_OPERATIONS.labels(
            provider=self._provider_name, operation="create_commit", status="ok"
        ).inc()
        return (True, commit_hash)

    @hookimpl
    def vcs_create_proposal(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        """Save diff and clean workspace - proposals don't commit."""
        from sase.workflows.commit_utils.workspace import clean_workspace, save_diff

        cl_name = payload.get("name", "") or payload.get("_cl_name", "")
        diff_path = save_diff(cl_name, target_dir=cwd)
        if not diff_path:
            return (False, "No changes to save as proposal diff")

        clean_workspace(cwd)
        return (True, diff_path)

    @hookimpl
    def vcs_create_pull_request(
        self, payload: dict, cwd: str
    ) -> tuple[bool, str | None]:
        name = payload.get("name", "")
        message = payload.get("message", "")
        files = payload.get("files", [])

        out = self._run(["git", "checkout", "-b", name], cwd)
        if not out.success:
            return self._to_result(out, "git checkout -b")

        if files:
            out = self._run(["git", "add", "--"] + files, cwd)
        else:
            out = self._run(["git", "add", "-A"], cwd)
        if not out.success:
            return self._to_result(out, "git add")

        # Stage .sase_beads/ and extra paths
        self._stage_bead_dirs(cwd)
        self._stage_extra_paths(payload, cwd)

        # Validate staged changes
        ok, err = self._validate_staged(cwd)
        if not ok:
            return (False, err)

        out = self._run(["git", "commit", "-m", message], cwd)
        if not out.success:
            return self._to_result(out, "git commit")

        ok, err = self._push_with_retry(cwd, ["-u", "origin", name])
        if not ok:
            return (False, err)
        return (True, None)
