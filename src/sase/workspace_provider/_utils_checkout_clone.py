"""Git clone creation and corrupt-checkout replacement helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from sase._git_worktree import is_worktree_root, require_worktree_root
from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider._utils_git import (
    command_output,
    git_result_adapter,
    non_interactive_git_env,
    read_required_origin_url,
    set_origin_url,
)
from sase.workspace_provider._utils_origin import (
    heal_clone_origin_if_needed,
    reconcile_managed_checkout_origin,
)
from sase.workspace_provider.git_objects import (
    GitObjectSharingError,
    classify_alternate_state,
    configure_primary_for_sharing,
    ensure_sase_alternate,
    ensure_sase_alternate_for_reuse,
)


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


def _refuse_existing_borrower_after_status_failure(
    primary_workspace_dir: str,
    target_checkout_dir: str,
    *,
    share_git_objects: bool,
    workspace_num: int,
    project_file: str | None,
) -> bool:
    """Preserve a SASE borrower that failed object lookup during ``git status``."""
    del share_git_objects, workspace_num, project_file
    target = target_checkout_dir.rstrip("/")
    if not os.path.exists(os.path.join(target, ".git")):
        return False
    try:
        state = classify_alternate_state(
            target,
            primary_checkout_dir=primary_workspace_dir.rstrip("/"),
        )
    except GitObjectSharingError as exc:
        raise RuntimeError(
            "existing managed checkout failed git status and SASE object-sharing "
            "inspection failed; leaving checkout intact for manual repair: "
            f"{exc}"
        ) from exc
    if state.sase_owned and state.status != "absent":
        raise RuntimeError(
            "existing managed checkout has a broken SASE Git object dependency; "
            "leaving checkout intact for `sase workspace repair`: "
            f"{state.detail or state.status}"
        )
    return False


def _require_clone_target_under(target: str, root: str | Path) -> None:
    """Refuse *target* unless it resolves strictly under *root*."""

    resolved_target = Path(target).expanduser().resolve(strict=False)
    resolved_root = Path(root).expanduser().resolve(strict=False)
    if resolved_target == resolved_root or not resolved_target.is_relative_to(
        resolved_root
    ):
        raise RuntimeError(
            "refusing to clone outside sase/repos/: "
            f"{str(resolved_target)!r} is not under {str(resolved_root)!r}"
        )


def ensure_git_clone_at(
    primary_workspace_dir: str,
    workspace_num: int,
    target_checkout_dir: str,
    *,
    assume_managed_checkout: bool = False,
    share_git_objects: bool = False,
    project_file: str | None = None,
    require_under: str | Path | None = None,
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
        project_file: ProjectSpec path accepted from higher-level checkout
            callers. Existing broken SASE borrowers are preserved for explicit
            repair instead of being recovered during clone materialization.
        require_under: When set (linked/sidecar clones), refuse *target*
            unless it resolves to a strict child of this directory. Callers
            pass the host checkout's ``sase/repos`` root.

    Returns:
        The materialized checkout directory.

    Raises:
        RuntimeError: If the primary directory is missing, the clone fails,
            or *require_under* is set and the target escapes that root.
    """
    if require_under is not None:
        _require_clone_target_under(target_checkout_dir, require_under)
    if workspace_num <= 1:
        if not os.path.isdir(target_checkout_dir.rstrip("/")):
            raise RuntimeError(
                f"Primary workspace directory does not exist: {target_checkout_dir}"
            )
        return target_checkout_dir

    if os.path.lexists(target_checkout_dir) and not is_worktree_root(
        target_checkout_dir
    ):
        target = target_checkout_dir.rstrip("/")
        if (
            os.path.isdir(target)
            and not os.path.islink(target)
            and not os.listdir(target)
        ):
            os.rmdir(target)
        else:
            require_worktree_root(target)

    if os.path.isdir(target_checkout_dir):
        result = subprocess.run(
            ["git", "status"],
            cwd=target_checkout_dir,
            capture_output=True,
            text=True,
            check=False,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            if assume_managed_checkout:
                _heal_reusable_clone_origin(
                    primary_workspace_dir.rstrip("/"),
                    target_checkout_dir.rstrip("/"),
                    assume_managed_checkout=True,
                )
            else:
                heal_clone_origin_if_needed(
                    primary_workspace_dir=primary_workspace_dir.rstrip("/"),
                    target_checkout_dir=target_checkout_dir.rstrip("/"),
                )
            if share_git_objects:
                try:
                    ensure_sase_alternate_for_reuse(
                        primary_workspace_dir.rstrip("/"),
                        target_checkout_dir.rstrip("/"),
                    )
                except GitObjectSharingError as exc:
                    raise RuntimeError(str(exc)) from exc
            return target_checkout_dir
        if _refuse_existing_borrower_after_status_failure(
            primary_workspace_dir,
            target_checkout_dir,
            share_git_objects=share_git_objects,
            workspace_num=workspace_num,
            project_file=project_file,
        ):
            if assume_managed_checkout:
                _heal_reusable_clone_origin(
                    primary_workspace_dir.rstrip("/"),
                    target_checkout_dir.rstrip("/"),
                    assume_managed_checkout=True,
                )
            else:
                heal_clone_origin_if_needed(
                    primary_workspace_dir=primary_workspace_dir.rstrip("/"),
                    target_checkout_dir=target_checkout_dir.rstrip("/"),
                )
            if share_git_objects:
                try:
                    ensure_sase_alternate(
                        primary_workspace_dir.rstrip("/"),
                        target_checkout_dir.rstrip("/"),
                    )
                except GitObjectSharingError as exc:
                    raise RuntimeError(str(exc)) from exc
            return target_checkout_dir
        _remove_corrupt_checkout(target_checkout_dir, workspace_num)

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

    real_url = read_required_origin_url(primary_workspace_dir.rstrip("/"))
    if share_git_objects:
        try:
            configure_primary_for_sharing(primary_workspace_dir.rstrip("/"))
        except GitObjectSharingError as exc:
            raise RuntimeError(str(exc)) from exc

    # Clone builds a fresh target with no pre-existing index.lock to recover.
    clone_cmd = ["git", "clone"]
    if share_git_objects:
        clone_cmd.append("--shared")
    clone_cmd.extend(
        [
            primary_workspace_dir.rstrip("/"),
            target_checkout_dir.rstrip("/"),
        ]
    )
    try:
        subprocess.run(
            clone_cmd,
            capture_output=True,
            text=True,
            check=True,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        if is_worktree_root(target_checkout_dir):
            check = subprocess.run(
                ["git", "status"],
                cwd=target_checkout_dir,
                capture_output=True,
                text=True,
                check=False,
                env=non_interactive_git_env(),
                stdin=subprocess.DEVNULL,
            )
            if check.returncode == 0:
                if assume_managed_checkout:
                    _heal_reusable_clone_origin(
                        primary_workspace_dir.rstrip("/"),
                        target_checkout_dir.rstrip("/"),
                        assume_managed_checkout=True,
                    )
                else:
                    heal_clone_origin_if_needed(
                        primary_workspace_dir=primary_workspace_dir.rstrip("/"),
                        target_checkout_dir=target_checkout_dir.rstrip("/"),
                    )
                if share_git_objects:
                    try:
                        ensure_sase_alternate_for_reuse(
                            primary_workspace_dir.rstrip("/"),
                            target_checkout_dir.rstrip("/"),
                        )
                    except GitObjectSharingError as share_exc:
                        raise RuntimeError(str(share_exc)) from share_exc
                return target_checkout_dir
        if os.path.lexists(target_checkout_dir) and not is_worktree_root(
            target_checkout_dir
        ):
            require_worktree_root(target_checkout_dir)
        error_msg = f"git clone failed (exit code {e.returncode})"
        if e.stderr:
            error_msg += f": {e.stderr.strip()}"
        raise RuntimeError(error_msg) from e

    require_worktree_root(target_checkout_dir)
    set_url_result = set_origin_url(target_checkout_dir.rstrip("/"), real_url)
    if set_url_result.returncode != 0:
        detail = command_output(set_url_result) or "unknown error"
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
        result_adapter=git_result_adapter,
    )

    if share_git_objects:
        try:
            ensure_sase_alternate(
                primary_workspace_dir.rstrip("/"),
                target_checkout_dir.rstrip("/"),
            )
        except GitObjectSharingError as exc:
            raise RuntimeError(str(exc)) from exc

    return target_checkout_dir


def _rescue_doomed_sidecars(target_checkout_dir: str, workspace_num: int) -> None:
    """Bundle every doomed clone under the checkout into the rescue store.

    Best-effort: an unreadable main checkout must never take unpublished
    sidecar, linked, or external repo commits with it. Every rescue call is
    itself non-raising; directory-listing failures simply mean there is
    nothing to rescue.
    """
    from sase.workspace_provider.rescue import rescue_git_repo
    from sase.axe.runner_workspace_protection import (
        rescue_repo_clones_before_eviction,
    )

    target = target_checkout_dir.rstrip("/") or target_checkout_dir
    rescue_repo_clones_before_eviction(
        target,
        workspace_num,
        reason="corrupt workspace checkout replacement: rescuing linked or external repo clone",
    )
    try:
        repos_root = os.path.join(target, "sase", "repos")
        roles = sorted(os.listdir(repos_root)) if os.path.isdir(repos_root) else []
    except OSError:
        return
    for role in roles:
        clone = os.path.join(repos_root, role)
        if not os.path.isdir(os.path.join(clone, ".git")):
            continue
        rescue_git_repo(
            clone,
            workspace_dir=target,
            workspace_num=workspace_num,
            label=role,
            reason=(
                "workspace checkout failed git status and is being replaced; "
                "rescuing sidecar clone before deletion"
            ),
            include_worktree=True,
        )


def _remove_corrupt_checkout(target_checkout_dir: str, workspace_num: int) -> None:
    """Rescue child repositories, then move a corrupt checkout aside for deletion.

    The move is a same-parent rename with background deletion, so replacing
    a corrupt checkout never blocks on a large synchronous ``rmtree``. When
    the rename fails, fall back to a synchronous ``rmtree`` so callers keep
    today's clone-fresh recovery.
    """
    from sase._linked_repo_workspaces import move_aside_for_background_delete
    from sase.workspace_provider.snapshot import (
        NestedPreservationError,
        PreservationError,
        format_preservation_locations,
        preserve_nested_repositories,
    )

    target = target_checkout_dir.rstrip("/") or target_checkout_dir
    try:
        nested = preserve_nested_repositories(
            target,
            workspace_dir=target,
            workspace_num=workspace_num,
            reason="corrupt workspace checkout replacement: nested preservation",
        )
    except NestedPreservationError as exc:
        loc = format_preservation_locations(exc.locations)
        raise RuntimeError(
            "refusing to replace corrupt workspace checkout without complete "
            f"verified nested preservation ({target}): {exc}{loc}"
        ) from exc
    except PreservationError as exc:
        raise RuntimeError(
            "refusing to replace corrupt workspace checkout without complete "
            f"verified nested preservation ({target}): {exc}"
        ) from exc
    if nested.locations:
        print(f"Verified nested preservation: {', '.join(nested.locations)}")
    _rescue_doomed_sidecars(target_checkout_dir, workspace_num)
    try:
        move_aside_for_background_delete(target, tag="sase-corrupt-trash")
    except OSError:
        import shutil

        shutil.rmtree(target, ignore_errors=True)
