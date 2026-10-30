"""Shared types and helpers for the prompt-artifact staging split.

The names here are public so the sibling ``prompt_artifact_staging_*``
modules can import them without touching a ``_``-prefixed symbol across
files. Each value keeps the behavior the former monolithic
:mod:`sase.core.prompt_artifact_staging` module used.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
import os
from pathlib import Path
from typing import TypedDict

from sase.core.rust import require_rust_binding


log = logging.getLogger(__name__)

PROMPT_ARTIFACT_MANIFEST_NAME = "prompt-artifacts.jsonl"
PROMPT_ARTIFACT_MANIFEST_LOCK_NAME = "prompt-artifacts.lock"
PROMPT_ARTIFACT_POOL_DIR = "pool"


class PromptArtifactRecord(TypedDict):
    """Python projection of the Rust-owned prompt-artifact manifest wire."""

    schema_version: int
    recorded_at: str
    agent_artifacts_dir: str
    raw_ref: str
    expanded_ref: str
    ref_kind: str
    label: str
    source_path: str | None
    sha256: str | None
    size_bytes: int | None
    mime_type: str | None
    pool_relpath: str | None
    vcs_repo: str | None
    vcs_relpath: str | None
    vcs_revision: str | None
    locator: str | None
    skipped_reason: str | None
    logical_path: str | None
    root_name: str | None
    authored_path: str | None
    origin: str | None
    object_relpath: str | None
    sidecar_visibility: str | None


def base_record(
    *,
    raw_ref: str,
    expanded_ref: str,
    ref_kind: str,
    label: str,
    locator: str | None,
    agent_artifacts_dir: Path,
) -> PromptArtifactRecord:
    """Return a blank prompt-artifact row stamped with the current wire schema."""

    schema_version = int(require_rust_binding("prompt_artifact_wire_schema_version")())
    return PromptArtifactRecord(
        schema_version=schema_version,
        recorded_at=datetime.now(tz=UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        agent_artifacts_dir=str(agent_artifacts_dir),
        raw_ref=raw_ref,
        expanded_ref=expanded_ref,
        ref_kind=ref_kind,
        label=label,
        source_path=None,
        sha256=None,
        size_bytes=None,
        mime_type=None,
        pool_relpath=None,
        vcs_repo=None,
        vcs_relpath=None,
        vcs_revision=None,
        locator=locator,
        skipped_reason=None,
        logical_path=None,
        root_name=None,
        authored_path=None,
        origin=None,
        object_relpath=None,
        sidecar_visibility=None,
    )


def resolve_agent_artifacts_dir(
    value: Path | str | None,
) -> Path | None:
    """Resolve the per-run artifacts directory, or ``None`` when unset."""

    raw = value if value is not None else os.environ.get("SASE_ARTIFACTS_DIR")
    if raw is None or not str(raw).strip():
        return None
    return Path(raw).expanduser().resolve(strict=False)


def agents_sidecar_metadata(workspace: Path) -> tuple[str, str]:
    """Return ``(repo, visibility)`` for the workspace's agents sidecar."""

    try:
        from sase._linked_repo_config import (
            merged_sidecar_entries_from_config,
            resolution_config,
        )
        from sase._linked_repo_config_keys import (
            SIDECAR_ROLE_KEY,
            SIDECAR_SLUG_KEY,
        )

        config = resolution_config(str(workspace), None)
        for entry in merged_sidecar_entries_from_config(
            config,
            primary_workspace_dir=str(workspace),
        ):
            if entry.get(SIDECAR_ROLE_KEY) == "agents":
                repo = str(entry.get(SIDECAR_SLUG_KEY) or entry.get("name") or "agents")
                visibility = str(entry.get("visibility") or "public")
                return repo, visibility
    except Exception:
        log.debug("Could not resolve agents sidecar visibility", exc_info=True)
    return "agents", "public"


__all__ = [
    "PROMPT_ARTIFACT_MANIFEST_LOCK_NAME",
    "PROMPT_ARTIFACT_MANIFEST_NAME",
    "PROMPT_ARTIFACT_POOL_DIR",
    "PromptArtifactRecord",
    "agents_sidecar_metadata",
    "base_record",
    "resolve_agent_artifacts_dir",
]
