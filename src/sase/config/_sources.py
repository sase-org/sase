"""Merged-config loaders, local-path resolution, and owner-snapshot caching.

Reads cache slots and overlay paths through :mod:`sase.config._cache` and
looks ``CONFIG_DIR``, ``Path``, ``importlib``, and ``merge_config_sources``
up on :mod:`sase.config.core` so the facade stays the patch surface.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.config import _cache as cache
from sase.config._owner import selected_overlay_paths
from sase.config.identity import (
    AgentOwnerConfigSnapshot,
    build_agent_owner_config_snapshot,
    read_machine_name_selector,
    read_machine_name_selector_text,
)
from sase.config.layers import ConfigLayer
from sase.config.layers import load_config_layers as load_layer_metadata
from sase.config.local_trust_enforcement import effective_local_layer
from sase.config.loading import (
    load_default_config as load_default_config_resource,
    load_plugin_configs as load_plugin_config_resources,
    load_yaml_file as load_yaml_file_path,
)
from sase.config.macro_sources import load_macros_by_source as load_macro_source_layers
from sase.content_layout import discover_project_root, resolve_project_layout
from sase.core.paths import machine_name_path


log = logging.getLogger(__name__)


def _facade() -> Any:
    """Return the public ``sase.config.core`` module (the patch surface)."""
    from sase.config import core

    return core


def _filtered_local_yaml_loader(
    base_loader: Any,
    local_path: Path | None,
    effective: dict[str, Any],
) -> Any:
    """Return a loader serving the evaluated effective layer for *local_path*.

    The same decoded snapshot is digested, filtered, and merged; the merge
    never performs a second unchecked read of the local file.
    """

    def _loader(path: Path) -> dict[str, Any] | None:
        if local_path is not None and path == local_path:
            return dict(effective)
        return base_loader(path)

    return _loader


def _trusted_yaml_loader(
    base_loader: Any,
    local_path: Path | None,
    local_override: Mapping[str, Any] | None = None,
    local_snapshot: Any | None = None,
) -> Any:
    """Wrap *base_loader* so the local layer is trust-filtered when enabled.

    Reads the candidate once and evaluates that same snapshot, so digest,
    filter, and merge cannot diverge. Missing local files keep the original
    loader to preserve today's missing-file merge behavior.
    """
    if local_snapshot is not None:
        return _filtered_local_yaml_loader(
            base_loader, local_path, dict(local_snapshot.effective)
        )
    if local_path is None:
        return base_loader
    if local_override is not None:
        candidate: dict[str, Any] | None = dict(local_override)
    else:
        try:
            raw = base_loader(local_path)
        except Exception:
            raw = None
        if not isinstance(raw, dict):
            return base_loader
        candidate = dict(raw)
    try:
        effective, _evaluation = effective_local_layer(local_path, candidate)
    except Exception:
        log.debug("Local trust filtering failed closed", exc_info=True)
        return _filtered_local_yaml_loader(base_loader, local_path, {})
    return _filtered_local_yaml_loader(base_loader, local_path, effective)


def _load_default_config() -> dict[str, Any]:
    return load_default_config_resource(_facade().importlib.resources.files)


def _load_yaml_file(path: Path) -> dict[str, Any] | None:
    return load_yaml_file_path(path)


def _load_plugin_configs() -> list[dict[str, Any]]:
    return load_plugin_config_resources(_facade().importlib.resources.files)


def _build_agent_owner_config_snapshot() -> AgentOwnerConfigSnapshot:
    from sase.config._cache import overlay_paths

    selector_path = machine_name_path()
    return build_agent_owner_config_snapshot(
        config_dir=_facade().CONFIG_DIR,
        overlay_paths=overlay_paths(),
        yaml_loader=_load_yaml_file,
        selector_path=selector_path,
        selector_text=read_machine_name_selector_text(selector_path),
        selector=read_machine_name_selector(selector_path),
    )


def get_agent_owner_config_snapshot() -> AgentOwnerConfigSnapshot:
    """Return the cached selected-overlay identity state used by init/doctor."""
    token = _facade().current_config_token()
    cached = cache.agent_owner_config_cache
    if cached is not None and cached[0] == token:
        return cached[1]
    generation = cache.config_cache_generation
    snapshot = _build_agent_owner_config_snapshot()
    # A concurrent clear_config_cache() during the build means this snapshot
    # is already known stale; publish only when the generation held steady so
    # a build that outlived a cache clear cannot install itself as current.
    if cache.config_cache_generation == generation:
        cache.agent_owner_config_cache = (token, snapshot)
    return snapshot


def get_local_config_path() -> Path | None:
    """Return the selected project-local config path, if one exists.

    Canonical ``sase/sase.yml`` is preferred, while root-level ``sase.yml``
    remains readable for compatibility.
    """
    if not cache.include_local_config:
        return None
    project_root = discover_project_root()
    if project_root is None:
        return None
    return resolve_project_layout(project_root).config.resolve_read("project config")


def _get_local_config_write_path() -> Path | None:
    """Return the canonical destination for the current project's config."""
    if not cache.include_local_config:
        return None
    project_root = discover_project_root()
    if project_root is None:
        return None
    return resolve_project_layout(project_root).config.write_path


def load_macros_by_source() -> list[tuple[str, dict[str, Any]]]:
    """Load config-defined macros with source provenance."""
    core = _facade()
    return load_macro_source_layers(
        config_dir=core.CONFIG_DIR,
        default_loader=_load_default_config,
        yaml_loader=_load_yaml_file,
        overlay_paths=selected_overlay_paths(),
        local_path=core.get_local_config_path(),
        resource_files=core.importlib.resources.files,
    )


