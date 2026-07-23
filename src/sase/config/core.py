"""Centralized configuration loading with multi-file merge support.

Loads ``default_config.yml`` (bundled in the package) as the base layer,
then deep-merges plugin ``default_config.yml`` files, then
``~/.config/sase/sase.yml`` (with list replacement), then
deep-merges any overlay files matching ``~/.config/sase/sase_*.yml`` (sorted
alphabetically, with list concatenation) on top. Overlays whose top-level YAML
mapping contains ``machine_name`` participate only when that value matches the
machine-local ``~/.sase/machine_name`` selector; ordinary overlays always
participate. The current project's ``sase/sase.yml`` (with root-level
``sase.yml`` as a read fallback) is merged last, unless local config loading has
been disabled via ``set_include_local_config(False)`` (e.g. for ``sase ace``
runs where the TUI should not inherit repo-level config).

After the first config-token read, filesystem freshness checks use
stale-while-revalidate semantics so render-path callers never perform stat/glob
I/O.  Explicit cache invalidation still makes the next read synchronous, while
external file edits may take roughly two polling windows to become visible.
"""

from __future__ import annotations

import importlib.resources
import logging
import threading
import time
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

from sase.config.layers import (
    DEPRECATED_TOP_LEVEL_KEYS,
    RETIRED_SDD_SELECTOR_KEYS,
    UNSUPPORTED_TOP_LEVEL_KEYS,
    ConfigLayer,
    load_config_layers as _load_config_layers,
    load_yaml_file_with_metadata,
    without_retired_sdd_selectors,
)
from sase.config.identity import (
    AgentOwnerConfigSnapshot,
    AgentOwnerConfigStatus,
    MACHINE_NAME_PATTERN,
    RawOverlayIdentity,
    is_valid_machine_name,
    read_machine_name_selector as _read_machine_name_selector_path,
    read_machine_name_selector_text as _read_machine_name_selector_text_path,
)
from sase.config.xprompt_sources import (
    load_xprompts_by_source as _load_xprompts_by_source,
)
from sase.content_layout import discover_project_root, resolve_project_layout
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    validate_agent_owner,
    validate_agent_username,
)
from sase.core.paths import machine_name_path


log = logging.getLogger(__name__)

CONFIG_DIR = Path("~/.config/sase").expanduser()
CHEZMOI_HOME = Path("~/.local/share/chezmoi/home").expanduser()
# When False, get_local_config_path() always returns None.
# Set to False for `sase ace` so the TUI doesn't pick up a repo's project config;
# agent runs are separate processes and keep the default (True).
_include_local_config: bool = True

# Process-wide caches.  The merged-config cache is keyed on a tuple of mtime/size
# stat tokens for every candidate config file (cheap to recompute), plus the
# include-local flag and cwd.  The bundled-default and plugin-default layers ship
# inside packages and never change in a process, so they're memoized once.  Note:
# callers must not mutate the returned dict; the cache returns the same object.
_default_config_cache: dict[str, Any] | None = None
_plugin_configs_cache: list[dict[str, Any]] | None = None
_merged_config_cache_token: tuple[Any, ...] | None = None
_merged_config_cache_value: dict[str, Any] | None = None
_agent_owner_config_cache_token: tuple[Any, ...] | None = None
_agent_owner_config_cache_value: AgentOwnerConfigSnapshot | None = None

# Config freshness checks run from latency-sensitive render paths, so bound the
# synchronous stat/glob work to one pass per short polling window.  Explicit
# cache clears increment the generation to invalidate downstream caches keyed by
# ``current_config_token()`` even when a rapid, same-size edit happens to retain
# an otherwise-identical filesystem token.
_CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS = 0.75
_config_cache_generation = 0
_current_config_token_cache_value: tuple[Any, ...] | None = None
_current_config_token_cache_deadline = 0.0
_current_config_token_cache_epoch = 0
_current_config_token_cache_lock = threading.RLock()
_current_config_token_refresh_thread: threading.Thread | None = None


