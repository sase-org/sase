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
from sase.config.inventory import serialize_config_layer

from ._config_layers import (
    compose_axe_layers,
    compose_keyed_axe_layers as _compose_keyed_axe_layers,
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
from .config_backend import AxeConfigComposition

_keyed_config_cache_lock = threading.RLock()
_keyed_config_cache_token: tuple[Any, ...] | None = None
_keyed_config_cache_value: AxeConfigComposition | None = None


def _parse_lumberjacks(
    raw: dict[str, Any],
    *,
    provenance: dict[str, str] | None = None,
    exact_chop_provenance: dict[tuple[str, str], dict[str, str]] | None = None,
) -> dict[str, LumberjackConfig]:
    """Parse lumberjacks while retaining the patchable project-row hook."""
    return parse_lumberjacks(
        raw,
        provenance=provenance,
        exact_chop_provenance=exact_chop_provenance,
        project_target_rows=_project_target_rows,
    )


def _effective_axe_composition(data: dict[str, Any]) -> AxeConfigComposition:
    """Compose every runtime layer stack through the Rust AXE authority."""
    global _keyed_config_cache_token, _keyed_config_cache_value

    # `load_merged_config` is an established test/injection patch surface.
    # When replaced, treat its supplied document as a synthetic layer while
    # still routing composition through Rust.
    if getattr(load_config_layers, "__module__", "") != "sase.config.core":
        layers = load_config_layers()
    elif getattr(load_merged_config, "__module__", "") != "sase.config.core":
        layers = [
            ConfigLayer(
                name="merged",
                path=None,
                exists=True,
                list_strategy="replace",
                data=data,
            )
        ]
    else:
        layers = load_config_layers()
    layer_inputs = [serialize_config_layer(layer) for layer in layers]
    token = (*current_config_token(), json.dumps(layer_inputs, sort_keys=True))
    with _keyed_config_cache_lock:
        if _keyed_config_cache_token == token and _keyed_config_cache_value is not None:
            return _keyed_config_cache_value

    composition = compose_axe_layers(layers)
    with _keyed_config_cache_lock:
        _keyed_config_cache_token = token
        _keyed_config_cache_value = composition
    return composition


def load_axe_config() -> AxeConfig:
    """Load and fail-closed validate the effective axe configuration."""
    composition = _effective_axe_composition(load_merged_config())
    if composition.diagnostics:
        raise AxeConfigError(
            [
                _AxeConfigDiagnostic(
                    code=item.code,
                    message=item.message,
                    path=item.path,
                    layer=item.layer,
                    severity=item.severity,
                )
                for item in composition.diagnostics
            ]
        )
    data = composition.effective_config
    provenance = composition.legacy_provenance()

    axe_data = data.get("axe")
    if not isinstance(axe_data, dict):
        return AxeConfig()

    raw_lumberjacks = axe_data.get("lumberjacks")
    exact_chop_provenance = {
        (entry.selector.lumberjack, entry.selector.chop): composition.chop_provenance(
            entry.selector.lumberjack,
            entry.selector.chop,
        )
        for entry in composition.entries
        if entry.selector.kind == "chop"
        and entry.selector.chop is not None
        and not entry.generated
    }
    lumberjacks = (
        _parse_lumberjacks(
            raw_lumberjacks,
            provenance=provenance,
            exact_chop_provenance=exact_chop_provenance,
        )
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
