"""Commit and push helpers for successful ``sase bead work`` launches."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder


def _resolve_push_mode(no_push: bool) -> str:
    """Resolve the post-commit push mode: ``"sync"``, ``"async"`` or ``"off"``.

    ``--no-push`` always wins. Otherwise ``bead.push_after_commit`` selects the
    behavior: ``true`` (default) pushes synchronously, ``false`` skips the push,
    and ``async`` launches a detached push helper so the command returns without
    waiting on remote network/credential latency. Unknown string values fall
    back to the conservative synchronous push.
    """
    if no_push:
        return "off"

    from sase.config import load_merged_config

    raw = load_merged_config().get("bead", {}).get("push_after_commit", True)
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized == "async":
            return "async"
        if normalized in {"false", "no", "off", "0"}:
            return "off"
        return "sync"
    return "sync" if bool(raw) else "off"


def commit_successful_work_launch(
    beads_dir: Path,
    bead_id: str,
    title: str,
    *,
    kind: str,
    no_push: bool,
    timer: LaunchTimingRecorder,
) -> None:
    from sase.bead.sync import (
        commit_bead_work_launch,
        push_bead_work_launch,
        push_bead_work_launch_async,
    )

    with timer.stage("commit"):
        committed = commit_bead_work_launch(beads_dir, bead_id, title, kind=kind)

    if not committed:
        return

    push_mode = _resolve_push_mode(no_push)
    suffix = ""
    with timer.stage("push", mode=push_mode):
        if push_mode == "sync":
            outcome = push_bead_work_launch(beads_dir)
            if outcome.pushed:
                suffix = " Pushed to remote."
            elif outcome.error is not None:
                from sase.bead._sync_git import find_git_root

                repo_root = find_git_root(beads_dir) or beads_dir
                print(
                    f"Warning: committed bead state for {kind} {bead_id}, "
                    f"but {outcome.error}. Push manually with "
                    f"`cd {shlex.quote(str(repo_root))} && git push`.",
                    file=sys.stderr,
                )
        elif push_mode == "async":
            handle = push_bead_work_launch_async(beads_dir)
            if handle is not None:
                suffix = (
                    f" Pushing to remote in the background (pid {handle.pid}); "
                    f"output logged to {handle.log_path}."
                )
    print(f"Committed bead state for {kind} {bead_id}.{suffix}")
