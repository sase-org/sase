"""Sidecar repo config checks for ``sase doctor``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase._linked_repo_config import (
    SIDECAR_BUILTIN_CONFIG_KEY,
    SIDECAR_CUSTOM_CONFIG_KEY,
)
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS
from sase.plugins.qualified_id import (
    PluginQualifiedIdError,
    parse_plugin_qualified_id,
    plugin_qualified_id_matches,
)
from sase.sdd._store_types import RESERVED_SIDECAR_ROLES
from sase.sidecar_ref_config import (
    REF_DETAIL_CONFIG_KEY,
    REF_EXPANSION_FORMAT_CONFIG_KEY,
    REF_CAPABILITIES_CONFIG_KEY,
    REF_CONFIG_KEY,
    REF_FILTERS_CONFIG_KEY,
    REF_IDENTITY_CONFIG_KEY,
    REF_INVENTORY_CONFIG_KEY,
    REF_INVENTORY_GLOBS_CONFIG_KEY,
    REF_KIND_CONFIG_KEY,
    REF_PATH_GLOBS_CONFIG_KEY,
    REF_PROPERTIES_CONFIG_KEY,
    REF_PUBLICATION_CONFIG_KEY,
    REF_USE_CONFIG_KEY,
    REF_XPROMPT_CONFIG_KEY,
)

_SIDECAR_KEY = "repos.sidecar"


def _bucket_for_role(role: str) -> str:
    return (
        SIDECAR_BUILTIN_CONFIG_KEY
        if role in RESERVED_SIDECAR_ROLES
        else SIDECAR_CUSTOM_CONFIG_KEY
    )


def check_config_repos() -> DiagnosticCheck:
    """Surface ``repos.sidecar`` config that needs migrating (epic sase-gu).

    ``repos.sidecar`` is a two-bucket mapping keyed by role: the reserved
    ``plans``/``beads``/``agents`` roles under ``builtin`` and every document
    sidecar under ``custom``. The removed list form is no longer parsed, so
    this check is the actionable migration report for stale configs, for roles
    filed in the wrong bucket, and for entries the schema cannot reject on its
    own.
    """
    from sase.config.core import load_merged_config

    config = load_merged_config()
    repos = config.get("repos")
    raw = repos.get("sidecar") if isinstance(repos, Mapping) else None
    problems: list[dict[str, str]] = []

    if isinstance(raw, list):
        problems.extend(_legacy_list_problems(raw))
    elif isinstance(raw, Mapping):
        problems.extend(_mapping_problems(raw))
    elif raw is not None:
        problems.append(
            {
                "key": _SIDECAR_KEY,
                "message": (
                    f"{_SIDECAR_KEY} must be an object with builtin and/or "
                    "custom role maps"
                ),
            }
        )
    problems.extend(_artifact_provider_registry_problems())

    status: CheckStatus = "WARN" if problems else "OK"
    summary = (
        f"{len(problems)} sidecar repo config issue(s) found"
        if problems
        else "sidecar repo config is current"
    )
    next_steps = (
        (
            "Move each sidecar under repos.sidecar.builtin (plans, beads, "
            "agents) or repos.sidecar.custom (document sidecars) keyed by role, "
            "then rerun `sase doctor -C config.repos`.",
        )
        if problems
        else ()
    )

    return DiagnosticCheck(
        id="config.repos",
        group="config",
        status=status,
        title="Sidecar repo config",
        summary=summary,
        details=tuple(row["message"] for row in problems)[:MAX_DETAIL_ROWS],
        next_steps=next_steps,
        data={"problems": problems},
    )


def _legacy_list_problems(entries: list[Any]) -> list[dict[str, str]]:
    """Report the removed list form, naming each entry's target bucket."""

    problems: list[dict[str, str]] = []
    for index, entry in enumerate(entries):
        key = f"{_SIDECAR_KEY}[{index}]"
        if not isinstance(entry, Mapping):
            problems.append({"key": key, "message": f"{key} must be a mapping"})
            continue
        role = entry.get("name")
        if not isinstance(role, str) or not role.strip():
            problems.append(
                {
                    "key": key,
                    "message": (
                        f"{key} is an unsupported list entry with no usable "
                        f"'name' role; move it under {_SIDECAR_KEY}.custom.<role>"
                    ),
                }
            )
            continue
        role = role.strip()
        target = f"{_SIDECAR_KEY}.{_bucket_for_role(role)}.{role}"
        problems.append(
            {
                "key": key,
                "message": (
                    f"{key} ({role!r}) uses the removed list form and is "
                    f"ignored; move it to {target} and drop its 'name' field"
                ),
            }
        )
    if not problems:
        problems.append(
            {
                "key": _SIDECAR_KEY,
                "message": (
                    f"{_SIDECAR_KEY} uses the removed list form and is "
                    "ignored; replace it with a builtin/custom mapping keyed "
                    "by role"
                ),
            }
        )
    return problems