def _reset_current_config_token_cache_locked() -> None:
    """Reset the config-token cache while its lock is held."""
    global _current_config_token_cache_value, _current_config_token_cache_deadline
    global _current_config_token_cache_epoch
    _current_config_token_cache_value = None
    _current_config_token_cache_deadline = 0.0
    _current_config_token_cache_epoch += 1


def _reset_current_config_token_cache() -> None:
    """Force the next config-token lookup to inspect the filesystem."""
    with _current_config_token_cache_lock:
        _reset_current_config_token_cache_locked()


def set_include_local_config(value: bool) -> None:
    """Enable or disable loading of the current project's config."""
    global _include_local_config
    with _current_config_token_cache_lock:
        if _include_local_config == value:
            return
        _include_local_config = value
        _reset_current_config_token_cache()


def stat_token(path: Path) -> tuple[str, int, int] | None:
    """Return ``(path, mtime_ns, size)`` for *path* or ``None`` if missing.

    Combines mtime_ns with size to defeat coarse-grained filesystem timestamps.
    """
    try:
        st = path.stat()
    except (OSError, FileNotFoundError):
        return None
    return (str(path), st.st_mtime_ns, st.st_size)


def _compute_current_config_token() -> tuple[Any, ...]:
    """Inspect config sources and return their current cache key."""
    parts: list[Any] = [_config_cache_generation, _include_local_config]
    if _include_local_config:
        try:
            parts.append(str(Path.cwd()))
        except FileNotFoundError:
            parts.append(None)
    else:
        parts.append(None)

    parts.append(stat_token(CONFIG_DIR / "sase.yml"))
    parts.append(stat_token(machine_name_path()))
    parts.append(tuple(stat_token(p) for p in _get_overlay_paths()))

    project_root = discover_project_root() if _include_local_config else None
    if project_root is None:
        parts.append(None)
    else:
        project_config = resolve_project_layout(project_root).config
        parts.append(tuple(stat_token(path) for path in project_config.candidates))

    return tuple(parts)


def _refresh_current_config_token(cache_epoch: int) -> None:
    """Recompute and publish a config token from the daemon worker."""
    global _current_config_token_cache_value, _current_config_token_cache_deadline
    global _current_config_token_refresh_thread

    try:
        token = _compute_current_config_token()
    except Exception:
        log.debug("Background config-token refresh failed", exc_info=True)
        token = None

    with _current_config_token_cache_lock:
        if cache_epoch == _current_config_token_cache_epoch:
            if token is not None:
                _current_config_token_cache_value = token
            _current_config_token_cache_deadline = (
                time.monotonic() + _CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS
            )
        _current_config_token_refresh_thread = None


def current_config_token() -> tuple[Any, ...]:
    """Return the cache key for the current merged-config state.

    Includes the include-local flag, cwd (when local config is enabled), and a
    stat tuple per candidate file layer.  Bundled and plugin defaults aren't
    keyed because they ship in packages and don't change at runtime.

    The first call after process start or explicit invalidation computes the
    token synchronously.  After that, an expired token is returned stale while
    a single daemon worker revalidates it off-thread.
    """
    global _current_config_token_cache_value, _current_config_token_cache_deadline
    global _current_config_token_refresh_thread

    with _current_config_token_cache_lock:
        cached = _current_config_token_cache_value
        if cached is None:
            token = _compute_current_config_token()
            _current_config_token_cache_value = token
            _current_config_token_cache_deadline = (
                time.monotonic() + _CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS
            )
            return token

        if time.monotonic() >= _current_config_token_cache_deadline:
            if _current_config_token_refresh_thread is None:
                refresh_thread = threading.Thread(
                    target=_refresh_current_config_token,
                    args=(_current_config_token_cache_epoch,),
                    name="sase-config-token-refresh",
                    daemon=True,
                )
                _current_config_token_refresh_thread = refresh_thread
                refresh_thread.start()

        return cached


