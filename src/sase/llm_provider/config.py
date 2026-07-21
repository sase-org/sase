"""Configuration reader for the LLM provider layer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal

from sase.config import load_merged_config
from sase.config.core import current_config_token
from sase.xprompt.effort import is_valid_effort, split_model_effort

from .load_balancing import (
    ModelAliasSelector,
    ModelAliasSelectorError,
    ModelAliasSelectorMode,
    parse_model_alias_selector,
    select_model_alias_fallback_member,
    select_model_alias_pool_member,
)

if TYPE_CHECKING:
    from sase.xprompt.directives import PromptDirectives

_ALIAS_RESOLUTION_DEPTH_LIMIT = 16

ModelAliasConfigSource = Literal["builtin", "custom"]

# ---------------------------------------------------------------------------
# Model alias policy (epic sase-5d)
# ---------------------------------------------------------------------------
#
# Builtin-role overrides are configured under
# ``llm_provider.model_aliases.builtin``; user-created aliases live under
# ``llm_provider.model_aliases.custom`` so they can carry required descriptions.
# On top of the configured maps, SASE exposes a fixed set of *implicit* special
# aliases that always resolve, even when the user has not defined them:
#
#   - ``default``: the model used when a prompt has no explicit ``%model``.
#   - ``coder`` / ``<provider>_coder``: coder follow-up roles.
#   - ``epic_lander`` / ``big_epic_lander`` /
#     ``<size>_phase_worker`` / ``smartest`` / ``cheaper`` / ``cheapest``:
#     bead/epic roles.
#
# Most roles fall back to another alias (ultimately ``@default``) when they are
# not explicitly configured. ``smartest`` instead owns an ordered provider
# fallback. ``default`` itself falls back to the configured or autodetected
# provider's tier default (see :func:`_resolve_default_alias_target` and
# :func:`sase.llm_provider.registry.resolve_default_alias_provider_model`).
#
# Alias *values* may reference other aliases with an ``@`` marker (for example
# ``coder: "@default"`` or ``codex_coder: "@coder"``); :func:`resolve_model_alias`
# follows those references with cycle/depth protection.

#: The implicit "default" alias name (used for no-``%model`` launches).
DEFAULT_MODEL_ALIAS_NAME = "default"

#: The implicit "coder" alias name (``<provider>_coder`` falls back to this).
CODER_MODEL_ALIAS_NAME = "coder"

#: Suffix that turns a provider name into its ``<provider>_coder`` alias.
PROVIDER_CODER_ALIAS_SUFFIX = "_coder"

#: Legacy epic-creator alias name. It is no longer implicit or used by SASE,
#: but configured builtin entries remain accepted for compatibility.
EPIC_CREATOR_MODEL_ALIAS_NAME = "epic_creator"

#: The implicit "epic_lander" role alias (epic land follow-up default).
EPIC_LANDER_MODEL_ALIAS_NAME = "epic_lander"

#: The implicit large-epic lander role alias (threshold-selected follow-up).
BIG_EPIC_LANDER_MODEL_ALIAS_NAME = "big_epic_lander"

#: The implicit small-phase role alias.
SMALL_PHASE_WORKER_MODEL_ALIAS_NAME = "small_phase_worker"

#: The implicit medium-phase role alias.
MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME = "medium_phase_worker"

#: The implicit large-phase role alias.
LARGE_PHASE_WORKER_MODEL_ALIAS_NAME = "large_phase_worker"

#: The implicit "smartest" highest-capability alias.
SMARTEST_MODEL_ALIAS_NAME = "smartest"

#: Provider-aware ordered fallback for the implicit smartest alias.
SMARTEST_MODEL_ALIAS_DEFAULT = "claude/claude-fable-5 || codex/gpt-5.6-sol"

#: The implicit load-balanced small-phase alias.
CHEAPER_MODEL_ALIAS_NAME = "cheaper"

#: Default target pool for the implicit :data:`CHEAPER_MODEL_ALIAS_NAME`.
CHEAPER_MODEL_ALIAS_DEFAULT = "claude/opus@medium | codex/gpt-5.5"

#: The implicit load-balanced cheapest-agent alias.
CHEAPEST_MODEL_ALIAS_NAME = "cheapest"

#: Default target pool for the implicit :data:`CHEAPEST_MODEL_ALIAS_NAME`.
CHEAPEST_MODEL_ALIAS_DEFAULT = "claude/sonnet | codex/gpt-5.3-codex-spark"

#: Fixed implicit role aliases (besides ``default``) mapped to the alias each
#: falls back to when the user has not configured it explicitly.
_ROLE_ALIAS_FALLBACKS: dict[str, str] = {
    CODER_MODEL_ALIAS_NAME: f"@{DEFAULT_MODEL_ALIAS_NAME}",
    EPIC_LANDER_MODEL_ALIAS_NAME: f"@{DEFAULT_MODEL_ALIAS_NAME}",
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME: f"@{EPIC_LANDER_MODEL_ALIAS_NAME}",
    SMALL_PHASE_WORKER_MODEL_ALIAS_NAME: f"@{CHEAPER_MODEL_ALIAS_NAME}",
    MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME: f"@{DEFAULT_MODEL_ALIAS_NAME}",
    LARGE_PHASE_WORKER_MODEL_ALIAS_NAME: f"@{SMARTEST_MODEL_ALIAS_NAME}",
}

_IMPLICIT_ALIAS_TARGETS: dict[str, str] = {
    SMARTEST_MODEL_ALIAS_NAME: SMARTEST_MODEL_ALIAS_DEFAULT,
    CHEAPER_MODEL_ALIAS_NAME: CHEAPER_MODEL_ALIAS_DEFAULT,
    CHEAPEST_MODEL_ALIAS_NAME: CHEAPEST_MODEL_ALIAS_DEFAULT,
}

_LEGACY_BUILTIN_ALIAS_NAMES = {EPIC_CREATOR_MODEL_ALIAS_NAME}

_ROLE_ALIAS_DESCRIPTIONS: dict[str, str] = {
    DEFAULT_MODEL_ALIAS_NAME: (
        "Model used when a prompt has no %model directive; every other alias "
        "ultimately falls back to it."
    ),
    CODER_MODEL_ALIAS_NAME: (
        "Coder follow-up agents launched from plans (fallback for every "
        "<provider>_coder alias)."
    ),
    EPIC_LANDER_MODEL_ALIAS_NAME: (
        "Epic land agents that finalize and submit an epic."
    ),
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME: (
        "Epic land agents selected for plans at or above the configured "
        "phase-count threshold."
    ),
    SMALL_PHASE_WORKER_MODEL_ALIAS_NAME: (
        "Small bead phase agents that implement directly."
    ),
    MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME: (
        "Medium bead phase agents that plan before implementation."
    ),
    LARGE_PHASE_WORKER_MODEL_ALIAS_NAME: (
        "Large bead phase agents that plan before implementation."
    ),
    SMARTEST_MODEL_ALIAS_NAME: (
        "Highest-capability model used automatically by large phase agents."
    ),
    CHEAPER_MODEL_ALIAS_NAME: (
        "Load-balanced pool used automatically by small phase agents."
    ),
    CHEAPEST_MODEL_ALIAS_NAME: (
        "Lowest-cost load-balanced pool available for explicit use."
    ),
}


def get_llm_provider_config() -> dict[str, Any]:
    """Read the ``llm_provider`` section from ``sase.yml``.

    Looks for ``~/.config/sase/sase.yml`` and returns the ``llm_provider``
    section, or an empty dict if not found.

    Returns:
        The llm_provider configuration dict.
    """
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
    """Return the configured ``llm_provider.default_effort`` level, or ``None``.

    Reads the layered ``llm_provider.default_effort`` value, normalizes it
    (strip + lowercase), and validates it against the canonical effort
    vocabulary shared with the xprompt directive parser
    (:func:`sase.xprompt.effort.is_valid_effort`, the single source of truth).
    Returns ``None`` when the value is unset, blank, non-string, or not a
    recognized effort level, so a malformed config never forces an effort onto
    agent launches.
    """
    raw = get_llm_provider_config().get("default_effort", "")
    if not isinstance(raw, str):
        return None
    level = raw.strip().lower()
    if level and is_valid_effort(level):
        return level
    return None


def resolve_effective_effort(
    directives: PromptDirectives,
    alias_effort: str | None = None,
) -> tuple[str | None, bool]:
    """Resolve the effective reasoning effort and whether it was explicit.

    Precedence (epic sase-55 design decisions):

    1. An explicit per-branch ``%effort``/``@effort`` value
       (``directives.reasoning_effort``) — returned with ``explicit=True``.
    2. A reasoning-effort suffix carried by an alias target — returned with
       ``explicit=False`` because config-derived effort is best-effort.
    3. The ``llm_provider.default_effort`` config value — returned with
       ``explicit=False`` (best-effort: providers silently skip levels they
       cannot honor).
    4. Nothing — ``(None, False)`` so each runtime keeps its own default.

    Centralizing the precedence here (reused by invocation and, later, the TUI
    metadata) keeps display and behavior from ever disagreeing. The ``explicit``
    flag lets the provider adapter raise on an unsupported *explicit* request
    while quietly skipping an unsupported *config-default* one.
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


