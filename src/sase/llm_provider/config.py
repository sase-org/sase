"""Stable configuration façade for the LLM provider layer.

Provider defaults live here. Model-alias parsing, policy, and resolution are
implemented in focused sibling modules and re-exported here to preserve the
long-standing import and monkeypatch surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.config import load_merged_config
from sase.xprompt.effort import is_valid_effort

from .effort_resolution import (
    EffectiveDefaultEffortSnapshot,
    build_effective_default_effort_snapshot,
    resolve_effective_effort_from_snapshot,
)

DEFAULT_MODEL_ALIAS_HISTORY_LIMIT = 10

if TYPE_CHECKING:
    from sase.xprompt.directives import PromptDirectives

    from .effort_override import TemporaryEffortOverride


def get_llm_provider_config() -> dict[str, Any]:
    """Read the ``llm_provider`` section from the merged SASE config."""
    try:
        data = load_merged_config()
        if not isinstance(data, dict):
            return {}

        config = data.get("llm_provider", {}) or {}
        if not isinstance(config, dict):
            return {}
        return config
    except Exception:
        return {}


def _get_default_effort() -> str | None:
    """Return the configured and validated default reasoning effort."""
    raw = get_llm_provider_config().get("default_effort", "")
    if not isinstance(raw, str):
        return None
    level = raw.strip().lower()
    if level and is_valid_effort(level):
        return level
    return None


def default_reasoning_effort() -> str | None:
    """Return the validated, normalized default reasoning-effort level."""
    return _get_default_effort()


def get_model_alias_history_limit() -> int:
    """Return the validated per-alias Launch Control history limit."""
    raw = get_llm_provider_config().get(
        "model_alias_history_limit",
        DEFAULT_MODEL_ALIAS_HISTORY_LIMIT,
    )
    if type(raw) is int and raw >= 1:
        return raw
    return DEFAULT_MODEL_ALIAS_HISTORY_LIMIT


def _get_temporary_default_effort(now: float) -> TemporaryEffortOverride | None:
    """Load the Rust-backed temporary effort record (test seam)."""
    from .effort_override import get_active_effort_override

    return get_active_effort_override(now)


def effective_default_effort_snapshot(
    now: float | None = None,
) -> EffectiveDefaultEffortSnapshot:
    """Capture configured and active temporary launch defaults together."""
    snapshot = build_effective_default_effort_snapshot(
        _get_default_effort(),
        None,
        now=now,
    )
    return build_effective_default_effort_snapshot(
        snapshot.configured_effort,
        _get_temporary_default_effort(snapshot.captured_at),
        now=snapshot.captured_at,
    )


def resolve_effective_effort(
    directives: PromptDirectives,
    alias_effort: str | None = None,
) -> tuple[str | None, bool]:
    """Resolve effective effort and whether it came from an explicit directive.

    Precedence:

    1. An explicit per-branch ``%effort``/``@effort`` value
       (``directives.reasoning_effort``) — returned with ``explicit=True``.
    2. A reasoning-effort suffix carried by an alias target — returned with
       ``explicit=False`` because config-derived effort is best-effort.
    3. The active machine-wide temporary default-effort override — returned
       with ``explicit=False``.
    4. The ``llm_provider.default_effort`` config value — returned with
       ``explicit=False`` (best-effort: providers silently skip levels they
       cannot honor).
    5. Nothing — ``(None, False)`` so each runtime keeps its own default.

    Centralizing the precedence here (reused by invocation and, later, the TUI
    metadata) keeps display and behavior from ever disagreeing. The ``explicit``
    flag lets the provider adapter raise on an unsupported *explicit* request
    while quietly skipping an unsupported *config-default* one.
    """
    return resolve_effective_effort_from_snapshot(
        directives,
        alias_effort,
        effective_default_effort_snapshot(),
    )


# Alias configuration and presentation metadata. Explicit same-name aliases
# mark these imports as intentional re-exports from this compatibility façade.
from .model_alias_config import (  # noqa: E402
    ModelAliasConfigSource as ModelAliasConfigSource,
    default_model_alias_name as default_model_alias_name,
    format_model_directive_value as format_model_directive_value,
    get_builtin_model_aliases as get_builtin_model_aliases,
    get_configured_model_aliases as _get_model_aliases,
    get_custom_model_aliases as get_custom_model_aliases,
    get_model_aliases_for_token as _get_model_aliases_for_token,
    get_model_aliases as get_model_aliases,
    implicit_model_alias_fallback_effort as implicit_model_alias_fallback_effort,
    implicit_model_alias_fallback_reference as implicit_model_alias_fallback_reference,
    implicit_model_alias_fallback as implicit_model_alias_fallback,
    implicit_model_alias_value as implicit_model_alias_value,
    model_alias_bucket as model_alias_bucket,
    model_alias_bucket_description as model_alias_bucket_description,
    model_alias_bucket_names as model_alias_bucket_names,
    model_alias_config_source as model_alias_config_source,
    model_alias_description as model_alias_description,
    model_alias_kind as model_alias_kind,
    model_alias_names as model_alias_names,
    role_model_alias_names as _role_model_alias_names,
    role_model_directive_value as role_model_directive_value,
    special_model_alias_names as _special_model_alias_names,
    strip_model_alias_prefix as strip_model_alias_prefix,
)
from .model_alias_policy import (  # noqa: E402
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME as BIG_EPIC_LANDER_MODEL_ALIAS_NAME,
    BUILTIN_MODEL_ALIAS_NAMES as BUILTIN_MODEL_ALIAS_NAMES,
    CHEAP_MODEL_ALIAS_NAME as CHEAP_MODEL_ALIAS_NAME,
    CHEAPER_MODEL_ALIAS_NAME as CHEAPER_MODEL_ALIAS_NAME,
    CHEAPEST_MODEL_ALIAS_NAME as CHEAPEST_MODEL_ALIAS_NAME,
    DEFAULT_MODEL_ALIAS_NAME as DEFAULT_MODEL_ALIAS_NAME,
    EPIC_LANDER_MODEL_ALIAS_NAME as EPIC_LANDER_MODEL_ALIAS_NAME,
    LARGE_MODEL_ALIAS_NAME as LARGE_MODEL_ALIAS_NAME,
    LARGE_WORKER_MODEL_ALIAS_NAME as LARGE_WORKER_MODEL_ALIAS_NAME,
    MEDIUM_MODEL_ALIAS_NAME as MEDIUM_MODEL_ALIAS_NAME,
    MEDIUM_WORKER_MODEL_ALIAS_NAME as MEDIUM_WORKER_MODEL_ALIAS_NAME,
    SMALL_MODEL_ALIAS_NAME as SMALL_MODEL_ALIAS_NAME,
    SMALL_WORKER_MODEL_ALIAS_NAME as SMALL_WORKER_MODEL_ALIAS_NAME,
    SMART_MODEL_ALIAS_NAME as SMART_MODEL_ALIAS_NAME,
    SMARTER_MODEL_ALIAS_NAME as SMARTER_MODEL_ALIAS_NAME,
    SMARTEST_MODEL_ALIAS_NAME as SMARTEST_MODEL_ALIAS_NAME,
    XLARGE_MODEL_ALIAS_NAME as XLARGE_MODEL_ALIAS_NAME,
    XLARGE_WORKER_MODEL_ALIAS_NAME as XLARGE_WORKER_MODEL_ALIAS_NAME,
    XSMALL_MODEL_ALIAS_NAME as XSMALL_MODEL_ALIAS_NAME,
    XSMALL_WORKER_MODEL_ALIAS_NAME as XSMALL_WORKER_MODEL_ALIAS_NAME,
    implicit_alias_targets as _implicit_alias_targets,
    role_alias_descriptions as _role_alias_descriptions,
    role_alias_fallbacks as _role_alias_fallbacks,
)
from .model_launch_settings import (  # noqa: E402
    BIG_EPIC_LANDER_MODEL_FIELD as BIG_EPIC_LANDER_MODEL_FIELD,
    DEFAULT_MODEL_FIELD as DEFAULT_MODEL_FIELD,
    EPIC_LANDER_MODEL_FIELD as EPIC_LANDER_MODEL_FIELD,
    LaunchModelSettingSnapshot as LaunchModelSettingSnapshot,
    build_launch_model_setting_snapshot as build_launch_model_setting_snapshot,
    get_big_epic_lander_model as get_big_epic_lander_model,
    get_default_model as get_default_model,
    get_epic_lander_model as get_epic_lander_model,
    launch_model_setting_alias as launch_model_setting_alias,
    launch_model_setting_override_key as launch_model_setting_override_key,
    launch_model_setting_override_keys as launch_model_setting_override_keys,
    resolve_default_launch_provider_model as resolve_default_launch_provider_model,
    resolve_default_launch_provider_model_with_effort as resolve_default_launch_provider_model_with_effort,
    select_epic_land_model_expression as select_epic_land_model_expression,
)
from .model_alias_resolution import (  # noqa: E402
    ModelAliasSelectorMember as ModelAliasSelectorMember,
    _ALIAS_RESOLUTION_DEPTH_LIMIT as _ALIAS_RESOLUTION_DEPTH_LIMIT,
    active_alias_overrides as _active_alias_overrides,
    model_alias_selector_details as model_alias_selector_details,
    normalize_model_alias_reference as normalize_model_alias_reference,
    provider_for_resolved_target as _provider_for_resolved_target,
    resolve_default_alias_target as _resolve_default_alias_target,
    resolve_model_alias as resolve_model_alias,
    resolve_model_alias_with_effort as resolve_model_alias_with_effort,
    resolved_target_is_available as _resolved_target_is_available,
    validate_model_alias_selector_value as validate_model_alias_selector_value,
)
