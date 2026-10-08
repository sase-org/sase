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


#: ``agent_meta.json`` keys owned by the ``A`` toggle's ``%auto`` state. The
#: toggle adds/removes exactly these keys on disk; every runner write-back
#: after initial directive extraction must let the on-disk values win so a
#: stale in-memory copy cannot undo the toggle.
AUTO_STATE_KEYS = ("approve", "auto_approve_plan_action", "auto_approve_argument")


def read_live_agent_meta(artifacts_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Return the on-disk ``agent_meta.json`` dict, or ``{}`` when unusable.

    Missing, unreadable, or non-dict meta means no auto (fail closed); the
    caller treats the empty dict as "no live auto state".
    """
    loaded = _read_disk_meta(artifacts_dir)
    return loaded if loaded is not None else {}


def _read_disk_meta(
    artifacts_dir: str | os.PathLike[str],
) -> dict[str, Any] | None:
    """Return the on-disk ``agent_meta.json`` dict, or ``None`` when unusable."""
    try:
        with open(Path(artifacts_dir) / "agent_meta.json", encoding="utf-8") as stream:
            loaded = json.load(stream)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return loaded if isinstance(loaded, dict) else None


def overlay_live_auto_keys(
    artifacts_dir: str | os.PathLike[str],
    agent_meta: MutableMapping[str, Any],
    *,
    disk_meta: Mapping[str, Any] | None = None,
) -> MutableMapping[str, Any]:
    """Overlay the on-disk auto keys onto an in-memory meta dict.

    The live ``agent_meta.json`` values of :data:`AUTO_STATE_KEYS` win,
    including their absence: a key the toggle removed from disk is removed
    from *agent_meta* too, so a later write-back cannot resurrect it. Pass
    an already-loaded *disk_meta* when the caller holds one to avoid a
    second read; otherwise the file is read fresh. When no usable disk
    meta exists (the file is not written yet, or it is corrupt), *agent_meta*
    passes through unchanged: there is no live state to win, and a corrupt
    file must not destroy the only good copy.
    """
    live = disk_meta if disk_meta is not None else _read_disk_meta(artifacts_dir)
    if live is None:
        return agent_meta
    for key in AUTO_STATE_KEYS:
        if key in live:
            agent_meta[key] = live[key]
        else:
            agent_meta.pop(key, None)
    return agent_meta


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
    from sase.core.agent_tribe_evidence import invalidate_agent_tribe_evidence_cache

    invalidate_agent_tribe_evidence_cache()


__all__ = [
    "AUTO_STATE_KEYS",
    "overlay_live_auto_keys",
    "read_live_agent_meta",
    "write_agent_meta_atomic",
]