def _raw_model_aliases_config() -> dict[str, Any]:
    """Return the nested ``llm_provider.model_aliases`` object, or ``{}``."""
    value = get_llm_provider_config().get("model_aliases", {})
    return value if isinstance(value, dict) else {}


def get_builtin_model_aliases() -> dict[str, str]:
    """Return cleaned ``llm_provider.model_aliases.builtin`` entries."""
    return _clean_string_mapping(_raw_model_aliases_config().get("builtin", {}))


def get_custom_model_aliases() -> dict[str, str]:
    """Return cleaned ``llm_provider.model_aliases.custom`` entries.

    Values in the custom-alias map are objects. Runtime parsing is deliberately
    defensive: non-object entries and entries with missing/blank ``model`` are
    skipped so malformed config cannot crash alias resolution. Missing
    descriptions are reported by schema validation/doctor and simply produce no
    runtime description.
    """
    value = _raw_model_aliases_config().get("custom", {})
    if not isinstance(value, dict):
        return {}

    cleaned: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, dict):
            continue
        alias = key.strip()
        model = item.get("model")
        if not isinstance(model, str):
            continue
        target = model.strip()
        if alias and target:
            cleaned[alias] = target
    return cleaned


def _custom_model_alias_descriptions() -> dict[str, str]:
    """Return configured descriptions for custom aliases that have one."""
    value = _raw_model_aliases_config().get("custom", {})
    if not isinstance(value, dict):
        return {}

    descriptions: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, dict):
            continue
        alias = key.strip()
        description = item.get("description")
        if not isinstance(description, str):
            continue
        text = description.strip()
        if alias and text:
            descriptions[alias] = text
    return descriptions