def clear_config_cache() -> None:
    """Drop cached config layers and force the next freshness inspection."""
    global _config_cache_generation
    global _default_config_cache, _plugin_configs_cache
    global _merged_config_cache_token, _merged_config_cache_value
    global _agent_owner_config_cache_token, _agent_owner_config_cache_value
    with _current_config_token_cache_lock:
        _config_cache_generation += 1
        _default_config_cache = None
        _plugin_configs_cache = None
        _merged_config_cache_token = None
        _merged_config_cache_value = None
        _agent_owner_config_cache_token = None
        _agent_owner_config_cache_value = None
        _reset_current_config_token_cache()


def get_use_chezmoi() -> bool:
    """Return whether chezmoi path remapping is enabled."""
    data = load_merged_config()
    return bool(data.get("use_chezmoi", False))


def get_agent_owner_identity() -> AgentOwnerIdentity | None:
    """Return the complete owner configured by the selected raw overlay.

    Identity is deliberately resolved outside the ordinary merge chain:
    defaults, plugins, the user base file, ordinary overlays, and project-local
    config cannot change provenance. The returned dataclass is immutable and
    cached against the normal selector/overlay freshness token.
    """
    return get_agent_owner_config_snapshot().owner


def require_agent_owner_identity() -> AgentOwnerIdentity:
    """Return the complete owner or raise with an actionable initializer hint."""
    snapshot = get_agent_owner_config_snapshot()
    if snapshot.owner is None:
        raise RuntimeError(
            "SASE agent owner identity is not configured "
            f"({snapshot.detail}); run `sase config init`."
        )
    return snapshot.owner


def get_machine_name() -> str | None:
    """Compatibility projection of a complete configured owner identity."""
    owner = get_agent_owner_identity()
    return owner.machine_name if owner is not None else None


def require_machine_name() -> str:
    """Compatibility projection requiring a complete configured owner."""
    return require_agent_owner_identity().machine_name


DEFAULT_MAX_RUNNING_AGENTS = 10


def get_configured_max_running_agents() -> int:
    """Return the validated configured global runner limit.

    ``load_merged_config()`` provides the process cache and invalidates it when
    a config source changes, so callers can poll this accessor without parsing
    unchanged YAML on every call while still observing live config edits.
    """
    value = load_merged_config().get("max_running_agents", DEFAULT_MAX_RUNNING_AGENTS)
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_MAX_RUNNING_AGENTS


def get_max_running_agents(now: float | None = None) -> int:
    """Return the live admission limit, preferring a temporary override.

    State-access errors deliberately propagate. Admission callers must fail
    closed for that poll rather than silently falling back to configuration.
    """
    from sase.config.runner_limit_override import get_active_runner_limit_override

    override = get_active_runner_limit_override(now)
    if override is not None:
        return override.limit
    return get_configured_max_running_agents()


def _deep_merge(
    base: dict[str, Any],
    override: dict[str, Any],
    *,
    list_strategy: Literal["concatenate", "replace"] = "concatenate",
) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict.

    Merge semantics:
    - **Dicts** are merged recursively (overlay keys override base keys).
    - **Lists** behaviour depends on *list_strategy*:
      - ``"concatenate"`` (default): overlay list is appended to base list.
      - ``"replace"``: overlay list replaces base list entirely.
    - **Scalars** in *override* replace those in *base*.

    Neither *base* nor *override* is mutated.
    """
    result: dict[str, Any] = dict(base)
    for key, override_val in override.items():
        if key in result:
            base_val = result[key]
            if isinstance(base_val, dict) and isinstance(override_val, dict):
                result[key] = _deep_merge(
                    base_val, override_val, list_strategy=list_strategy
                )
            elif isinstance(base_val, list) and isinstance(override_val, list):
                if list_strategy == "replace":
                    log.debug(
                        "Merging key %r: list replace (base=%d items → override=%d items)",
                        key,
                        len(base_val),
                        len(override_val),
                    )
                    result[key] = override_val
                else:
                    log.debug(
                        "Merging key %r: list concatenate (base=%d items, override=%d items → %d items)",
                        key,
                        len(base_val),
                        len(override_val),
                        len(base_val) + len(override_val),
                    )
                    result[key] = base_val + override_val
            else:
                result[key] = override_val
        else:
            result[key] = override_val
    return result


def _load_default_config() -> dict[str, Any]:
    """Load the bundled ``default_config.yml`` from the sase package.

    Returns the parsed YAML as a dict, or an empty dict on any error.
    """
    try:
        ref = importlib.resources.files("sase").joinpath("default_config.yml")
        text = ref.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if isinstance(data, dict):
            return data
    except Exception:
        log.debug("Failed to load default_config.yml", exc_info=True)
    return {}


def _load_yaml_file(path: Path) -> dict[str, Any] | None:
    """Load a single YAML file, returning ``None`` on any error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        log.debug("Failed to load YAML file: %s", path, exc_info=True)
    return None