def _mapping_problems(raw: Mapping[str, Any]) -> list[dict[str, str]]:
    """Report bucket, entry, and description problems in the mapping form."""

    problems: list[dict[str, str]] = []
    for extra in sorted(
        str(key)
        for key in raw
        if key not in {SIDECAR_BUILTIN_CONFIG_KEY, SIDECAR_CUSTOM_CONFIG_KEY}
    ):
        problems.append(
            {
                "key": f"{_SIDECAR_KEY}.{extra}",
                "message": (
                    f"{_SIDECAR_KEY}.{extra} is not a sidecar bucket; only "
                    "builtin and custom are supported"
                ),
            }
        )

    roles_by_bucket: dict[str, dict[str, Mapping[str, Any]]] = {}
    for bucket in (SIDECAR_BUILTIN_CONFIG_KEY, SIDECAR_CUSTOM_CONFIG_KEY):
        values = raw.get(bucket)
        if values is None:
            continue
        if not isinstance(values, Mapping):
            problems.append(
                {
                    "key": f"{_SIDECAR_KEY}.{bucket}",
                    "message": (
                        f"{_SIDECAR_KEY}.{bucket} must be a map of role names "
                        "to sidecar entries"
                    ),
                }
            )
            continue
        entries: dict[str, Mapping[str, Any]] = {}
        for raw_role, entry in values.items():
            role = str(raw_role).strip()
            key = f"{_SIDECAR_KEY}.{bucket}.{role or repr(raw_role)}"
            if not role:
                problems.append({"key": key, "message": f"{key} has a blank role name"})
                continue
            if not isinstance(entry, Mapping):
                problems.append(
                    {
                        "key": key,
                        "message": (f"{key} must be a mapping of sidecar entry fields"),
                    }
                )
                continue
            entries[role] = entry
            if (
                bucket == SIDECAR_BUILTIN_CONFIG_KEY
                and role not in RESERVED_SIDECAR_ROLES
            ):
                problems.append(
                    {
                        "key": key,
                        "message": (
                            f"{key} is not a reserved role; move it to "
                            f"{_SIDECAR_KEY}.custom.{role}"
                        ),
                    }
                )
            elif bucket == SIDECAR_CUSTOM_CONFIG_KEY and role in RESERVED_SIDECAR_ROLES:
                problems.append(
                    {
                        "key": key,
                        "message": (
                            f"{key} is a reserved role; move it to "
                            f"{_SIDECAR_KEY}.builtin.{role}"
                        ),
                    }
                )
            if "name" in entry:
                problems.append(
                    {
                        "key": f"{key}.name",
                        "message": (
                            f"{key} still carries a 'name' field; the role is "
                            "the map key, so remove it"
                        ),
                    }
                )
            if bucket == SIDECAR_CUSTOM_CONFIG_KEY:
                problems.extend(_missing_description_problems(key, entry))
            problems.extend(_ref_policy_problems(key, role, entry))
        roles_by_bucket[bucket] = entries

    both = sorted(
        set(roles_by_bucket.get(SIDECAR_BUILTIN_CONFIG_KEY, {}))
        & set(roles_by_bucket.get(SIDECAR_CUSTOM_CONFIG_KEY, {}))
    )
    for role in both:
        problems.append(
            {
                "key": f"{_SIDECAR_KEY}.custom.{role}",
                "message": (
                    f"{role!r} is configured in both {_SIDECAR_KEY}.builtin and "
                    f"{_SIDECAR_KEY}.custom; custom wins, so remove the "
                    "duplicate entry"
                ),
            }
        )
    return problems


