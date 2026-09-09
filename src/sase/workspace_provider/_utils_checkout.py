"""Project-file helpers and checkout materialization.

Split out of :mod:`sase.workspace_provider.utils`. Import the public
names from that module rather than depending on this one directly.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from typing import Any

from sase.ace.patch import (
    patch_lock,
    write_patch_atomic,
)
from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider._utils_git import (
    command_output as _command_output,
    git_result_adapter as _git_result_adapter,
    non_interactive_git_env,
    read_required_origin_url as _read_required_origin_url,
    set_origin_url as _set_origin_url,
)
from sase.workspace_provider._utils_origin import (
    heal_clone_origin_if_needed as _heal_clone_origin_if_needed,
    reconcile_managed_checkout_origin,
)
from sase.workspace_provider.store import WorkspacePath, WorkspaceStore


def parse_workspace_dir(project_file: str) -> str | None:
    """Parse the WORKSPACE_DIR field from a .gp project file.

    Scans lines before the first ``NAME:`` line for a
    ``WORKSPACE_DIR: <path>`` entry.

    Returns:
        The expanded workspace directory path, or ``None`` if the field
        is absent, the file is missing, or the value is empty.
    """
    if not os.path.exists(project_file):
        return None

    try:
        with open(project_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("NAME:"):
                    break
                if line.startswith("WORKSPACE_DIR:"):
                    value = line.split(":", 1)[1].strip()
                    if value:
                        return os.path.expanduser(value)
                    return None
    except Exception:
        return None

    return None


def parse_bare_repo_dir(project_file: str) -> str | None:
    """Parse the BARE_REPO_DIR field from a .gp project file.

    Scans lines before the first ``NAME:`` line for a
    ``BARE_REPO_DIR: <path>`` entry.

    Returns:
        The expanded bare repo directory path, or ``None`` if the field
        is absent, the file is missing, or the value is empty.
    """
    if not os.path.exists(project_file):
        return None

    try:
        with open(project_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("NAME:"):
                    break
                if line.startswith("BARE_REPO_DIR:"):
                    value = line.split(":", 1)[1].strip()
                    if value:
                        return os.path.expanduser(value)
                    return None
    except Exception:
        return None

    return None


def _invalidate_project_identity() -> None:
    try:
        from sase.project_display_names import invalidate_project_display_snapshot

        invalidate_project_display_snapshot()
    except Exception:
        pass


def set_workspace_dir(project_file: str, workspace_dir: str) -> bool:
    """Set or update the WORKSPACE_DIR field in a .gp project file.

    Creates the file and parent directories if they don't exist.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    try:
        parent_dir = os.path.dirname(project_file)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        if not os.path.exists(project_file):
            with open(project_file, "w", encoding="utf-8") as f:
                f.write(f"WORKSPACE_DIR: {workspace_dir}\n")
            _invalidate_project_identity()
            return True

        with patch_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                content = f.read()

            lines = content.splitlines(keepends=True)
            new_line = f"WORKSPACE_DIR: {workspace_dir}\n"

            # Check if WORKSPACE_DIR already exists — update in place
            for i, line in enumerate(lines):
                if line.startswith("WORKSPACE_DIR:"):
                    lines[i] = new_line
                    write_patch_atomic(
                        project_file,
                        "".join(lines),
                        f"Update WORKSPACE_DIR to {workspace_dir}",
                    )
                    _invalidate_project_identity()
                    return True

            # Insert before first RUNNING: or NAME: line
            insert_idx = len(lines)
            for i, line in enumerate(lines):
                if line.startswith("RUNNING:") or line.startswith("NAME:"):
                    insert_idx = i
                    break

            lines.insert(insert_idx, new_line)
            write_patch_atomic(
                project_file,
                "".join(lines),
                f"Set WORKSPACE_DIR to {workspace_dir}",
            )
            _invalidate_project_identity()
            return True
    except Exception:
        return False


def _heal_reusable_clone_origin(
    primary_workspace_dir: str,
    target_checkout_dir: str,
    *,
    assume_managed_checkout: bool,
) -> None:
    reconcile_managed_checkout_origin(
        target_checkout_dir,
        primary_workspace_dir=primary_workspace_dir,
        assume_managed_checkout=assume_managed_checkout,
    )


