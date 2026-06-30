"""Configuration reader for the LLM provider layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.config import load_merged_config
from sase.xprompt.effort import is_valid_effort

if TYPE_CHECKING:
    from sase.xprompt.directives import PromptDirectives

_ALIAS_RESOLUTION_DEPTH_LIMIT = 16

# ---------------------------------------------------------------------------
# Model alias policy (epic sase-5d)
# ---------------------------------------------------------------------------
#
# Model indirection is configured under ``llm_provider.model_aliases``. On top
# of the user-configured map, SASE exposes a fixed set of *implicit* special
# aliases that always resolve, even when the user has not defined them:
#
#   - ``default``: the model used when a prompt has no explicit ``%model``.
#   - ``coder`` / ``<provider>_coder``: coder follow-up roles.
#   - ``epic_creator`` / ``epic_lander`` / ``phase_worker``: bead/epic roles.
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

#: Fixed implicit role aliases (besides ``default``) mapped to the alias each
#: falls back to when the user has not configured it explicitly.
_ROLE_ALIAS_FALLBACKS: dict[str, str] = {
    CODER_MODEL_ALIAS_NAME: f"@{DEFAULT_MODEL_ALIAS_NAME}",
    "epic_creator": f"@{DEFAULT_MODEL_ALIAS_NAME}",
    "epic_lander": f"@{DEFAULT_MODEL_ALIAS_NAME}",
    "phase_worker": f"@{DEFAULT_MODEL_ALIAS_NAME}",
}

# Legacy reserved aliases retained as deprecated stubs until the worker lane is
# retired (epic sase-5d phase 4) and the plan/bead emit sites stop producing
# them (phases 3-4). New configs should use the role aliases above instead.
# ``model_completion`` still surfaces these until phase 2 reworks the catalog.
RESERVED_MODEL_ALIASES: tuple[tuple[str, str], ...] = (
    ("worker", "reserved alias: current worker-lane model"),
    ("other", "reserved alias: model active before a temporary override"),
)


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


def _get_model_aliases() -> dict[str, str]:
    """Return cleaned ``llm_provider.model_aliases`` entries from config."""
    return _clean_string_mapping(get_llm_provider_config().get("model_aliases", {}))


def get_model_aliases() -> dict[str, str]:
    """Return configured model aliases usable from ``%model:<alias>``."""
    return _get_model_aliases()


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


def special_model_alias_names() -> set[str]:
    """Return every implicit (non-user-configured) model alias name.

    This is the centralized alias policy that replaces the old
    ``RESERVED_MODEL_ALIASES`` constant as the source of truth for which alias
    names always resolve: the fixed role aliases, a ``<provider>_coder`` alias
    per registered provider, and (temporarily, until epic sase-5d phases 3-4
    retire them) the legacy ``worker``/``other`` reserved aliases.
    """
    legacy = {name for name, _ in RESERVED_MODEL_ALIASES}
    return _role_model_alias_names() | _provider_coder_model_alias_names() | legacy


def model_alias_names() -> set[str]:
    """Return every name that is a user-facing model alias."""
    return set(get_model_aliases()) | special_model_alias_names()


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


def _get_configured_worker_models() -> dict[str, str]:
    """Return cleaned ``llm_provider.worker_models`` mapping entries."""
    return _clean_string_mapping(get_llm_provider_config().get("worker_models", {}))


def get_configured_worker_model_entry_for_primary(
    primary_provider: str,
    primary_model: str,
) -> tuple[str, str] | None:
    """Return ``(matched_key, configured_target)`` for an effective primary lane.

    Resolves the most specific ``worker_models`` key that matches the supplied
    primary lane — exact ``provider/model``, then bare model, then provider —
    and reports both the matched key (so callers can surface the provenance of
    a worker choice) and its configured target. Returns ``None`` when no key
    matches or the lane is incomplete.
    """
    provider = primary_provider.strip()
    model = primary_model.strip()
    if not provider or not model:
        return None

    worker_models = _get_configured_worker_models()
    for key in (f"{provider}/{model}", model, provider):
        configured = worker_models.get(key)
        if configured is not None:
            return key, configured
    return None


def _resolve_default_alias_target() -> str:
    """Return the implicit ``@default`` target as a ``provider/model`` string.

    Only reached when ``default`` is *not* user-configured (a configured
    ``model_aliases.default`` is followed by the normal alias chain in
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


def resolve_model_alias(model: str) -> str:
    """Resolve a model alias to its final target.

    Resolution follows configured ``llm_provider.model_aliases`` chains and the
    implicit special aliases (``default``, ``coder``, ``<provider>_coder``,
    ``epic_creator``, ``epic_lander``, ``phase_worker``). Alias *values* may
    reference other aliases with an ``@`` marker (e.g. ``coder: "@default"``);
    those references are followed too. A user-configured alias always shadows
    the implicit special of the same name.

    Unknown tokens return *model* unchanged. Cycles and overly deep chains fall
    back to the original input so a bad config cannot crash launches.

    The literal aliases ``"worker"`` and ``"other"`` are legacy reserved stubs
    retained until epic sase-5d phases 3-4 retire the worker lane:

    - ``"worker"`` short-circuits to the effective worker-lane model and shadows
      ``model_aliases.worker``.
    - ``"other"`` short-circuits to the ``(provider, model)`` that was the
      effective default immediately before an active temporary override was set,
      falling through to ``model_aliases.other`` when no override is active.
    """
    cleaned_model = model.strip()
    if cleaned_model == "worker":
        # Lazy import to avoid an import cycle: temporary_override imports
        # resolve_model_provider from registry, which imports this module.
        from .temporary_override import resolve_effective_worker_provider_model

        provider, worker_model = resolve_effective_worker_provider_model()
        return f"{provider}/{worker_model}"

    if cleaned_model == "other":
        # Lazy import to avoid an import cycle: temporary_override imports
        # resolve_model_provider from registry, which imports this module.
        from .temporary_override import get_active_temporary_override

        override = get_active_temporary_override()
        if (
            override is not None
            and override.pre_override_provider
            and override.pre_override_model
        ):
            return f"{override.pre_override_provider}/{override.pre_override_model}"

    aliases = _get_model_aliases()
    original = model
    current = cleaned_model
    seen: set[str] = set()
    for _ in range(_ALIAS_RESOLUTION_DEPTH_LIMIT):
        # An ``@`` marker on a value means "reference this alias by name".
        bare = current[1:].strip() if current.startswith("@") else current
        if not bare:
            return original

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
            fallback = _ROLE_ALIAS_FALLBACKS[CODER_MODEL_ALIAS_NAME]
        if fallback is not None:
            if bare in seen:
                return original
            seen.add(bare)
            current = fallback
            continue

        # A concrete model name (or a dangling ``@`` reference): terminal.
        return bare if current.startswith("@") else current
    return original
