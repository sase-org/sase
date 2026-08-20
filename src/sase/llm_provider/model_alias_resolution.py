"""Resolution and selector validation for configured and implicit model aliases.

Target availability, alias-chain resolution, and selector diagnostics live in
sibling modules and are re-exported here to preserve the import and
monkeypatch surface.
"""

from __future__ import annotations

from . import model_alias_resolution_types as _resolution_types
from .load_balancing import (
    fallback_availability_mask as fallback_availability_mask,
    pool_availability_mask as pool_availability_mask,
    select_model_alias_fallback_member as select_model_alias_fallback_member,
    select_model_alias_pool_member as select_model_alias_pool_member,
)
from .model_alias_resolution_resolve import (
    resolve_model_alias as resolve_model_alias,
    resolve_model_alias_with_effort as resolve_model_alias_with_effort,
)
from .model_alias_resolution_selector import (
    model_alias_selector_details as model_alias_selector_details,
    validate_model_alias_selector_value as validate_model_alias_selector_value,
)
from .model_alias_resolution_types import (
    ModelAliasSelectorMember as ModelAliasSelectorMember,
    ProviderDisableSnapshot as ProviderDisableSnapshot,
    _ALIAS_RESOLUTION_DEPTH_LIMIT as _ALIAS_RESOLUTION_DEPTH_LIMIT,
    active_alias_overrides as active_alias_overrides,
    normalize_model_alias_reference as normalize_model_alias_reference,
    provider_for_resolved_target as provider_for_resolved_target,
    resolve_default_alias_target as resolve_default_alias_target,
    resolved_target_availability as resolved_target_availability,
    resolved_target_is_available as resolved_target_is_available,
)

_active_provider_disables = _resolution_types._active_provider_disables
