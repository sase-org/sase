"""Configuration reader for the LLM provider layer."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from sase.config import load_merged_config
from sase.xprompt.effort import is_valid_effort

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
#   - ``epic_lander`` / ``phase_worker``: bead/epic roles.
#
# Each role falls back to another alias (ultimately ``@default``) when it is not
# explicitly configured. ``default`` itself falls back to the configured or
# autodetected provider's tier default (see :func:`_resolve_default_alias_target`
# and :func:`sase.llm_provider.registry.resolve_default_alias_provider_model`).
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

#: The implicit "phase_worker" role alias (bead phase agent default).
PHASE_WORKER_MODEL_ALIAS_NAME = "phase_worker"

#: Fixed implicit role aliases (besides ``default``) mapped to the alias each
#: falls back to when the user has not configured it explicitly.
_ROLE_ALIAS_FALLBACKS: dict[str, str] = {
    CODER_MODEL_ALIAS_NAME: f"@{DEFAULT_MODEL_ALIAS_NAME}",
    EPIC_LANDER_MODEL_ALIAS_NAME: f"@{DEFAULT_MODEL_ALIAS_NAME}",
    PHASE_WORKER_MODEL_ALIAS_NAME: f"@{DEFAULT_MODEL_ALIAS_NAME}",
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
    PHASE_WORKER_MODEL_ALIAS_NAME: (
        "Bead phase agents that implement individual plan phases."
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
) -> tuple[str | None, bool]:
    """Resolve the effective reasoning effort and whether it was explicit.

    Precedence (epic sase-55 design decisions):

    1. An explicit per-branch ``%effort``/``@effort`` value
       (``directives.reasoning_effort``) — returned with ``explicit=True``.
    2. The ``llm_provider.default_effort`` config value — returned with
       ``explicit=False`` (best-effort: providers silently skip levels they
       cannot honor).
    3. Nothing — ``(None, False)`` so each runtime keeps its own default.

    Centralizing the precedence here (reused by invocation and, later, the TUI
    metadata) keeps display and behavior from ever disagreeing. The ``explicit``
    flag lets the provider adapter raise on an unsupported *explicit* request
    while quietly skipping an unsupported *config-default* one.
    """
    explicit_effort = directives.reasoning_effort
    if explicit_effort:
        return explicit_effort, True
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


def _get_model_aliases() -> dict[str, str]:
    """Return merged configured aliases; custom aliases win collisions."""
    return get_builtin_model_aliases() | get_custom_model_aliases()


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

    For example ``role_model_directive_value("phase_worker") -> "@phase_worker"``.
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
    return {DEFAULT_MODEL_ALIAS_NAME, *_ROLE_ALIAS_FALLBACKS}


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
    ``coder``/``epic_lander``/``phase_worker``) and a
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
    if name in _ROLE_ALIAS_FALLBACKS:
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


def resolve_model_alias(
    model: str,
    model_alias_overrides: Mapping[str, str] | None = None,
) -> str:
    """Resolve a model alias to its final target.

    Resolution follows configured ``llm_provider.model_aliases.builtin`` /
    ``llm_provider.model_aliases.custom`` chains and the implicit special aliases
    (``default``, ``coder``, ``<provider>_coder``, ``epic_lander``,
    ``phase_worker``). A configured legacy ``epic_creator`` entry remains an
    ordinary compatibility alias. Alias *values* may reference other aliases
    with an ``@`` marker (e.g. ``coder: "@default"``); those references
    are followed too. A user-configured alias always shadows the implicit
    special of the same name.

    Unknown tokens return *model* unchanged. Cycles and overly deep chains fall
    back to the original input so a bad config cannot crash launches.

    A launch-family override wins at every alias hop, including ``default``.
    The generic ``coder`` launch override also shadows a provider-specific
    ``<provider>_coder`` hop unless the launch supplies that more-specific key.
    Machine-global temporary overrides are consulted next for non-``default``
    aliases. Their ``default`` override remains limited to the no-``%model``
    launch lane (see
    :func:`sase.llm_provider.temporary_override.resolve_effective_default_provider_model`).

    The literal aliases ``"worker"`` and ``"other"`` are no longer special: the
    worker lane was retired in epic sase-5d phase 4, so they resolve only when a
    user defines them as ordinary configured aliases.
    """
    from .launch_alias_overrides import active_launch_alias_overrides

    cleaned_model = model.strip()
    aliases = _get_model_aliases()
    launch_overrides = active_launch_alias_overrides(model_alias_overrides)
    original = model
    current = cleaned_model
    seen: set[str] = set()
    # Active per-alias temporary overrides, loaded lazily (and at most once) the
    # first time a non-``default`` alias token is seen, so a pure ``default``
    # resolution never touches the override state file.
    overrides: dict[str, Any] | None = None
    for _ in range(_ALIAS_RESOLUTION_DEPTH_LIMIT):
        # An ``@`` marker on a value means "reference this alias by name".
        bare = current[1:].strip() if current.startswith("@") else current
        if not bare:
            return original

        launch_target = launch_overrides.get(bare)
        if launch_target is None and _is_provider_coder_alias(bare):
            launch_target = launch_overrides.get(CODER_MODEL_ALIAS_NAME)
        if launch_target is not None:
            if bare in seen:
                return original
            seen.add(bare)
            current = launch_target
            continue

        # A temporary override on a non-``default`` alias beats the configured
        # and implicit lookups for that alias.
        if bare != DEFAULT_MODEL_ALIAS_NAME:
            if overrides is None:
                overrides = _active_alias_overrides()
            override = overrides.get(bare)
            if override is not None:
                return f"{override.provider}/{override.model}"

        if bare in aliases:
            if bare in seen:
                return original
            seen.add(bare)
            nxt = aliases[bare].strip()
            if not nxt:
                return original
            current = nxt
            continue

        # Implicit special aliases (only when not user-configured above).
        if bare == DEFAULT_MODEL_ALIAS_NAME:
            return _resolve_default_alias_target()

        fallback = _ROLE_ALIAS_FALLBACKS.get(bare)
        if fallback is None and _is_provider_coder_alias(bare):
            # An unconfigured ``<provider>_coder`` inherits the generic ``coder``
            # alias itself (not ``coder``'s own resolved fallback), so configuring
            # ``coder`` once flows through to every provider-specific coder lane.
            fallback = f"@{CODER_MODEL_ALIAS_NAME}"
        if fallback is not None:
            if bare in seen:
                return original
            seen.add(bare)
            current = fallback
            continue

        # A concrete model name (or a dangling ``@`` reference): terminal.
        return bare if current.startswith("@") else current
    return original