def _ref_policy_problems(
    key: str,
    role: str,
    entry: Mapping[str, Any],
) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    raw_ref = entry.get(REF_CONFIG_KEY)
    if raw_ref is None:
        return problems
    ref_key = f"{key}.{REF_CONFIG_KEY}"
    if not isinstance(raw_ref, Mapping):
        return [
            {
                "key": ref_key,
                "message": f"{ref_key} must be a mapping",
            }
        ]

    unknown = sorted(str(key) for key in raw_ref if str(key) not in _KNOWN_REF_FIELDS)
    if unknown:
        problems.append(
            {
                "key": ref_key,
                "message": f"{ref_key} has unknown field(s): {', '.join(unknown)}",
            }
        )

    use = raw_ref.get(REF_USE_CONFIG_KEY)
    if use is not None:
        use_key = f"{ref_key}.{REF_USE_CONFIG_KEY}"
        if not isinstance(use, str) or not use.strip():
            problems.append(
                {
                    "key": use_key,
                    "message": f"{use_key} must be a nonempty string",
                }
            )
        else:
            from sase.artifact_providers import get_artifact_provider_registry

            use_value = use.strip()
            try:
                plugin, provider_id = parse_plugin_qualified_id(use_value)
            except PluginQualifiedIdError:
                problems.append(
                    {
                        "key": use_key,
                        "message": (
                            f"{use_key}: {_missing_use_prefix_message(use_value)}"
                        ),
                    }
                )
            else:
                registry = get_artifact_provider_registry()
                provider = registry.ref_providers_by_id.get(provider_id)
                if provider is None:
                    problems.append(
                        {
                            "key": use_key,
                            "message": (
                                f"{use_key} references missing artifact ref "
                                f"provider {provider_id!r}. A cloned sidecar repo "
                                "is not an installed plugin; install a plugin "
                                "exposing the sase_artifact_refs entry point "
                                "group, or replace this with an inline ref spec."
                            ),
                        }
                    )
                elif not plugin_qualified_id_matches(
                    plugin,
                    builtin=provider.provenance.builtin,
                    package=provider.provenance.package,
                ):
                    actual = (
                        "builtin"
                        if provider.provenance.builtin
                        else provider.provenance.package
                    )
                    problems.append(
                        {
                            "key": use_key,
                            "message": (
                                f"{use_key}: artifact ref provider "
                                f"{provider_id!r} is provided by {actual!r}, not "
                                f"{plugin!r}; use {f'{actual}@{provider_id}'!r}"
                            ),
                        }
                    )

    xprompt = raw_ref.get(REF_XPROMPT_CONFIG_KEY)
    if xprompt is not None:
        problems.append(
            {
                "key": f"{ref_key}.{REF_XPROMPT_CONFIG_KEY}",
                "message": (
                    f"{ref_key}.{REF_XPROMPT_CONFIG_KEY} was retired; use "
                    "provider-backed or inline ref specs"
                ),
            }
        )

    inventory = raw_ref.get(REF_INVENTORY_CONFIG_KEY)
    if inventory is not None:
        inventory_key = f"{ref_key}.{REF_INVENTORY_CONFIG_KEY}"
        if not isinstance(inventory, Mapping):
            problems.append(
                {
                    "key": inventory_key,
                    "message": f"{inventory_key} must be a mapping",
                }
            )
        else:
            globs = inventory.get(REF_INVENTORY_GLOBS_CONFIG_KEY)
            if globs is not None and (
                not isinstance(globs, list)
                or any(not isinstance(item, str) or not item for item in globs)
            ):
                problems.append(
                    {
                        "key": f"{inventory_key}.{REF_INVENTORY_GLOBS_CONFIG_KEY}",
                        "message": (
                            f"{inventory_key}.{REF_INVENTORY_GLOBS_CONFIG_KEY} "
                            "must be a list of nonempty strings"
                        ),
                    }
                )

    filters = raw_ref.get(REF_FILTERS_CONFIG_KEY)
    if filters is None:
        return problems
    filters_key = f"{ref_key}.{REF_FILTERS_CONFIG_KEY}"
    if not isinstance(filters, Mapping):
        problems.append(
            {
                "key": filters_key,
                "message": f"{filters_key} must be a mapping",
            }
        )
        return problems
    if role in {"beads", "agents"}:
        problems.append(
            {
                "key": filters_key,
                "message": (
                    f"{filters_key} is not supported for {role!r}; bead and "
                    "agent refs are entity-backed, not document-filtered"
                ),
            }
        )
        return problems
    if REF_PATH_GLOBS_CONFIG_KEY in filters:
        globs = filters.get(REF_PATH_GLOBS_CONFIG_KEY)
        globs_key = f"{filters_key}.{REF_PATH_GLOBS_CONFIG_KEY}"
        problems.append(
            {
                "key": globs_key,
                "message": (
                    f"{globs_key} is deprecated; use "
                    f"{ref_key}.{REF_INVENTORY_CONFIG_KEY}."
                    f"{REF_INVENTORY_GLOBS_CONFIG_KEY}"
                ),
            }
        )
        if not isinstance(globs, list) or any(
            not isinstance(item, str) or not item for item in globs
        ):
            problems.append(
                {
                    "key": globs_key,
                    "message": (
                        f"{globs_key} must be a list of nonempty strings; use "
                        "an empty list only to allow no document paths"
                    ),
                }
            )
    return problems