def ensure_git_clone_at(
    primary_workspace_dir: str,
    workspace_num: int,
    target_checkout_dir: str,
    *,
    assume_managed_checkout: bool = False,
) -> str:
    """Materialize a Git clone at a caller-supplied target directory.

    The primary checkout (``workspace_num <= 1``) is validated in place
    and the existing path is returned. Any other workspace number
    triggers a clone of ``primary_workspace_dir`` into
    ``target_checkout_dir`` when the target is missing or corrupt.

    Args:
        primary_workspace_dir: Path to the primary checkout (``#0``/``#1``).
        workspace_num: Workspace identity. ``0``/``1`` mean primary;
            everything else materializes a managed clone.
        target_checkout_dir: Absolute path where the clone should live.

    Returns:
        The materialized checkout directory.

    Raises:
        RuntimeError: If the primary directory is missing or the clone fails.
    """
    if workspace_num <= 1:
        if not os.path.isdir(target_checkout_dir.rstrip("/")):
            raise RuntimeError(
                f"Primary workspace directory does not exist: {target_checkout_dir}"
            )
        return target_checkout_dir

    if os.path.isdir(target_checkout_dir):
        result = subprocess.run(
            ["git", "status"],
            cwd=target_checkout_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            if assume_managed_checkout:
                _heal_reusable_clone_origin(
                    primary_workspace_dir.rstrip("/"),
                    target_checkout_dir.rstrip("/"),
                    assume_managed_checkout=True,
                )
            else:
                _heal_clone_origin_if_needed(
                    primary_workspace_dir=primary_workspace_dir.rstrip("/"),
                    target_checkout_dir=target_checkout_dir.rstrip("/"),
                )
            return target_checkout_dir
        import shutil

        shutil.rmtree(target_checkout_dir.rstrip("/"), ignore_errors=True)

    if not os.path.isdir(primary_workspace_dir.rstrip("/")):
        raise RuntimeError(
            f"Primary workspace directory does not exist: {primary_workspace_dir}"
        )

    # Ensure the target's parent directory exists. Adjacent layout always
    # has the parent in place, but managed roots (xdg-state/absolute) may
    # need to create intermediate directories on first use.
    parent = os.path.dirname(target_checkout_dir.rstrip("/"))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    real_url = _read_required_origin_url(primary_workspace_dir.rstrip("/"))

    # Clone builds a fresh target with no pre-existing index.lock to recover.
    try:
        subprocess.run(
            [
                "git",
                "clone",
                primary_workspace_dir.rstrip("/"),
                target_checkout_dir.rstrip("/"),
            ],
            capture_output=True,
            text=True,
            check=True,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        if os.path.isdir(target_checkout_dir):
            check = subprocess.run(
                ["git", "status"],
                cwd=target_checkout_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if check.returncode == 0:
                if assume_managed_checkout:
                    _heal_reusable_clone_origin(
                        primary_workspace_dir.rstrip("/"),
                        target_checkout_dir.rstrip("/"),
                        assume_managed_checkout=True,
                    )
                else:
                    _heal_clone_origin_if_needed(
                        primary_workspace_dir=primary_workspace_dir.rstrip("/"),
                        target_checkout_dir=target_checkout_dir.rstrip("/"),
                    )
                return target_checkout_dir
        error_msg = f"git clone failed (exit code {e.returncode})"
        if e.stderr:
            error_msg += f": {e.stderr.strip()}"
        raise RuntimeError(error_msg) from e

    set_url_result = _set_origin_url(target_checkout_dir.rstrip("/"), real_url)
    if set_url_result.returncode != 0:
        detail = _command_output(set_url_result) or "unknown error"
        raise RuntimeError(
            "git clone succeeded, but rewriting clone origin to the primary "
            f"remote failed: {detail}"
        )

    run_with_git_lock_retry(
        lambda: subprocess.run(
            ["git", "fetch", "--quiet"],
            cwd=target_checkout_dir,
            capture_output=True,
            text=True,
            check=False,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
        ),
        cwd=target_checkout_dir,
        result_adapter=_git_result_adapter,
    )

    return target_checkout_dir


def ensure_workspace_checkout(
    primary_workspace_dir: str,
    workspace_num: int,
    *,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Resolve and materialize the checkout for *workspace_num*.

    Direct callers (git setup, CRS workflow runner, generic workspace
    fallback) use this helper so the path selection rules live in one
    place rather than being re-derived as ``primary_<num>`` string
    concatenations.

    Phase 4 reserved workspace numbers ``1-9``; legacy ``workspace_num
    == 1`` callers that still mean "primary" are normalized to ``#0`` so
    the store routes them through every root policy consistently.

    When the resolved checkout lives under a managed root (xdg-state or
    an absolute ``workspace.root``), this helper also records the
    materialized workspace in the registry and writes a checkout marker
    so ``sase workspace`` and managed-CWD inference can find it later.
    """
    if workspace_num == 1:
        workspace_num = 0
    if config is None:
        from sase.config.core import load_merged_config

        config = load_merged_config()
    store = WorkspaceStore(primary_workspace_dir, config=config, env=env)
    path = store.resolve(workspace_num)
    checkout_dir = ensure_git_clone_at(
        primary_workspace_dir,
        workspace_num,
        path.checkout_dir,
        assume_managed_checkout=store.root_policy != "adjacent",
    )
    _record_managed_workspace(store, path)
    try:
        from sase.sdd.store import ensure_workspace_sdd_clone

        ensure_workspace_sdd_clone(checkout_dir, workspace_num)
    except Exception:
        pass
    return checkout_dir


def _record_managed_workspace(store: WorkspaceStore, path: WorkspacePath) -> None:
    """Best-effort registry + marker write for managed (non-adjacent) roots.

    Adjacent layout keeps its legacy sibling-directory behavior and does
    not need a registry; the operation is intentionally swallowed if the
    write fails so a transient state-root permission error never blocks
    a workspace claim.
    """
    if store.root_policy == "adjacent":
        return
    if path.materialization == "primary":
        return
    try:
        from sase.workspace_provider.marker import write_marker
        from sase.workspace_provider.registry import record_workspace

        record_workspace(store, path)
        write_marker(store, path)
    except Exception:
        return
