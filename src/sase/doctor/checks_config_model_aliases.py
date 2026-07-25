"""Model alias migration checks for ``sase doctor``."""

from __future__ import annotations

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import (
    MAX_DETAIL_ROWS,
    REMOVED_IMPLICIT_ALIAS_GUIDANCE,
)
from sase.xprompt.effort import split_model_effort


def check_config_model_aliases() -> DiagnosticCheck:
    """Surface model-alias config that needs migrating (epic sase-5d).

    Stale config is reported as actionable warnings:

    - the removed ``llm_provider.worker_models`` and ``llm_provider.default_model``
      keys (the former is replaced by ``<provider>_coder`` aliases, the latter by
      ``model_aliases.builtin.default``);
    - legacy flat entries directly under ``llm_provider.model_aliases``;
    - the removed top-level ``llm_provider.custom_model_aliases`` map;
    - user-created aliases that live in ``model_aliases.builtin`` or builtin
      aliases that live in ``model_aliases.custom``;
    - names present in both nested maps;
    - custom alias objects missing a usable ``model`` or ``description``;
    - bucket metadata entries that have no member aliases;
    - stale ``model_aliases.builtin.phase_worker`` entries and alias values that
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
    raw_custom_entries = raw_custom if isinstance(raw_custom, dict) else {}
    raw_buckets = raw_model_alias_entries.get("buckets", {})
    raw_top_custom = config.get("custom_model_aliases")
    problems: list[dict[str, str]] = []
    notes: list[str] = []

    if config.get("worker_models"):
        problems.append(
            {
                "key": "worker_models",
                "message": (
                    "llm_provider.worker_models is no longer supported; migrate "
                    "each entry to a `<provider>_coder` alias under "
                    "llm_provider.model_aliases.builtin"
                ),
            }
        )
    if "default_model" in config:
        problems.append(
            {
                "key": "default_model",
                "message": (
                    "llm_provider.default_model is not a supported key; move its "
                    "value to llm_provider.model_aliases.builtin.default"
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
        if model_alias_kind(alias) == "user":
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

    for alias in sorted(builtin_aliases):
        if alias == "phase_worker":
            problems.append(
                {
                    "key": "model_aliases.builtin.phase_worker",
                    "message": (
                        "model_aliases.builtin.phase_worker is no longer a "
                        "builtin alias override; move its target to "
                        "llm_provider.model_aliases.builtin.medium_phase_worker "
                        "to keep controlling medium phases, or remove it to "
                        "accept the @default fallback"
                    ),
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
        if alias == "phase_worker" and alias in builtin_aliases:
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
            referenced not in known_aliases
            and referenced in REMOVED_IMPLICIT_ALIAS_GUIDANCE
        ):
            guidance = REMOVED_IMPLICIT_ALIAS_GUIDANCE[referenced]
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
