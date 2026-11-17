"""Origin synchronization and push helpers for git commit dispatch."""

from typing import TYPE_CHECKING, Any, Literal

from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._types import CommandOutput

_SEMANTIC_REBASE_CONTINUE_LIMIT = 20
_PUSH_REBASE_RETRY_LIMIT = 3


def _rebase_was_noop(output: object) -> bool:
    """Recognize Git's explicit successful no-op rebase result."""
    text = "\n".join(
        str(getattr(output, field, "") or "") for field in ("stdout", "stderr")
    ).lower()
    return "is up to date" in text or "is already up to date" in text


class GitCommitSyncMixin(CommandRunner):
    """Fetch, rebase, and publish commits to the origin remote."""

    if TYPE_CHECKING:

        def _get_default_branch(self, cwd: str) -> str: ...

        def _to_result(
            self, output: CommandOutput, command: str
        ) -> tuple[bool, str | None]: ...

        def vcs_existing_branch_suffixes(
            self, base_name: str, cwd: str
        ) -> set[int]: ...

    def _current_branch(self, cwd: str) -> str | None:
        """Return the checked-out branch, or None for detached HEAD."""
        branch_out = self._run(["git", "symbolic-ref", "--short", "HEAD"], cwd)
        if not branch_out.success:
            return None
        branch = branch_out.stdout.strip()
        return branch or None

    def _head_revision(self, cwd: str, revision: str) -> str | None:
        out = self._run(["git", "rev-parse", revision], cwd)
        if not out.success:
            return None
        value = out.stdout.strip()
        return value or None

    def _has_origin(self, cwd: str) -> bool:
        remote_check = self._run(["git", "remote", "get-url", "origin"], cwd)
        return remote_check.success

    def sync_with_origin_after_commit(
        self, cwd: str, payload: dict | None = None
    ) -> tuple[bool, str | None]:
        """Fetch and rebase the local commit onto origin/<default>."""
        if self._current_branch(cwd) is None:
            return (True, None)
        if not self._has_origin(cwd):
            return (True, None)
        if self._remote_is_empty(cwd):
            return (True, None)
        default_branch = self._get_default_branch(cwd)
        fetch = self._run(
            ["git", "fetch", "origin", default_branch, "--quiet"],
            cwd,
            timeout=600,
        )
        if not fetch.success:
            return self._to_result(fetch, f"git fetch origin {default_branch}")
        gate_capture = None
        if payload is not None:
            from sase.workflows.commit.rebase_gate_coordinator import (
                begin_rebase_gate_capture,
            )

            gate_capture = begin_rebase_gate_capture(
                cwd, self._run, f"origin/{default_branch}", payload
            )
        return self._rebase_onto_origin_default(
            cwd, default_branch, payload=payload, gate_capture=gate_capture
        )

    def _rebase_onto_origin_default(
        self,
        cwd: str,
        default_branch: str,
        payload: dict | None = None,
        gate_capture: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        rebase = self._run(
            ["git", "rebase", "--autostash", f"origin/{default_branch}"],
            cwd,
            timeout=600,
        )
        semantic_rebase = False
        if not rebase.success:
            semantic_rebase = self._continue_rebase_resolving_semantic_conflicts(cwd)
        if rebase.success or semantic_rebase:
            if payload is not None:
                from sase.workflows.commit.rebase_gate_coordinator import (
                    complete_rebase_gate_check,
                )

                gate_outcome: Literal["applied", "no_op"] = (
                    "applied"
                    if semantic_rebase or not _rebase_was_noop(rebase)
                    else "no_op"
                )
                allowed, gate_message = complete_rebase_gate_check(
                    cwd, self._run, payload, gate_capture, outcome=gate_outcome
                )
                if not allowed:
                    self.record_unpushed_commit_marker(payload, cwd, gate_message)
                    return (False, gate_message)
            return (True, None)
        if payload is not None and gate_capture is not None:
            from sase.workflows.commit.rebase_gate_coordinator import (
                stash_rebase_gate_for_conflict,
            )

            stash_rebase_gate_for_conflict(cwd, self._run, payload, gate_capture)
        return (
            False,
            self._format_rebase_conflict(cwd, default_branch, rebase),
        )

    def _continue_rebase_resolving_semantic_conflicts(self, cwd: str) -> bool:
        for _ in range(_SEMANTIC_REBASE_CONTINUE_LIMIT):
            conflicted = self._conflicted_files(cwd)
            if not conflicted:
                return False
            try:
                from sase.sdd._semantic_conflict_resolver import (
                    resolve_semantic_conflicts,
                )

                result = resolve_semantic_conflicts(cwd)
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
            "Resolve the conflict, continue the rebase, then run `sase stitch create --resume`."
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

    def push_with_retry(
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

        if "Refusing Git" in push_out.stderr:
            return self._to_result(push_out, "git push")

        if self._remote_is_empty(cwd):
            err = push_out.stderr.strip() or push_out.stdout.strip()
            return (False, f"git push failed: {err}")

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

    def push_current_branch_with_rebase_retry(
        self, cwd: str, payload: dict | None = None
    ) -> tuple[bool, str | None]:
        """Push current branch, rebasing and retrying on remote movement."""
        if not self._has_origin(cwd):
            return (True, None)
        branch = self._current_branch(cwd)
        if branch is None:
            return (True, None)
        if self._remote_is_empty(cwd):
            push = self._run(["git", "push", "-u", "origin", branch], cwd)
            if push.success:
                if payload is not None:
                    from sase.workflows.commit.rebase_gate_coordinator import (
                        clear_rebase_gate_state,
                    )

                    clear_rebase_gate_state(payload)
                return (True, None)
            return self._to_result(push, "git push")
        default_branch = self._get_default_branch(cwd)
        last_err: str | None = None
        for attempt in range(_PUSH_REBASE_RETRY_LIMIT + 1):
            push = self._run(["git", "push", "origin", branch], cwd)
            if push.success:
                if payload is not None:
                    from sase.workflows.commit.rebase_gate_coordinator import (
                        clear_rebase_gate_state,
                    )

                    clear_rebase_gate_state(payload)
                return (True, None)
            last_err = push.stderr.strip() or push.stdout.strip()
            if "Refusing Git" in last_err:
                return (False, last_err)
            if attempt >= _PUSH_REBASE_RETRY_LIMIT:
                break
            fetch = self._run(
                ["git", "fetch", "origin", default_branch, "--quiet"],
                cwd,
                timeout=600,
            )
            if not fetch.success:
                return self._to_result(fetch, f"git fetch origin {default_branch}")
            from sase.workflows.commit.rebase_gate_coordinator import (
                begin_rebase_gate_capture,
                is_gate_blocked,
            )

            gate_capture = None
            if payload is not None:
                gate_capture = begin_rebase_gate_capture(
                    cwd, self._run, f"origin/{default_branch}", payload
                )
            ok, err = self._rebase_onto_origin_default(
                cwd, default_branch, payload=payload, gate_capture=gate_capture
            )
            if not ok:
                if payload is not None and is_gate_blocked(payload) and err is not None:
                    # Explicit gate finding: keep the message unwrapped so the
                    # workflow can return CONFLICT with repair guidance.
                    return (False, err)
                return (
                    False,
                    f"git push failed and rebase could not resolve it: {err}",
                )
        return (False, f"git push failed after rebase retries: {last_err}")

    def record_unpushed_commit_marker(
        self,
        payload: dict,
        cwd: str,
        push_error: str | None,
    ) -> str | None:
        commit_sha = self._head_revision(cwd, "HEAD")
        if not commit_sha:
            return None
        commit_tree = self._head_revision(cwd, "HEAD^{tree}")
        try:
            from sase.workflows.commit.commit_tracking import (
                write_unpushed_commit_marker,
            )

            write_unpushed_commit_marker(
                "create_commit",
                payload,
                cwd=cwd,
                result=commit_sha,
                commit_sha=commit_sha,
                commit_tree=commit_tree,
                push_error=push_error,
            )
        except Exception:
            pass
        return commit_sha

    def _remote_is_empty(self, cwd: str) -> bool:
        """Return True only when ``origin`` has no heads at all.

        A failed ``ls-remote`` returns False so today's behaviour stays.
        """
        out = self._run(["git", "ls-remote", "--heads", "origin"], cwd, timeout=60)
        return out.success and not out.stdout.strip()
