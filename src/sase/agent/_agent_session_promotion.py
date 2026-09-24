"""Persist the first member identity when an agent becomes an agent session."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from collections.abc import Mapping
from typing import Any

from sase.agent._agent_session_attach_types import AgentSessionAttachError
from sase.plan_chain import (
    AGENT_SESSION_SEPARATOR,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_ROOT_FIELD,
    agent_session_value,
    canonical_plan_chain_suffix,
    set_agent_session_fields,
)

_GENERIC_ROOT_SUFFIX = f"{AGENT_SESSION_SEPARATOR}0"
_PLAN_ROOT_SUFFIX = PLAN_CHAIN_PLAN_SUFFIX


def agent_session_root_role_suffix(meta: Mapping[str, object]) -> str:
    """Return the persisted suffix for a bare agent becoming a session member."""
    role_suffix = meta.get("role_suffix")
    canonical = canonical_plan_chain_suffix(role_suffix)
    if (
        canonical == PLAN_CHAIN_PLAN_SUFFIX
        or meta.get(PLAN_CHAIN_ROOT_FIELD) is True
        or meta.get("approve") is True
        or meta.get("plan") is True
    ):
        return _PLAN_ROOT_SUFFIX
    return _GENERIC_ROOT_SUFFIX


def normalized_agent_session_root_role_suffix(role_suffix: str | None) -> str:
    """Normalize a caller's original role into its first session-member slot."""
    if canonical_plan_chain_suffix(role_suffix) == PLAN_CHAIN_PLAN_SUFFIX:
        return _PLAN_ROOT_SUFFIX
    return _GENERIC_ROOT_SUFFIX


def promote_agent_session_parent_for_attach(
    plan: Any,
    *,
    wait_for_meta_seconds: float = 5.0,
) -> str:
    """Rename the original parent described by an agent-session-attach launch plan."""
    if not plan.parent_needs_rename:
        return plan.parent_name
    return promote_agent_to_agent_session(
        plan.parent_artifacts_dir,
        plan.parent_base,
        root_role_suffix=plan.parent_agent_session_role_suffix,
        wait_for_meta_seconds=wait_for_meta_seconds,
    )


def promote_agent_to_agent_session(
    artifacts_dir: str | Path,
    base_name: str,
    *,
    root_role_suffix: str | None = None,
    wait_for_meta_seconds: float = 0.0,
) -> str:
    """Persistently rename a bare agent and reserve its session container.

    The artifact directory is timestamp-keyed, so only metadata and the name
    registry change. Both mutations run under the global name-allocation lock;
    the metadata write uses ``os.replace`` so scanners never observe partial
    JSON. Repeated calls are idempotent.
    """
    from sase.agent.names import agent_name_allocation_lock
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        current_owner_agent_name_key,
        normalize_owned_agent_name,
    )

    artifact_path = Path(artifacts_dir).expanduser().resolve(strict=False)
    identity = AgentIdentitySnapshot.current()
    durable_base = normalize_owned_agent_name(base_name, identity)
    meta_path = artifact_path / "agent_meta.json"
    if wait_for_meta_seconds > 0:
        # A just-spawned parent publishes its metadata while holding this same
        # allocation lock. Wait for that first publication before taking the
        # lock, then reread under the lock for the serialized mutation below.
        _read_meta_with_retry(meta_path, timeout_seconds=wait_for_meta_seconds)
    with agent_name_allocation_lock():
        meta = _read_meta_with_retry(
            artifact_path / "agent_meta.json",
            timeout_seconds=0.0,
        )
        current_name = meta.get("name")
        if not isinstance(current_name, str) or not current_name:
            raise AgentSessionAttachError(
                f"Cannot create agent session '{base_name}': parent metadata "
                "does not contain a name."
            )

        existing_agent_session = agent_session_value(meta)
        agent_session_prefix = f"{durable_base}{AGENT_SESSION_SEPARATOR}"
        legacy_agent_session_prefix = f"{base_name}{AGENT_SESSION_SEPARATOR}"
        if current_name.startswith((agent_session_prefix, legacy_agent_session_prefix)):
            if not isinstance(existing_agent_session, str) or (
                current_owner_agent_name_key(existing_agent_session, identity)
                != current_owner_agent_name_key(durable_base, identity)
            ):
                raise AgentSessionAttachError(
                    f"Cannot create agent session '{base_name}': parent "
                    f"'{current_name}' belongs to a different agent session."
                )
            from sase.agent.names import convert_registered_agent_to_agent_session

            convert_registered_agent_to_agent_session(
                durable_base,
                current_name,
                artifact_path,
            )
            _refresh_artifact_index(artifact_path)
            return current_name

        if current_owner_agent_name_key(
            current_name, identity
        ) != current_owner_agent_name_key(durable_base, identity):
            raise AgentSessionAttachError(
                f"Cannot create agent session '{base_name}': resolved parent "
                f"is named '{current_name}'."
            )

        derived_suffix = agent_session_root_role_suffix(meta)
        suffix = (
            _PLAN_ROOT_SUFFIX
            if _PLAN_ROOT_SUFFIX in {root_role_suffix, derived_suffix}
            else root_role_suffix or derived_suffix
        )
        if suffix not in {_GENERIC_ROOT_SUFFIX, _PLAN_ROOT_SUFFIX}:
            raise AgentSessionAttachError(
                f"Cannot create agent session '{base_name}': invalid original "
                f"member suffix '{suffix}'."
            )
        member_name = f"{durable_base}{suffix}"
        promoted = dict(meta)
        promoted["name"] = member_name
        promoted["workflow_name"] = durable_base
        promoted["role_suffix"] = suffix
        set_agent_session_fields(promoted, session=durable_base, role="root")
        if suffix == _PLAN_ROOT_SUFFIX:
            promoted[PLAN_CHAIN_ROOT_FIELD] = True
        else:
            promoted.pop(PLAN_CHAIN_ROOT_FIELD, None)

        _write_json_atomic(meta_path, promoted)
        try:
            from sase.agent.names import convert_registered_agent_to_agent_session

            convert_registered_agent_to_agent_session(
                durable_base,
                member_name,
                artifact_path,
            )
        except Exception:
            _write_json_atomic(meta_path, meta)
            raise

        _refresh_artifact_index(artifact_path)
        return member_name


def _refresh_artifact_index(artifact_path: Path) -> None:
    from sase.core.agent_artifact_index_lifecycle import (
        update_agent_artifact_index_for_marker_mutation,
    )

    update_agent_artifact_index_for_marker_mutation(artifact_path)


def _read_meta_with_retry(path: Path, *, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while True:
        try:
            with open(path, encoding="utf-8") as stream:
                data = json.load(stream)
            if isinstance(data, dict):
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        if time.monotonic() >= deadline:
            raise AgentSessionAttachError(
                f"Cannot create agent session: parent metadata is unavailable at {path}."
            )
        time.sleep(0.05)


def _write_json_atomic(path: Path, data: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    tmp_path = Path(tmp_name)
    replaced = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        os.replace(tmp_path, path)
        replaced = True
    finally:
        if not replaced:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


__all__ = [
    "agent_session_root_role_suffix",
    "normalized_agent_session_root_role_suffix",
    "promote_agent_to_agent_session",
    "promote_agent_session_parent_for_attach",
]