def _get_overlay_paths() -> list[Path]:
    """Return sorted overlay paths matching ``sase_*.yml``."""
    if not CONFIG_DIR.is_dir():
        return []
    return sorted(CONFIG_DIR.glob("sase_*.yml"))


def _raw_overlay_identity(
    path: Path, data: dict[str, Any] | None
) -> RawOverlayIdentity:
    """Project identity-shaped fields from one unmerged overlay."""
    if data is None:
        return RawOverlayIdentity(
            path=path,
            yaml_valid=False,
            id_present=False,
            id_mapping=False,
            username_present=False,
            username=None,
            machine_name_present=False,
            machine_name=None,
            legacy_machine_name_present=False,
            legacy_machine_name=None,
        )

    id_present = "id" in data
    id_value = data.get("id")
    nested: dict[Any, Any] = id_value if isinstance(id_value, dict) else {}
    id_mapping = isinstance(id_value, dict)
    username_present = "username" in nested
    machine_name_present = "machine_name" in nested
    username_value = nested.get("username")
    machine_name_value = nested.get("machine_name")
    legacy_present = "machine_name" in data
    legacy_value = data.get("machine_name")
    return RawOverlayIdentity(
        path=path,
        yaml_valid=True,
        id_present=id_present,
        id_mapping=id_mapping,
        username_present=username_present,
        username=username_value if isinstance(username_value, str) else None,
        machine_name_present=machine_name_present,
        machine_name=(
            machine_name_value if isinstance(machine_name_value, str) else None
        ),
        legacy_machine_name_present=legacy_present,
        legacy_machine_name=legacy_value if isinstance(legacy_value, str) else None,
    )


def _valid_existing_usernames(
    overlays: tuple[RawOverlayIdentity, ...],
) -> tuple[str, ...]:
    usernames: set[str] = set()
    for overlay in overlays:
        username = overlay.username
        if username is None:
            continue
        try:
            validate_agent_username(username)
        except (RuntimeError, ValueError):
            continue
        usernames.add(username)
    return tuple(sorted(usernames))


def _owner_for_overlay(
    overlay: RawOverlayIdentity, selector: str
) -> tuple[AgentOwnerIdentity | None, str | None]:
    """Validate a complete nested identity from the selected overlay."""
    if not overlay.id_mapping:
        return None, "selected overlay has no nested `id` object"
    if not overlay.username_present:
        return None, "selected overlay is missing `id.username`"
    if overlay.username is None:
        return None, "selected overlay has an invalid `id.username` value"
    if not overlay.machine_name_present:
        return None, "selected overlay is missing `id.machine_name`"
    if overlay.machine_name is None:
        return None, "selected overlay has an invalid `id.machine_name` value"
    if overlay.machine_name != selector:
        return (
            None,
            "selector "
            f"'{selector}' does not match `id.machine_name: {overlay.machine_name}` "
            f"in {overlay.path}",
        )
    owner = AgentOwnerIdentity(
        username=overlay.username,
        machine_name=overlay.machine_name,
    )
    try:
        validate_agent_owner(owner)
    except (RuntimeError, ValueError) as exc:
        return None, f"invalid owner identity in {overlay.path}: {exc}"
    return owner, None


