"""Bounded clan index for pending chop launch batches."""

from __future__ import annotations

import errno
import json
from pathlib import Path
from typing import Any

from ._chop_batch_store_paths import clan_batch_index_lock_path, clan_batch_index_path
from ._chop_batch_store_shared import (
    MAX_CLAN_BATCH_INDEX_ENTRIES,
    ChopBatchCorruptError,
    ChopBatchError,
    atomic_write_manifest,
    locked,
)


def manifest_clans(manifest: dict[str, Any]) -> set[str]:
    clans: set[str] = set()
    for key in ("clan", "clan_name"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            clans.add(value)
    members = manifest.get("members")
    if isinstance(members, list):
        for member in members:
            if isinstance(member, dict):
                clan = member.get("clan")
                if isinstance(clan, str) and clan:
                    clans.add(clan)
    return clans


def update_clan_batch_index(
    routine: str,
    job: str,
    batch_id: str,
    old_clans: set[str],
    new_clans: set[str],
) -> None:
    path = clan_batch_index_path()
    with locked(clan_batch_index_lock_path()):
        index = read_clan_batch_index(path)
        clans = index.get("clans")
        if not isinstance(clans, dict):
            clans = {}
        entry = {"routine": routine, "job": job, "batch_id": batch_id}
        for clan in old_clans | new_clans:
            rows = clans.get(clan)
            if not isinstance(rows, list):
                rows = []
            rows = [
                item
                for item in rows
                if not (
                    isinstance(item, dict)
                    and item.get("routine") == routine
                    and item.get("job") == job
                    and item.get("batch_id") == batch_id
                )
            ]
            if clan in new_clans:
                rows.append(entry)
                if len(rows) > MAX_CLAN_BATCH_INDEX_ENTRIES:
                    raise ChopBatchError(
                        f"clan {clan!r} reached the bounded pending batch index "
                        f"limit ({MAX_CLAN_BATCH_INDEX_ENTRIES})"
                    )
            if rows:
                clans[clan] = rows
            else:
                clans.pop(clan, None)
        index["schema_version"] = 1
        index["clans"] = clans
        atomic_write_manifest(path, index)


def read_clan_batch_index(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return {"schema_version": 1, "clans": {}}
        raise ChopBatchError(f"cannot read pending batch clan index: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ChopBatchCorruptError(
            f"pending batch clan index is corrupt: {exc}"
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("clans"), dict)
    ):
        raise ChopBatchCorruptError("pending batch clan index has an invalid shape")
    return value
