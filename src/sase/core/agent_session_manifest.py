"""Rust-backed policy facade for agent-session manifest compatibility."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding

SESSION_MANIFEST_WIRE_SCHEMA_VERSION = 1

SESSION_MANIFEST_CLASS_CURRENT = "current"
SESSION_MANIFEST_CLASS_SUPPORTED_LEGACY = "supported_legacy"
SESSION_MANIFEST_CLASS_SLIM = "slim"
SESSION_MANIFEST_CLASS_INVALID = "invalid"

_CLASSIFICATIONS = frozenset(
    {
        SESSION_MANIFEST_CLASS_CURRENT,
        SESSION_MANIFEST_CLASS_SUPPORTED_LEGACY,
        SESSION_MANIFEST_CLASS_SLIM,
        SESSION_MANIFEST_CLASS_INVALID,
    }
)


@dataclass(frozen=True)
class _SessionManifestClassification:
    schema_version: int
    canonical_files: tuple[str, ...]
    legacy_files: tuple[str, ...]
    classification: str
    reason: str


def canonical_session_manifest_files(
    *,
    owner_username: str,
    owner_machine: str,
    local_hood: str,
    run_global_names: tuple[str, ...] | list[str] = (),
    run_file_paths: tuple[str, ...] | list[str] = (),
    containers: tuple[tuple[str, str], ...] | list[tuple[str, str]] = (),
) -> tuple[str, ...]:
    """Derive the current canonical explicit file set through Rust."""
    result = classify_session_manifest_files(
        owner_username=owner_username,
        owner_machine=owner_machine,
        local_hood=local_hood,
        run_global_names=run_global_names,
        run_file_paths=run_file_paths,
        containers=containers,
        explicit_files=None,
    )
    return result.canonical_files


def classify_session_manifest_files(
    *,
    owner_username: str,
    owner_machine: str,
    local_hood: str,
    run_global_names: tuple[str, ...] | list[str] = (),
    run_file_paths: tuple[str, ...] | list[str] = (),
    containers: tuple[tuple[str, str], ...] | list[tuple[str, str]] = (),
    explicit_files: tuple[str, ...] | list[str] | None = None,
) -> _SessionManifestClassification:
    """Classify one explicit manifest list through ``sase_core_rs``."""
    request = {
        "schema_version": SESSION_MANIFEST_WIRE_SCHEMA_VERSION,
        "snapshot": {
            "owner_username": _require_str(owner_username, "owner_username"),
            "owner_machine": _require_str(owner_machine, "owner_machine"),
            "local_hood": _require_str(local_hood, "local_hood"),
            "run_global_names": _require_str_list(run_global_names, "run_global_names"),
            "run_file_paths": _require_str_list(run_file_paths, "run_file_paths"),
            "containers": _containers_to_list(containers),
        },
        "explicit_files": (
            None
            if explicit_files is None
            else _require_str_list(explicit_files, "explicit_files")
        ),
    }
    binding = require_rust_binding("classify_session_manifest_files")
    raw = binding(request)
    return _classification_from_dict(raw)


def _containers_to_list(
    containers: tuple[tuple[str, str], ...] | list[tuple[str, str]],
) -> list[dict[str, str]]:
    if not isinstance(containers, (tuple, list)):
        raise TypeError("containers must be a tuple or list")
    rows: list[dict[str, str]] = []
    for index, item in enumerate(containers):
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise TypeError(f"containers[{index}] must be a (kind, global_name) pair")
        kind, global_name = item
        rows.append(
            {
                "kind": _require_str(kind, f"containers[{index}].kind"),
                "global_name": _require_str(
                    global_name, f"containers[{index}].global_name"
                ),
            }
        )
    return rows


def _classification_from_dict(raw: Any) -> _SessionManifestClassification:
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict manifest decision")
    try:
        result = _SessionManifestClassification(
            schema_version=_require_int(raw, "schema_version"),
            canonical_files=_require_str_tuple(raw, "canonical_files"),
            legacy_files=_require_str_tuple(raw, "legacy_files"),
            classification=_require_str_field(raw, "classification"),
            reason=_require_str_field(raw, "reason"),
        )
    except KeyError as exc:
        raise RuntimeError(
            "sase_core_rs returned an incomplete session manifest "
            f"decision: missing {exc}"
        ) from exc
    if result.schema_version != SESSION_MANIFEST_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs session manifest wire is stale: {result.schema_version}"
        )
    if result.classification not in _CLASSIFICATIONS:
        raise RuntimeError(
            "sase_core_rs returned an unknown manifest "
            f"classification: {result.classification}"
        )
    return result


def _require_str(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a str")
    return value


def _require_str_field(raw: dict[str, Any], key: str) -> str:
    value = raw[key]
    if not isinstance(value, str):
        raise RuntimeError(f"sase_core_rs session manifest field {key!r} is not str")
    return value


def _require_int(raw: dict[str, Any], key: str) -> int:
    value = raw[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(f"sase_core_rs session manifest field {key!r} is not int")
    return value


def _require_str_list(value: object, key: str) -> list[str]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{key} must be a tuple or list")
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise TypeError(f"{key}[{index}] must be a str")
        items.append(item)
    return items


def _require_str_tuple(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    value = raw[key]
    if not isinstance(value, list):
        raise RuntimeError(f"sase_core_rs session manifest field {key!r} is not list")
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise RuntimeError(
                f"sase_core_rs session manifest field {key!r} item {index} is not str"
            )
    return tuple(value)


__all__ = [
    "SESSION_MANIFEST_CLASS_CURRENT",
    "SESSION_MANIFEST_CLASS_INVALID",
    "SESSION_MANIFEST_CLASS_SLIM",
    "SESSION_MANIFEST_CLASS_SUPPORTED_LEGACY",
    "SESSION_MANIFEST_WIRE_SCHEMA_VERSION",
    "canonical_session_manifest_files",
    "classify_session_manifest_files",
]