def _missing_use_prefix_message(value: str) -> str:
    from sase.artifact_providers import get_artifact_provider_registry

    provider = get_artifact_provider_registry().ref_providers_by_id.get(value)
    if provider is not None:
        prefix = (
            "builtin" if provider.provenance.builtin else provider.provenance.package
        )
        return f"{value!r} is missing its plugin prefix; use {f'{prefix}@{value}'!r}"
    return (
        f"{value!r} is missing its required plugin prefix; use "
        "'<plugin>@<id>' where <plugin> is 'builtin' or an installed "
        "distribution name"
    )


_KNOWN_REF_FIELDS = frozenset(
    {
        REF_USE_CONFIG_KEY,
        REF_KIND_CONFIG_KEY,
        REF_EXPANSION_FORMAT_CONFIG_KEY,
        REF_PROPERTIES_CONFIG_KEY,
        REF_DETAIL_CONFIG_KEY,
        REF_IDENTITY_CONFIG_KEY,
        REF_INVENTORY_CONFIG_KEY,
        REF_PUBLICATION_CONFIG_KEY,
        REF_CAPABILITIES_CONFIG_KEY,
        REF_FILTERS_CONFIG_KEY,
        REF_XPROMPT_CONFIG_KEY,
    }
)


def _artifact_provider_registry_problems() -> list[dict[str, str]]:
    try:
        from sase.artifact_providers import get_artifact_provider_registry

        registry = get_artifact_provider_registry()
    except Exception as exc:
        return [
            {
                "key": "artifact_providers",
                "message": (
                    "artifact provider registry could not be assembled: "
                    f"{type(exc).__name__}: {exc}"
                ),
            }
        ]
    problems: list[dict[str, str]] = []
    for diagnostic in registry.diagnostics:
        if diagnostic.severity not in {"warning", "error"}:
            continue
        suffix = diagnostic.provider or diagnostic.kind or diagnostic.code
        problems.append(
            {
                "key": f"artifact_providers.{suffix}",
                "message": diagnostic.message,
            }
        )
    if registry.disabled_env:
        problems.append(
            {
                "key": "artifact_providers.disabled",
                "message": (
                    "artifact provider plugin discovery is disabled by "
                    f"{', '.join(registry.disabled_env)}"
                ),
            }
        )
    return problems


def _missing_description_problems(
    key: str, entry: Mapping[str, Any]
) -> list[dict[str, str]]:
    """Report enabled lazy custom entries that ``sase init memory`` will reject."""

    if entry.get("disabled") is True or entry.get("auto_clone") is True:
        return []
    description = entry.get("description")
    if isinstance(description, str) and description.strip():
        return []
    return [
        {
            "key": f"{key}.description",
            "message": (
                f"{key} is enabled and lazily cloned but has no description; "
                "`sase memory init` requires one to generate agent instructions"
            ),
        }
    ]
