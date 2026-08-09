"""Git commit dispatch mixin.

Provides the high-level commit dispatch methods (create_commit,
create_proposal, create_pull_request) and their supporting helpers,
shared across all git-based VCS plugins.
"""

import os
from typing import TYPE_CHECKING

from sase.bead.project import BEADS_DIRNAME
from sase.telemetry.metrics import VCS_OPERATIONS
from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import hookimpl

_BEAD_REBASE_CONTINUE_LIMIT = 20
_PUSH_REBASE_RETRY_LIMIT = 3


class GitCommitDispatchMixin(CommandRunner):
    """Commit dispatch: create_commit, create_proposal, create_pull_request."""

    _provider_name: str

    if TYPE_CHECKING:
        # Provided by GitCoreOpsMixin in the composed class.
        def _get_default_branch(self, cwd: str) -> str: ...

        # Provided by GitQueryOpsMixin in the composed class.
        def vcs_existing_branch_suffixes(
            self, base_name: str, cwd: str
        ) -> set[int]: ...

    # --- Helpers ---

    def _changed_bead_files(self, cwd: str) -> list[str]:
        """Return concrete changed files in the version-controlled bead store."""
        bead_dir = os.path.join(cwd, BEADS_DIRNAME)
        bead_pathspec = f"{BEADS_DIRNAME}/"
        if not os.path.isdir(bead_dir):
            return []
        out = self._run(
            [
                "git",
                "ls-files",
                "--modified",
                "--others",
                "--deleted",
                "--exclude-standard",
                "-z",
                "--",
                bead_pathspec,
            ],
            cwd,
        )
        if not out.success:
            return []
        return [path for path in out.stdout.split("\0") if path]

    def _stage_bead_dirs(self, cwd: str) -> None:
        """Stage the version-controlled bead store if it has changes."""
        changed_files = self._changed_bead_files(cwd)
        if changed_files:
            self._run(["git", "add", "--"] + changed_files, cwd)

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

    def _current_branch(self, cwd: str) -> str | None:
        """Return the checked-out branch, or None for detached HEAD."""
        branch_out = self._run(["git", "symbolic-ref", "--short", "HEAD"], cwd)
        if not branch_out.success:
            return None
        branch = branch_out.stdout.strip()
        return branch or None

    def _has_origin(self, cwd: str) -> bool:
        remote_check = self._run(["git", "remote", "get-url", "origin"], cwd)
        return remote_check.success

    def _sync_with_origin_after_commit(self, cwd: str) -> tuple[bool, str | None]:
        """Fetch and rebase the local commit onto origin/<default>."""
        if self._current_branch(cwd) is None:
            return (True, None)
        if not self._has_origin(cwd):
            return (True, None)
        default_branch = self._get_default_branch(cwd)
        fetch = self._run(
            ["git", "fetch", "origin", default_branch, "--quiet"],
            cwd,
            timeout=600,
        )
        if not fetch.success:
            return self._to_result(fetch, f"git fetch origin {default_branch}")
        return self._rebase_onto_origin_default(cwd, default_branch)

    def _rebase_onto_origin_default(
        self, cwd: str, default_branch: str
    ) -> tuple[bool, str | None]:
        rebase = self._run(
            ["git", "rebase", "--autostash", f"origin/{default_branch}"],
            cwd,
            timeout=600,
        )
        if rebase.success:
            return (True, None)
        if self._continue_rebase_resolving_beads(cwd):
            return (True, None)
        return (
            False,
            self._format_rebase_conflict(cwd, default_branch, rebase),
        )

    def _continue_rebase_resolving_beads(self, cwd: str) -> bool:
        for _ in range(_BEAD_REBASE_CONTINUE_LIMIT):
            conflicted = self._conflicted_files(cwd)
            if not conflicted or not self._all_bead_conflicts(conflicted):
                return False
            try:
                from sase.bead.conflict_resolver import resolve_bead_conflicts

                result = resolve_bead_conflicts(cwd)
            except Exception:
                return False
            if not result.ok:
                return False
            continued = self._run(
                ["git", "-c", "core.editor=true", "rebase", "--continue"],
                cwd,
                timeout=600,
            )
            if continued.success:
                return True
        return False

    def _conflicted_files(self, cwd: str) -> list[str]:
        out = self._run(["git", "diff", "--name-only", "--diff-filter=U"], cwd)
        if not out.success:
            return []
        return [line.strip() for line in out.stdout.splitlines() if line.strip()]

    def _all_bead_conflicts(self, files: list[str]) -> bool:
        prefix = f"{BEADS_DIRNAME}/"
        return bool(files) and all(path.startswith(prefix) for path in files)

    def _format_rebase_conflict(
        self, cwd: str, default_branch: str, rebase_out: object
    ) -> str:
        conflicted = self._conflicted_files(cwd)
        detail = getattr(rebase_out, "stderr", "") or getattr(rebase_out, "stdout", "")
        parts = [
            f"Rebase conflict syncing with origin/{default_branch}.",
        ]
        if conflicted:
            parts.append("Conflicted files: " + ", ".join(conflicted))
            incoming = self._incoming_commits_for_files(cwd, default_branch, conflicted)
            if incoming:
                parts.append("Incoming commits touching conflicted files:\n" + incoming)
        if detail.strip():
            parts.append(detail.strip())
        parts.append(
            "Resolve the conflict, continue the rebase, then run `sase commit --resume`."
        )
        return "\n".join(parts)

    def _incoming_commits_for_files(
        self, cwd: str, default_branch: str, files: list[str]
    ) -> str:
        for rev_range in (
            f"ORIG_HEAD..origin/{default_branch}",
            f"HEAD..origin/{default_branch}",
        ):
            out = self._run(
                ["git", "log", "--oneline", rev_range, "--", *files],
                cwd,
            )
            if out.success and out.stdout.strip():
                return out.stdout.strip()
        return ""

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

    def _push_current_branch_with_rebase_retry(
        self, cwd: str
    ) -> tuple[bool, str | None]:
        """Push current branch, rebasing and retrying on remote movement."""
        if not self._has_origin(cwd):
            return (True, None)
        branch = self._current_branch(cwd)
        if branch is None:
            return (True, None)
        default_branch = self._get_default_branch(cwd)
        last_err: str | None = None
        for attempt in range(_PUSH_REBASE_RETRY_LIMIT + 1):
            push = self._run(["git", "push", "origin", branch], cwd)
            if push.success:
                return (True, None)
            last_err = push.stderr.strip() or push.stdout.strip()
            if attempt >= _PUSH_REBASE_RETRY_LIMIT:
                break
            fetch = self._run(
                ["git", "fetch", "origin", default_branch, "--quiet"],
                cwd,
                timeout=600,
            )
            if not fetch.success:
                return self._to_result(fetch, f"git fetch origin {default_branch}")
            ok, err = self._rebase_onto_origin_default(cwd, default_branch)
            if not ok:
                return (
                    False,
                    f"git push failed and rebase could not resolve it: {err}",
                )
        return (False, f"git push failed after rebase retries: {last_err}")

    def _remote_branch_exists(self, name: str, cwd: str) -> bool:
        """Return True when ``name`` already exists as a remote head on origin."""
        out = self._run(
            ["git", "ls-remote", "--heads", "origin", name], cwd, timeout=60
        )
        return out.success and bool(out.stdout.strip())

    def _resuffix_and_push(
        self, payload: dict, cwd: str, name: str
    ) -> tuple[bool, str | None]:
        """Rename the local branch to the next free remote suffix and push.

        Handles the residual race where another agent pushes ``<base>_<N>``
        between suffix reservation and this push.  On success the new name is
        written back into ``payload["name"]`` and ``payload["_resuffixed"]`` is
        set so the commit workflow re-points the Patch reservation to the
        branch that was actually pushed (keeping NAME and branch consistent).

        Returns ``(True, None)`` once a free branch is pushed, or
        ``(False, err)`` if no suffixed name can be derived or all attempts
        collide.
        """
        import re

        match = re.match(r"^(.*)_(\d+)$", name)
        if not match:
            # Not a ``_<N>`` name — nothing to re-suffix.
            return (False, f"branch '{name}' already exists on the remote")
        base = match.group(1)

        last_err: str | None = None
        for _ in range(10):
            taken = self.vcs_existing_branch_suffixes(base, cwd)
            next_n = 1
            while next_n in taken:
                next_n += 1
            new_name = f"{base}_{next_n}"

            rename = self._run(["git", "branch", "-m", new_name], cwd)
            if not rename.success:
                return self._to_result(rename, "git branch -m")

            ok, err = self._push_with_retry(cwd, ["-u", "origin", new_name])
            if ok:
                payload["name"] = new_name
                payload["_resuffixed"] = True
                return (True, None)

            last_err = err
            if not self._remote_branch_exists(new_name, cwd):
                # Failure was not a branch collision — stop retrying.
                break
            name = new_name

        return (False, last_err or "exhausted branch re-suffix attempts")

    def _amend_bead_changes(self, payload: dict, cwd: str) -> None:
        """Fold any post-commit bead-store changes into the commit.

        This intentionally does not write the commit SHA into bead notes: the SHA
        would become stale after the amend or rebase, and ``--notes`` overwrites
        existing notes rather than appending to them.
        """
        bead_id = payload.get("bead_id")
        if not bead_id:
            return

        # Fold bead tracking changes into the commit via amend
        changed_files = self._changed_bead_files(cwd)
        if changed_files:
            add_out = self._run(["git", "add", "--"] + changed_files, cwd)
            if add_out.success:
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

        # Stage bead state and extra paths (plan file)
        self._stage_bead_dirs(cwd)
        self._stage_extra_paths(payload, cwd)

        # Validate staged changes exist
        ok, err = self._validate_staged(cwd)
        if not ok:
            return (False, err)

        out = self._run(["git", "commit", "-m", message], cwd)
        if not out.success:
            return self._to_result(out, "git commit")

        # Fold post-commit bead changes in (skip for create_proposal delegation)
        if not payload.get("_skip_bead_amend"):
            self._amend_bead_changes(payload, cwd)

        ok, err = self._sync_with_origin_after_commit(cwd)
        if not ok:
            return (False, err)

        ok, err = self._push_current_branch_with_rebase_retry(cwd)
        if not ok:
            return (False, err)

        rev = self._run(["git", "rev-parse", "--short", "HEAD"], cwd)
        commit_hash = rev.stdout.strip() if rev.success else None
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

        # Stage bead state and extra paths
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
            # A concurrent agent may have pushed this branch between suffix
            # reservation and now (a namespace race that remote-aware
            # reservation narrows but cannot fully close). Recover by renaming
            # to the next free remote suffix and retrying, so the workflow
            # still records a Patch instead of leaving the agent to
            # hand-roll an orphaned PR.
            if self._remote_branch_exists(name, cwd):
                ok, err = self._resuffix_and_push(payload, cwd, name)
            if not ok:
                return (False, err)
        return (True, None)

    @hookimpl
    def vcs_finalize_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        """Re-run idempotent post-commit operations after a resumed workflow."""
        if not payload.get("_skip_bead_amend"):
            self._amend_bead_changes(payload, cwd)
        ok, err = self._push_current_branch_with_rebase_retry(cwd)
        if not ok:
            return (False, err)
        VCS_OPERATIONS.labels(
            provider=self._provider_name,
            operation="finalize_commit",
            status="ok",
        ).inc()
        return (True, None)
