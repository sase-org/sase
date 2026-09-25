"""Project-owned named-tool catalog and ToolRun operational policy.

``tools:`` is read only from the project layer (``sase/sase.yml``) as complete
entries and normalized through Rust. ``tool_runs:`` uses ordinary merged-config
precedence.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
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

_GIT_REMOTE_TIMEOUT_SECONDS = 5.0
_WORKSPACE_SUFFIX = re.compile(r"_\d+$")
_UNSAFE_KEY_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")

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


def tool_project_identity(root: Path | str | None = None) -> str:
    """Return the project identity a ToolRun is recorded and queried under.

    *root* is the repository that owns the resolved tool catalog (or, for an
    ad-hoc run, the repository of its working directory); ``None`` means the
    current directory's repository. The identity comes from that repository,
    never from ``SASE_PROJECT``: that variable names the agent's own project,
    so a run from a linked repo checkout must not inherit it. A registered
    project keeps its registry key; any other repository gets a stable key
    derived from its origin remote or directory name. Failures degrade to
    ``"unknown"`` because recording is fail-open.
    """
    try:
        project_root = discover_project_root(root)
        if project_root is None:
            return "unknown"
        return _registered_project_name(project_root) or _derived_project_key(
            project_root
        )
    except Exception:  # noqa: BLE001 - attribution still works without a registry hit.
        return "unknown"


def _registered_project_name(root: Path) -> str | None:
    from sase.bead.project_name import infer_project_name_from_cwd

    try:
        return infer_project_name_from_cwd(str(root), exact=True)
    except Exception:  # noqa: BLE001 - an unregistered repo still has an identity.
        return None


def _derived_project_key(root: Path) -> str:
    """Key an unregistered repo the way ProjectSpec directories are keyed.

    A GitHub origin yields ``gh_<owner>__<repo>``; otherwise the directory
    name with any ``_<N>`` workspace suffix stripped, so every numbered
    checkout of one repo shares an identity.
    """
    from sase._git_remote import parse_hosted_git_remote

    remote = ""
    # Only a repo's own remote counts; git would otherwise walk up to a parent.
    if (root / ".git").exists():
        try:
            completed = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=_GIT_REMOTE_TIMEOUT_SECONDS,
            )
            remote = completed.stdout.strip() if completed.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            pass
    parsed = parse_hosted_git_remote(remote) if remote else None
    if parsed is not None and parsed.host == "github.com":
        owner, _, repo = parsed.repo.partition("/")
        if owner and repo and "/" not in repo:
            return f"gh_{owner}__{repo}"
    name = _WORKSPACE_SUFFIX.sub("", root.name)
    return _UNSAFE_KEY_CHARACTERS.sub("-", name).strip("-") or "unknown"


def load_project_tool_catalog() -> ToolCatalog:
    """Load and Rust-normalize the project-layer ``tools:`` catalog.

    Malformed project YAML or catalog fields raise :class:`ToolCatalogError`
    (CLI exit 2). Missing catalogs are empty, not an error. ``tools:`` entries
    in non-project layers become diagnostics and never change argv identity.
    """
    diagnostics = list(_non_project_tools_diagnostics())
    local_path = get_local_config_path()
    return _load_catalog_from_path(
        local_path, root=discover_project_root(), diagnostics=diagnostics
    )


def load_project_tool_catalog_at(start: Path | str | None) -> ToolCatalog:
    """Load the ``tools:`` catalog for the project containing *start*.

    Unlike :func:`load_project_tool_catalog` this resolves the project root
    from *start* instead of the current working directory, so a monitor
    started for another checkout resolves that checkout's catalog rather
    than the starting agent's. Malformed catalogs raise
    :class:`ToolCatalogError`; a missing root or config is an empty catalog.
    """
    from sase.content_layout import (
        discover_project_root,
        resolve_project_config_read_path,
    )

    root = discover_project_root(start)
    if root is None:
        return ToolCatalog(
            project=tool_project_identity(start),
            path=None,
            entries=(),
            diagnostics=(),
        )
    try:
        local_path = resolve_project_config_read_path(root)
    except Exception as exc:
        raise ToolCatalogError(f"{root}: {exc}") from exc
    return _load_catalog_from_path(local_path, root=root, diagnostics=[])


def _load_catalog_from_path(
    local_path: Path | None, *, root: Path | None, diagnostics: list[str]
) -> ToolCatalog:
    project = tool_project_identity(root)
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
    "load_project_tool_catalog_at",
    "tool_project_identity",
]
