"""Public API for planning and executing source-preserving config edits.

The Rust core owns the edit decision logic. The private ``_edit_*`` modules
wrap that with Python-only target-file diffing and YAML source preservation.
This module remains the stable import point for callers.
"""

from __future__ import annotations

from sase.config._edit_plan import apply_config_edit
from sase.config._edit_plan import plan_config_edit as plan_config_edit_impl
from sase.config._edit_types import (
    AppliedResult,
    ConfigEditConflict,
    ConfigEditError,
    ConfigEditOp,
    ConfigEffectivePreview,
    ConfigWritePlan,
    EditPlanResult,
)
from sase.config._edit_yaml import set_key, unset_key
from sase.config.core import get_use_chezmoi
from sase.config.inventory import ConfigInventory


def plan_config_edit(
    inventory: ConfigInventory,
    path: str | None,
    target: str,
    op: ConfigEditOp,
    *,
    key_path: tuple[str, ...] | list[str] | None = None,
    use_chezmoi: bool | None = None,
) -> EditPlanResult:
    """Plan a config edit while preserving this module's patch surface."""
    effective_use_chezmoi = get_use_chezmoi() if use_chezmoi is None else use_chezmoi
    return plan_config_edit_impl(
        inventory,
        path,
        target,
        op,
        key_path=key_path,
        use_chezmoi=effective_use_chezmoi,
    )


__all__ = [
    "AppliedResult",
    "ConfigEditError",
    "ConfigEditConflict",
    "ConfigEditOp",
    "ConfigEffectivePreview",
    "ConfigWritePlan",
    "EditPlanResult",
    "apply_config_edit",
    "plan_config_edit",
    "set_key",
    "unset_key",
]
