"""File-hook configuration loading, validation, and event matching."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
import os
import re
from typing import Any, cast, Literal

from sase.artifact_providers.registry import ArtifactProviderRegistry
from sase.config.core import (
    current_config_token,
    load_config_layers,
)


logger = logging.getLogger(__name__)

FileHookOp = Literal["ADD", "MODIFY", "REMOVE"]
FILE_HOOK_OPS: frozenset[FileHookOp] = frozenset({"ADD", "MODIFY", "REMOVE"})
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_DURATION_RE = re.compile(r"^([0-9]+)(ms|s|m|h)$")
_DURATION_MULTIPLIERS = {
    "ms": 0.001,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
}
#: Config layers are not validated against ``sase.schema.json`` at runtime, so
#: unknown keys must be rejected here. A stale ``globs:`` entry would otherwise
#: parse to ``path_globs=None``, which means *match every file*.
_KNOWN_FILE_HOOK_KEYS = frozenset(
    {
        "name",
        "use",
        "description",
        "command",
        "filters",
        "timeout",
    }
)
_FILE_HOOK_FILTER_KEYS = frozenset(
    {
        "projects",
        "sidecars",
        "path_globs",
        "agent_name_globs",
        "ops",
        "causes",
    }
)
_MISSING = object()

_file_hooks_cache_token: tuple[Any, ...] | None = None
_file_hooks_cache_value: list[FileHookConfig] | None = None


@dataclass(frozen=True)
class FileHookFilters:
    """Event-selection criteria for one file hook."""

    projects: tuple[str, ...] | None = None
    sidecars: tuple[str, ...] | None = None
    path_globs: tuple[str, ...] | None = None
    agent_name_globs: tuple[str, ...] | None = None
    ops: tuple[FileHookOp, ...] | None = None
    causes: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        """Validate values supplied directly as well as parsed YAML entries."""
        if self.ops is not None:
            unknown_ops = set(self.ops) - FILE_HOOK_OPS
            if unknown_ops:
                joined = ", ".join(sorted(unknown_ops))
                raise ValueError(f"unknown operation(s): {joined}")


@dataclass(frozen=True)
class FileHookConfig:
    """One validated ``file_hooks`` configuration entry."""

    name: str
    description: str | None
    command: str
    timeout_seconds: float
    filters: FileHookFilters = field(default_factory=FileHookFilters)
    source_layer: str = "unknown"

    def __post_init__(self) -> None:
        """Validate values supplied directly as well as parsed YAML entries."""
        if not self.name or _NAME_RE.fullmatch(self.name) is None:
            raise ValueError(
                "'name' must be a lowercase slug containing letters, digits, "
                "hyphens, or underscores"
            )
        if not self.command.strip():
            raise ValueError("'command' must be non-empty")
        if self.timeout_seconds < 0:
            raise ValueError("'timeout' must not be negative")


@dataclass(frozen=True)
class FileHookEvent:
    """The matching fields for one repository file event."""

    project: str
    repo_kind: str
    sidecar_role: str | None
    rel_path: str
    op: FileHookOp
    cause: str = "user"
    #: ``None`` is legitimate for a commit made outside a SASE agent, so this
    #: field is deliberately not validated below.
    agent_name: str | None = None

    def __post_init__(self) -> None:
        if self.op not in FILE_HOOK_OPS:
            raise ValueError(f"unknown file-hook operation: {self.op}")
        if not self.cause:
            raise ValueError("file-hook event cause must be non-empty")
        if not self.rel_path:
            raise ValueError("file-hook event path must be non-empty")


@dataclass(frozen=True)
class PlannedRun:
    """One matched hook/event pair for the execution engine."""

    hook: FileHookConfig
    event: FileHookEvent


def _parse_duration(value: object) -> float:
    if not isinstance(value, str):
        raise ValueError("'timeout' must be a duration string")
    match = _DURATION_RE.fullmatch(value)
    if match is None:
        raise ValueError("'timeout' must be an integer followed by ms, s, m, or h")
    amount, unit = match.groups()
    return int(amount) * _DURATION_MULTIPLIERS[unit]


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{field}' must be a string")
    return value


def _optional_string_tuple(
    value: object,
    field: str,
) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"'{field}' must be a list of strings")
    return tuple(value)


def _optional_ops(value: object, field: str) -> tuple[FileHookOp, ...] | None:
    raw_ops = _optional_string_tuple(value, field)
    if raw_ops is None:
        return None
    unknown_ops = set(raw_ops) - FILE_HOOK_OPS
    if unknown_ops:
        joined = ", ".join(sorted(unknown_ops))
        raise ValueError(f"'{field}' contains unknown operation(s): {joined}")
    return cast(tuple[FileHookOp, ...], raw_ops)


def _parse_file_hook_filters(
    value: object,
    *,
    source_layer: str,
    detected_project: str | None,
) -> FileHookFilters:
    if value is _MISSING:
        raw_filters: Mapping[object, object] = {}
    elif isinstance(value, Mapping):
        raw_filters = value
    else:
        raise ValueError("'filters' must be a mapping")

    filter_keys = {str(key) for key in raw_filters}
    unknown_keys = filter_keys - _FILE_HOOK_FILTER_KEYS
    if unknown_keys:
        if "globs" in unknown_keys:
            raise ValueError("'filters.globs' was renamed to 'filters.path_globs'")
        joined = ", ".join(sorted(unknown_keys))
        raise ValueError(f"unknown filters field(s): {joined}")

    projects = _optional_string_tuple(
        raw_filters.get("projects"),
        "filters.projects",
    )
    if projects is None and source_layer == "local" and detected_project is not None:
        projects = (detected_project,)

    return FileHookFilters(
        projects=projects,
        sidecars=_optional_string_tuple(
            raw_filters.get("sidecars"),
            "filters.sidecars",
        ),
        path_globs=_optional_string_tuple(
            raw_filters.get("path_globs"),
            "filters.path_globs",
        ),
        agent_name_globs=_optional_string_tuple(
            raw_filters.get("agent_name_globs"),
            "filters.agent_name_globs",
        ),
        ops=_optional_ops(raw_filters.get("ops"), "filters.ops"),
        causes=_optional_string_tuple(
            raw_filters.get("causes"),
            "filters.causes",
        ),
    )


def _parse_file_hook(
    item: object,
    *,
    source_layer: str,
    detected_project: str | None,
) -> FileHookConfig:
    if not isinstance(item, Mapping):
        raise ValueError("each file hook must be a dictionary")

    unknown_keys = {str(key) for key in item} - _KNOWN_FILE_HOOK_KEYS
    if unknown_keys:
        legacy_filter_keys = unknown_keys & _FILE_HOOK_FILTER_KEYS
        if legacy_filter_keys:
            joined = ", ".join(sorted(legacy_filter_keys))
            raise ValueError(
                f"file-hook filter field(s) must be nested under 'filters': {joined}"
            )
        if "globs" in unknown_keys:
            raise ValueError("'globs' was renamed to 'filters.path_globs'")
        joined = ", ".join(sorted(unknown_keys))
        raise ValueError(f"unknown field(s): {joined}")

    name = item.get("name")
    command = item.get("command")
    if not isinstance(name, str):
        raise ValueError("'name' is required and must be a string")
    if not isinstance(command, str):
        raise ValueError("'command' is required and must be a string")

    return FileHookConfig(
        name=name,
        description=_optional_string(item.get("description"), "description"),
        command=command,
        filters=_parse_file_hook_filters(
            item.get("filters", _MISSING),
            source_layer=source_layer,
            detected_project=detected_project,
        ),
        timeout_seconds=_parse_duration(item.get("timeout", "120s")),
        source_layer=source_layer,
    )


def _resolve_file_hook_provider(
    item: object,
    *,
    registry: ArtifactProviderRegistry,
) -> object:
    if not isinstance(item, Mapping) or "use" not in item:
        return item
    raw_use = item.get("use")
    if not isinstance(raw_use, str) or not raw_use.strip():
        raise ValueError("'use' must be a nonempty file-hook provider id")
    provider_id = raw_use.strip()
    providers = registry.file_hook_providers_by_id
    provider = providers.get(provider_id)
    if provider is None:
        raise ValueError(
            f"unknown file-hook provider '{provider_id}'; install a plugin "
            "exposing the sase_file_hooks entry point group or remove 'use'"
        )
    for field_name in provider.required_fields:
        if _missing_local_override(item, field_name):
            raise ValueError(
                f"file-hook provider '{provider_id}' requires local field "
                f"'{field_name}'"
            )
    overrides = {str(key): value for key, value in item.items() if str(key) != "use"}
    merged = _deep_merge(provider.template, overrides)
    merged.setdefault("name", provider_id)
    return merged


def _missing_local_override(item: Mapping[Any, Any], field_name: str) -> bool:
    if field_name not in item:
        return True
    value = item.get(field_name)
    if isinstance(value, str):
        return not value.strip()
    return value is None


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = _plain_mapping(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = _plain_value(value)
    return result


def _plain_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    return {str(key): _plain_value(item) for key, item in value.items()}


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _plain_mapping(value)
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    return value


def _effective_raw_file_hooks() -> list[tuple[object, str]]:
    """Replay config-list merge semantics while retaining source provenance."""
    effective: list[tuple[object, str]] = []
    for layer in load_config_layers():
        if not layer.exists or "file_hooks" not in layer.data:
            continue

        raw_items = layer.data["file_hooks"]
        if layer.list_strategy == "replace":
            effective = []
        if not isinstance(raw_items, list):
            logger.warning(
                "Skipping invalid file_hooks value from config layer '%s': "
                "expected a list",
                layer.name,
            )
            continue
        effective.extend((item, layer.name) for item in raw_items)
    return effective


def _needs_detected_project(item: object, source_layer: str) -> bool:
    if source_layer != "local" or not isinstance(item, Mapping):
        return False
    if "use" in item:
        return True
    if "filters" not in item:
        return True
    raw_filters = item.get("filters")
    if not isinstance(raw_filters, Mapping):
        return True
    return raw_filters.get("projects") is None


def _load_file_hooks() -> list[FileHookConfig]:
    """Load validated file hooks, memoized on the merged config token."""
    global _file_hooks_cache_token, _file_hooks_cache_value

    token = (
        current_config_token(),
        os.environ.get("SASE_DISABLE_PLUGINS"),
        os.environ.get("SASE_DISABLE_PLUGIN_FILE_HOOKS"),
    )
    if _file_hooks_cache_value is not None and _file_hooks_cache_token == token:
        return _file_hooks_cache_value

    from sase.artifact_providers import get_artifact_provider_registry

    registry = get_artifact_provider_registry()
    raw_hooks = _effective_raw_file_hooks()
    detected_project: str | None = None
    if any(_needs_detected_project(item, source) for item, source in raw_hooks):
        from sase.xprompt.loader import detect_project

        detected_project = detect_project()

    hooks: list[FileHookConfig] = []
    seen_names: set[str] = set()
    for item, source_layer in raw_hooks:
        try:
            resolved_item = _resolve_file_hook_provider(item, registry=registry)
            hook = _parse_file_hook(
                resolved_item,
                source_layer=source_layer,
                detected_project=detected_project,
            )
            if hook.name in seen_names:
                raise ValueError(f"duplicate hook name '{hook.name}'")
        except ValueError as exc:
            hook_name = (
                item.get("name") or item.get("use") or "<unknown>"
                if isinstance(item, Mapping)
                else "<unknown>"
            )
            logger.warning(
                "Skipping invalid file hook '%s' from config layer '%s': %s",
                hook_name,
                source_layer,
                exc,
            )
            continue
        hooks.append(hook)
        seen_names.add(hook.name)

    _file_hooks_cache_token = token
    _file_hooks_cache_value = hooks
    return hooks


def get_all_file_hooks() -> list[FileHookConfig]:
    """Return every valid effective file hook, failing soft on config errors."""
    try:
        return _load_file_hooks()
    except (FileNotFoundError, TypeError, ValueError) as exc:
        logger.warning("Failed to load file hooks: %s", exc)
        return []


def _glob_matches(patterns: tuple[str, ...], value: str) -> bool:
    from wcmatch import glob

    flags = glob.DOTGLOB | glob.GLOBSTAR | glob.NEGATE | glob.NEGATEALL
    return glob.globmatch(value, patterns, flags=flags)


def hook_matches_event(hook: FileHookConfig, event: FileHookEvent) -> bool:
    """Return whether all configured hook filters accept one event."""
    filters = hook.filters
    if filters.projects is not None and event.project not in filters.projects:
        return False
    if filters.sidecars is not None and event.sidecar_role not in filters.sidecars:
        return False
    if filters.ops is not None and event.op not in filters.ops:
        return False
    if event.cause != "user" and event.cause not in (filters.causes or ()):
        return False

    if filters.path_globs:
        rel_path = event.rel_path.replace("\\", "/").removeprefix("./")
        if not _glob_matches(filters.path_globs, rel_path):
            return False
    # An unattributed event is matched as the empty string, so it clears a
    # negative-only list but never one containing a positive pattern.
    return not filters.agent_name_globs or _glob_matches(
        filters.agent_name_globs,
        event.agent_name or "",
    )


def match_events(
    hooks: list[FileHookConfig],
    events: list[FileHookEvent],
) -> list[PlannedRun]:
    """Return matched hook/event pairs in hook order, then event order."""
    return [
        PlannedRun(hook=hook, event=event)
        for hook in hooks
        for event in events
        if hook_matches_event(hook, event)
    ]


__all__ = [
    "FILE_HOOK_OPS",
    "FileHookConfig",
    "FileHookEvent",
    "FileHookFilters",
    "FileHookOp",
    "PlannedRun",
    "get_all_file_hooks",
    "hook_matches_event",
    "match_events",
]
