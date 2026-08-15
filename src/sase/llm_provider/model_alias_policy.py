"""Names, defaults, and descriptions for built-in model aliases.

Shipped defaults (targets and descriptions) live in the bundled
``model_alias_defaults.yml`` sibling file, not in this module. Editing that
YAML is the single change needed to alter what a built-in size alias resolves
to out of the box; this module only owns the alias *name* constants and the
loader that turns the YAML into cached accessor mappings.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import functools
from importlib.resources import files
from types import MappingProxyType

import yaml  # type: ignore[import-untyped]

from sase._yaml_safe import yaml_safe_load
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED, split_model_effort

from .load_balancing import ModelAliasSelectorError, parse_model_alias_selector

# Builtin overrides are configured under ``llm_provider.model_aliases.builtin``;
# user-created aliases live under ``llm_provider.model_aliases.custom`` so they
# can carry required descriptions. SASE ships exactly five implicit built-in
# aliases that always resolve, even when the user has not defined them:
# ``xsmall``, ``small``, ``medium``, ``large``, and ``xlarge``.
# See ``model_alias_defaults.yml`` for the current value of every default.

#: Retired public alias name retained only for compatibility wrappers and
#: migration diagnostics. No-``%model`` launches now use
#: ``llm_provider.default_model``.
DEFAULT_MODEL_ALIAS_NAME = "default"

#: Retired public alias names retained only for migrations/diagnostics.
EPIC_LANDER_MODEL_ALIAS_NAME = "epic_lander"
BIG_EPIC_LANDER_MODEL_ALIAS_NAME = "big_epic_lander"
XSMALL_WORKER_MODEL_ALIAS_NAME = "xsmall_worker"
SMALL_WORKER_MODEL_ALIAS_NAME = "small_worker"
MEDIUM_WORKER_MODEL_ALIAS_NAME = "medium_worker"
LARGE_WORKER_MODEL_ALIAS_NAME = "large_worker"
XLARGE_WORKER_MODEL_ALIAS_NAME = "xlarge_worker"
SMART_MODEL_ALIAS_NAME = "smart"
SMARTER_MODEL_ALIAS_NAME = "smarter"
SMARTEST_MODEL_ALIAS_NAME = "smartest"
CHEAP_MODEL_ALIAS_NAME = "cheap"
CHEAPER_MODEL_ALIAS_NAME = "cheaper"
CHEAPEST_MODEL_ALIAS_NAME = "cheapest"

#: Public built-in size alias names.
XSMALL_MODEL_ALIAS_NAME = "xsmall"
SMALL_MODEL_ALIAS_NAME = "small"
MEDIUM_MODEL_ALIAS_NAME = "medium"
LARGE_MODEL_ALIAS_NAME = "large"
XLARGE_MODEL_ALIAS_NAME = "xlarge"

#: Every shipped built-in alias name declared by this module, in YAML-entry order.
BUILTIN_MODEL_ALIAS_NAMES: tuple[str, ...] = (
    XSMALL_MODEL_ALIAS_NAME,
    SMALL_MODEL_ALIAS_NAME,
    MEDIUM_MODEL_ALIAS_NAME,
    LARGE_MODEL_ALIAS_NAME,
    XLARGE_MODEL_ALIAS_NAME,
)

_DEFAULTS_RESOURCE_NAME = "model_alias_defaults.yml"


@dataclass(frozen=True, slots=True)
class _ModelAliasDefaults:
    """Cached, immutable views over the bundled defaults YAML."""

    role_alias_fallbacks: Mapping[str, str]
    implicit_alias_targets: Mapping[str, str]
    role_alias_descriptions: Mapping[str, str]


def _defaults_error(resource: object, problem: str) -> RuntimeError:
    return RuntimeError(
        f"bundled model alias defaults ({resource}) {problem}; this is a SASE "
        "installation defect"
    )


def _parse_fallback_reference(
    resource: object,
    *,
    name: str,
    fallback: str,
    known_names: set[str],
) -> str:
    clean_reference, effort = split_model_effort(fallback)
    if not clean_reference.startswith("@"):
        raise _defaults_error(
            resource,
            f"entry {name!r} fallback {fallback!r} must be an @<alias> reference",
        )

    referenced = clean_reference[1:].strip()
    if not referenced:
        raise _defaults_error(
            resource, f"entry {name!r} fallback {fallback!r} references no alias"
        )
    if "@" in referenced:
        suffix = referenced.rsplit("@", 1)[-1]
        if effort is None and suffix not in EFFORT_LEVELS_ORDERED:
            levels = ", ".join(EFFORT_LEVELS_ORDERED)
            raise _defaults_error(
                resource,
                f"entry {name!r} fallback {fallback!r} has an invalid effort "
                f"overlay; expected one of: {levels}",
            )
        raise _defaults_error(
            resource,
            f"entry {name!r} fallback {fallback!r} must reference one alias",
        )
    if referenced not in known_names:
        raise _defaults_error(
            resource,
            f"entry {name!r} fallback {fallback!r} references unknown alias "
            f"'@{referenced}'",
        )
    return referenced


def _validate_target(resource: object, *, name: str, target: str) -> None:
    try:
        selector = parse_model_alias_selector(target)
    except ModelAliasSelectorError as exc:
        raise _defaults_error(
            resource, f"entry {name!r} target {target!r} is malformed: {exc}"
        ) from exc

    if selector is not None and not selector.members:
        raise _defaults_error(
            resource, f"entry {name!r} target {target!r} has no selector members"
        )


def _validate_fallback_graph(
    resource: object,
    *,
    fallback_refs: Mapping[str, str],
    target_names: set[str],
) -> None:
    for start in fallback_refs:
        path = [start]
        seen = {start}
        current = start
        while True:
            referenced = fallback_refs[current]
            if referenced in target_names:
                break
            if referenced in seen:
                cycle_start = path.index(referenced)
                cycle = [*path[cycle_start:], referenced]
                rendered = " -> ".join(f"@{alias}" for alias in cycle)
                raise _defaults_error(
                    resource,
                    f"fallback chain for entry {start!r} creates a cycle: {rendered}",
                )
            if referenced not in fallback_refs:
                if referenced == DEFAULT_MODEL_ALIAS_NAME:
                    break
                raise _defaults_error(
                    resource,
                    f"fallback chain for entry {start!r} terminates at "
                    f"alias {referenced!r}, which has no target",
                )
            seen.add(referenced)
            path.append(referenced)
            current = referenced


def _parse_model_alias_defaults(text: str, *, source: object) -> _ModelAliasDefaults:
    """Parse and validate model-alias defaults YAML from *text*."""
    try:
        data = yaml_safe_load(text)
    except yaml.YAMLError as exc:
        raise _defaults_error(source, f"is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise _defaults_error(source, "must contain a YAML mapping at the top level")

    aliases = data.get("aliases")
    if not isinstance(aliases, dict):
        raise _defaults_error(source, "must have a top-level 'aliases' mapping")

    known_names = set(BUILTIN_MODEL_ALIAS_NAMES)
    yaml_names = set(aliases)
    if yaml_names != known_names:
        missing = sorted(known_names - yaml_names)
        unknown = sorted(yaml_names - known_names)
        details = []
        if missing:
            details.append(f"missing entries for {missing}")
        if unknown:
            details.append(f"unknown entries for {sorted(unknown, key=repr)}")
        raise _defaults_error(source, "; ".join(details))

    fallbacks: dict[str, str] = {}
    fallback_refs: dict[str, str] = {}
    targets: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    for name, entry in aliases.items():
        if not isinstance(entry, dict):
            raise _defaults_error(source, f"entry {name!r} must be a mapping")

        fallback = entry.get("fallback")
        target = entry.get("target")
        if fallback is not None and target is not None:
            raise _defaults_error(
                source, f"entry {name!r} sets both 'fallback' and 'target'"
            )
        if fallback is None and target is None:
            raise _defaults_error(
                source, f"entry {name!r} must set either 'fallback' or 'target'"
            )
        if fallback is not None:
            if not isinstance(fallback, str) or not fallback.strip():
                raise _defaults_error(
                    source, f"entry {name!r} has a non-string or empty 'fallback'"
                )
            clean_fallback = fallback.strip()
            fallback_refs[name] = _parse_fallback_reference(
                source,
                name=name,
                fallback=clean_fallback,
                known_names=known_names,
            )
            fallbacks[name] = clean_fallback
        if target is not None:
            if not isinstance(target, str) or not target.strip():
                raise _defaults_error(
                    source, f"entry {name!r} has a non-string or empty 'target'"
                )
            clean_target = target.strip()
            _validate_target(source, name=name, target=clean_target)
            targets[name] = clean_target

        description = entry.get("description")
        if not isinstance(description, str) or not description.strip():
            raise _defaults_error(
                source, f"entry {name!r} is missing a non-empty 'description'"
            )
        descriptions[name] = description.strip()

    _validate_fallback_graph(
        source,
        fallback_refs=fallback_refs,
        target_names=set(targets),
    )

    return _ModelAliasDefaults(
        role_alias_fallbacks=MappingProxyType(fallbacks),
        implicit_alias_targets=MappingProxyType(targets),
        role_alias_descriptions=MappingProxyType(descriptions),
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

    return _parse_model_alias_defaults(text, source=resource)


def role_alias_fallbacks() -> Mapping[str, str]:
    """Return built-in alias fallback references, if any.

    The compact built-in contract ships no fallbacks; this accessor remains as
    a compatibility surface for older callers and tests that exercise malformed
    bundled defaults.
    """
    return _load_model_alias_defaults().role_alias_fallbacks


def implicit_alias_targets() -> Mapping[str, str]:
    """Return concrete/selector default targets for implicit aliases."""
    return _load_model_alias_defaults().implicit_alias_targets


def role_alias_descriptions() -> Mapping[str, str]:
    """Return user-facing descriptions for every implicit alias."""
    return _load_model_alias_defaults().role_alias_descriptions