def _build_agent_owner_config_snapshot() -> AgentOwnerConfigSnapshot:
    """Build the identity view from the selector and raw user overlays."""
    selector_path = machine_name_path()
    selector_text = _read_machine_name_selector_text_path(selector_path)
    selector = _read_machine_name_selector_path(selector_path)
    overlays = tuple(
        _raw_overlay_identity(path, _load_yaml_file(path))
        for path in _get_overlay_paths()
    )
    existing_usernames = _valid_existing_usernames(overlays)

    if selector_text is None:
        return AgentOwnerConfigSnapshot(
            selector=None,
            selector_text=None,
            status="missing_selector",
            detail="the machine selector is missing",
            owner=None,
            selected_overlay=None,
            matching_overlays=(),
            overlays=overlays,
            existing_usernames=existing_usernames,
        )
    if selector is None:
        return AgentOwnerConfigSnapshot(
            selector=None,
            selector_text=selector_text,
            status="invalid_selector",
            detail=(
                f"the selector at {machine_name_path()} must contain one machine "
                f"name matching {MACHINE_NAME_PATTERN}"
            ),
            owner=None,
            selected_overlay=None,
            matching_overlays=(),
            overlays=overlays,
            existing_usernames=existing_usernames,
        )

    matching = tuple(
        overlay for overlay in overlays if overlay.discriminator == selector
    )
    matching_paths = tuple(overlay.path for overlay in matching)
    if len(matching) > 1:
        paths = ", ".join(str(path) for path in matching_paths)
        usernames = {
            overlay.username for overlay in matching if overlay.username is not None
        }
        status: AgentOwnerConfigStatus = (
            "conflict" if len(usernames) > 1 else "duplicate"
        )
        label = "conflicting" if status == "conflict" else "duplicate"
        return AgentOwnerConfigSnapshot(
            selector=selector,
            selector_text=selector_text,
            status=status,
            detail=(
                f"{label} identity overlays declare machine '{selector}': {paths}; "
                "keep exactly one machine overlay"
            ),
            owner=None,
            selected_overlay=None,
            matching_overlays=matching_paths,
            overlays=overlays,
            existing_usernames=existing_usernames,
        )

    conventional_path = CONFIG_DIR / f"sase_{selector}.yml"
    conventional = next(
        (overlay for overlay in overlays if overlay.path == conventional_path),
        None,
    )
    selected = matching[0] if matching else None
    if selected is None and conventional is not None:
        selected = conventional

    if selected is None:
        discovered = tuple(
            sorted(
                {
                    value
                    for overlay in overlays
                    if (value := overlay.discriminator) is not None
                    and is_valid_machine_name(value)
                }
            )
        )
        if discovered:
            return AgentOwnerConfigSnapshot(
                selector=selector,
                selector_text=selector_text,
                status="selector_mismatch",
                detail=(
                    f"selector '{selector}' matches no machine overlay; declared "
                    f"machines: {', '.join(discovered)}"
                ),
                owner=None,
                selected_overlay=None,
                matching_overlays=(),
                overlays=overlays,
                existing_usernames=existing_usernames,
            )
        return AgentOwnerConfigSnapshot(
            selector=selector,
            selector_text=selector_text,
            status="missing_overlay",
            detail=f"selector '{selector}' has no machine overlay",
            owner=None,
            selected_overlay=conventional_path,
            matching_overlays=(),
            overlays=overlays,
            existing_usernames=existing_usernames,
        )

    if not selected.yaml_valid:
        return AgentOwnerConfigSnapshot(
            selector=selector,
            selector_text=selector_text,
            status="invalid",
            detail=f"selected overlay {selected.path} is not a valid YAML mapping",
            owner=None,
            selected_overlay=selected.path,
            matching_overlays=matching_paths,
            overlays=overlays,
            existing_usernames=existing_usernames,
        )
    if selected.nested_legacy_conflict:
        return AgentOwnerConfigSnapshot(
            selector=selector,
            selector_text=selector_text,
            status="conflict",
            detail=(
                f"{selected.path} declares conflicting nested "
                f"`id.machine_name: {selected.machine_name}` and legacy "
                f"`machine_name: {selected.legacy_machine_name}` values"
            ),
            owner=None,
            selected_overlay=selected.path,
            matching_overlays=matching_paths,
            overlays=overlays,
            existing_usernames=existing_usernames,
        )
    if (
        selected.machine_name_present
        and selected.machine_name is not None
        and selected.machine_name != selector
    ):
        return AgentOwnerConfigSnapshot(
            selector=selector,
            selector_text=selector_text,
            status="selector_mismatch",
            detail=(
                f"selector '{selector}' does not match "
                f"`id.machine_name: {selected.machine_name}` in {selected.path}"
            ),
            owner=None,
            selected_overlay=selected.path,
            matching_overlays=matching_paths,
            overlays=overlays,
            existing_usernames=existing_usernames,
        )

    owner, owner_error = _owner_for_overlay(selected, selector)
    if owner is not None:
        status = "legacy" if selected.legacy_machine_name_present else "complete"
        detail = (
            f"{selected.path} still contains deprecated top-level `machine_name`"
            if status == "legacy"
            else f"owner identity is configured by {selected.path}"
        )
        return AgentOwnerConfigSnapshot(
            selector=selector,
            selector_text=selector_text,
            status=status,
            detail=detail,
            owner=owner,
            selected_overlay=selected.path,
            matching_overlays=matching_paths,
            overlays=overlays,
            existing_usernames=existing_usernames,
        )

    invalid_username = selected.username_present and selected.username is None
    if selected.username is not None:
        try:
            validate_agent_username(selected.username)
        except (RuntimeError, ValueError):
            invalid_username = True

    legacy = (
        selected.legacy_machine_name_present
        and selected.legacy_machine_name == selector
    )
    if invalid_username:
        status = "invalid"
        detail = f"selected overlay {selected.path} has an invalid `id.username`"
    elif legacy:
        status = "legacy"
        detail = (
            f"selected overlay {selected.path} uses deprecated top-level "
            "`machine_name` and must add `id.username`"
        )
    elif selected.id_present:
        invalid = (
            (selected.username_present and selected.username is None)
            or (selected.machine_name_present and selected.machine_name is None)
            or (
                owner_error is not None
                and owner_error.startswith("invalid owner identity")
            )
        )
        status = "invalid" if invalid else "partial"
        detail = owner_error or f"selected overlay {selected.path} is incomplete"
    else:
        status = "missing_overlay"
        detail = f"{selected.path} has no owner identity"
    return AgentOwnerConfigSnapshot(
        selector=selector,
        selector_text=selector_text,
        status=status,
        detail=detail,
        owner=None,
        selected_overlay=selected.path,
        matching_overlays=matching_paths,
        overlays=overlays,
        existing_usernames=existing_usernames,
    )


