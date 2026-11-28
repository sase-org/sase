"""Safely preserve and replay unpublished plan-launch graphs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn


def replay_publication_conflict(
    *,
    beads_dir: Path,
    launch_base: str | None,
    epic_id: str,
    checkpoint_sha: str | None,
    attempt_tip_sha: str | None,
    cause: str,
    archived_path: Path,
) -> str:
    """Discard this attempt's unpublished graph; return the recovery ref.

    Raises :class:`EpicFromPlanError` with manual recovery steps when any
    safety check fails; the caller must not reset then.
    """
    from sase.bead.epic_from_plan import EpicFromPlanError
    from sase.bead.sync import bead_store_git_root

    def _refuse(reason: str) -> NoReturn:
        raise EpicFromPlanError(
            _publication_replay_refusal_message(
                cause=cause,
                epic_id=epic_id,
                beads_dir=beads_dir,
                archived_path=archived_path,
                reason=reason,
            ),
            publication_conflict=True,
        )

    repo_root = bead_store_git_root(beads_dir)
    if repo_root is None:
        _refuse(f"could not locate the beads git repo for {beads_dir}")

    try:
        from sase.workspace_provider.ownership import authorize_store_mutation

        authorize_store_mutation(repo_root)
    except Exception as exc:
        _refuse(f"the workspace ownership guard refused the reset: {exc}")

    try:
        from sase.core.state_write_guard import assert_bead_store_write_sandboxed

        assert_bead_store_write_sandboxed(
            beads_dir, operation="publication conflict replay"
        )
    except Exception as exc:
        _refuse(f"the bead-store write sandbox refused the reset: {exc}")

    import subprocess

    from sase.sdd._git import run_sdd_git
    from sase.sdd._git_contention import store_git_write_lock

    def _git(args: list[str], op: str) -> subprocess.CompletedProcess[Any]:
        return run_sdd_git(
            args,
            cwd=repo_root,
            op=op,
            check=False,
            capture_output=True,
            text=True,
        )

    with store_git_write_lock(
        repo_root,
        op="bead.publication_conflict_replay",
        mutates_worktree=True,
    ) as acquired:
        if not acquired:
            _refuse(
                "could not acquire the beads store write lock; another writer holds it"
            )
        fetched = _git(["fetch"], "bead.publication_conflict_replay.fetch")
        if fetched.returncode != 0:
            _refuse(
                "could not fetch the beads repo: "
                f"{(fetched.stderr or fetched.stdout or '').strip()}"
            )
        upstream = _git(
            ["rev-parse", "--verify", "@{upstream}"],
            "bead.publication_conflict_replay.upstream",
        )
        if upstream.returncode != 0 or not upstream.stdout.strip():
            _refuse("the beads clone has no configured upstream to reset to")
        upstream_sha = upstream.stdout.strip()

        if not launch_base:
            _refuse("no launch base was recorded before minting this attempt")
        ancestor = _git(
            ["merge-base", "--is-ancestor", launch_base, "@{upstream}"],
            "bead.publication_conflict_replay.ancestor",
        )
        if ancestor.returncode != 0:
            _refuse(
                f"the launch base {launch_base} is not an ancestor of "
                "@{upstream}; another writer moved the store"
            )

        head = _git(["rev-parse", "HEAD"], "bead.publication_conflict_replay.head")
        if head.returncode != 0 or not head.stdout.strip():
            _refuse("could not read the beads clone HEAD")
        head_sha = head.stdout.strip()

        symbolic = _git(
            ["symbolic-ref", "--quiet", "HEAD"],
            "bead.publication_conflict_replay.branch",
        )
        if symbolic.returncode != 0:
            _refuse("the beads clone is on a detached HEAD; refusing to reset")
        branch = symbolic.stdout.strip().removeprefix("refs/heads/")

        git_dir_result = _git(
            ["rev-parse", "--absolute-git-dir"],
            "bead.publication_conflict_replay.git_dir",
        )
        git_dir_text = git_dir_result.stdout.strip()
        git_dir = Path(git_dir_text) if git_dir_text else None
        markers = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD")
        if git_dir is not None and any(
            (git_dir / marker).exists() for marker in markers
        ):
            _refuse("a git operation is still in progress in the beads clone")

        if head_sha == launch_base:
            _refuse("the beads store holds no unpublished commits for this attempt")

        rev_list = _git(
            ["rev-list", f"{launch_base}..HEAD"],
            "bead.publication_conflict_replay.range",
        )
        if rev_list.returncode != 0:
            _refuse(
                "could not list the unpublished commits: "
                f"{(rev_list.stderr or rev_list.stdout or '').strip()}"
            )
        unpublished = [line for line in rev_list.stdout.splitlines() if line.strip()]
        if not unpublished:
            _refuse("the beads store holds no unpublished commits for this attempt")
        allowed = {sha for sha in (checkpoint_sha, attempt_tip_sha) if sha is not None}
        if not allowed:
            _refuse("this attempt recorded no checkpoint commit to compare against")
        foreign = [sha for sha in unpublished if sha not in allowed]
        if foreign:
            _refuse(
                "commit "
                + ", ".join(foreign)
                + " is not part of this attempt's unpublished graph"
            )

        status = _git(
            ["status", "--porcelain"],
            "bead.publication_conflict_replay.status",
        )
        if status.returncode != 0:
            _refuse("could not inspect the beads worktree for tracked changes")
        tracked_changes = [
            line for line in status.stdout.splitlines() if not line.startswith("??")
        ]
        if tracked_changes:
            _refuse("the beads worktree has other tracked changes")

        import time

        from sase.sdd._repository_recovery_git import (
            recovery_ref,
            update_and_verify_ref,
            verify_managed_reset,
        )

        ref = recovery_ref(repo_root, epic_id, head_sha, time.time())

        def _locked_runner(
            root: Path, args: list[str], *, op: str, network: bool = False
        ) -> subprocess.CompletedProcess[Any]:
            del network
            return run_sdd_git(
                args,
                cwd=root,
                op=op,
                check=False,
                capture_output=True,
                text=True,
            )

        try:
            preserve_problem = update_and_verify_ref(
                repo_root,
                ref,
                head_sha,
                _locked_runner,
                "bead.publication_conflict_replay",
            )
        except Exception as exc:
            _refuse(f"timed out preserving the unpublished graph: {exc}")
        if preserve_problem is not None:
            _refuse(preserve_problem)

        reset = _git(
            ["reset", "--hard", "@{upstream}"],
            "bead.publication_conflict_replay.reset",
        )
        if reset.returncode != 0:
            _refuse(
                "could not reset the beads clone to upstream: "
                f"{(reset.stderr or reset.stdout or '').strip()}; the "
                f"unpublished graph is preserved under {ref}"
            )
        reset_problem = verify_managed_reset(
            repo_root,
            branch=branch,
            upstream_sha=upstream_sha,
            runner=_locked_runner,
        )
        if reset_problem is not None:
            _refuse(f"{reset_problem}; the unpublished graph is preserved under {ref}")
        return ref


def _publication_replay_refusal_message(
    *,
    cause: str,
    epic_id: str,
    beads_dir: Path,
    archived_path: Path,
    reason: str,
) -> str:
    """Render the no-reset failure: cause first, then manual recovery."""
    return (
        f"{cause}\n"
        f"The unpublished launch graph for {epic_id} was NOT discarded: "
        f"{reason}.\n"
        "Recover manually:\n"
        f"  1. rescue the unpublished commits, e.g. `git -C {beads_dir} "
        "update-ref refs/sase/recovery/<name> HEAD`;\n"
        f"  2. reset the beads clone to upstream: `git -C {beads_dir} fetch "
        f"&& git -C {beads_dir} reset --hard @{{upstream}}`;\n"
        f"  3. remove the plan's `bead_id` header from {archived_path};\n"
        f"  4. rerun `sase bead work {archived_path}`.\n"
        "For broader diagnostics, run `sase doctor -v`."
    )
