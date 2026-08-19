"""Fingerprinted on-disk cache for the slow half of the tmux Agent catalog.

The cache stores plugin-derived provider metadata, assigned shortcut keys, the
resolved ``tmux_agent`` config, and the effective effort. Installed state,
provider disables, the pane directory, and the window list stay live: those
change often, and a stale cache must never claim an uninstalled CLI is
installed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Any

from sase.config.tmux_agent import TmuxAgentConfig, TmuxAgentProviderConfig
from sase.core.paths import ensure_sase_directory, sase_subdir

#: Bump when the cached envelope shape changes incompatibly.
SCHEMA_VERSION = 1

_CACHE_SUBDIR = "tmux_agent"
_CACHE_FILENAME = "catalog_cache.json"

CaptureFn = Callable[[], "CatalogCachePayload"]
FingerprintFn = Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class CachedProvider:
    """The slow-changing, plugin-derived half of one catalog row."""

    provider: str
    display_name: str
    vendor: str
    color: str
    binary: str
    descriptor: dict[str, Any]
    key: str
    install_hint: str
    autodetect_priority: int | None
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    effort: str | None
    effort_skipped: str | None
    bypass: bool


@dataclass(frozen=True)
class CatalogCachePayload:
    """On-disk catalog cache: metadata plus config, never installed-state."""

    fingerprint: dict[str, Any]
    config: TmuxAgentConfig
    effort: str | None
    configured_provider: str | None
    providers: tuple[CachedProvider, ...] = field(default_factory=tuple)


_last_payload: CatalogCachePayload | None = None


def _cache_path() -> Path:
    return sase_subdir(_CACHE_SUBDIR) / _CACHE_FILENAME


def _sase_version() -> str:
    from sase import __version__

    return __version__


def _llm_entry_points() -> list[list[str]]:
    """Sorted ``(name, value)`` pairs of the ``sase_llm`` entry points."""
    entry_points = importlib.metadata.entry_points(group="sase_llm")
    pairs = [[ep.name, ep.value] for ep in entry_points]
    pairs.sort(key=lambda item: (item[0], item[1]))
    return pairs


def _contributing_config_layers() -> list[list[str | int]]:
    """``(path, mtime_ns, size)`` of every file-backed config layer that exists."""
    from sase.config.core import CONFIG_DIR, get_local_config_path, stat_token
    from sase.config.loading import get_overlay_paths

    candidates = [CONFIG_DIR / "sase.yml", *get_overlay_paths(CONFIG_DIR)]
    local = get_local_config_path()
    if local is not None:
        candidates.append(local)

    layers: list[list[str | int]] = []
    seen: set[str] = set()
    for path in candidates:
        token = stat_token(path)
        if token is None:
            continue
        path_str, mtime_ns, size = token
        if path_str in seen:
            continue
        seen.add(path_str)
        layers.append([path_str, mtime_ns, size])
    layers.sort(key=lambda item: str(item[0]))
    return layers


def _catalog_fingerprint(
    *,
    sase_version: str | None = None,
    entry_points: Sequence[Sequence[str]] | None = None,
    config_layers: Sequence[Sequence[str | int]] | None = None,
) -> dict[str, Any]:
    """Return the cache invalidation fingerprint.

    Any mismatch against a stored envelope rebuilds the cache: SASE version,
    the sorted ``sase_llm`` entry points, the ``(path, mtime_ns, size)`` of
    every contributing config layer, and the cache schema version itself.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "sase_version": _sase_version() if sase_version is None else sase_version,
        "entry_points": (
            _llm_entry_points()
            if entry_points is None
            else [list(item) for item in entry_points]
        ),
        "config_layers": (
            _contributing_config_layers()
            if config_layers is None
            else [list(item) for item in config_layers]
        ),
    }


def read_cache(path: Path | None = None) -> CatalogCachePayload | None:
    """Read the cache envelope, or ``None`` if missing, unreadable, or stale."""
    try:
        raw = (path or _cache_path()).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return _parse_envelope(envelope)


