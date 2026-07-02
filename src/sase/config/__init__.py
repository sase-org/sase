"""Configuration loading and domain-specific config modules.

Re-exports the public API from ``config.core`` so that existing
``from sase.config import X`` imports continue to work, plus the Config Center
backend (inventory, edit planning/execution, and write-target resolution) that
the TUI panel and any future CLI/web frontend call through.
"""

from sase.config.core import (
    CHEZMOI_HOME,
    CONFIG_DIR,
    ConfigLayer,
    get_use_chezmoi,
    load_config_layers,
    load_merged_config,
    load_xprompts_by_source,
    load_yaml_file_with_metadata,
)
from sase.config.edit import (
    AppliedResult,
    ConfigEditError,
    ConfigEditOp,
    ConfigEffectivePreview,
    ConfigWritePlan,
    EditPlanResult,
    apply_config_edit,
    plan_config_edit,
    set_key,
    unset_key,
)
from sase.config.inventory import (
    ConfigBackendError,
    ConfigConstraints,
    ConfigContribution,
    ConfigDiagnostic,
    ConfigField,
    ConfigFieldModel,
    ConfigFieldState,
    ConfigInventory,
    ConfigSource,
    build_config_inventory,
    config_field_model,
    config_schema_path,
    discover_layer_inputs,
    inventory_with_new_overlay,
    load_config_schema,
    overlay_layer_input,
)
from sase.config.targets import (
    apply_chezmoi,
    chezmoi_source_path,
    default_target_layer,
    overlay_config_path,
    resolve_write_path,
)


__all__ = [
    "CHEZMOI_HOME",
    "CONFIG_DIR",
    "AppliedResult",
    "ConfigBackendError",
    "ConfigConstraints",
    "ConfigContribution",
    "ConfigDiagnostic",
    "ConfigEditError",
    "ConfigEditOp",
    "ConfigEffectivePreview",
    "ConfigField",
    "ConfigFieldModel",
    "ConfigFieldState",
    "ConfigInventory",
    "ConfigLayer",
    "ConfigSource",
    "ConfigWritePlan",
    "EditPlanResult",
    "apply_chezmoi",
    "apply_config_edit",
    "build_config_inventory",
    "chezmoi_source_path",
    "config_field_model",
    "config_schema_path",
    "default_target_layer",
    "discover_layer_inputs",
    "get_use_chezmoi",
    "inventory_with_new_overlay",
    "load_config_layers",
    "load_config_schema",
    "load_merged_config",
    "load_xprompts_by_source",
    "load_yaml_file_with_metadata",
    "overlay_config_path",
    "overlay_layer_input",
    "plan_config_edit",
    "resolve_write_path",
    "set_key",
    "unset_key",
]
