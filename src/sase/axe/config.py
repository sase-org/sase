"""Public configuration interface for the lumberjack-based axe architecture.

The implementation is split by responsibility across runtime types, target
expansion, and layered composition modules. This module retains the established
import and test-patching surface while coordinating the complete load flow.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from sase.config import load_merged_config
from sase.config.core import ConfigLayer, current_config_token, load_config_layers
from sase.core.axe_chop_facade import validate_axe_config

from ._config_layers import (
    build_axe_config_provenance,
    compose_keyed_axe_layers as _compose_keyed_axe_layers,
    has_map_form_chops,
    map_form_chop_layers,
)
from ._config_targets import (
    parse_lumberjacks,
    parse_duration as _parse_duration,
    project_target_rows as _project_target_rows,
)
from ._config_types import (
    DEFAULT_LUMBERJACK_LOG_MAX_BYTES,
    DEFAULT_LUMBERJACK_LOG_TEMP_MAX_AGE_SECONDS,
    DEFAULT_LUMBERJACK_RESTART_BACKOFF_MAX_SECONDS,
    AxeConfig,
    AxeConfigDiagnostic as _AxeConfigDiagnostic,
    AxeConfigError,
    ChopConfig,
    LumberjackConfig,
)

_keyed_config_cache_lock = threading.RLock()
_keyed_config_cache_token: tuple[Any, ...] | None = None
_keyed_config_cache_value: tuple[dict[str, Any], dict[str, str]] | None = None


def _parse_lumberjacks(
    raw: dict[str, Any],
    *,
    provenance: dict[str, str] | None = None,
) -> dict[str, LumberjackConfig]:
    """Parse lumberjacks while retaining the patchable project-row hook."""
    return parse_lumberjacks(
        raw,
        provenance=provenance,
        project_target_rows=_project_target_rows,
    )


def _axe_config_provenance(
    layers: list[ConfigLayer] | None = None,
) -> dict[str, str]:
    """Build dotted-path provenance for the effective ``axe:`` section."""
    return build_axe_config_provenance(
        load_config_layers() if layers is None else layers
    )


def _effective_axe_config_data(
    data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Apply keyed chop composition when any source layer uses map form."""
    global _keyed_config_cache_token, _keyed_config_cache_value
    if not has_map_form_chops(data):
        return data, {}

    token = (
        *current_config_token(),
        json.dumps(data.get("axe"), sort_keys=True, separators=(",", ":")),
    )
    with _keyed_config_cache_lock:
        if _keyed_config_cache_token == token and _keyed_config_cache_value is not None:
            return _keyed_config_cache_value

    layers = load_config_layers()
    if not map_form_chop_layers(layers):
        return data, _axe_config_provenance(layers)
    composed, provenance, diagnostics = _compose_keyed_axe_layers(layers)
    if diagnostics:
        raise AxeConfigError(diagnostics)
    with _keyed_config_cache_lock:
        _keyed_config_cache_token = token
        _keyed_config_cache_value = (composed, provenance)
    return composed, provenance


def _validate_effective_axe_config(
    data: dict[str, Any],
    *,
    provenance: dict[str, str] | None = None,
) -> None:
    request: dict[str, Any]
    if "axe" in data:
        request = {"axe": data["axe"]}
    else:
        request = {}
    diagnostics = validate_axe_config(request, provenance=provenance)
    if not diagnostics:
        return
    if provenance is None:
        # Provenance discovery performs file/plugin IO, so only pay for it on
        # the error path when callers did not already compose keyed layers.
        diagnostics = validate_axe_config(
            request,
            provenance=_axe_config_provenance(),
        )
    raise AxeConfigError([_AxeConfigDiagnostic.from_wire(item) for item in diagnostics])


def load_axe_config() -> AxeConfig:
    """Load and fail-closed validate the effective axe configuration."""
    data, provenance = _effective_axe_config_data(load_merged_config())
    _validate_effective_axe_config(data, provenance=provenance or None)

    axe_data = data.get("axe")
    if not isinstance(axe_data, dict):
        return AxeConfig()

    raw_lumberjacks = axe_data.get("lumberjacks")
    lumberjacks = (
        _parse_lumberjacks(raw_lumberjacks, provenance=provenance)
        if isinstance(raw_lumberjacks, dict)
        else {}
    )

    return AxeConfig(
        max_hook_runners=int(axe_data.get("max_hook_runners", 3)),
        max_agent_runners=int(axe_data.get("max_agent_runners", 3)),
        zombie_timeout_seconds=int(axe_data.get("zombie_timeout_seconds", 7200)),
        lumberjack_log_max_bytes=int(
            axe_data.get(
                "lumberjack_log_max_bytes",
                DEFAULT_LUMBERJACK_LOG_MAX_BYTES,
            )
        ),
        lumberjack_log_temp_max_age_seconds=int(
            axe_data.get(
                "lumberjack_log_temp_max_age_seconds",
                DEFAULT_LUMBERJACK_LOG_TEMP_MAX_AGE_SECONDS,
            )
        ),
        lumberjack_restart_backoff_max_seconds=int(
            axe_data.get(
                "lumberjack_restart_backoff_max_seconds",
                DEFAULT_LUMBERJACK_RESTART_BACKOFF_MAX_SECONDS,
            )
        ),
        verbose_lumberjack_diagnostics=bool(
            axe_data.get("verbose_lumberjack_diagnostics", False)
        ),
        query=str(axe_data.get("query", "")),
        chop_script_dirs=[str(item) for item in axe_data.get("chop_script_dirs", [])],
        lumberjacks=lumberjacks,
    )
