"""Configuration loader for explicit ``@file`` artifact-reference roots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from pathlib import Path
import re
from typing import Any

from sase.config.core import current_config_token, load_config_layers


logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_KNOWN_ROOT_KEYS = frozenset({"name", "path", "path_globs"})
_cache_token: tuple[Any, ...] | None = None
_cache_value: tuple[ArtifactFileRoot, ...] | None = None


@dataclass(frozen=True)
class ArtifactFileRoot:
    """One configured allow-list root for ``@file:<path>`` references."""

    name: str
    path: Path
    path_globs: tuple[str, ...] | None = None
    source_layer: str = "unknown"


def get_artifact_file_roots() -> tuple[ArtifactFileRoot, ...]:
    """Return effective ``@file`` roots, skipping invalid entries."""

    try:
        return _load_artifact_file_roots()
    except (FileNotFoundError, TypeError, ValueError) as exc:
        logger.warning("Failed to load artifact file roots: %s", exc)
        return ()


def _load_artifact_file_roots() -> tuple[ArtifactFileRoot, ...]:
    global _cache_token, _cache_value

    token = current_config_token()
    if _cache_value is not None and _cache_token == token:
        return _cache_value

    effective: dict[str, ArtifactFileRoot] = {}
    order: list[str] = []
    for item, source_layer in _effective_raw_artifact_file_roots():
        try:
            root = parse_artifact_file_root(item, source_layer=source_layer)
        except ValueError as exc:
            root_name = item.get("name") if isinstance(item, Mapping) else "<unknown>"
            logger.warning(
                "Skipping invalid artifact file root '%s' from config layer '%s': %s",
                root_name or "<unknown>",
                source_layer,
                exc,
            )
            continue
        if root.name not in effective:
            order.append(root.name)
        effective[root.name] = root

    _cache_token = token
    _cache_value = tuple(effective[name] for name in order if name in effective)
    return _cache_value


def _effective_raw_artifact_file_roots() -> list[tuple[object, str]]:
    effective: list[tuple[object, str]] = []
    for layer in load_config_layers():
        if not layer.exists or "artifact_refs" not in layer.data:
            continue
        raw_artifact_refs = layer.data.get("artifact_refs")
        if layer.list_strategy == "replace":
            effective = []
        if not isinstance(raw_artifact_refs, Mapping):
            logger.warning(
                "Skipping invalid artifact_refs value from config layer '%s': "
                "expected a mapping",
                layer.name,
            )
            continue
        raw_file = raw_artifact_refs.get("file")
        if raw_file is None:
            continue
        if not isinstance(raw_file, Mapping):
            logger.warning(
                "Skipping invalid artifact_refs.file value from config layer '%s': "
                "expected a mapping",
                layer.name,
            )
            continue
        raw_roots = raw_file.get("roots")
        if raw_roots is None:
            continue
        if not isinstance(raw_roots, list):
            logger.warning(
                "Skipping invalid artifact_refs.file.roots value from config layer "
                "'%s': expected a list",
                layer.name,
            )
            continue
        effective.extend((item, layer.name) for item in raw_roots)
    return effective


def parse_artifact_file_root(
    item: object,
    *,
    source_layer: str,
) -> ArtifactFileRoot:
    if not isinstance(item, Mapping):
        raise ValueError("each root must be a mapping")
    unknown = {str(key) for key in item} - _KNOWN_ROOT_KEYS
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"unknown field(s): {joined}")
    name = item.get("name")
    path = item.get("path")
    if not isinstance(name, str):
        raise ValueError("'name' is required and must be a string")
    if _NAME_RE.fullmatch(name) is None:
        raise ValueError(
            "'name' must be a lowercase slug containing letters, digits, "
            "hyphens, or underscores"
        )
    if not isinstance(path, str) or not path.strip():
        raise ValueError("'path' is required and must be a non-empty string")
    raw_path = path.strip()
    if not (
        raw_path == "~" or raw_path.startswith("~/") or Path(raw_path).is_absolute()
    ):
        raise ValueError("'path' must be absolute or ~/ rooted")
    path_globs = _optional_string_tuple(item.get("path_globs"), "path_globs")
    _validate_path_globs(path_globs)
    return ArtifactFileRoot(
        name=name,
        path=Path(raw_path).expanduser().resolve(strict=False),
        path_globs=path_globs,
        source_layer=source_layer,
    )


def _optional_string_tuple(
    value: object,
    field: str,
) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"'{field}' must be a list of strings")
    return tuple(value)


def _validate_path_globs(path_globs: tuple[str, ...] | None) -> None:
    if path_globs is None:
        return
    from sase.artifact_ref_operations import filter_artifact_ref_paths

    try:
        filter_artifact_ref_paths("file", ("probe",), path_globs=path_globs)
    except (RuntimeError, ValueError) as exc:
        raise ValueError(f"'path_globs' is invalid: {exc}") from exc


__all__ = [
    "ArtifactFileRoot",
    "get_artifact_file_roots",
    "parse_artifact_file_root",
]
