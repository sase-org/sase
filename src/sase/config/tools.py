"""Project-owned named-tool catalog and ToolRun operational policy.

``tools:`` is read only from the project layer (``sase/sase.yml``) as complete
entries and normalized through Rust. ``tool_runs:`` uses ordinary merged-config
precedence.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.config.core import get_local_config_path, load_config_layers
from sase.config.layers import load_yaml_file_with_metadata
from sase.content_layout import discover_project_root
from sase.core.tool_run import tool_run_normalize_definition


DEFAULT_TOOL_RUNS_SUMMARY_DAYS = 180
DEFAULT_TOOL_RUNS_DETAIL_DAYS = 60
DEFAULT_TOOL_RUNS_LOG_DAYS = 14
DEFAULT_TOOL_RUNS_LOG_MAX_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_TOOL_RUNS_RUN_LOG_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_TOOL_RUNS_EVENT_MAX_BYTES = 16 * 1024 * 1024

_TOOL_RUNS_FIELDS = (
    "summary_days",
    "detail_days",
    "log_days",
    "log_max_bytes",
    "run_log_max_bytes",
    "event_max_bytes",
)


class ToolCatalogError(ValueError):
    """The project tool catalog is missing required shape or failed validation."""


class ToolRunsConfigError(ValueError):
    """Operational ``tool_runs:`` policy is unknown or internally inconsistent."""


@dataclass(frozen=True)
class _ToolCatalogEntry:
    """One normalized named tool plus its definition digest."""

    name: str
    definition: dict[str, Any]
    digest: str
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class ToolCatalog:
    """Provenance-preserving snapshot of the current project's tool catalog."""

    project: str
    path: str | None
    entries: tuple[_ToolCatalogEntry, ...]
    diagnostics: tuple[str, ...]


def tool_project_identity() -> str:
    """Return the stable project identity used for LAST/TYPICAL queries.

    Cheap by design: unlike :func:`load_project_tool_catalog` it reads no config
    layers, so a foreground run can resolve it once per process without paying
    for plugin discovery.
    """
    env = (
        os.environ.get("SASE_PROJECT") or os.environ.get("SASE_PROJECT_NAME") or ""
    ).strip()
    if env:
        return env
    try:
        from sase.bead.project_name import infer_project_name_from_cwd

        inferred = infer_project_name_from_cwd()
        if inferred:
            return inferred
    except Exception:  # noqa: BLE001 - listing still works without a registry hit.
        pass
    root = discover_project_root()
    if root is not None:
        return root.name
    return "unknown"


def load_project_tool_catalog() -> ToolCatalog:
    """Load and Rust-normalize the project-layer ``tools:`` catalog.

    Malformed project YAML or catalog fields raise :class:`ToolCatalogError`
    (CLI exit 2). Missing catalogs are empty, not an error. ``tools:`` entries
    in non-project layers become diagnostics and never change argv identity.
    """
    diagnostics = list(_non_project_tools_diagnostics())
    local_path = get_local_config_path()
    project = tool_project_identity()
    if local_path is None:
        return ToolCatalog(
            project=project,
            path=None,
            entries=(),
            diagnostics=tuple(diagnostics),
        )

    present, data, error = load_yaml_file_with_metadata(local_path)
    if error:
        raise ToolCatalogError(f"{local_path}: {error}")
    if not present or data is None:
        return ToolCatalog(
            project=project,
            path=str(local_path),
            entries=(),
            diagnostics=tuple(diagnostics),
        )

    raw_tools = data.get("tools", {})
    if raw_tools is None:
        raw_tools = {}
    if not isinstance(raw_tools, dict):
        raise ToolCatalogError(
            f"{local_path}: tools must be a mapping of tool name to definition, "
            f"not {type(raw_tools).__name__}"
        )

    entries = tuple(
        _normalize_entry(name, spec, source=str(local_path))
        for name, spec in sorted(raw_tools.items())
    )
    return ToolCatalog(
        project=project,
        path=str(local_path),
        entries=entries,
        diagnostics=tuple(diagnostics),
    )


