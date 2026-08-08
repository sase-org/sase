"""File-hook configuration loading, validation, and event matching."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, cast, Literal

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
        "description",
        "command",
        "projects",
        "sidecars",
        "path_globs",
        "agent_name_globs",
        "ops",
        "timeout",
    }
)

_file_hooks_cache_token: tuple[Any, ...] | None = None
_file_hooks_cache_value: list[FileHookConfig] | None = None


@dataclass(frozen=True)
class FileHookConfig:
    """One validated ``file_hooks`` configuration entry."""

    name: str
    description: str | None
    command: str
    projects: tuple[str, ...] | None
    sidecars: tuple[str, ...] | None
    path_globs: tuple[str, ...] | None
    agent_name_globs: tuple[str, ...] | None
    ops: tuple[FileHookOp, ...] | None
    timeout_seconds: float
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
        if self.ops is not None:
            unknown_ops = set(self.ops) - FILE_HOOK_OPS
            if unknown_ops:
                joined = ", ".join(sorted(unknown_ops))
                raise ValueError(f"unknown operation(s): {joined}")
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
    #: ``None`` is legitimate for a commit made outside a SASE agent, so this
    #: field is deliberately not validated below.
    agent_name: str | None = None

    def __post_init__(self) -> None:
        if self.op not in FILE_HOOK_OPS:
            raise ValueError(f"unknown file-hook operation: {self.op}")
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


def _optional_ops(value: object) -> tuple[FileHookOp, ...] | None:
    raw_ops = _optional_string_tuple(value, "ops")
    if raw_ops is None:
        return None
    unknown_ops = set(raw_ops) - FILE_HOOK_OPS
    if unknown_ops:
        joined = ", ".join(sorted(unknown_ops))
        raise ValueError(f"unknown operation(s): {joined}")
    return cast(tuple[FileHookOp, ...], raw_ops)


def _parse_file_hook(
    item: object,
    *,
    source_layer: str,
    detected_project: str | None,
) -> FileHookConfig:
    if not isinstance(item, dict):
        raise ValueError("each file hook must be a dictionary")

    unknown_keys = {str(key) for key in item} - _KNOWN_FILE_HOOK_KEYS
    if unknown_keys:
        if "globs" in unknown_keys:
            raise ValueError("'globs' was renamed to 'path_globs'")
        joined = ", ".join(sorted(unknown_keys))
        raise ValueError(f"unknown field(s): {joined}")

    name = item.get("name")
    command = item.get("command")
    if not isinstance(name, str):
        raise ValueError("'name' is required and must be a string")
    if not isinstance(command, str):
        raise ValueError("'command' is required and must be a string")

    projects = _optional_string_tuple(item.get("projects"), "projects")
    if projects is None and source_layer == "local" and detected_project is not None:
        projects = (detected_project,)

    return FileHookConfig(
        name=name,
        description=_optional_string(item.get("description"), "description"),
        command=command,
        projects=projects,
        sidecars=_optional_string_tuple(item.get("sidecars"), "sidecars"),
        path_globs=_optional_string_tuple(item.get("path_globs"), "path_globs"),
        agent_name_globs=_optional_string_tuple(
            item.get("agent_name_globs"),
            "agent_name_globs",
        ),
        ops=_optional_ops(item.get("ops")),
        timeout_seconds=_parse_duration(item.get("timeout", "120s")),
        source_layer=source_layer,
    )


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


def _load_file_hooks() -> list[FileHookConfig]:
    """Load validated file hooks, memoized on the merged config token."""
    global _file_hooks_cache_token, _file_hooks_cache_value

    token = current_config_token()
    if _file_hooks_cache_value is not None and _file_hooks_cache_token == token:
        return _file_hooks_cache_value

    raw_hooks = _effective_raw_file_hooks()
    detected_project: str | None = None
    if any(
        source == "local" and isinstance(item, dict) and item.get("projects") is None
        for item, source in raw_hooks
    ):
        from sase.xprompt.loader import detect_project

        detected_project = detect_project()

    hooks: list[FileHookConfig] = []
    seen_names: set[str] = set()
    for item, source_layer in raw_hooks:
        try:
            hook = _parse_file_hook(
                item,
                source_layer=source_layer,
                detected_project=detected_project,
            )
            if hook.name in seen_names:
                raise ValueError(f"duplicate hook name '{hook.name}'")
        except ValueError as exc:
            hook_name = (
                item.get("name", "<unknown>") if isinstance(item, dict) else "<unknown>"
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
    if hook.projects is not None and event.project not in hook.projects:
        return False
    if hook.sidecars is not None and event.sidecar_role not in hook.sidecars:
        return False
    if hook.ops is not None and event.op not in hook.ops:
        return False

    if hook.path_globs:
        rel_path = event.rel_path.replace("\\", "/").removeprefix("./")
        if not _glob_matches(hook.path_globs, rel_path):
            return False
    # An unattributed event is matched as the empty string, so it clears a
    # negative-only list but never one containing a positive pattern.
    return not hook.agent_name_globs or _glob_matches(
        hook.agent_name_globs,
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
    "FileHookOp",
    "PlannedRun",
    "get_all_file_hooks",
    "hook_matches_event",
    "match_events",
]
