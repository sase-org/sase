"""Journal and destination storage helpers for transactional v2 imports."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
from typing import Any

from sase.agents_sync.io import AgentsSyncFormatError, atomic_write_bytes
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_import_history import read_json
from sase.agents_sync.v2_import_rendering import json_bytes
from sase.agents_sync.v2_io import content_digest, validate_relative_path
from sase.core.dismissed_agents_facade import (
    dismissed_agent_groups_dir as _dismissed_agent_groups_dir,
    dismissed_bundles_dir as _dismissed_bundles_dir,
)
from sase.core.paths import sase_home, sase_projects_dir

JOURNAL_SCHEMA_VERSION = 3
_SUPPORTED_JOURNAL_SCHEMA_VERSIONS = {1, 2, JOURNAL_SCHEMA_VERSION}
_IMPORT_DIR_NAME = "agents_sync_imports"
_TRANSACTION_RE = re.compile(r"^[a-z0-9-]{16,96}$")


def transaction_key_is_valid(transaction_key: str) -> bool:
    return _TRANSACTION_RE.fullmatch(transaction_key) is not None


def transaction_is_complete(project_key: str, transaction_key: str) -> bool:
    path = journal_path(project_key, transaction_key)
    try:
        return read_journal(path).get("state") == "complete"
    except (OSError, AgentsSyncFormatError):
        return False


def imports_root(project_key: str) -> Path:
    return sase_projects_dir() / project_key / _IMPORT_DIR_NAME


def journals_dir(project_key: str) -> Path:
    return imports_root(project_key) / "journals"


def journal_path(project_key: str, transaction_key: str) -> Path:
    if not transaction_key_is_valid(transaction_key):
        raise AgentsSyncFormatError("invalid import transaction key")
    return journals_dir(project_key) / f"{transaction_key}.json"


def read_journal(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise AgentsSyncFormatError(f"invalid import journal {path}")
    schema_version = value.get("schema_version")
    if schema_version not in _SUPPORTED_JOURNAL_SCHEMA_VERSIONS:
        raise AgentsSyncFormatError("unsupported import journal schema")
    key = value.get("transaction_key")
    if not isinstance(key, str) or not transaction_key_is_valid(key):
        raise AgentsSyncFormatError("invalid import journal transaction key")
    if value.get("state") not in {
        "prepared",
        "applying",
        "applied",
        "finalizing",
        "complete",
    }:
        raise AgentsSyncFormatError("invalid import journal state")
    if schema_version in (1, 2):
        value = dict(value)
        value.setdefault("dismissed_identities", [])
        value.setdefault("adopted_v1_artifact_relatives", [])
        value.setdefault("stale_bundle_relatives", [])
        value["schema_version"] = JOURNAL_SCHEMA_VERSION
    for list_key in (
        "files",
        "groups",
        "claims",
        "artifact_relatives",
        "dismissed_identities",
        "adopted_v1_artifact_relatives",
        "stale_bundle_relatives",
    ):
        if not isinstance(value.get(list_key), list):
            raise AgentsSyncFormatError(f"import journal {list_key} must be a list")
    return value


def write_journal(path: Path, journal: dict[str, Any]) -> None:
    atomic_write_bytes(path, json_bytes(journal))


def stage_dir_from_journal(
    target: ProjectTarget,
    journal: Mapping[str, Any],
) -> Path:
    relative = validate_relative_path(journal["stage_relative"])
    root = imports_root(target.project_key)
    stage = root / relative
    if not stage.resolve(strict=False).is_relative_to(root.resolve(strict=False)):
        raise AgentsSyncFormatError("import stage escapes project import root")
    return stage


def stage_file(
    stage: Path,
    rows: list[dict[str, str]],
    destination_kind: str,
    relative: str,
    payload: bytes,
) -> None:
    validate_relative_path(relative)
    stage_relative = f"{destination_kind}/{relative}"
    destination = stage / stage_relative
    atomic_write_bytes(destination, payload)
    rows.append(
        {
            "destination_kind": destination_kind,
            "relative": relative,
            "stage_relative": stage_relative,
            "digest": content_digest(payload),
        }
    )


def destination_path(target: ProjectTarget, row: Mapping[str, str]) -> Path:
    relative = validate_relative_path(row["relative"])
    kind = row["destination_kind"]
    roots = {
        "project": sase_projects_dir() / target.project_key,
        "state": sase_home(),
        "bundles": dismissed_bundles_dir(),
        "groups": dismissed_groups_dir(),
    }
    root = roots.get(kind)
    if root is None:
        raise AgentsSyncFormatError(f"unknown import destination kind {kind!r}")
    destination = root / relative
    if not destination.resolve(strict=False).is_relative_to(root.resolve(strict=False)):
        raise AgentsSyncFormatError("import destination escapes its local root")
    return destination


def dismissed_bundles_dir() -> Path:
    return _dismissed_bundles_dir()


def dismissed_groups_dir() -> Path:
    return _dismissed_agent_groups_dir()


@contextmanager
def project_import_lock(project_key: str) -> Iterator[None]:
    root = imports_root(project_key)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "mutation.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


__all__ = [
    "JOURNAL_SCHEMA_VERSION",
    "destination_path",
    "dismissed_bundles_dir",
    "dismissed_groups_dir",
    "imports_root",
    "journal_path",
    "journals_dir",
    "project_import_lock",
    "read_journal",
    "stage_dir_from_journal",
    "stage_file",
    "transaction_is_complete",
    "transaction_key_is_valid",
    "write_journal",
]
