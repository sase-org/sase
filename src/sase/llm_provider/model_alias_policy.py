"""Names, defaults, and descriptions for built-in model aliases.

Shipped defaults (targets, role fallbacks, provider-coder targets, and
descriptions) live in the bundled ``model_alias_defaults.yml`` sibling file,
not in this module. Editing that YAML is the single change needed to alter what
an implicit alias resolves to out of the box; this module only owns the alias
*name* constants and the loader that turns the YAML into cached accessor
mappings.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import functools
from importlib.resources import files
from types import MappingProxyType

import yaml  # type: ignore[import-untyped]

# Builtin-role overrides are configured under
# ``llm_provider.model_aliases.builtin``; user-created aliases live under
# ``llm_provider.model_aliases.custom`` so they can carry required descriptions.
# On top of the configured maps, SASE exposes a fixed set of *implicit* special
# aliases that always resolve, even when the user has not defined them:
#
#   - ``default``: the model used when a prompt has no explicit ``%model``.
#   - ``coder`` / ``<provider>_coder``: coder follow-up roles.
#   - ``epic_lander`` / ``big_epic_lander`` /
#     ``<size>_phase_worker`` / ``smart`` / ``smartest`` /
#     ``cheap`` / ``cheaper`` / ``cheapest``: bead/epic roles.
#
# Most roles fall back to another alias (ultimately ``@default``) when they are
# not explicitly configured. A fallback reference may carry an effort overlay,
# such as ``@default@high``; an outer effort still wins. Selected
# ``<provider>_coder`` aliases own direct shipped targets, while unpinned
# providers inherit ``@coder``. ``smartest`` owns an independent concrete
# maximum-effort target, while ``cheap``, ``cheaper``, and ``cheapest`` own
# load-balanced pools. ``default`` itself falls back to the configured or
# autodetected provider's tier default. See ``model_alias_defaults.yml`` for
# the current value of every default.

#: The implicit "default" alias name (used for no-``%model`` launches).
DEFAULT_MODEL_ALIAS_NAME = "default"

#: The implicit "coder" alias name (unpinned ``<provider>_coder`` aliases use it).
CODER_MODEL_ALIAS_NAME = "coder"

#: Suffix that turns a provider name into its ``<provider>_coder`` alias.
PROVIDER_CODER_ALIAS_SUFFIX = "_coder"

#: The implicit "epic_lander" role alias (epic land follow-up default).
EPIC_LANDER_MODEL_ALIAS_NAME = "epic_lander"

#: The implicit large-epic lander role alias (threshold-selected follow-up).
BIG_EPIC_LANDER_MODEL_ALIAS_NAME = "big_epic_lander"

#: The implicit extra-small-phase role alias.
XSMALL_PHASE_WORKER_MODEL_ALIAS_NAME = "xsmall_phase_worker"

#: The implicit small-phase role alias.
SMALL_PHASE_WORKER_MODEL_ALIAS_NAME = "small_phase_worker"

#: The implicit medium-phase role alias.
MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME = "medium_phase_worker"

#: The implicit large-phase role alias.
LARGE_PHASE_WORKER_MODEL_ALIAS_NAME = "large_phase_worker"

#: The implicit extra-large-phase role alias.
XLARGE_PHASE_WORKER_MODEL_ALIAS_NAME = "xlarge_phase_worker"

#: The implicit "smart" high-capability alias.
SMART_MODEL_ALIAS_NAME = "smart"

#: The implicit "smartest" highest-capability alias.
SMARTEST_MODEL_ALIAS_NAME = "smartest"

#: The implicit load-balanced small-phase alias.
CHEAP_MODEL_ALIAS_NAME = "cheap"

#: The implicit load-balanced extra-small-phase alias.
CHEAPER_MODEL_ALIAS_NAME = "cheaper"

#: The implicit lowest-cost alias.
CHEAPEST_MODEL_ALIAS_NAME = "cheapest"

#: Every implicit role-alias name declared by this module, in YAML-entry order.
_ROLE_ALIAS_NAME_CONSTANTS: tuple[str, ...] = (
    DEFAULT_MODEL_ALIAS_NAME,
    CODER_MODEL_ALIAS_NAME,
    EPIC_LANDER_MODEL_ALIAS_NAME,
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME,
    XSMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
    SMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
    MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME,
    LARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
    XLARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
    SMART_MODEL_ALIAS_NAME,
    SMARTEST_MODEL_ALIAS_NAME,
    CHEAP_MODEL_ALIAS_NAME,
    CHEAPER_MODEL_ALIAS_NAME,
    CHEAPEST_MODEL_ALIAS_NAME,
)

_DEFAULTS_RESOURCE_NAME = "model_alias_defaults.yml"


@dataclass(frozen=True, slots=True)
class _ModelAliasDefaults:
    """Cached, immutable views over the bundled defaults YAML."""

    role_alias_fallbacks: Mapping[str, str]
    implicit_alias_targets: Mapping[str, str]
    provider_coder_targets: Mapping[str, str]
    role_alias_descriptions: Mapping[str, str]


def _defaults_error(resource: object, problem: str) -> RuntimeError:
    return RuntimeError(
        f"bundled model alias defaults ({resource}) {problem}; this is a SASE "
        "installation defect"
    )


@functools.cache
def _load_model_alias_defaults() -> _ModelAliasDefaults:
    """Load and validate the bundled model-alias defaults YAML.

    A missing or malformed file ships with the package, so it is an
    installation defect rather than user error: raise loudly instead of
    silently degrading to an empty mapping, which would reroute every implicit
    role alias.
    """
    resource = files("sase.llm_provider").joinpath(_DEFAULTS_RESOURCE_NAME)

    try:
        text = resource.read_text(encoding="utf-8")
    except OSError as exc:
        raise _defaults_error(resource, f"could not be read: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise _defaults_error(resource, f"is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise _defaults_error(resource, "must contain a YAML mapping at the top level")

    aliases = data.get("aliases")
    if not isinstance(aliases, dict):
        raise _defaults_error(resource, "must have a top-level 'aliases' mapping")

    known_names = set(_ROLE_ALIAS_NAME_CONSTANTS)
    yaml_names = set(aliases)
    if yaml_names != known_names:
        missing = sorted(known_names - yaml_names)
        unknown = sorted(yaml_names - known_names)
        details = []
        if missing:
            details.append(f"missing entries for {missing}")
        if unknown:
            details.append(f"unknown entries for {unknown}")
        raise _defaults_error(resource, "; ".join(details))

    fallbacks: dict[str, str] = {}
    targets: dict[str, str] = {}
    coder_targets: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    for name, entry in aliases.items():
        if not isinstance(entry, dict):
            raise _defaults_error(resource, f"entry {name!r} must be a mapping")

        fallback = entry.get("fallback")
        target = entry.get("target")
        if fallback is not None and target is not None:
            raise _defaults_error(
                resource, f"entry {name!r} sets both 'fallback' and 'target'"
            )
        if name == DEFAULT_MODEL_ALIAS_NAME and (
            fallback is not None or target is not None
        ):
            raise _defaults_error(
                resource,
                f"entry {name!r} must not set 'fallback' or 'target'",
            )
        if fallback is not None:
            if not isinstance(fallback, str) or not fallback.strip():
                raise _defaults_error(
                    resource, f"entry {name!r} has a non-string or empty 'fallback'"
                )
            fallbacks[name] = fallback.strip()
        if target is not None:
            if not isinstance(target, str) or not target.strip():
                raise _defaults_error(
                    resource, f"entry {name!r} has a non-string or empty 'target'"
                )
            targets[name] = target.strip()

        if "provider_targets" in entry:
            provider_targets = entry["provider_targets"]
            if name != CODER_MODEL_ALIAS_NAME:
                raise _defaults_error(
                    resource,
                    f"entry {name!r} must not set 'provider_targets'; only "
                    f"{CODER_MODEL_ALIAS_NAME!r} may set it",
                )
            if not isinstance(provider_targets, dict):
                raise _defaults_error(
                    resource,
                    f"entry {name!r} has a non-mapping 'provider_targets'",
                )
            for provider, provider_target in provider_targets.items():
                if not isinstance(provider, str) or not provider.strip():
                    raise _defaults_error(
                        resource,
                        f"entry {name!r} has a non-string or empty provider name",
                    )
                if not isinstance(provider_target, str) or not provider_target.strip():
                    raise _defaults_error(
                        resource,
                        f"entry {name!r} provider {provider!r} has a non-string "
                        "or empty target",
                    )
                clean_provider = provider.strip()
                if clean_provider in coder_targets:
                    raise _defaults_error(
                        resource,
                        f"entry {name!r} repeats provider {clean_provider!r} after "
                        "whitespace normalization",
                    )
                coder_targets[clean_provider] = provider_target.strip()

        description = entry.get("description")
        if not isinstance(description, str) or not description.strip():
            raise _defaults_error(
                resource, f"entry {name!r} is missing a non-empty 'description'"
            )
        descriptions[name] = description.strip()

    return _ModelAliasDefaults(
        role_alias_fallbacks=MappingProxyType(fallbacks),
        implicit_alias_targets=MappingProxyType(targets),
        provider_coder_targets=MappingProxyType(coder_targets),
        role_alias_descriptions=MappingProxyType(descriptions),
    )


def role_alias_fallbacks() -> Mapping[str, str]:
    """Return the ``@<alias>`` reference each role falls back to, if any.

    A reference may carry a trailing ``@<effort>`` overlay; it does not form a
    separate target, and an outer effort still wins.
    """
    return _load_model_alias_defaults().role_alias_fallbacks


def implicit_alias_targets() -> Mapping[str, str]:
    """Return concrete/selector default targets for implicit aliases."""
    return _load_model_alias_defaults().implicit_alias_targets


def provider_coder_targets() -> Mapping[str, str]:
    """Return shipped provider-name targets for ``<provider>_coder`` aliases."""
    return _load_model_alias_defaults().provider_coder_targets


def role_alias_descriptions() -> Mapping[str, str]:
    """Return user-facing descriptions for every implicit alias."""
    return _load_model_alias_defaults().role_alias_descriptions
