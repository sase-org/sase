"""tmux Agent configuration loading and validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
from types import MappingProxyType
from typing import Any

from sase.config.core import current_config_token, load_merged_config


logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_NAME = "ai"
_DEFAULT_BYPASS_PERMISSIONS = True
_DEFAULT_EFFORT = ""
_DEFAULT_CLEAR_SCREEN = True
_DEFAULT_AFTER_CLOSE_COMMAND = ""

_TMUX_AGENT_EFFORT_VALUES: frozenset[str] = frozenset(
    {
        "",
        "off",
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }
)
_KNOWN_TMUX_AGENT_KEYS = frozenset(
    {
        "window_name",
        "bypass_permissions",
        "effort",
        "clear_screen",
        "after_close_command",
        "providers",
    }
)
_KNOWN_PROVIDER_KEYS = frozenset(
    {
        "enabled",
        "key",
        "model",
        "effort",
        "args",
        "env",
        "bypass_permissions",
    }
)


@dataclass(frozen=True)
class TmuxAgentProviderConfig:
    """Per-provider overrides under ``tmux_agent.providers``."""

    enabled: bool = True
    key: str = ""
    model: str = ""
    effort: str = ""
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    bypass_permissions: bool | None = None


@dataclass(frozen=True)
class TmuxAgentConfig:
    """Validated ``tmux_agent`` configuration section."""

    window_name: str = _DEFAULT_WINDOW_NAME
    bypass_permissions: bool = _DEFAULT_BYPASS_PERMISSIONS
    effort: str = _DEFAULT_EFFORT
    clear_screen: bool = _DEFAULT_CLEAR_SCREEN
    after_close_command: str = _DEFAULT_AFTER_CLOSE_COMMAND
    providers: Mapping[str, TmuxAgentProviderConfig] = field(default_factory=dict)


_cache_token: tuple[Any, ...] | None = None
_cache_value: TmuxAgentConfig | None = None


def get_tmux_agent_config() -> TmuxAgentConfig:
    """Return the effective ``tmux_agent`` config, failing soft on errors."""
    try:
        return _load_tmux_agent_config()
    except (FileNotFoundError, TypeError, ValueError) as exc:
        logger.warning("Failed to load tmux_agent config: %s", exc)
        return TmuxAgentConfig()


def _load_tmux_agent_config() -> TmuxAgentConfig:
    global _cache_token, _cache_value

    token = current_config_token()
    if _cache_value is not None and _cache_token == token:
        return _cache_value

    data = load_merged_config()
    if not isinstance(data, Mapping):
        logger.warning(
            "Skipping invalid tmux_agent config: merged config is not a mapping"
        )
        parsed = TmuxAgentConfig()
    else:
        parsed = _parse_tmux_agent_section(data.get("tmux_agent"))

    _cache_token = token
    _cache_value = parsed
    return parsed


def _parse_tmux_agent_section(raw: object) -> TmuxAgentConfig:
    if raw is None:
        return TmuxAgentConfig()
    if not isinstance(raw, Mapping):
        logger.warning(
            "Skipping invalid tmux_agent value: expected a mapping, got %s",
            type(raw).__name__,
        )
        return TmuxAgentConfig()

    _warn_unknown_keys(raw, _KNOWN_TMUX_AGENT_KEYS, "tmux_agent")
    return TmuxAgentConfig(
        window_name=_optional_string(
            raw.get("window_name"),
            "tmux_agent.window_name",
            default=_DEFAULT_WINDOW_NAME,
            allow_empty=False,
        ),
        bypass_permissions=_optional_bool(
            raw.get("bypass_permissions"),
            "tmux_agent.bypass_permissions",
            default=_DEFAULT_BYPASS_PERMISSIONS,
        ),
        effort=_optional_effort(raw.get("effort"), "tmux_agent.effort"),
        clear_screen=_optional_bool(
            raw.get("clear_screen"),
            "tmux_agent.clear_screen",
            default=_DEFAULT_CLEAR_SCREEN,
        ),
        after_close_command=_optional_string(
            raw.get("after_close_command"),
            "tmux_agent.after_close_command",
            default=_DEFAULT_AFTER_CLOSE_COMMAND,
            allow_empty=True,
        ),
        providers=_parse_providers(raw.get("providers")),
    )


def _parse_providers(raw: object) -> Mapping[str, TmuxAgentProviderConfig]:
    if raw is None:
        return MappingProxyType({})
    if not isinstance(raw, Mapping):
        logger.warning(
            "Skipping invalid tmux_agent.providers value: expected a mapping, got %s",
            type(raw).__name__,
        )
        return MappingProxyType({})

    providers: dict[str, TmuxAgentProviderConfig] = {}
    for raw_name, item in raw.items():
        if not isinstance(raw_name, str) or not raw_name:
            logger.warning(
                "Skipping invalid tmux_agent.providers entry: provider name "
                "must be a non-empty string, got %r",
                raw_name,
            )
            continue
        parsed = _parse_provider(raw_name, item)
        if parsed is not None:
            providers[raw_name] = parsed
    return MappingProxyType(providers)


def _parse_provider(
    name: str,
    item: object,
) -> TmuxAgentProviderConfig | None:
    if not isinstance(item, Mapping):
        logger.warning(
            "Skipping invalid tmux_agent.providers.%s value: "
            "expected a mapping, got %s",
            name,
            type(item).__name__,
        )
        return None

    path = f"tmux_agent.providers.{name}"
    _warn_unknown_keys(item, _KNOWN_PROVIDER_KEYS, path)
    return TmuxAgentProviderConfig(
        enabled=_optional_bool(item.get("enabled"), f"{path}.enabled", default=True),
        key=_optional_menu_key(item.get("key"), f"{path}.key"),
        model=_optional_string(
            item.get("model"),
            f"{path}.model",
            default="",
            allow_empty=True,
        ),
        effort=_optional_effort(item.get("effort"), f"{path}.effort"),
        args=_optional_string_tuple(item.get("args"), f"{path}.args"),
        env=_optional_str_mapping(item.get("env"), f"{path}.env"),
        bypass_permissions=_optional_bool_or_none(
            item.get("bypass_permissions"),
            f"{path}.bypass_permissions",
        ),
    )


def _warn_unknown_keys(
    raw: Mapping[object, object],
    known: frozenset[str],
    path: str,
) -> None:
    unknown = sorted({str(key) for key in raw} - known)
    if unknown:
        logger.warning(
            "Ignoring unknown %s field(s): %s",
            path,
            ", ".join(unknown),
        )


def _optional_string(
    value: object,
    field: str,
    *,
    default: str,
    allow_empty: bool,
) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        logger.warning(
            "Ignoring invalid %s: expected a string, got %s",
            field,
            type(value).__name__,
        )
        return default
    if not allow_empty and not value:
        logger.warning("Ignoring empty %s", field)
        return default
    return value


def _optional_bool(value: object, field: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        logger.warning(
            "Ignoring invalid %s: expected a boolean, got %s",
            field,
            type(value).__name__,
        )
        return default
    return value


def _optional_bool_or_none(value: object, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        logger.warning(
            "Ignoring invalid %s: expected a boolean, got %s",
            field,
            type(value).__name__,
        )
        return None
    return value


def _optional_effort(value: object, field: str) -> str:
    if value is None:
        return _DEFAULT_EFFORT
    if not isinstance(value, str):
        logger.warning(
            "Ignoring invalid %s: expected a string, got %s",
            field,
            type(value).__name__,
        )
        return _DEFAULT_EFFORT
    level = value.strip().lower()
    if level not in _TMUX_AGENT_EFFORT_VALUES:
        logger.warning(
            "Ignoring invalid %s %r: expected one of %s",
            field,
            value,
            ", ".join(sorted(repr(item) for item in _TMUX_AGENT_EFFORT_VALUES)),
        )
        return _DEFAULT_EFFORT
    return level


def _optional_menu_key(value: object, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        logger.warning(
            "Ignoring invalid %s: expected a string, got %s",
            field,
            type(value).__name__,
        )
        return ""
    if value == "":
        return ""
    if not _is_valid_menu_key(value):
        logger.warning(
            "Ignoring invalid %s %r: must be exactly one printable "
            "non-whitespace character",
            field,
            value,
        )
        return ""
    return value


def _is_valid_menu_key(value: str) -> bool:
    return len(value) == 1 and value.isprintable() and not value.isspace()


def _optional_string_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        logger.warning(
            "Ignoring invalid %s: expected a list of strings, got %s",
            field,
            type(value).__name__,
        )
        return ()
    return tuple(value)


def _optional_str_mapping(value: object, field: str) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        logger.warning(
            "Ignoring invalid %s: expected a mapping, got %s",
            field,
            type(value).__name__,
        )
        return MappingProxyType({})

    env: dict[str, str] = {}
    for raw_key, raw_item in value.items():
        if not isinstance(raw_key, str) or not isinstance(raw_item, str):
            logger.warning(
                "Ignoring invalid %s entry %r: keys and values must be strings",
                field,
                raw_key,
            )
            continue
        env[raw_key] = raw_item
    return MappingProxyType(env)


__all__ = [
    "TmuxAgentConfig",
    "TmuxAgentProviderConfig",
    "get_tmux_agent_config",
]
