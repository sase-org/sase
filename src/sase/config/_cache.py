"""Process-wide config-token cache and merged-config cache slots.

:mod:`sase.config.core` remains the public facade and the patch surface for
``CONFIG_DIR``, ``Path``, ``time``, and ``threading``. This module owns the
cache state those facade entry points publish. :mod:`sase.config._sources`
reads the public names here rather than binding them at import time.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from sase.config.identity import AgentOwnerConfigSnapshot
from sase.content_layout import discover_project_root, resolve_project_layout
from sase.core.paths import machine_name_path


log = logging.getLogger(__name__)

# When false, project-local config is excluded from the source chain.
include_local_config = True

# Bundled and plugin defaults are process-static.  The merged and identity
# values are keyed by ``current_config_token()``.  Callers must not mutate a
# returned merged dict because repeat reads intentionally return the same object.
#
# Each cache below is a single module global holding an immutable
# ``(token, value)`` pair so a publish is one atomic store and a read is one
# atomic load: no concurrent reader can ever observe a token paired with the
# wrong value.
default_config_cache: dict[str, Any] | None = None
plugin_configs_cache: list[dict[str, Any]] | None = None
merged_config_cache: tuple[tuple[Any, ...], dict[str, Any]] | None = None
agent_owner_config_cache: tuple[tuple[Any, ...], AgentOwnerConfigSnapshot] | None = None

# Explicit clears increment the generation so rapid same-size edits cannot
# retain an otherwise-identical filesystem token.
# Keep this above the one-second countdown tick in sase's TUI so periodic UI
# refreshes revalidate cached config on a slower cadence than they repaint.
_CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS = 5.0
CONFIG_TOKEN_REFRESH_THREAD_NAME = "sase-config-token-refresh"
config_cache_generation = 0
_current_config_token_cache_value: tuple[Any, ...] | None = None
_current_config_token_cache_deadline = 0.0
_current_config_token_cache_epoch = 0
_current_config_token_cache_dir: Path | None = None
_current_config_token_cache_cwd: str | None = None
_current_config_token_cache_lock = threading.RLock()
_current_config_token_refresh_thread: threading.Thread | None = None
_config_token_revalidator_stop: threading.Event | None = None
_config_token_revalidator_wake: threading.Event | None = None


def _facade() -> Any:
    """Return the public ``sase.config.core`` module (the patch surface)."""
    from sase.config import core

    return core


def overlay_paths() -> list[Path]:
    """Return overlay YAML paths under the current ``CONFIG_DIR``."""
    from sase.config.loading import get_overlay_paths

    return get_overlay_paths(_facade().CONFIG_DIR)


def _reset_current_config_token_cache_locked() -> None:
    """Reset the config-token cache while its lock is held."""
    global _current_config_token_cache_value, _current_config_token_cache_deadline
    global _current_config_token_cache_epoch, _current_config_token_cache_dir
    global _current_config_token_cache_cwd
    _current_config_token_cache_value = None
    _current_config_token_cache_deadline = 0.0
    _current_config_token_cache_dir = None
    _current_config_token_cache_cwd = None
    _current_config_token_cache_epoch += 1


def _reset_current_config_token_cache() -> None:
    """Force the next config-token lookup to inspect the filesystem."""
    with _current_config_token_cache_lock:
        _reset_current_config_token_cache_locked()


def set_include_local_config(value: bool) -> None:
    """Enable or disable loading of the current project's config."""
    global include_local_config
    with _current_config_token_cache_lock:
        if include_local_config == value:
            return
        include_local_config = value
        _reset_current_config_token_cache()


def stat_token(path: Path) -> tuple[str, int, int] | None:
    """Return ``(path, mtime_ns, size)`` or ``None`` when *path* is missing.

    Combining mtime_ns with size handles coarse-grained filesystem timestamps.
    """
    try:
        stat = path.stat()
    except (OSError, FileNotFoundError):
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _current_config_token_cache_cwd_key() -> str | None:
    """Return the cwd half of the token cache key, or None when unused."""
    if not include_local_config:
        return None
    try:
        return str(_facade().Path.cwd())
    except OSError:
        return None