def _custom_model_alias_buckets() -> dict[str, str]:
    """Return custom alias-to-bucket membership from configured ``bucket`` tags."""
    value = _raw_model_aliases_config().get("custom", {})
    if not isinstance(value, dict):
        return {}

    buckets: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, dict):
            continue
        alias = key.strip()
        bucket = item.get("bucket")
        if not isinstance(bucket, str):
            continue
        bucket_name = bucket.strip()
        if alias and bucket_name:
            buckets[alias] = bucket_name
    return buckets


def model_alias_bucket(name: str) -> str | None:
    """Return the Models-panel bucket for custom alias *name*, if configured."""
    alias = name.strip()
    if not alias:
        return None
    return _custom_model_alias_buckets().get(alias)


def model_alias_bucket_description(bucket: str) -> str | None:
    """Return the optional human description for Models-panel *bucket*."""
    bucket_name = bucket.strip()
    if not bucket_name:
        return None
    value = _raw_model_aliases_config().get("buckets", {})
    if not isinstance(value, dict):
        return None
    metadata = value.get(bucket_name)
    if not isinstance(metadata, dict):
        return None
    description = metadata.get("description")
    if not isinstance(description, str):
        return None
    text = description.strip()
    return text or None


def model_alias_bucket_names() -> set[str]:
    """Return bucket names referenced by at least one custom alias."""
    return set(_custom_model_alias_buckets().values())


