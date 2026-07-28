"""Shared git operations for configured sidecar initialization."""

from __future__ import annotations

from pathlib import Path
import subprocess

from sase.sdd._commit import network_git_timeout, run_sdd_git
from sase.sdd._store_types import SddMaterializationError


def push_sidecar(root: Path) -> None:
    """Push the current sidecar HEAD or raise a materialization error."""

    try:
        # Push does not update the local index, so index.lock recovery is irrelevant.
        run_sdd_git(
            ["push", "origin", "HEAD"],
            cwd=root,
            op="sdd.sidecar_init.push",
            timeout=network_git_timeout(),
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        raise SddMaterializationError(
            f"failed to push initialized sidecar {root}: {exc}"
        ) from exc
