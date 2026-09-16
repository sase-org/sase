"""Parent-node-id hydration and starter-parent repair for monitor records."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
import os
from pathlib import Path
from typing import Any

from ._disposition import CAPTURE_DISPOSITION_NEEDS_RECOVERY, CAPTURE_DISPOSITION_OK
from ._storage import (
    RequiredPortableCaptureError,
    attach_portable_locator,
    continuation_root,
    iter_string_list,
    optional_str,
    read_json_object,
    unique_identifiers,
    update_agent_meta_fields,
    write_json_atomic,
)


def _parent_node_ids_from_meta(
    meta: Mapping[str, Any],
    *,
    exclude: str | None = None,
) -> list[str]:
    return [
        node_id
        for node_id in unique_identifiers(
            [
                meta.get("continuation_node_id"),
                *iter_string_list(meta.get("continuation_parent_node_ids")),
                meta.get("continuation_parent_node_id"),
                meta.get("continuation_parent"),
            ]
        )
        if node_id != exclude
    ]


def wait_for_starter_settle(starter_artifacts_dir: str) -> bool:
    """Wait, bounded, for a named starter to reach its terminal marker.

    Imported lazily: :mod:`sase.shells.followup` pulls in :mod:`sase.agent`
    and :mod:`sase.xprompt`, which import back from this package, so a
    top-level import here would be circular.
    """
    from sase.shells.followup import (
        DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS,
        STARTER_SETTLE_POLL_SECONDS,
        wait_for_starter_artifacts_dir,
    )

    return wait_for_starter_artifacts_dir(
        starter_artifacts_dir,
        timeout_seconds=DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS,
        poll_seconds=STARTER_SETTLE_POLL_SECONDS,
    )


def hydrate_parent_node_ids(
    meta: Mapping[str, Any],
    *,
    exclude: str | None = None,
    starter_artifacts_dir: str | None = None,
) -> list[str]:
    ids = _parent_node_ids_from_meta(meta, exclude=exclude)
    if ids:
        return ids
    starter_dir = starter_artifacts_dir or optional_str(
        meta.get("monitor_starter_artifacts_dir")
    )
    if not starter_dir:
        return []
    starter_meta = read_json_object(Path(starter_dir) / "agent_meta.json")
    return _parent_node_ids_from_meta(starter_meta, exclude=exclude)


_MISSING_STARTER_PARENT_ERROR = (
    "monitor result is missing its exact starter parent node; "
    "automatic dispatch is blocked pending recovery"
)


def missing_essential_starter_parent(
    meta: Mapping[str, Any],
    parent_ids: Sequence[str],
) -> str | None:
    if optional_str(meta.get("monitor_state")) in {"stopped", "lost"}:
        return None
    next_action = optional_str(meta.get("monitor_next_action"))
    if not next_action:
        return None
    has_starter = optional_str(meta.get("monitor_starter_agent")) or optional_str(
        meta.get("monitor_starter_artifacts_dir")
    )
    if not has_starter:
        return None
    if parent_ids:
        return None
    return _MISSING_STARTER_PARENT_ERROR


def repair_missing_starter_parent_disposition(
    artifacts_dir: str | os.PathLike[str],
    meta: MutableMapping[str, Any],
) -> bool:
    """Re-hydrate a published monitor result's starter parent, once more.

    Settlement calls this immediately before it would short-circuit a
    monitor follow-up as ``not-launchable`` because the result-capture
    publish path stamped ``needs_recovery`` for a missing starter parent: the
    starter may have settled in the gap between capture and settlement, after
    the capture path's own bounded wait already expired. When recovery data
    now exists, this backfills the already-written node record and result
    manifest on disk (not just ``meta``) so they stop contradicting each
    other, and clears the disposition. Returns whether it did so.
    """
    if (
        meta.get("continuation_capture_disposition")
        != CAPTURE_DISPOSITION_NEEDS_RECOVERY
    ):
        return False
    if meta.get("continuation_capture_error") != _MISSING_STARTER_PARENT_ERROR:
        return False
    node_id = optional_str(meta.get("continuation_monitor_result_node_id"))
    if not node_id:
        return False
    parent_ids = hydrate_parent_node_ids(meta, exclude=node_id)
    if not parent_ids:
        return False

    root = continuation_root(artifacts_dir)
    node_path = root / "nodes" / f"{node_id}.json"
    node_payload = read_json_object(node_path)
    if not node_payload:
        return False
    node_payload["parent_ids"] = list(parent_ids)
    node_sha = write_json_atomic(node_path, node_payload)

    manifest_path = root / "monitor_result_manifest.json"
    manifest_payload = read_json_object(manifest_path)
    if manifest_payload:
        manifest_payload["parent_node_ids"] = list(parent_ids)
        manifest_payload["node_sha256"] = node_sha
        write_json_atomic(manifest_path, manifest_payload)

    fields: dict[str, Any] = {
        "continuation_capture_disposition": CAPTURE_DISPOSITION_OK,
        "continuation_parent_node_ids": list(parent_ids),
    }
    starter_dir = optional_str(meta.get("monitor_starter_artifacts_dir"))
    try:
        parent_portable = collect_parent_portable_refs(
            artifacts_dir, parent_ids, starter_dir
        )
    except RequiredPortableCaptureError:
        parent_portable = {}
    if parent_portable:
        fields["continuation_parent_portable_refs"] = parent_portable
    meta.update(fields)
    meta.pop("continuation_capture_error", None)
    update_agent_meta_fields(
        artifacts_dir, fields, remove_keys=("continuation_capture_error",)
    )
    return True


def collect_parent_portable_refs(
    artifacts_dir: str | os.PathLike[str],
    parent_ids: Sequence[str],
    starter_artifacts_dir: str | None,
) -> dict[str, str]:
    refs: dict[str, str] = {}
    search_roots = [Path(artifacts_dir)]
    if starter_artifacts_dir:
        starter = Path(starter_artifacts_dir)
        if starter not in search_roots:
            search_roots.append(starter)
    for parent_id in parent_ids:
        node_path = None
        for root in search_roots:
            candidate = root / "continuation" / "nodes" / f"{parent_id}.json"
            if candidate.is_file():
                node_path = candidate
                break
        if node_path is None:
            continue
        portable = attach_portable_locator(
            artifacts_dir,
            parent_id,
            node_path,
            label="parent-node",
            required=True,
        )
        node_payload = read_json_object(node_path)
        content_ref = node_payload.get("content_ref")
        if isinstance(content_ref, str) and content_ref.startswith("local:"):
            content_path = node_path.parent.parent / content_ref.removeprefix(
                "local:continuation/"
            )
            if content_path.is_file():
                attach_portable_locator(
                    artifacts_dir,
                    content_ref,
                    content_path,
                    label="parent-content",
                    required=True,
                )
        if portable:
            refs[parent_id] = portable
    return refs
