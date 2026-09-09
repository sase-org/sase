"""Pre-commit tracking: env resolution and diff capture."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sase.core.paths import sase_subdir

if TYPE_CHECKING:
    from sase.vcs_provider._base import VCSProvider


def resolve_cl_name() -> str | None:
    """Resolve the Patch/branch name from env var or current branch."""
    cl_name = os.environ.get("SASE_AGENT_CL_NAME")
    if cl_name:
        return cl_name
    try:
        from sase.workflows.utils import get_cl_name_from_branch

        return get_cl_name_from_branch()
    except Exception:
        return None


def resolve_project_file() -> str | None:
    """Resolve the project file path from env var or workspace detection."""
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    if project_file:
        return project_file
    try:
        from sase.workflows.utils import (
            get_project_file_path,
            get_project_from_workspace,
        )

        project_name = get_project_from_workspace()
        if not project_name:
            return None
        return get_project_file_path(project_name)
    except Exception:
        return None


def capture_pre_commit_diff(
    provider: VCSProvider, cwd: str, cl_name: str | None
) -> str | None:
    """Capture VCS diff before committing and save it for the COMMITS entry.

    After the VCS commit the working-tree diff is empty, so this must run
    beforehand.  When ``SASE_ARTIFACTS_DIR`` is set (agent context), the
    diff is saved there.  Otherwise it falls back to
    ``~/.sase/diffs/<cl_name>-<timestamp>.diff`` so human CLI commits get
    diffs too.

    Returns the path to the saved diff file, or ``None`` on failure.
    """
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir and not cl_name:
        return None

    try:
        diff_with_untracked = getattr(provider, "diff_with_untracked", None)
        if callable(diff_with_untracked):
            try:
                result = diff_with_untracked(cwd)
            except NotImplementedError:
                result = None
            if isinstance(result, tuple) and len(result) == 2:
                ok, diff_text = result
            else:
                ok, diff_text = provider.diff(cwd)  # type: ignore[union-attr]
        else:
            ok, diff_text = provider.diff(cwd)  # type: ignore[union-attr]
    except Exception:
        return None
    if not ok or not diff_text:
        return None
    if artifacts_dir:
        return write_commit_diff_artifact(
            diff_text,
            artifacts_dir=artifacts_dir,
            write_legacy=True,
        )
    assert cl_name is not None
    from sase.core.time import generate_timestamp

    diffs_dir = str(sase_subdir("diffs"))
    os.makedirs(diffs_dir, exist_ok=True)
    diff_path = os.path.join(diffs_dir, f"{cl_name}-{generate_timestamp()}.diff")
    try:
        with open(diff_path, "w", encoding="utf-8") as f:
            f.write(diff_text)
    except Exception:
        return None
    return diff_path


def write_commit_diff_artifact(
    diff_text: str,
    *,
    artifacts_dir: str | os.PathLike[str],
    write_legacy: bool = False,
) -> str | None:
    """Write a sequential per-commit diff artifact and return its path."""

    artifacts_dir_str = os.fspath(artifacts_dir)
    diff_dir = os.path.join(artifacts_dir_str, "commit_diffs")
    try:
        os.makedirs(diff_dir, exist_ok=True)
        existing_count = sum(
            1
            for name in os.listdir(diff_dir)
            if name.endswith(".diff") and os.path.isfile(os.path.join(diff_dir, name))
        )
        next_index = existing_count + 1
        diff_path = os.path.join(diff_dir, f"{next_index:03d}.diff")
        while os.path.exists(diff_path):
            next_index += 1
            diff_path = os.path.join(diff_dir, f"{next_index:03d}.diff")
        with open(diff_path, "w", encoding="utf-8") as f:
            f.write(diff_text)
    except OSError:
        return None

    if write_legacy:
        try:
            with open(
                os.path.join(artifacts_dir_str, "commit_diff.diff"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(diff_text)
        except OSError:
            pass
    return diff_path