def get_agent_owner_config_snapshot() -> AgentOwnerConfigSnapshot:
    """Return the cached selected-overlay identity state used by init/doctor."""
    global _agent_owner_config_cache_token, _agent_owner_config_cache_value
    token = current_config_token()
    if (
        _agent_owner_config_cache_value is not None
        and _agent_owner_config_cache_token == token
    ):
        return _agent_owner_config_cache_value
    snapshot = _build_agent_owner_config_snapshot()
    _agent_owner_config_cache_token = token
    _agent_owner_config_cache_value = snapshot
    return snapshot


def discover_machine_names() -> tuple[str, ...]:
    """Return valid nested-first machine discriminators from raw overlays."""
    return tuple(
        sorted(
            {
                name
                for overlay in get_agent_owner_config_snapshot().overlays
                if (name := overlay.discriminator) is not None
                and is_valid_machine_name(name)
            }
        )
    )


def _get_selected_overlay_paths() -> list[Path]:
    """Return ordinary overlays plus the overlay selected for this machine.

    Every candidate is parsed only when a config consumer is rebuilding its
    view. The freshness token still stats every raw overlay, so a foreign
    overlay edit can invalidate the cached view without adding YAML parsing to
    render-path token checks.
    """
    snapshot = get_agent_owner_config_snapshot()
    selector = snapshot.selector
    selected: list[Path] = []
    for overlay in snapshot.overlays:
        if not overlay.declares_machine_overlay:
            selected.append(overlay.path)
            continue
        if overlay.discriminator == selector:
            selected.append(overlay.path)
    return selected