def write_cache(payload: CatalogCachePayload, *, path: Path | None = None) -> None:
    """Atomically persist *payload*. Failures are swallowed, never raised."""
    cache_path = path or _cache_path()
    tmp_path: Path | None = None
    try:
        if path is None:
            ensure_sase_directory(_CACHE_SUBDIR)
        else:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(
            json.dumps(_envelope_to_json(payload), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, cache_path)
    except OSError:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def load_catalog_payload(
    *,
    refresh: bool = False,
    path: Path | None = None,
    capture_fn: CaptureFn | None = None,
    fingerprint_fn: FingerprintFn | None = None,
) -> CatalogCachePayload:
    """Return a fingerprint-matching cache payload, rebuilding on miss.

    ``-r/--refresh`` maps to *refresh*: skip the stored envelope and rewrite.
    """
    fingerprint = (fingerprint_fn or _catalog_fingerprint)()
    if not refresh:
        cached = read_cache(path)
        if cached is not None and cached.fingerprint == fingerprint:
            _set_last_payload(cached)
            return cached

    capture = capture_fn or _default_capture
    payload = replace(capture(), fingerprint=fingerprint)
    write_cache(payload, path=path)
    _set_last_payload(payload)
    return payload


def refresh_catalog_cache(
    *,
    path: Path | None = None,
    capture_fn: CaptureFn | None = None,
    fingerprint_fn: FingerprintFn | None = None,
) -> CatalogCachePayload:
    """Force a catalog-cache rebuild and rewrite, then return the new payload."""
    return load_catalog_payload(
        refresh=True,
        path=path,
        capture_fn=capture_fn,
        fingerprint_fn=fingerprint_fn,
    )


def cached_tmux_agent_config() -> TmuxAgentConfig | None:
    """Return the ``tmux_agent`` config from the last successful cache load."""
    return None if _last_payload is None else _last_payload.config


def _default_capture() -> CatalogCachePayload:
    from .catalog import capture_catalog_snapshot

    return capture_catalog_snapshot()


def _set_last_payload(payload: CatalogCachePayload) -> None:
    global _last_payload
    _last_payload = payload


def _envelope_to_json(payload: CatalogCachePayload) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "fingerprint": payload.fingerprint,
        "config": _config_to_json(payload.config),
        "effort": payload.effort,
        "configured_provider": payload.configured_provider,
        "providers": [_provider_to_json(item) for item in payload.providers],
    }


def _parse_envelope(envelope: object) -> CatalogCachePayload | None:
    if not isinstance(envelope, dict):
        return None
    if envelope.get("schema_version") != SCHEMA_VERSION:
        return None
    fingerprint = envelope.get("fingerprint")
    if not isinstance(fingerprint, dict):
        return None
    config = _config_from_json(envelope.get("config"))
    if config is None:
        return None
    effort = envelope.get("effort")
    if effort is not None and not isinstance(effort, str):
        return None
    configured = envelope.get("configured_provider")
    if configured is not None and not isinstance(configured, str):
        return None
    raw_providers = envelope.get("providers")
    if not isinstance(raw_providers, list):
        return None
    providers: list[CachedProvider] = []
    for raw in raw_providers:
        parsed = _provider_from_json(raw)
        if parsed is None:
            return None
        providers.append(parsed)
    return CatalogCachePayload(
        fingerprint=fingerprint,
        config=config,
        effort=effort,
        configured_provider=configured,
        providers=tuple(providers),
    )


def _config_to_json(config: TmuxAgentConfig) -> dict[str, Any]:
    return {
        "window_name": config.window_name,
        "bypass_permissions": config.bypass_permissions,
        "effort": config.effort,
        "clear_screen": config.clear_screen,
        "after_close_command": config.after_close_command,
        "providers": {
            name: {
                "enabled": item.enabled,
                "key": item.key,
                "model": item.model,
                "effort": item.effort,
                "args": list(item.args),
                "env": dict(item.env),
                "bypass_permissions": item.bypass_permissions,
            }
            for name, item in sorted(config.providers.items())
        },
    }


def _config_from_json(raw: object) -> TmuxAgentConfig | None:
    if not isinstance(raw, dict):
        return None
    window_name = raw.get("window_name")
    effort = raw.get("effort")
    after_close = raw.get("after_close_command")
    if not isinstance(window_name, str) or not isinstance(effort, str):
        return None
    if not isinstance(after_close, str):
        return None
    bypass = raw.get("bypass_permissions")
    clear_screen = raw.get("clear_screen")
    if not isinstance(bypass, bool) or not isinstance(clear_screen, bool):
        return None
    providers = _providers_config_from_json(raw.get("providers"))
    if providers is None:
        return None
    return TmuxAgentConfig(
        window_name=window_name,
        bypass_permissions=bypass,
        effort=effort,
        clear_screen=clear_screen,
        after_close_command=after_close,
        providers=providers,
    )


