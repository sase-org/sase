"""Lock-protected read-modify-write updates for ``agent_meta.json``."""

from __future__ import annotations

import fcntl
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.artifact_file_helpers import read_json_object

#: Flock guard sibling for ``agent_meta.json`` writers.
_META_LOCK_SUFFIX = ".lock"


def update_agent_meta_locked[T](
    artifacts_dir: Path | str,
    mutate: Callable[[dict[str, Any]], T],
) -> T:
    """Apply ``mutate`` to ``agent_meta.json`` under an exclusive lock.

    ``mutate`` receives the live metadata mapping to update in place and its
    return value is passed through. The marker is written atomically and the
    artifact index is refreshed once after the lock is released.
    """
    artifacts_path = Path(artifacts_dir).expanduser()
    if not artifacts_path.is_dir():
        raise ValueError(f"agent artifacts directory not found: {artifacts_path}")
    meta_path = artifacts_path / "agent_meta.json"
    lock_path = meta_path.with_name(f".{meta_path.name}{_META_LOCK_SUFFIX}")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            meta = read_json_object(meta_path)
            result = mutate(meta)
            write_agent_meta_atomic(artifacts_path, meta, update_index=False)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    update_agent_artifact_index_for_marker_mutation(artifacts_path)
    return result


__all__ = ["update_agent_meta_locked"]