@lru_cache(maxsize=1)
def _get_model_aliases_for_token(_token: tuple[Any, ...]) -> dict[str, str]:
    """Return configured aliases for one merged-config freshness token."""
    return get_builtin_model_aliases() | get_custom_model_aliases()


def _get_model_aliases() -> dict[str, str]:
    """Return merged configured aliases; custom aliases win collisions."""
    return _get_model_aliases_for_token(current_config_token())


def get_model_aliases() -> dict[str, str]:
    """Return configured model aliases usable from ``%model:<alias>``."""
    return _get_model_aliases()


def model_alias_config_source(name: str) -> ModelAliasConfigSource | None:
    """Return where *name* is configured, or ``None`` when it is implicit.

    When the builtin and custom maps both define the name, the custom map is the
    effective source because it wins during merge.
    """
    alias = name.strip()
    if not alias:
        return None
    if alias in get_custom_model_aliases():
        return "custom"
    if alias in get_builtin_model_aliases():
        return "builtin"
    return None


def default_model_alias_name() -> str:
    """Return the implicit "default" model alias name."""
    return DEFAULT_MODEL_ALIAS_NAME


def coder_model_alias_for_provider(provider: str) -> str:
    """Return the ``<provider>_coder`` model alias name for *provider*."""
    return f"{provider.strip()}{PROVIDER_CODER_ALIAS_SUFFIX}"


def role_model_directive_value(role: str) -> str:
    """Return the ``%model`` directive value (``@<role>``) for a role alias.

    For example ``role_model_directive_value("small_phase_worker") ->
    "@small_phase_worker"``.
    """
    return f"@{role}"


def _registered_provider_names() -> list[str]:
    """Return registered LLM provider names, or ``[]`` if discovery fails.

    Looked up lazily to avoid an import cycle: :mod:`registry` imports this
    module at import time, so this module must not import it at module scope.
    """
    try:
        from .registry import registered_provider_names

        return registered_provider_names()
    except Exception:
        return []


def _active_alias_overrides() -> dict[str, Any]:
    """Return active per-alias temporary overrides, keyed by alias name.

    Looked up lazily to avoid an import cycle: :mod:`temporary_override` imports
    the registry, which imports this module. Any failure (missing/locked/corrupt
    state file) falls back to *no overrides* so a bad override file can never
    crash alias resolution.
    """
    try:
        from .temporary_override import get_active_alias_overrides

        return get_active_alias_overrides()
    except Exception:
        return {}


def _is_provider_coder_alias(name: str) -> bool:
    """Return ``True`` if *name* is a ``<provider>_coder`` alias for a provider."""
    if not name.endswith(PROVIDER_CODER_ALIAS_SUFFIX):
        return False
    provider = name[: -len(PROVIDER_CODER_ALIAS_SUFFIX)]
    return bool(provider) and provider in _registered_provider_names()


def _role_model_alias_names() -> set[str]:
    """Return the fixed implicit role aliases (``default`` plus role aliases)."""
    return {
        DEFAULT_MODEL_ALIAS_NAME,
        *_ROLE_ALIAS_FALLBACKS,
        *_IMPLICIT_ALIAS_TARGETS,
    }


def _provider_coder_model_alias_names() -> set[str]:
    """Return a ``<provider>_coder`` alias for every registered provider."""
    return {
        coder_model_alias_for_provider(provider)
        for provider in _registered_provider_names()
    }


