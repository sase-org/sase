"""Filesystem locations used by the incoming-agent cache."""

from pathlib import Path

from sase.agents_sync.incoming_cache_metadata import (
    metadata_component,
    validate_digest,
)
from sase.core.paths import sase_home


def _agents_sync_state_root() -> Path:
    return sase_home() / "agents_sync"


def receipts_dir() -> Path:
    return _agents_sync_state_root() / "receipts"


def receipts_path(project_key: str) -> Path:
    safe = metadata_component(project_key, "project key")
    return receipts_dir() / f"{safe}.json"


def cache_objects_dir() -> Path:
    return _agents_sync_state_root() / "cache" / "objects"


def cache_staging_dir() -> Path:
    return _agents_sync_state_root() / "cache" / "staging"


def cache_object_path(cache_id: str) -> Path:
    safe = validate_digest(cache_id, "cache ID")
    return cache_objects_dir() / safe
