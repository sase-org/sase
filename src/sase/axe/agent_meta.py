"""Atomic persistence helpers for axe ``agent_meta.json`` files."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path
from typing import Any

from sase.core.agent_tribe import canonicalize_agent_tribe_metadata
from sase.core.patch_metadata import canonicalize_patch_metadata


def write_agent_meta_atomic(
    artifacts_dir: str | os.PathLike[str],
    agent_meta: Mapping[str, Any],
    *,
    update_index: bool = True,
    index_updater: Callable[[str], object] | None = None,
) -> None:
    """Publish ``agent_meta.json`` as a complete sibling-file replacement."""
    payload = dict(agent_meta)
    canonicalize_patch_metadata(payload)
    canonicalize_agent_tribe_metadata(payload)
    if isinstance(agent_meta, MutableMapping):
        agent_meta.clear()
        agent_meta.update(payload)
    artifacts_path = Path(artifacts_dir)
    meta_path = artifacts_path / "agent_meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{meta_path.name}.",
        suffix=".tmp",
        dir=meta_path.parent,
    )
    tmp_path = Path(tmp_name)
    replaced = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
        os.replace(tmp_path, meta_path)
        replaced = True
    finally:
        if not replaced:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
    if update_index:
        if index_updater is None:
            from sase.core.agent_artifact_index_lifecycle import (
                update_agent_artifact_index_for_marker_mutation,
            )

            update_agent_artifact_index_for_marker_mutation(str(artifacts_path))
        else:
            index_updater(str(artifacts_path))


__all__ = ["write_agent_meta_atomic"]
