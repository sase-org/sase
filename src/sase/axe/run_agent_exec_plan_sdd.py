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
    include_plan: bool = True,
    logger: logging.Logger,
    subprocess_run: Callable[..., Any],
) -> bool:
    """Commit an approved SDD plan via ``sase stitch create``.

    The ``#gh`` workflow pre-step runs ``git checkout . && git clean -fd`` which
    wipes uncommitted files.  Committing (and pushing) the SDD files first
    ensures the epic agent can still read them.

    Returns ``True`` when all discovered files are committed, or no files were
    found. Returns ``False`` when ``sase stitch create`` reports failure.
    """
    from sase.sdd.files import find_sdd_file

    fname = f"{plan_name}.md"
    base = Path(workspace_dir)
    plan_found = find_sdd_file(base, "plans", fname)
    if plan_found is None:
        try:
            from sase.sdd.store import read_sdd_store_record, resolve_sdd_dir

            record = read_sdd_store_record(base)
            if record is None:
                from sase.workspace_provider.marker import find_marker_from_cwd

                found = find_marker_from_cwd(str(base))
                if found is not None and found[1].primary_workspace_dir:
                    record = read_sdd_store_record(found[1].primary_workspace_dir)
            if record is not None:
                resolved = resolve_sdd_dir(base, 1)
                if resolved.is_dir():
                    plan_found = find_sdd_file(resolved, "plans", fname)
        except Exception:
            pass
    candidates = (plan_found,) if include_plan else ()
    files = [str(f) for f in candidates if f is not None]
    if not files:
        return True
    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    message = apply_auto_commit_type_tag(
        f"chore: Add SDD plan for {plan_name}",
        "sdd",
    )
    # -M / --message-file expects a file path, not a raw string.
    # handle_commit_command deletes the file after reading it.
    from sase.core.paths import get_sase_managed_tmpdir

    msg_fd, msg_path = tempfile.mkstemp(
        suffix=".txt",
        prefix="sase_sdd_msg_",
        dir=get_sase_managed_tmpdir("commit-messages"),
    )
    try:
        os.write(msg_fd, message.encode())
    finally:
        os.close(msg_fd)
    cmd = ["sase", "stitch", "create", "-M", msg_path]
    for f in files:
        cmd.extend(["-f", f])
    try:
        result = subprocess_run(
            cmd,
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        try:
            os.unlink(msg_path)
        except OSError:
            pass
    if result.returncode != 0:
        logger.warning(
            "sase stitch create for SDD files failed (exit %d): %s",
            result.returncode,
            result.stderr,
        )
        return False
    return True


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
    sdd_sidecar_storage: bool = False,
    fallback_plan_file: str,
) -> str:
    """Build the plan reference passed to a normal coder follow-up."""
    if sdd_plan_path and sdd_plan_path.exists():
        if sdd_sidecar_storage:
            return _workspace_relative_or_absolute(sdd_plan_path, workspace_dir)
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


def _workspace_relative_or_absolute(path: Path, workspace_dir: str) -> str:
    try:
        return path.relative_to(Path(workspace_dir)).as_posix()
    except ValueError:
        return path.as_posix()