def _compute_current_config_token() -> tuple[Any, ...]:
    """Inspect config sources and return their current cache key."""
    core = _facade()
    parts: list[Any] = [config_cache_generation, include_local_config]
    if include_local_config:
        try:
            parts.append(str(core.Path.cwd()))
        except FileNotFoundError:
            parts.append(None)
    else:
        parts.append(None)

    parts.append(core.stat_token(core.CONFIG_DIR / "sase.yml"))
    parts.append(core.stat_token(machine_name_path()))
    parts.append(tuple(core.stat_token(path) for path in overlay_paths()))

    project_root = discover_project_root() if include_local_config else None
    if project_root is None:
        parts.append(None)
    else:
        config = resolve_project_layout(project_root).config
        parts.append(tuple(core.stat_token(path) for path in config.candidates))
    return tuple(parts)


def _publish_revalidator_token(
    token: tuple[Any, ...] | None,
    *,
    cache_epoch: int,
    cache_cwd: str | None,
) -> bool:
    """Publish one revalidator recompute when its epoch is still current."""
    global _current_config_token_cache_value, _current_config_token_cache_deadline
    with _current_config_token_cache_lock:
        # A recompute that raced a `chdir` ran against a directory the cache
        # is no longer keyed to. Declining to publish is safe: the next
        # synchronous read sees the CWD mismatch and recomputes.
        if cache_epoch == _current_config_token_cache_epoch and (
            _current_config_token_cache_cwd == cache_cwd
            and _current_config_token_cache_cwd_key() == cache_cwd
        ):
            if token is not None:
                _current_config_token_cache_value = token
            _current_config_token_cache_deadline = (
                _facade().time.monotonic() + _CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS
            )
            return True
        return False


def _config_token_revalidator_loop(
    stop: threading.Event,
    wake: threading.Event,
) -> None:
    """Refresh an expired config token until ``stop`` is set.

    The loop never reads live ``self`` state: each iteration captures the
    epoch/cwd under the cache lock, recomputes off-lock, and publishes only
    when the epoch still matches. A missed drain window therefore cannot
    install a stale token into a successor generation.

    The loop blocks on ``wake`` instead of polling: an expired getter read
    sets ``wake`` to trigger a recompute, and the deadline wait uses
    ``wake.wait(timeout=<time to deadline>)`` so the thread stays idle when
    nothing reads the token. Every stop path must set ``wake`` as well as
    ``stop`` so a parked wait returns promptly; ``stop`` is re-checked after
    every wake.
    """
    core = _facade()
    while not stop.is_set():
        with _current_config_token_cache_lock:
            cached = _current_config_token_cache_value
            deadline = _current_config_token_cache_deadline
            epoch = _current_config_token_cache_epoch
            cwd = _current_config_token_cache_cwd
        if cached is None:
            # No token yet; the next getter warms the cache synchronously.
            # Park until signalled or one cadence elapses, then re-check.
            wake.wait(timeout=_CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS)
            if stop.is_set():
                break
            wake.clear()
            continue
        try:
            now = core.time.monotonic()
        except Exception:
            now = deadline
        if now < deadline:
            remaining = deadline - now
            if remaining > _CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS:
                remaining = _CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS
            # A getter expiry signal wakes us early; otherwise we sleep
            # until the deadline (at most one cadence, never sub-second
            # polling while idle).
            wake.wait(timeout=remaining)
            if stop.is_set():
                break
            wake.clear()
            continue
        wake.clear()
        try:
            token = _compute_current_config_token()
        except Exception:
            log.debug("Background config-token refresh failed", exc_info=True)
            token = None
        published = _publish_revalidator_token(token, cache_epoch=epoch, cache_cwd=cwd)
        if stop.is_set():
            break
        if not published:
            # Stale epoch or raced chdir: park instead of busy-looping
            # on an expired deadline the getter will recompute synchronously.
            wake.wait(timeout=_CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS)
            if stop.is_set():
                break
            wake.clear()