def _special_model_alias_names() -> set[str]:
    """Return every implicit (non-user-configured) model alias name.

    This is the centralized alias policy that is the source of truth for which
    alias names always resolve: the fixed role aliases (``default`` plus
    ``coder``/``epic_lander``/``big_epic_lander``/
    ``<size>_phase_worker``/``smartest``/``cheaper``/``cheapest``) and a
    ``<provider>_coder`` alias per registered provider. The legacy
    ``worker``/``other`` reserved aliases were retired with the worker lane
    (epic sase-5d phase 4); they only resolve now if a user defines them as
    ordinary configured aliases.
    """
    return _role_model_alias_names() | _provider_coder_model_alias_names()


def model_alias_names() -> set[str]:
    """Return every name that is a user-facing model alias."""
    return set(get_model_aliases()) | _special_model_alias_names()


def model_alias_kind(name: str) -> str:
    """Classify *name* into its display kind.

    Returns one of ``"default"``, ``"role"``, ``"provider_coder"``, or
    ``"user"``. ``default`` and the fixed role aliases keep their semantic kind
    even when a user has configured them explicitly (provenance is tracked
    separately). This is the public entry point behind the Models-panel
    aggregation (:func:`sase.llm_provider.alias_view.build_alias_views`).
    """
    if name == DEFAULT_MODEL_ALIAS_NAME:
        return "default"
    if name in _ROLE_ALIAS_FALLBACKS or name in _IMPLICIT_ALIAS_TARGETS:
        return "role"
    if name in _LEGACY_BUILTIN_ALIAS_NAMES and name in get_builtin_model_aliases():
        return "role"
    if _is_provider_coder_alias(name):
        return "provider_coder"
    return "user"


def model_alias_description(name: str) -> str | None:
    """Return the display description for a model alias, if one is known."""
    alias = name.strip()
    if not alias:
        return None
    if alias in _ROLE_ALIAS_DESCRIPTIONS:
        return _ROLE_ALIAS_DESCRIPTIONS[alias]
    if alias in _LEGACY_BUILTIN_ALIAS_NAMES and alias in get_builtin_model_aliases():
        return "Legacy compatibility alias; SASE no longer launches this role."
    if _is_provider_coder_alias(alias):
        provider = alias[: -len(PROVIDER_CODER_ALIAS_SUFFIX)]
        return f"Coder follow-up agents for plans authored by {provider}."
    return _custom_model_alias_descriptions().get(alias)


def strip_model_alias_prefix(value: str) -> str:
    """Strip the surface ``@`` marker from a model alias token, if present."""
    if value.startswith("@"):
        return value[1:]
    return value


def implicit_model_alias_fallback(name: str) -> str | None:
    """Return the immediate implicit fallback alias for *name*, if any."""
    alias = name.strip()
    fallback = _ROLE_ALIAS_FALLBACKS.get(alias)
    if fallback is None and _is_provider_coder_alias(alias):
        fallback = f"@{CODER_MODEL_ALIAS_NAME}"
    return strip_model_alias_prefix(fallback) if fallback is not None else None


def implicit_model_alias_value(name: str) -> str | None:
    """Return a concrete/selector implicit target value for *name*, if any."""
    return _IMPLICIT_ALIAS_TARGETS.get(name.strip())


def format_model_directive_value(value: str) -> str:
    """Return *value* formatted for a user-facing ``%model`` directive."""
    bare_value = strip_model_alias_prefix(value)
    if bare_value in model_alias_names():
        return f"@{bare_value}"
    return value


def _clean_string_mapping(value: Any) -> dict[str, str]:
    """Return stripped string-to-string entries from a config mapping."""
    if not isinstance(value, dict):
        return {}

    cleaned: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            continue
        alias = key.strip()
        target = item.strip()
        if alias and target:
            cleaned[alias] = target
    return cleaned


