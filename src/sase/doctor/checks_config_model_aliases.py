"""Model alias migration checks for ``sase doctor``."""

from __future__ import annotations

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import (
    MAX_DETAIL_ROWS,
    REMOVED_IMPLICIT_ALIAS_GUIDANCE,
)
from sase.xprompt.effort import split_model_effort


_RETIRED_BUILTIN_ALIAS_NAMES = {
    "default",
    "epic_lander",
    "big_epic_lander",
    "xsmall_worker",
    "small_worker",
    "medium_worker",
    "large_worker",
    "xlarge_worker",
    "smart",
    "smarter",
    "smartest",
    "cheap",
    "cheaper",
    "cheapest",
    "coder",
    "epic_creator",
    "phase_worker",
    "xsmall_phase_worker",
    "small_phase_worker",
    "medium_phase_worker",
    "large_phase_worker",
    "xlarge_phase_worker",
}

#: Retired builtin-alias names mapped to exact config destinations.
_RETIRED_BUILTIN_DESTINATIONS = {
    "default": "llm_provider.default_model",
    "epic_lander": "llm_provider.epic_lander_model",
    "big_epic_lander": "llm_provider.big_epic_lander_model",
    "phase_worker": "llm_provider.model_aliases.builtin.medium",
    "xsmall_worker": "llm_provider.model_aliases.builtin.xsmall",
    "small_worker": "llm_provider.model_aliases.builtin.small",
    "medium_worker": "llm_provider.model_aliases.builtin.medium",
    "large_worker": "llm_provider.model_aliases.builtin.large",
    "xlarge_worker": "llm_provider.model_aliases.builtin.xlarge",
    "xsmall_phase_worker": "llm_provider.model_aliases.builtin.xsmall",
    "small_phase_worker": "llm_provider.model_aliases.builtin.small",
    "medium_phase_worker": "llm_provider.model_aliases.builtin.medium",
    "large_phase_worker": "llm_provider.model_aliases.builtin.large",
    "xlarge_phase_worker": "llm_provider.model_aliases.builtin.xlarge",
}

_CONCEPTUAL_SIZE_REPLACEMENTS = {
    "cheaper": "xsmall",
    "cheap": "small",
    "smart": "medium",
    "smarter": "large",
    "smartest": "xlarge",
}