def get_local_config_path() -> Path | None:
    """Return the selected project-local config path, if one exists.

    Returns ``None`` when ``_include_local_config`` is ``False`` (e.g. during
    ``sase ace`` runs where the TUI shouldn't inherit repo-level config).
    Canonical ``sase/sase.yml`` is preferred, root-level ``sase.yml`` remains
    readable for compatibility, and coexistence raises a collision diagnostic.
    """
    if not _include_local_config:
        return None
    project_root = discover_project_root()
    if project_root is None:
        return None
    return resolve_project_layout(project_root).config.resolve_read("project config")


def _get_local_config_write_path() -> Path | None:
    """Return the canonical destination for the current project's config."""
    if not _include_local_config:
        return None
    project_root = discover_project_root()
    if project_root is None:
        return None
    return resolve_project_layout(project_root).config.write_path


def _load_plugin_configs() -> list[dict[str, Any]]:
    """Load ``default_config.yml`` from each plugin in the ``sase_config`` group.

    Returns config dicts sorted by entry-point name for determinism.
    """
    from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

    if is_plugin_disabled("CONFIG"):
        return []

    configs: list[dict[str, Any]] = []
    for module in discover_plugin_resources("sase_config"):
        try:
            ref = importlib.resources.files(module).joinpath("default_config.yml")
            text = ref.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
            if isinstance(data, dict):
                configs.append(data)
        except Exception:
            log.debug(
                "Failed to load plugin config from %s",
                getattr(module, "__name__", module),
                exc_info=True,
            )
    return configs


def load_xprompts_by_source() -> list[tuple[str, dict[str, Any]]]:
    """Load xprompt entries from each config source with provenance tracking.

    Instead of merging all configs and extracting xprompts (which loses source
    information), this returns xprompt dicts from each source separately so the
    xprompt loader can assign proper source attribution.

    Returns:
        List of ``(source_label, xprompts_dict)`` tuples in priority order
        (lowest priority first).  Source labels:

        - ``"default_config"`` — built-in package defaults
        - ``"plugin_config:{module_name}"`` — plugin default configs
        - ``"config"`` — user ``sase.yml``
        - ``"config_overlay:{filename}"`` — ``sase_*.yml`` overlays
    """
    return _load_xprompts_by_source(
        config_dir=CONFIG_DIR,
        default_loader=_load_default_config,
        yaml_loader=_load_yaml_file,
        overlay_paths=_get_selected_overlay_paths(),
        local_path=get_local_config_path(),
        resource_files=importlib.resources.files,
    )