def load_merged_config() -> dict[str, Any]:
    """Load and cache the effective config from all source layers.

    The merge order is bundled defaults, plugin defaults, user config (lists
    replace), selected overlays (lists concatenate), and project-local config
    (lists concatenate).  The cache invalidates when candidate files, cwd, or
    local-config inclusion changes. Each authored layer is normalized to
    canonical macro spellings before merging; the constant retired
    legacy-syntax policy bit joins the cache key for shape compatibility.
    """
    core = _facade()
    token = core.current_config_token()
    # Retired spellings are always accepted; the constant policy bit stays
    # in the cache key for shape compatibility.
    local_path = core.get_local_config_path()
    local_snapshot = core.local_config_snapshot(local_path)
    evaluation = local_snapshot.evaluation
    trust_key = (
        getattr(evaluation, "enabled", True),
        getattr(evaluation, "trusted", False),
        getattr(evaluation, "digest", ""),
        getattr(evaluation, "acknowledged_digest", None),
        getattr(evaluation, "identity", None),
        getattr(evaluation, "logical_path", None),
        getattr(evaluation, "policy_version", None),
        getattr(evaluation, "status", "evaluation-error"),
    )
    key = (token, True, str(local_path), local_snapshot.content_key, trust_key)
    cached = cache.merged_config_cache
    if cached is not None and cached[0] == key:
        return cached[1]
    if cache.default_config_cache is None:
        cache.default_config_cache = _load_default_config()
    if cache.plugin_configs_cache is None:
        cache.plugin_configs_cache = _load_plugin_configs()

    generation = cache.config_cache_generation
    result = core.merge_config_sources(
        default_config=cache.default_config_cache,
        plugin_configs=cache.plugin_configs_cache,
        user_base_path=core.CONFIG_DIR / "sase.yml",
        overlay_paths=selected_overlay_paths(),
        selected_identity_snapshot=core.get_agent_owner_config_snapshot(),
        local_path=local_path,
        yaml_loader=_trusted_yaml_loader(
            _load_yaml_file, local_path, local_snapshot=local_snapshot
        ),
    )
    # A concurrent clear_config_cache() during the merge means this build is
    # already known stale; publish only when the generation held steady so a
    # build that outlived a cache clear cannot install itself as current.
    if cache.config_cache_generation == generation:
        cache.merged_config_cache = (key, result)
    return result


def load_merged_config_for_local_path(
    local_path: Path | None,
    *,
    linked_repo_origin_key: str | None = None,
    local_config_override: Mapping[str, Any] | None = None,
    local_snapshot: Any | None = None,
) -> dict[str, Any]:
    """Load config with an explicitly selected project-local layer.

    Repository inventory walks registered projects that can differ from the
    current working directory. This entry point composes the same bundled,
    plugin, user, and overlay layers as :func:`load_merged_config`, but uses
    the caller's local path instead of discovering one from cwd.
    """
    if cache.default_config_cache is None:
        cache.default_config_cache = _load_default_config()
    if cache.plugin_configs_cache is None:
        cache.plugin_configs_cache = _load_plugin_configs()

    from sase.config._cache import overlay_paths

    yaml_loader = _trusted_yaml_loader(
        _load_yaml_file, local_path, local_config_override, local_snapshot
    )
    core = _facade()
    return core.merge_config_sources(
        default_config=cache.default_config_cache,
        plugin_configs=cache.plugin_configs_cache,
        user_base_path=core.CONFIG_DIR / "sase.yml",
        overlay_paths=overlay_paths(),
        selected_identity_snapshot=core.get_agent_owner_config_snapshot(),
        local_path=local_path,
        yaml_loader=yaml_loader,
        linked_repo_origin_key=linked_repo_origin_key,
    )


def load_public_merged_config() -> dict[str, Any]:
    """Return the effective config projected for public display surfaces."""
    core = _facade()
    result = dict(core.load_merged_config())

    from sase.config.inventory import serialize_config_layer
    from sase.core.rust import require_rust_binding

    layer_inputs = [
        serialize_config_layer(layer) for layer in core.load_config_layers()
    ]
    if not any(
        isinstance(layer.get("value"), dict) and "axe" in layer["value"]
        for layer in layer_inputs
    ):
        return result
    binding = require_rust_binding("axe_config_compose")
    payload = binding(
        {
            "layers": layer_inputs,
            "require_descriptions": False,
            "require_description_shape": False,
            # The retired routine/job rollout switch is gone: the public
            # routine/job projection is always requested.
            "routine_job_contract": True,
        }
    )
    public_config = payload.get("public_config")
    public_axe = public_config.get("axe") if isinstance(public_config, dict) else None
    if isinstance(public_axe, dict):
        result["axe"] = public_axe
    return result


def load_config_layers() -> list[ConfigLayer]:
    """Load config-layer metadata without merging the layers."""
    core = _facade()
    local_path = core.get_local_config_path()
    fallback = (
        local_path
        or _get_local_config_write_path()
        or core.Path.cwd() / "sase" / "sase.yml"
    )
    return load_layer_metadata(
        config_dir=core.CONFIG_DIR,
        default_loader=_load_default_config,
        overlay_paths=selected_overlay_paths(),
        local_path=local_path,
        local_fallback_path=fallback,
        resource_files=core.importlib.resources.files,
    )