def check_config_model_aliases() -> DiagnosticCheck:
    """Surface model-alias config that needs migrating.

    Stale config is reported as actionable warnings:

    - the removed ``llm_provider.worker_models`` key (entries should move to
      size aliases or explicit launch choices);
    - legacy flat entries directly under ``llm_provider.model_aliases``;
    - the removed top-level ``llm_provider.custom_model_aliases`` map;
    - user-created aliases that live in ``model_aliases.builtin`` or builtin
      aliases that live in ``model_aliases.custom``;
    - names present in both nested maps;
    - custom alias objects missing a usable ``model`` or ``description``;
    - bucket metadata entries that have no member aliases;
    - stale ``model_aliases.builtin.coder``, registered
      ``model_aliases.builtin.<provider>_coder``,
      retired builtin aliases such as ``default``, ``<size>_worker``,
      ``smart``, ``cheap``, and ``phase_worker``, plus alias values that
      reference a retired implicit alias;
    - merged alias values that reference an ``@<alias>`` name that resolves to
      nothing, which would silently fall through at launch.
    """
    from sase.llm_provider.alias_view import BUILTIN_MODEL_ALIAS_BUCKET_NAMES
    from sase.llm_provider.config import (
        get_builtin_model_aliases,
        get_custom_model_aliases,
        get_llm_provider_config,
        get_model_aliases,
        model_alias_bucket_names,
        model_alias_kind,
        model_alias_names,
        model_alias_selector_details,
        strip_model_alias_prefix,
        validate_model_alias_selector_value,
    )
    from sase.llm_provider.model_alias_policy import (
        BUILTIN_MODEL_ALIAS_NAMES,
    )

    config = get_llm_provider_config()
    known_aliases = model_alias_names()
    builtin_aliases = get_builtin_model_aliases()
    custom_aliases = get_custom_model_aliases()
    raw_model_aliases = config.get("model_aliases", {})
    raw_model_alias_entries = (
        raw_model_aliases if isinstance(raw_model_aliases, dict) else {}
    )
    raw_builtin = raw_model_alias_entries.get("builtin", {})
    raw_custom = raw_model_alias_entries.get("custom", {})
    raw_builtin_entries = raw_builtin if isinstance(raw_builtin, dict) else {}
    raw_custom_entries = raw_custom if isinstance(raw_custom, dict) else {}
    raw_buckets = raw_model_alias_entries.get("buckets", {})
    raw_top_custom = config.get("custom_model_aliases")
    problems: list[dict[str, str]] = []
    notes: list[str] = []
    registered_provider_coder_aliases = _registered_provider_coder_alias_names()
    raw_builtin_alias_names = {
        raw_key.strip()
        for raw_key in raw_builtin_entries
        if isinstance(raw_key, str) and raw_key.strip()
    }
    stale_provider_coder_builtin_aliases = (
        raw_builtin_alias_names & registered_provider_coder_aliases
    )

    if config.get("worker_models"):
        problems.append(
            {
                "key": "worker_models",
                "message": (
                    "llm_provider.worker_models is no longer supported; migrate "
                    "entries to size aliases such as "
                    "llm_provider.model_aliases.builtin.medium, or use "
                    "explicit approval/model overrides"
                ),
            }
        )

    if raw_top_custom is not None:
        problems.append(
            {
                "key": "custom_model_aliases",
                "message": (
                    "llm_provider.custom_model_aliases is no longer supported; "
                    "move entries to llm_provider.model_aliases.custom"
                ),
            }
        )

    if raw_model_aliases and not isinstance(raw_model_aliases, dict):
        problems.append(
            {
                "key": "model_aliases",
                "message": (
                    "llm_provider.model_aliases must be an object with builtin "
                    "and/or custom maps"
                ),
            }
        )

    for raw_key, value in sorted(
        raw_model_alias_entries.items(), key=lambda item: str(item[0])
    ):
        if raw_key in {"builtin", "custom", "buckets"}:
            continue
        if not isinstance(raw_key, str):
            continue
        alias = raw_key.strip()
        if not alias:
            continue
        if (
            alias in _RETIRED_BUILTIN_ALIAS_NAMES
            or alias in registered_provider_coder_aliases
            or alias in BUILTIN_MODEL_ALIAS_NAMES
        ):
            message = _retired_builtin_alias_message(
                alias,
                key=f"model_aliases.{alias}",
                registered_provider_coder_aliases=registered_provider_coder_aliases,
            ) or (
                f"model_aliases.{alias} is a legacy builtin alias override; "
                f"move it to llm_provider.model_aliases.builtin.{alias}"
            )
        elif model_alias_kind(alias) == "user":
            message = (
                f"model_aliases.{alias} is a legacy custom alias; move it to "
                f"llm_provider.model_aliases.custom.{alias} with model and "
                "description fields"
            )
        else:
            message = (
                f"model_aliases.{alias} is a legacy builtin alias override; "
                f"move it to llm_provider.model_aliases.builtin.{alias}"
            )
        if not isinstance(value, str) or not value.strip():
            message += " (and keep the model target as a non-empty string)"
        problems.append({"key": f"model_aliases.{alias}", "message": message})

    if raw_buckets and not isinstance(raw_buckets, dict):
        problems.append(
            {
                "key": "model_aliases.buckets",
                "message": "llm_provider.model_aliases.buckets must be a metadata map",
            }
        )
    elif isinstance(raw_buckets, dict):
        member_buckets = model_alias_bucket_names() | BUILTIN_MODEL_ALIAS_BUCKET_NAMES
        for raw_bucket in sorted(raw_buckets, key=str):
            if not isinstance(raw_bucket, str):
                continue
            bucket = raw_bucket.strip()
            if bucket and bucket not in member_buckets:
                problems.append(
                    {
                        "key": f"model_aliases.buckets.{bucket}",
                        "message": (
                            f"model_aliases.buckets.{bucket} has metadata but no "
                            "custom aliases reference this bucket"
                        ),
                    }
                )

    if raw_builtin and not isinstance(raw_builtin, dict):
        problems.append(
            {
                "key": "model_aliases.builtin",
                "message": (
                    "llm_provider.model_aliases.builtin must be a map of alias "
                    "names to model target strings"
                ),
            }
        )

    if raw_custom and not isinstance(raw_custom, dict):
        problems.append(
            {
                "key": "model_aliases.custom",
                "message": (
                    "llm_provider.model_aliases.custom must be a map of alias "
                    "names to {model, description} objects"
                ),
            }
        )

    for alias in sorted(raw_builtin_alias_names):
        if alias not in builtin_aliases:
            retired_message = _retired_builtin_alias_message(
                alias,
                key=f"model_aliases.builtin.{alias}",
                registered_provider_coder_aliases=registered_provider_coder_aliases,
            )
            if retired_message is not None:
                problems.append(
                    {
                        "key": f"model_aliases.builtin.{alias}",
                        "message": retired_message,
                    }
                )
            elif model_alias_kind(alias) == "user":
                problems.append(
                    {
                        "key": f"model_aliases.builtin.{alias}",
                        "message": (
                            f"model_aliases.builtin.{alias} is a custom alias in "
                            "the builtin-override map; move it to "
                            f"llm_provider.model_aliases.custom.{alias} with a "
                            "description"
                        ),
                    }
                )
        if alias in custom_aliases:
            problems.append(
                {
                    "key": f"model_aliases.builtin.{alias}",
                    "message": (
                        f"{alias} is configured in both model_aliases.builtin "
                        "and model_aliases.custom; custom wins, so remove the "
                        "builtin entry"
                    ),
                }
            )

    for raw_alias, entry in sorted(
        raw_custom_entries.items(), key=lambda item: str(item[0])
    ):
        if not isinstance(raw_alias, str):
            continue
        alias = raw_alias.strip()
        if not alias:
            continue
        if model_alias_kind(alias) != "user":
            problems.append(
                {
                    "key": f"model_aliases.custom.{alias}",
                    "message": (
                        f"model_aliases.custom.{alias} is a builtin alias; move "
                        f"it to llm_provider.model_aliases.builtin.{alias}"
                    ),
                }
            )
        if not isinstance(entry, dict):
            problems.append(
                {
                    "key": f"model_aliases.custom.{alias}",
                    "message": (
                        f"model_aliases.custom.{alias} must be an object with "
                        "model and description"
                    ),
                }
            )
            continue
        model = entry.get("model")
        if not isinstance(model, str) or not model.strip():
            problems.append(
                {
                    "key": f"model_aliases.custom.{alias}.model",
                    "message": (
                        f"model_aliases.custom.{alias}.model is missing or blank"
                    ),
                }
            )
        description = entry.get("description")
        if not isinstance(description, str) or not description.strip():
            problems.append(
                {
                    "key": f"model_aliases.custom.{alias}.description",
                    "message": (
                        f"model_aliases.custom.{alias}.description is missing or blank"
                    ),
                }
            )

    for alias, target in sorted(get_model_aliases().items()):
        if (
            alias in _RETIRED_BUILTIN_ALIAS_NAMES
            or alias in stale_provider_coder_builtin_aliases
        ) and alias in builtin_aliases:
            # The focused migration warning above is the actionable truth for
            # this stale key; validating its retired target would only add
            # noisy or contradictory follow-on advice.
            continue
        target_key = (
            f"model_aliases.custom.{alias}.model"
            if alias in custom_aliases
            else f"model_aliases.builtin.{alias}"
        )
        selector_errors = validate_model_alias_selector_value(alias, target)
        if "|" in target:
            for message in selector_errors:
                problems.append(
                    {
                        "key": target_key,
                        "message": f"{target_key}: {message}",
                    }
                )
            if not selector_errors:
                selector = model_alias_selector_details(alias)
                if selector is None:
                    continue
                if selector.mode == "round_robin":
                    available = [
                        member for member in selector.members if member.available
                    ]
                    if available:
                        for member in selector.members:
                            if member.available:
                                continue
                            notes.append(
                                f"{target_key} pool member '{member.value}' is "
                                "currently unavailable and will be skipped while "
                                "another member is available"
                            )
                    else:
                        selected = next(
                            member for member in selector.members if member.selected
                        )
                        notes.append(
                            f"{target_key} has no available load-balanced pool "
                            f"members; current member '{selected.value}' is retained "
                            "for provider diagnostics"
                        )
                else:
                    selected = next(
                        member for member in selector.members if member.selected
                    )
                    available = [
                        member for member in selector.members if member.available
                    ]
                    if available:
                        for member in selector.members:
                            if member.available:
                                continue
                            notes.append(
                                f"{target_key} fallback candidate "
                                f"'{member.value}' is currently unavailable; "
                                "ordered fallback currently selects "
                                f"'{selected.value}'"
                            )
                    else:
                        notes.append(
                            f"{target_key} has no available ordered fallback "
                            f"candidates; first candidate '{selected.value}' is "
                            "retained for provider diagnostics"
                        )
            continue
        if not target.startswith("@"):
            continue
        target_reference, _ = split_model_effort(target.strip())
        referenced = strip_model_alias_prefix(target_reference).strip()
        if (
            guidance := _retired_alias_reference_guidance(
                referenced,
                custom_aliases=custom_aliases,
                registered_provider_coder_aliases=registered_provider_coder_aliases,
            )
        ) is not None:
            problems.append(
                {
                    "key": target_key,
                    "message": (
                        f"{target_key} -> {target} references the retired "
                        f"'@{referenced}' alias; {guidance}"
                    ),
                }
            )
        elif referenced and referenced not in known_aliases:
            problems.append(
                {
                    "key": target_key,
                    "message": (
                        f"{target_key} -> {target} references unknown alias "
                        f"'@{referenced}'"
                    ),
                }
            )

    status: CheckStatus = "WARN" if problems else "OK"
    if problems:
        summary = f"{len(problems)} model alias migration issue(s) found"
    elif notes:
        summary = (
            f"model alias config is current; {len(notes)} selector availability note(s)"
        )
    else:
        summary = "model alias config is current"
    next_steps = (
        (
            "Migrate the reported `llm_provider` config to model aliases "
            "(see `docs/llms.md`), then rerun `sase doctor -C config.model_aliases`.",
        )
        if problems
        else ()
    )

    return DiagnosticCheck(
        id="config.model_aliases",
        group="config",
        status=status,
        title="Model alias migration",
        summary=summary,
        details=tuple([row["message"] for row in problems] + notes)[:MAX_DETAIL_ROWS],
        next_steps=next_steps,
        data={"problems": problems, "notes": notes},
    )