def _without_owner_identity(data: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Remove identity keys from a non-authoritative merge contribution."""
    if "id" not in data and "machine_name" not in data:
        return data
    ignored = [key for key in ("id", "machine_name") if key in data]
    log.warning(
        "Ignoring owner identity key(s) %s from non-authoritative config source %s; "
        "run `sase config init` to manage identity in the selected machine overlay",
        ", ".join(ignored),
        source,
    )
    cleaned = dict(data)
    cleaned.pop("id", None)
    cleaned.pop("machine_name", None)
    return cleaned


def load_merged_config() -> dict[str, Any]:
    """Load and merge all sase config files.

    Merge chain (each layer merges on top of the previous):
    1. ``default_config.yml`` (bundled package defaults)
    2. Plugin ``default_config.yml`` files (sorted by EP name, lists concatenate)
    3. ``sase.yml`` (user config — lists **replace** defaults)
    4. ordinary ``sase_*.yml`` overlays plus the selected machine overlay
       (sorted alphabetically — lists **concatenate**)
    5. project ``sase/sase.yml`` (legacy ``sase.yml`` is read-compatible;
       lists **concatenate**, highest priority)

    Returns at least the defaults even when no user config files exist.

    The result is memoized; cache invalidates automatically when any candidate
    file's mtime/size changes, when ``set_include_local_config`` toggles, or when
    cwd changes (and local config is enabled).  Callers must not mutate the
    returned dict — every call site today reads via ``.get()`` or key access.
    Use :func:`clear_config_cache` to force a reload.
    """
    global _default_config_cache, _plugin_configs_cache
    global _merged_config_cache_token, _merged_config_cache_value

    token = current_config_token()
    if _merged_config_cache_value is not None and _merged_config_cache_token == token:
        return _merged_config_cache_value

    if _default_config_cache is None:
        _default_config_cache = _load_default_config()
    result = dict(_without_owner_identity(_default_config_cache, source="default"))
    log.debug("Loading layer 'default' (keys: %s)", ", ".join(result.keys()))

    # 2. Plugin configs (between defaults and user config)
    if _plugin_configs_cache is None:
        _plugin_configs_cache = _load_plugin_configs()
    for index, plugin_config in enumerate(_plugin_configs_cache, start=1):
        log.debug("Loading layer 'plugin' (keys: %s)", ", ".join(plugin_config.keys()))
        result = _deep_merge(
            result,
            _without_owner_identity(plugin_config, source=f"plugin #{index}"),
        )

    base_path = CONFIG_DIR / "sase.yml"
    user_base = _load_yaml_file(base_path)
    if user_base:
        log.debug(
            "Loading layer 'user' from %s (keys: %s) [list_strategy=replace]",
            base_path,
            ", ".join(user_base.keys()),
        )
        result = _deep_merge(
            result,
            _without_owner_identity(user_base, source=str(base_path)),
            list_strategy="replace",
        )

    identity_snapshot = get_agent_owner_config_snapshot()
    selected_identity: dict[str, Any] | None = None
    for overlay_path in _get_selected_overlay_paths():
        overlay = _load_yaml_file(overlay_path)
        if overlay:
            log.debug(
                "Loading layer 'overlay:%s' from %s (keys: %s)",
                overlay_path.name,
                overlay_path,
                ", ".join(overlay.keys()),
            )
            if overlay_path == identity_snapshot.selected_overlay:
                id_value = overlay.get("id")
                if isinstance(id_value, dict):
                    selected_identity = dict(id_value)
                contribution = dict(overlay)
                contribution.pop("id", None)
                contribution.pop("machine_name", None)
            else:
                contribution = _without_owner_identity(
                    overlay,
                    source=str(overlay_path),
                )
            result = _deep_merge(result, contribution)

    # 5. Local config (highest priority, lists concatenate so that
    #    project-specific entries *add to* rather than replace plugin/user lists
    #    — e.g. a repo's mentor_profiles should extend, not wipe, plugin profiles)
    local_path = get_local_config_path()
    if local_path:
        local_config = _load_yaml_file(local_path)
        if local_config:
            log.debug(
                "Loading layer 'local' from %s (keys: %s) [list_strategy=concatenate]",
                local_path,
                ", ".join(local_config.keys()),
            )
            result = _deep_merge(
                result,
                _without_owner_identity(local_config, source=str(local_path)),
            )

    result = without_retired_sdd_selectors(result)
    if selected_identity is not None:
        # Restore the selected raw object after every ordinary merge layer so
        # project-local config can never change provenance or its inspection
        # view.
        result["id"] = selected_identity
    _merged_config_cache_token = token
    _merged_config_cache_value = result
    return result


def load_config_layers() -> list[ConfigLayer]:
    """Load all config layers with metadata, without merging.

    Returns a list of ConfigLayer descriptors in merge order (lowest to highest
    priority).  Each entry records the source path, whether the file existed,
    which top-level keys it contributed, and the raw data.
    """
    local_path = get_local_config_path()
    local_fallback_path = (
        local_path or _get_local_config_write_path() or Path.cwd() / "sase" / "sase.yml"
    )
    return _load_config_layers(
        config_dir=CONFIG_DIR,
        default_loader=_load_default_config,
        overlay_paths=_get_selected_overlay_paths(),
        local_path=local_path,
        local_fallback_path=local_fallback_path,
        resource_files=importlib.resources.files,
    )