def _ensure_config_token_revalidator_locked() -> threading.Thread | None:
    """Register the long-lived revalidator; caller starts it outside the lock."""
    global _current_config_token_refresh_thread
    global _config_token_revalidator_stop, _config_token_revalidator_wake
    live = _current_config_token_refresh_thread
    # A registered-but-unstarted thread reports is_alive() False until start()
    # runs, so treat ident-is-None as live: only the registering caller starts it.
    if live is not None and (live.is_alive() or live.ident is None):
        return None
    core = _facade()
    stop = core.threading.Event()
    wake = core.threading.Event()
    worker = core.threading.Thread(
        target=_config_token_revalidator_loop,
        args=(stop, wake),
        name=CONFIG_TOKEN_REFRESH_THREAD_NAME,
        daemon=True,
    )
    _config_token_revalidator_stop = stop
    _config_token_revalidator_wake = wake
    _current_config_token_refresh_thread = worker
    return worker


def current_config_token() -> tuple[Any, ...]:
    """Return the cache key for the current merged-config state.

    The first lookup after process start or explicit invalidation is
    synchronous.  An expired cached token is returned stale while one
    long-lived daemon revalidator refreshes it off-thread on its cadence;
    this getter only peeks at the cached value and never starts a thread
    once the revalidator is running.

    The cached token is bound to the ``CONFIG_DIR`` object it was computed
    against and to the process's current working directory. Rebinding
    ``CONFIG_DIR`` (tests patch it; production never does) or a ``chdir`` is a
    cache-generation change, the same class of event as
    :func:`set_include_local_config`. Stale-while-revalidate timing is
    unchanged when neither ``CONFIG_DIR`` nor the working directory changes.
    """
    global _current_config_token_cache_value, _current_config_token_cache_deadline
    global _current_config_token_refresh_thread, _current_config_token_cache_dir
    global _current_config_token_cache_cwd
    global _config_token_revalidator_stop, _config_token_revalidator_wake

    core = _facade()
    revalidator_to_start: threading.Thread | None = None
    sync_token: tuple[Any, ...] | None = None
    with _current_config_token_cache_lock:
        cwd_key = _current_config_token_cache_cwd_key()
        cached = _current_config_token_cache_value
        if (
            cached is None
            or _current_config_token_cache_dir is not core.CONFIG_DIR
            or _current_config_token_cache_cwd != cwd_key
        ):
            if cached is not None:
                _reset_current_config_token_cache_locked()
            sync_token = _compute_current_config_token()
            _current_config_token_cache_value = sync_token
            _current_config_token_cache_dir = core.CONFIG_DIR
            _current_config_token_cache_cwd = cwd_key
            _current_config_token_cache_deadline = (
                core.time.monotonic() + _CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS
            )
            revalidator_to_start = _ensure_config_token_revalidator_locked()
            cached = sync_token
        else:
            revalidator_to_start = _ensure_config_token_revalidator_locked()
            if core.time.monotonic() >= _current_config_token_cache_deadline:
                wake = _config_token_revalidator_wake
                if wake is not None:
                    wake.set()

    if revalidator_to_start is not None:
        try:
            revalidator_to_start.start()
        except Exception:
            with _current_config_token_cache_lock:
                if _current_config_token_refresh_thread is revalidator_to_start:
                    _current_config_token_refresh_thread = None
                    _config_token_revalidator_stop = None
                    _config_token_revalidator_wake = None
            raise
    return cached


def clear_config_cache() -> None:
    """Drop cached config layers and force the next freshness inspection."""
    global config_cache_generation
    global default_config_cache, plugin_configs_cache
    global merged_config_cache, agent_owner_config_cache
    with _current_config_token_cache_lock:
        config_cache_generation += 1
        default_config_cache = None
        plugin_configs_cache = None
        merged_config_cache = None
        agent_owner_config_cache = None
        _reset_current_config_token_cache()