def get_tool_runs_config() -> dict[str, int]:
    """Return validated ``tool_runs:`` retention policy from merged config.

    Unknown fields and non-positive or inconsistent horizons are errors. This
    policy uses ordinary config precedence; it is independent of ``tools:``.
    """
    from sase.config.core import load_merged_config

    raw = load_merged_config().get("tool_runs", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ToolRunsConfigError("tool_runs must be a mapping")
    unknown = sorted(str(key) for key in raw if key not in _TOOL_RUNS_FIELDS)
    if unknown:
        raise ToolRunsConfigError("unknown tool_runs field(s): " + ", ".join(unknown))

    values = {
        "summary_days": _positive_int(
            raw.get("summary_days", DEFAULT_TOOL_RUNS_SUMMARY_DAYS),
            "tool_runs.summary_days",
            DEFAULT_TOOL_RUNS_SUMMARY_DAYS,
        ),
        "detail_days": _positive_int(
            raw.get("detail_days", DEFAULT_TOOL_RUNS_DETAIL_DAYS),
            "tool_runs.detail_days",
            DEFAULT_TOOL_RUNS_DETAIL_DAYS,
        ),
        "log_days": _positive_int(
            raw.get("log_days", DEFAULT_TOOL_RUNS_LOG_DAYS),
            "tool_runs.log_days",
            DEFAULT_TOOL_RUNS_LOG_DAYS,
        ),
        "log_max_bytes": _positive_int(
            raw.get("log_max_bytes", DEFAULT_TOOL_RUNS_LOG_MAX_BYTES),
            "tool_runs.log_max_bytes",
            DEFAULT_TOOL_RUNS_LOG_MAX_BYTES,
        ),
        "run_log_max_bytes": _positive_int(
            raw.get("run_log_max_bytes", DEFAULT_TOOL_RUNS_RUN_LOG_MAX_BYTES),
            "tool_runs.run_log_max_bytes",
            DEFAULT_TOOL_RUNS_RUN_LOG_MAX_BYTES,
        ),
        "event_max_bytes": _positive_int(
            raw.get("event_max_bytes", DEFAULT_TOOL_RUNS_EVENT_MAX_BYTES),
            "tool_runs.event_max_bytes",
            DEFAULT_TOOL_RUNS_EVENT_MAX_BYTES,
        ),
    }
    if values["detail_days"] > values["summary_days"]:
        raise ToolRunsConfigError("tool_runs.detail_days must be <= summary_days")
    if values["log_days"] > values["detail_days"]:
        raise ToolRunsConfigError("tool_runs.log_days must be <= detail_days")
    return values


def _non_project_tools_diagnostics() -> list[str]:
    try:
        layers = load_config_layers()
    except Exception:  # noqa: BLE001 - catalog listing still works without layers.
        return []
    messages: list[str] = []
    for layer in layers:
        if not layer.ignored_keys:
            continue
        location = layer.path or layer.name
        keys = ", ".join(layer.ignored_keys)
        messages.append(f"{location}: ignoring {keys} (project-owned; not merged)")
    return messages


def _normalize_entry(name: object, spec: object, *, source: str) -> _ToolCatalogEntry:
    if not isinstance(name, str) or not name.strip():
        raise ToolCatalogError(f"{source}: tools keys must be nonempty strings")
    tool_name = name.strip()
    if not isinstance(spec, Mapping):
        raise ToolCatalogError(
            f"{source}: tools.{tool_name} must be a mapping, not {type(spec).__name__}"
        )
    payload = dict(spec)
    payload["schema_version"] = 1
    payload["name"] = tool_name
    try:
        normalized = tool_run_normalize_definition(payload)
    except Exception as exc:  # noqa: BLE001 - surface the field-level diagnostic.
        raise ToolCatalogError(f"{source}: tools.{tool_name}: {exc}") from exc
    definition = dict(normalized.get("definition") or {})
    digest = str(normalized.get("digest") or "")
    if not digest:
        raise ToolCatalogError(
            f"{source}: tools.{tool_name}: missing definition digest"
        )
    diagnostics = tuple(str(item) for item in normalized.get("diagnostics") or ())
    return _ToolCatalogEntry(
        name=tool_name,
        definition=definition,
        digest=digest,
        diagnostics=diagnostics,
    )


def _positive_int(value: object, field: str, default: int) -> int:
    if value is None:
        return default
    if type(value) is int and value >= 1:
        return value
    raise ToolRunsConfigError(f"{field} must be a positive integer")


__all__ = [
    "ToolCatalog",
    "ToolCatalogError",
    "ToolRunsConfigError",
    "get_tool_runs_config",
    "load_project_tool_catalog",
    "tool_project_identity",
]