def _registered_provider_coder_alias_names() -> set[str]:
    """Return retired provider-coder aliases for currently registered providers."""
    try:
        from sase.llm_provider.registry import registered_provider_names

        return {f"{provider}_coder" for provider in registered_provider_names()}
    except Exception:
        return set()


def _retired_builtin_alias_message(
    alias: str,
    *,
    key: str,
    registered_provider_coder_aliases: set[str],
) -> str | None:
    """Return raw-config migration guidance for a retired builtin alias."""
    if alias in registered_provider_coder_aliases:
        return (
            f"{key} is retired; planner-provider coder aliases no longer exist. "
            "Route accepted tales by size with aliases such as @medium, or use "
            "an explicit approval/model override"
        )
    if alias == "coder":
        return (
            f"{key} is retired; accepted tale follow-ups now route by tale size. "
            "Move this target to llm_provider.model_aliases.builtin.medium or "
            "another size alias, define a described custom @coder alias for "
            "explicit use, or remove it"
        )
    if alias in _RETIRED_BUILTIN_DESTINATIONS:
        destination = _RETIRED_BUILTIN_DESTINATIONS[alias]
        return (
            f"{key} is retired; move its target to {destination} to preserve "
            "the customized routing, or remove it"
        )
    if alias in _CONCEPTUAL_SIZE_REPLACEMENTS:
        replacement = _CONCEPTUAL_SIZE_REPLACEMENTS[alias]
        return (
            f"{key} is retired; use @{replacement} for the closest shipped "
            f"size alias, or define a described custom @{alias} alias to "
            "preserve this customized target"
        )
    if alias == "cheapest":
        return (
            f"{key} is retired and has no automatic replacement; define a "
            "described custom @cheapest alias if you still need this target"
        )
    if alias == "epic_creator":
        return (
            f"{key} is retired; SASE no longer launches an epic-creator role, "
            "so remove this entry"
        )
    return None


def _retired_alias_reference_guidance(
    alias: str,
    *,
    custom_aliases: dict[str, str],
    registered_provider_coder_aliases: set[str],
) -> str | None:
    """Return migration guidance when *alias* is a retired implicit reference."""
    if not alias or alias in custom_aliases:
        return None
    if alias in REMOVED_IMPLICIT_ALIAS_GUIDANCE:
        return REMOVED_IMPLICIT_ALIAS_GUIDANCE[alias]
    if alias in registered_provider_coder_aliases:
        return (
            "accepted tale follow-ups now route by tale size; use a "
            "size alias such as @medium or an explicit model"
        )
    return None