def _resolve_default_alias_target() -> str:
    """Return the implicit ``@default`` target as a ``provider/model`` string.

    Only reached when ``default`` is *not* user-configured (a configured
    ``model_aliases.builtin.default`` is followed by the normal alias chain in
    :func:`resolve_model_alias`). Resolves to the configured or autodetected
    provider's large-tier default. Temporary overrides are intentionally *not*
    consulted: an explicit ``@default`` reference means "the configured default",
    while the no-``%model`` launch path applies an active override separately
    (see :func:`sase.llm_provider.temporary_override.resolve_effective_default_provider_model`).
    Failures fall back to the bare alias name so a bad config never crashes a
    launch.
    """
    try:
        # Lazy import to avoid an import cycle: registry imports this module.
        from .registry import get_configured_default_provider_name, get_provider

        provider_name = get_configured_default_provider_name()
        model = get_provider(provider_name).resolve_model_name("large")
        return f"{provider_name}/{model}"
    except Exception:
        return DEFAULT_MODEL_ALIAS_NAME


@dataclass(frozen=True, slots=True)
class _ResolvedModelAlias:
    """Concrete target plus config-derived effort and selector provenance."""

    target: str
    effort: str | None = None
    selector_alias: str | None = None
    valid: bool = True


@dataclass(frozen=True, slots=True)
class ModelAliasSelectorMember:
    """Display/diagnostic information for one alias-selector member."""

    value: str
    target: str
    effort: str | None
    provider: str | None
    available: bool
    valid: bool = True
    selected: bool = False


@dataclass(frozen=True, slots=True)
class _ModelAliasSelectorDetails:
    """Selector mode and resolved member metadata for one alias."""

    mode: ModelAliasSelectorMode
    members: tuple[ModelAliasSelectorMember, ...]


def _provider_for_resolved_target(target: str) -> str | None:
    """Return the explicit or metadata-inferred provider for *target*."""
    from .registry import model_to_provider_map, registered_provider_names

    if "/" in target:
        provider, _ = target.split("/", 1)
        return provider if provider else None
    inferred_provider = model_to_provider_map().get(target)
    return (
        inferred_provider if inferred_provider in registered_provider_names() else None
    )


def _resolved_target_is_available(target: str) -> bool:
    """Return whether *target* resolves to a registered, installed provider."""
    from .registry import provider_cli_available, registered_provider_names

    provider = _provider_for_resolved_target(target)
    if provider is None or provider not in registered_provider_names():
        return False
    return provider_cli_available(provider)