def _providers_config_from_json(
    raw: object,
) -> dict[str, TmuxAgentProviderConfig] | None:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return None
    providers: dict[str, TmuxAgentProviderConfig] = {}
    for name, item in raw.items():
        if not isinstance(name, str) or not isinstance(item, dict):
            return None
        parsed = _provider_config_from_json(item)
        if parsed is None:
            return None
        providers[name] = parsed
    return providers


def _provider_config_from_json(
    raw: Mapping[str, Any],
) -> TmuxAgentProviderConfig | None:
    enabled = raw.get("enabled", True)
    key = raw.get("key", "")
    model = raw.get("model", "")
    effort = raw.get("effort", "")
    if not isinstance(enabled, bool) or not isinstance(key, str):
        return None
    if not isinstance(model, str) or not isinstance(effort, str):
        return None
    args = _str_tuple(raw.get("args", []))
    env = _str_dict(raw.get("env", {}))
    if args is None or env is None:
        return None
    bypass = raw.get("bypass_permissions")
    if bypass is not None and not isinstance(bypass, bool):
        return None
    return TmuxAgentProviderConfig(
        enabled=enabled,
        key=key,
        model=model,
        effort=effort,
        args=args,
        env=env,
        bypass_permissions=bypass,
    )


def _provider_to_json(item: CachedProvider) -> dict[str, Any]:
    return {
        "provider": item.provider,
        "display_name": item.display_name,
        "vendor": item.vendor,
        "color": item.color,
        "binary": item.binary,
        "descriptor": item.descriptor,
        "key": item.key,
        "install_hint": item.install_hint,
        "autodetect_priority": item.autodetect_priority,
        "argv": list(item.argv),
        "env": [list(pair) for pair in item.env],
        "effort": item.effort,
        "effort_skipped": item.effort_skipped,
        "bypass": item.bypass,
    }


def _provider_from_json(raw: object) -> CachedProvider | None:
    if not isinstance(raw, dict):
        return None
    provider = raw.get("provider")
    display_name = raw.get("display_name")
    vendor = raw.get("vendor")
    color = raw.get("color")
    binary = raw.get("binary")
    key = raw.get("key")
    install_hint = raw.get("install_hint")
    if not isinstance(provider, str) or not isinstance(display_name, str):
        return None
    if not isinstance(vendor, str) or not isinstance(color, str):
        return None
    if not isinstance(binary, str) or not isinstance(key, str):
        return None
    if not isinstance(install_hint, str):
        return None
    descriptor = raw.get("descriptor")
    if not isinstance(descriptor, dict):
        return None
    if "installed" in raw or "executable" in raw or "routing_disabled" in raw:
        return None
    argv = _str_tuple(raw.get("argv"))
    env = _env_pairs(raw.get("env"))
    if argv is None or env is None:
        return None
    effort = raw.get("effort")
    skipped = raw.get("effort_skipped")
    if effort is not None and not isinstance(effort, str):
        return None
    if skipped is not None and not isinstance(skipped, str):
        return None
    bypass = raw.get("bypass")
    if not isinstance(bypass, bool):
        return None
    priority = raw.get("autodetect_priority")
    if priority is not None and not isinstance(priority, int):
        return None
    return CachedProvider(
        provider=provider,
        display_name=display_name,
        vendor=vendor,
        color=color,
        binary=binary,
        descriptor=dict(descriptor),
        key=key,
        install_hint=install_hint,
        autodetect_priority=priority,
        argv=argv,
        env=env,
        effort=effort,
        effort_skipped=skipped,
        bypass=bypass,
    )


def _str_tuple(value: object) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return None
    return tuple(value)


def _str_dict(value: object) -> dict[str, str] | None:
    if value is None:
        return {}
    if not isinstance(value, dict):
        return None
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            return None
        result[key] = item
    return result


def _env_pairs(value: object) -> tuple[tuple[str, str], ...] | None:
    if value is None:
        return ()
    if not isinstance(value, list):
        return None
    pairs: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, list | tuple) or len(item) != 2:
            return None
        key, raw = item
        if not isinstance(key, str) or not isinstance(raw, str):
            return None
        pairs.append((key, raw))
    return tuple(pairs)


__all__ = [
    "SCHEMA_VERSION",
    "CachedProvider",
    "CatalogCachePayload",
    "cached_tmux_agent_config",
    "load_catalog_payload",
    "read_cache",
    "refresh_catalog_cache",
    "write_cache",
]
