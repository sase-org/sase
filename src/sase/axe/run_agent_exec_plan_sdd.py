"""SDD plan-reference helpers for agent execution plans."""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


def commit_sdd_files_for_exec_plan(
    workspace_dir: str,
    plan_name: str,
    *,
    plan_tier: str = "tale",
    logger: logging.Logger,
    subprocess_run: Callable[..., Any],
) -> bool:
    """Commit SDD prompt and plan files via ``sase commit`` before launching the epic agent.

    The ``#gh`` workflow pre-step runs ``git checkout . && git clean -fd`` which
    wipes uncommitted files.  Committing (and pushing) the SDD files first
    ensures the epic agent can still read them.

    Returns ``True`` when all discovered files are committed, or no files were
    found. Returns ``False`` when ``sase commit`` reports failure.
    """
    from sase.sdd.files import find_sdd_file

    base = Path(workspace_dir)
    fname = f"{plan_name}.md"
    prompt_found = find_sdd_file(base, "prompts", fname)
    plan_found = find_sdd_file(base, "plans", fname)
    files = [str(f) for f in (prompt_found, plan_found) if f is not None]
    if not files:
        return True
    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    message = apply_auto_commit_type_tag(
        f"chore: Add SDD prompt and plan for {plan_name}",
        "sdd",
    )
    # -M / --message-file expects a file path, not a raw string.
    # handle_commit_command deletes the file after reading it.
    msg_fd, msg_path = tempfile.mkstemp(suffix=".txt", prefix="sase_sdd_msg_")
    try:
        os.write(msg_fd, message.encode())
    finally:
        os.close(msg_fd)
    cmd = ["sase", "commit", "-M", msg_path]
    for f in files:
        cmd.extend(["-f", f])
    result = subprocess_run(
        cmd,
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.warning(
            "sase commit for SDD files failed (exit %d): %s",
            result.returncode,
            result.stderr,
        )
        return False
    return True


def _build_sdd_plan_ref(
    *,
    sdd_plan_path: Path | None,
    sdd_dir: Path,
    workspace_dir: str,
    sdd_plan_name: str | None,
    sdd_in_tree: bool,
    fallback_plan_file: str,
) -> str:
    """Build the plan reference passed to a plan-container creation xprompt."""
    if sdd_plan_path and sdd_plan_path.exists():
        if sdd_in_tree:
            try:
                return sdd_plan_path.relative_to(Path(workspace_dir)).as_posix()
            except ValueError:
                return sdd_plan_path.as_posix()

        try:
            sdd_relative = sdd_plan_path.relative_to(sdd_dir)
            return (Path(".sase") / "sdd" / sdd_relative).as_posix()
        except ValueError:
            try:
                return sdd_plan_path.relative_to(Path(workspace_dir)).as_posix()
            except ValueError:
                return sdd_plan_path.as_posix()

    from sase.sdd.files import get_yyyymm

    yyyymm = get_yyyymm()
    if sdd_plan_name and not sdd_in_tree:
        return f".sase/sdd/plans/{yyyymm}/{sdd_plan_name}.md"
    if sdd_plan_name:
        return f"sdd/plans/{yyyymm}/{sdd_plan_name}.md"
    return fallback_plan_file


def build_epic_plan_ref(
    *,
    sdd_plan_path: Path | None,
    sdd_dir: Path,
    workspace_dir: str,
    sdd_plan_name: str | None,
    sdd_in_tree: bool,
    fallback_plan_file: str,
) -> str:
    """Build the plan reference passed to the epic-creation xprompt."""
    return _build_sdd_plan_ref(
        sdd_plan_path=sdd_plan_path,
        sdd_dir=sdd_dir,
        workspace_dir=workspace_dir,
        sdd_plan_name=sdd_plan_name,
        sdd_in_tree=sdd_in_tree,
        fallback_plan_file=fallback_plan_file,
    )


def plan_tier_for_action(action: str) -> str:
    if action == "epic":
        return "epic"
    return "tale"


def build_saved_plan_ref(
    *,
    sdd_plan_path: Path | None,
    sdd_dir: Path,
    workspace_dir: str,
    sdd_in_tree: bool,
    fallback_plan_file: str,
) -> str:
    """Build the plan reference passed to a normal coder follow-up."""
    if sdd_plan_path and sdd_plan_path.exists():
        if sdd_in_tree:
            try:
                return sdd_plan_path.relative_to(Path(workspace_dir)).as_posix()
            except ValueError:
                return sdd_plan_path.as_posix()

        try:
            sdd_relative = sdd_plan_path.relative_to(sdd_dir)
            return (Path(".sase") / "sdd" / sdd_relative).as_posix()
        except ValueError:
            return sdd_plan_path.as_posix()

    return fallback_plan_file