def _resolve_model_alias_result(
    model: str,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    initial_seen: set[str] | None = None,
    active_selector: str | None = None,
) -> _ResolvedModelAlias:
    """Internal alias resolver retaining effort and selector provenance."""
    from .launch_alias_overrides import active_launch_alias_overrides

    aliases = _get_model_aliases()
    launch_overrides = active_launch_alias_overrides(model_alias_overrides)
    original = model
    # Loaded lazily and shared by recursive member resolutions.
    overrides: dict[str, Any] | None = None

    def fail() -> _ResolvedModelAlias:
        return _ResolvedModelAlias(original, valid=False)

    def resolve(
        value: str,
        *,
        seen: set[str],
        steps: int,
        selector_owner: str | None,
        inherited_effort: str | None,
    ) -> _ResolvedModelAlias:
        nonlocal overrides
        current = value.strip()
        effort = inherited_effort
        while steps < _ALIAS_RESOLUTION_DEPTH_LIMIT:
            current, current_effort = split_model_effort(current.strip())
            if effort is None:
                effort = current_effort
            bare = current[1:].strip() if current.startswith("@") else current
            if not bare:
                return fail()

            is_provider_coder = _is_provider_coder_alias(bare)
            known_alias = (
                bare in aliases
                or bare == DEFAULT_MODEL_ALIAS_NAME
                or bare in _ROLE_ALIAS_FALLBACKS
                or bare in _IMPLICIT_ALIAS_TARGETS
                or is_provider_coder
            )
            launch_target = launch_overrides.get(bare) if known_alias else None
            if launch_target is None and is_provider_coder:
                launch_target = launch_overrides.get(CODER_MODEL_ALIAS_NAME)
            if launch_target is not None:
                if bare in seen:
                    return fail()
                seen.add(bare)
                current = launch_target
                steps += 1
                continue

            # A temporary override suspends selector behavior for that alias.
            if known_alias and bare != DEFAULT_MODEL_ALIAS_NAME:
                if overrides is None:
                    overrides = _active_alias_overrides()
                override = overrides.get(bare)
                if override is not None:
                    return _ResolvedModelAlias(
                        f"{override.provider}/{override.model}",
                        effort,
                        selector_owner,
                    )

            target: str | None = None
            if bare in aliases:
                target = aliases[bare].strip()
            elif bare in _IMPLICIT_ALIAS_TARGETS:
                target = _IMPLICIT_ALIAS_TARGETS[bare]

            if target is not None:
                if bare in seen or not target:
                    return fail()
                seen.add(bare)
                try:
                    selector = parse_model_alias_selector(target)
                except ModelAliasSelectorError:
                    return fail()
                if selector is not None:
                    # A selector reached from a member of another selector is
                    # invalid, matching cycle/depth fail-closed behavior.
                    if selector_owner is not None:
                        return fail()
                    member_results = [
                        resolve(
                            member,
                            seen=set(seen),
                            steps=steps + 1,
                            selector_owner=bare,
                            inherited_effort=effort,
                        )
                        for member in selector.members
                    ]
                    if any(not result.valid for result in member_results):
                        return fail()
                    availability = [
                        _resolved_target_is_available(result.target)
                        for result in member_results
                    ]
                    if selector.mode == "round_robin":
                        index = select_model_alias_pool_member(
                            bare, selector, availability, consume=consume
                        )
                    else:
                        index = select_model_alias_fallback_member(availability)
                    return member_results[index]
                current = target
                steps += 1
                continue

            if bare == DEFAULT_MODEL_ALIAS_NAME:
                target, target_effort = split_model_effort(
                    _resolve_default_alias_target()
                )
                return _ResolvedModelAlias(
                    target,
                    effort or target_effort,
                    selector_owner,
                )

            fallback = implicit_model_alias_fallback(bare)
            if fallback is not None:
                if bare in seen:
                    return fail()
                seen.add(bare)
                current = f"@{fallback}"
                steps += 1
                continue

            # A concrete model name (or dangling alias reference) is terminal.
            return _ResolvedModelAlias(
                bare if current.startswith("@") else current,
                effort,
                selector_owner,
            )
        return fail()

    return resolve(
        model,
        seen=set() if initial_seen is None else set(initial_seen),
        steps=0,
        selector_owner=active_selector,
        inherited_effort=None,
    )


def resolve_model_alias_with_effort(
    model: str,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
) -> _ResolvedModelAlias:
    """Resolve *model*, retaining alias-borne effort and selector provenance.

    ``consume=False`` is the safe default for display, completion, doctor, and
    preview callers.  Authoritative launch lanes pass ``consume=True`` so each
    launched agent advances a round-robin cursor exactly once. Ordered
    fallbacks never consume state.
    """
    return _resolve_model_alias_result(
        model,
        model_alias_overrides,
        consume=consume,
    )


def resolve_model_alias(
    model: str,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
) -> str:
    """Resolve a model alias to its concrete target string.

    Configured alias values may be ``|``-separated round-robin pools or
    ``||``-separated ordered fallback chains. Both skip unavailable providers;
    round-robin pools peek by default and launch callers opt into cursor
    advancement with ``consume=True``, while fallbacks are always stateless.
    Known trailing ``@<effort>`` suffixes are removed from alias-resolved
    targets and exposed by
    :func:`resolve_model_alias_with_effort`.

    Launch-scoped overrides win first, followed by machine-global temporary
    overrides, configured aliases, and implicit role fallbacks. Selectors are
    recognized only in configured/implicit alias values, never in directive or
    temporary override values. Cycles, nested selectors, malformed selectors,
    and overly deep chains fail closed to the original input.
    """
    return resolve_model_alias_with_effort(
        model,
        model_alias_overrides,
        consume=consume,
    ).target


