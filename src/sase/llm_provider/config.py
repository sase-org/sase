"""Stable configuration façade for the LLM provider layer.

Provider defaults live here. Model-alias parsing, policy, and resolution are
implemented in focused sibling modules and re-exported here to preserve the
long-standing import and monkeypatch surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.config import load_merged_config
from sase.xprompt.effort import is_valid_effort

if TYPE_CHECKING:
    from sase.xprompt.directives import PromptDirectives


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


def resolve_effective_effort(
    directives: PromptDirectives,
    alias_effort: str | None = None,
) -> tuple[str | None, bool]:
    """Resolve effective effort and whether it came from an explicit directive.

    Precedence is explicit prompt directive, alias target suffix, configured
    default, then the provider's own default.
    """
    explicit_effort = directives.reasoning_effort
    if explicit_effort:
        return explicit_effort, True
    if alias_effort and is_valid_effort(alias_effort):
        return alias_effort, False
    default_effort = _get_default_effort()
    if default_effort:
        return default_effort, False
    return None, False


# Alias configuration and presentation metadata. Explicit same-name aliases
# mark these imports as intentional re-exports from this compatibility façade.
from .model_alias_config import (  # noqa: E402
    ModelAliasConfigSource as ModelAliasConfigSource,
    coder_model_alias_for_provider as coder_model_alias_for_provider,
    default_model_alias_name as default_model_alias_name,
    format_model_directive_value as format_model_directive_value,
    get_builtin_model_aliases as get_builtin_model_aliases,
    get_configured_model_aliases as _get_model_aliases,
    get_custom_model_aliases as get_custom_model_aliases,
    get_model_aliases_for_token as _get_model_aliases_for_token,
    get_model_aliases as get_model_aliases,
    implicit_model_alias_fallback as implicit_model_alias_fallback,
    implicit_model_alias_value as implicit_model_alias_value,
    is_provider_coder_alias as _is_provider_coder_alias,
    model_alias_bucket as model_alias_bucket,
    model_alias_bucket_description as model_alias_bucket_description,
    model_alias_bucket_names as model_alias_bucket_names,
    model_alias_config_source as model_alias_config_source,
    model_alias_description as model_alias_description,
    model_alias_kind as model_alias_kind,
    model_alias_names as model_alias_names,
    provider_coder_model_alias_names as _provider_coder_model_alias_names,
    registered_provider_names_for_aliases as _registered_provider_names,
    role_model_alias_names as _role_model_alias_names,
    role_model_directive_value as role_model_directive_value,
    special_model_alias_names as _special_model_alias_names,
    strip_model_alias_prefix as strip_model_alias_prefix,
)
from .model_alias_policy import (  # noqa: E402
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME as BIG_EPIC_LANDER_MODEL_ALIAS_NAME,
    CHEAPER_MODEL_ALIAS_DEFAULT as CHEAPER_MODEL_ALIAS_DEFAULT,
    CHEAPER_MODEL_ALIAS_NAME as CHEAPER_MODEL_ALIAS_NAME,
    CHEAPEST_MODEL_ALIAS_DEFAULT as CHEAPEST_MODEL_ALIAS_DEFAULT,
    CHEAPEST_MODEL_ALIAS_NAME as CHEAPEST_MODEL_ALIAS_NAME,
    CODER_MODEL_ALIAS_NAME as CODER_MODEL_ALIAS_NAME,
    DEFAULT_MODEL_ALIAS_NAME as DEFAULT_MODEL_ALIAS_NAME,
    EPIC_CREATOR_MODEL_ALIAS_NAME as EPIC_CREATOR_MODEL_ALIAS_NAME,
    EPIC_LANDER_MODEL_ALIAS_NAME as EPIC_LANDER_MODEL_ALIAS_NAME,
    IMPLICIT_ALIAS_TARGETS as _IMPLICIT_ALIAS_TARGETS,
    LARGE_PHASE_WORKER_MODEL_ALIAS_NAME as LARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
    LEGACY_BUILTIN_ALIAS_NAMES as _LEGACY_BUILTIN_ALIAS_NAMES,
    MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME as MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME,
    PROVIDER_CODER_ALIAS_SUFFIX as PROVIDER_CODER_ALIAS_SUFFIX,
    ROLE_ALIAS_DESCRIPTIONS as _ROLE_ALIAS_DESCRIPTIONS,
    ROLE_ALIAS_FALLBACKS as _ROLE_ALIAS_FALLBACKS,
    SMALL_PHASE_WORKER_MODEL_ALIAS_NAME as SMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
    SMARTEST_MODEL_ALIAS_DEFAULT as SMARTEST_MODEL_ALIAS_DEFAULT,
    SMARTEST_MODEL_ALIAS_NAME as SMARTEST_MODEL_ALIAS_NAME,
)
from .model_alias_resolution import (  # noqa: E402
    ModelAliasSelectorMember as ModelAliasSelectorMember,
    _ALIAS_RESOLUTION_DEPTH_LIMIT as _ALIAS_RESOLUTION_DEPTH_LIMIT,
    active_alias_overrides as _active_alias_overrides,
    model_alias_selector_details as model_alias_selector_details,
    provider_for_resolved_target as _provider_for_resolved_target,
    resolve_default_alias_target as _resolve_default_alias_target,
    resolve_model_alias as resolve_model_alias,
    resolve_model_alias_with_effort as resolve_model_alias_with_effort,
    resolved_target_is_available as _resolved_target_is_available,
    validate_model_alias_selector_value as validate_model_alias_selector_value,
)