def _model_alias_selector(name: str) -> ModelAliasSelector | None:
    """Return the configured/implicit selector owned by alias *name*, if any."""
    alias = name.strip()
    value = _get_model_aliases().get(alias)
    if value is None:
        value = _IMPLICIT_ALIAS_TARGETS.get(alias)
    if value is None:
        return None
    try:
        return parse_model_alias_selector(value)
    except ModelAliasSelectorError:
        return None


def model_alias_selector_details(name: str) -> _ModelAliasSelectorDetails | None:
    """Return selector mode and resolved member details for alias *name*."""
    alias = name.strip()
    selector = _model_alias_selector(alias)
    if selector is None:
        return None
    resolved: list[tuple[str, _ResolvedModelAlias, str | None, bool]] = []
    for value in selector.members:
        result = _resolve_model_alias_result(
            value,
            initial_seen={alias},
            active_selector=alias,
        )
        provider = (
            _provider_for_resolved_target(result.target) if result.valid else None
        )
        available = result.valid and _resolved_target_is_available(result.target)
        resolved.append((value, result, provider, available))

    availability = [item[3] for item in resolved]
    if selector.mode == "round_robin":
        selected_index = select_model_alias_pool_member(
            alias, selector, availability, consume=False
        )
    else:
        selected_index = select_model_alias_fallback_member(availability)

    members: list[ModelAliasSelectorMember] = []
    for index, (value, result, provider, available) in enumerate(resolved):
        members.append(
            ModelAliasSelectorMember(
                value=value,
                target=result.target,
                effort=result.effort,
                provider=provider,
                available=available,
                valid=result.valid,
                selected=index == selected_index,
            )
        )
    return _ModelAliasSelectorDetails(mode=selector.mode, members=tuple(members))


def validate_model_alias_selector_value(name: str, value: str) -> tuple[str, ...]:
    """Return actionable validation errors for an alias selector value."""
    try:
        selector = parse_model_alias_selector(value)
    except ModelAliasSelectorError as exc:
        return (str(exc),)
    if selector is None:
        return ()

    aliases = _get_model_aliases()
    errors: list[str] = []
    owner = name.strip() or "<alias>"
    member_label = (
        "pool member" if selector.mode == "round_robin" else "fallback candidate"
    )
    for position, member in enumerate(selector.members, start=1):
        current, _ = split_model_effort(member)
        seen = {owner}
        for _ in range(_ALIAS_RESOLUTION_DEPTH_LIMIT):
            if not current.startswith("@"):
                if not current.strip():
                    errors.append(
                        f"{member_label} {position} resolves to an empty target"
                    )
                break
            referenced = current[1:].strip()
            referenced, _ = split_model_effort(referenced)
            if not referenced:
                errors.append(f"{member_label} {position} has an empty alias reference")
                break
            if referenced in seen:
                errors.append(
                    f"{member_label} {position} creates an alias cycle through "
                    f"'@{referenced}'"
                )
                break
            seen.add(referenced)
            target = aliases.get(referenced)
            if target is None:
                target = _IMPLICIT_ALIAS_TARGETS.get(referenced)
            if target is None:
                fallback = implicit_model_alias_fallback(referenced)
                target = f"@{fallback}" if fallback is not None else None
            if target is None:
                errors.append(
                    f"{member_label} {position} references unknown alias "
                    f"'@{referenced}'"
                )
                break
            try:
                nested = parse_model_alias_selector(target)
            except ModelAliasSelectorError as exc:
                errors.append(
                    f"{member_label} {position} reaches malformed alias "
                    f"'@{referenced}': {exc}"
                )
                break
            if nested is not None:
                nested_name = (
                    "load-balanced pool"
                    if nested.mode == "round_robin"
                    else "ordered fallback"
                )
                errors.append(
                    f"{member_label} {position} reaches nested {nested_name} "
                    f"'@{referenced}'; selector members must resolve to a single "
                    "target"
                )
                break
            current, _ = split_model_effort(target.strip())
        else:
            errors.append(
                f"{member_label} {position} exceeds the alias resolution depth limit"
            )
    return tuple(dict.fromkeys(errors))
