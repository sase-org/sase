"""Durable clan-record writes and launch defaults for the run agent runner.

A launch records the member's declared, script-generated, or propagated clan
attributes into the durable per-clan record, and a launch that creates a new
generation of a previously recorded clan inherits the remembered tribe and
summary. Every path here is best-effort so it can never block a launch.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClanSummaryResolutionRequest:
    """Stable inputs for a member's post-preparation clan-summary run."""

    script: str
    clan_name: str
    clan_generation: str
    clan_tribe: str | None


def _metadata_text(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def record_clan_attributes_at_launch(
    *,
    artifacts_dir: str,
    clan_membership_plan: Any,
    directives: Any,
    epic_clan_summary_script: str | None,
    epic_work_metadata: dict[str, Any],
    resolved_summary: str | None,
    used_summary_script: str | None,
) -> None:
    """Record this member's clan attributes into the durable clan record.

    Best-effort: record errors are logged and swallowed so they can never
    block a launch. User-initiated edits use the strict facade path instead.
    """
    try:
        from sase.core.agent_clan_record import (
            clan_attribute_update,
            record_clan_attributes,
        )
    except Exception as exc:  # noqa: BLE001 - launch is best-effort.
        log.warning(
            "Skipping clan record write for %r: %s",
            getattr(clan_membership_plan, "clan_name", None),
            exc,
        )
        return
    clan_name = clan_membership_plan.clan_name
    generation = clan_membership_plan.generation
    source_identity = artifacts_dir
    update: dict[str, Any] = {"clan": clan_name, "generation": generation}
    if directives.clan_declared:
        if directives.clan_tribe:
            update["tribe"] = clan_attribute_update(
                directives.clan_tribe,
                "declared",
                source_identity=source_identity,
            )
        if used_summary_script:
            raw_script = directives.clan_summary_script or used_summary_script
            update["summary_script"] = clan_attribute_update(
                raw_script,
                "declared",
                source_identity=source_identity,
            )
            if resolved_summary:
                update["summary"] = clan_attribute_update(
                    resolved_summary,
                    "script",
                    source_identity=source_identity,
                )
        elif resolved_summary:
            update["summary"] = clan_attribute_update(
                resolved_summary,
                "declared",
                source_identity=source_identity,
            )
    elif epic_clan_summary_script:
        if used_summary_script:
            update["summary_script"] = clan_attribute_update(
                used_summary_script,
                "propagated",
                source_identity=source_identity,
            )
        if resolved_summary:
            update["summary"] = clan_attribute_update(
                resolved_summary,
                "script",
                source_identity=source_identity,
            )
    if "tribe" not in update:
        epic_tribe = epic_work_metadata.get("clan_tribe")
        if isinstance(epic_tribe, str) and epic_tribe:
            update["tribe"] = clan_attribute_update(
                epic_tribe,
                "propagated",
                source_identity=source_identity,
            )
    if len(update) <= 2:
        return
    record_clan_attributes(update)


def _is_new_clan_generation(*, clan_membership_plan: Any, artifacts_dir: str) -> bool:
    """Return whether this launch created a new clan generation.

    New generations carry the artifacts directory basename as their
    generation: ``declare`` returns the passed generation for a fresh clan
    and ``resolve-or-create`` returns the existing generation when joining,
    so equality holds exactly for creation (verified against
    ``_resolve_clan_membership`` and ``reserve_registered_clan_name``).
    """
    generation = getattr(clan_membership_plan, "generation", None)
    if not isinstance(generation, str) or not generation:
        return False
    return Path(artifacts_dir).name == generation


def _append_clan_inheritance_log(output_path: str | None, message: str) -> None:
    """Append one inheritance line to the agent log, best-effort."""
    if output_path is None or not message:
        return
    try:
        with open(output_path, "a", encoding="utf-8") as log_file:
            log_file.write(message if message.endswith("\n") else message + "\n")
    except OSError as exc:
        log.warning(
            "Could not append clan inheritance to agent log %r (%s)",
            output_path,
            exc,
        )


def apply_clan_launch_defaults(
    *,
    artifacts_dir: str,
    workspace_dir: str,
    output_path: str | None,
    launch_environment: dict[str, str],
    clan_membership_plan: Any,
    directives: Any,
    epic_work_metadata: dict[str, Any],
    epic_clan_summary_script: str | None,
    preserved_metadata: dict[str, Any],
    agent_meta: dict[str, Any],
) -> tuple[
    ClanSummaryResolutionRequest | None,
    str | None,
    str | None,
]:
    """Inherit a remembered tribe and summary for a new clan generation.

    Best-effort: record/read failures are logged and swallowed so they can
    never block a launch. Returns the inherited
    ``(resolution, summary, script)`` triple, with ``None`` entries when
    nothing was inherited.
    """
    empty: tuple[ClanSummaryResolutionRequest | None, str | None, str | None] = (
        None,
        None,
        None,
    )
    if clan_membership_plan is None:
        return empty
    if not _is_new_clan_generation(
        clan_membership_plan=clan_membership_plan,
        artifacts_dir=artifacts_dir,
    ):
        return empty
    try:
        from sase.axe.clan_summary_script import (
            normalize_clan_summary,
            resolve_clan_summary_script,
        )
        from sase.core.agent_clan_record import (
            clan_attribute_update,
            record_clan_attributes,
            resolve_clan_launch_defaults,
        )
    except Exception as exc:  # noqa: BLE001 - launch defaults are best-effort.
        log.warning(
            "Skipping clan launch defaults for %r: %s",
            getattr(clan_membership_plan, "clan_name", None),
            exc,
        )
        return empty

    clan_name = clan_membership_plan.clan_name
    generation = clan_membership_plan.generation
    try:
        defaults = resolve_clan_launch_defaults(
            clan_name, exclude_generation=generation
        )
    except Exception:  # noqa: BLE001 - facade already logged in soft mode.
        return empty
    if not isinstance(defaults, dict):
        return empty

    def _remembered(key: str) -> str | None:
        value = defaults.get(key)
        return value if isinstance(value, str) and value else None

    remembered_tribe = _remembered("tribe")
    remembered_summary = _remembered("summary")
    remembered_script = _remembered("summary_script")
    tribe_generation = _remembered("tribe_generation")
    summary_generation = _remembered("summary_generation")
    script_generation = _remembered("summary_script_generation")
    if not remembered_tribe and not remembered_summary and not remembered_script:
        return empty

    epic_tribe = epic_work_metadata.get("clan_tribe")
    if not isinstance(epic_tribe, str) or not epic_tribe:
        epic_tribe = None

    inherited_tribe: str | None = None
    inherited_tribe_generation: str | None = None
    if (
        remembered_tribe
        and getattr(directives, "clan_tribe", None) is None
        and epic_tribe is None
        and not _metadata_text(preserved_metadata, "clan_tribe")
        and not _metadata_text(agent_meta, "clan_tribe")
    ):
        inherited_tribe = remembered_tribe
        inherited_tribe_generation = tribe_generation
        agent_meta["clan_tribe"] = inherited_tribe

    has_explicit_summary = bool(
        getattr(directives, "clan_summary", None)
        or getattr(directives, "clan_summary_script", None)
        or epic_clan_summary_script
    )
    if (
        has_explicit_summary
        or _metadata_text(preserved_metadata, "clan_summary")
        or _metadata_text(agent_meta, "clan_summary")
    ):
        remembered_script = None
        remembered_summary = None

    inherited_resolution: ClanSummaryResolutionRequest | None = None
    inherited_summary: str | None = None
    inherited_script: str | None = None
    if remembered_script or remembered_summary:
        tribe_for_script = _metadata_text(agent_meta, "clan_tribe")
        if remembered_script:
            inherited_script = remembered_script
            inherited_resolution = ClanSummaryResolutionRequest(
                script=remembered_script,
                clan_name=clan_name,
                clan_generation=generation,
                clan_tribe=tribe_for_script,
            )
            script_output = resolve_clan_summary_script(
                remembered_script,
                workspace_dir=workspace_dir,
                clan_name=clan_name,
                clan_generation=generation,
                clan_tribe=tribe_for_script,
                agent_log_path=output_path,
                artifacts_dir=artifacts_dir,
                environment=launch_environment,
            )
            if script_output:
                inherited_summary = script_output
            elif remembered_summary:
                inherited_summary = normalize_clan_summary(remembered_summary)
        elif remembered_summary:
            inherited_summary = normalize_clan_summary(remembered_summary)
        if inherited_summary:
            agent_meta["clan_summary"] = inherited_summary

    if not inherited_tribe and not inherited_summary and not inherited_script:
        return empty

    update: dict[str, Any] = {"clan": clan_name, "generation": generation}
    if inherited_tribe:
        update["tribe"] = clan_attribute_update(
            inherited_tribe,
            "inherited",
            source_identity=artifacts_dir,
        )
    if inherited_script:
        update["summary_script"] = clan_attribute_update(
            inherited_script,
            "inherited",
            source_identity=artifacts_dir,
        )
    if inherited_summary:
        update["summary"] = clan_attribute_update(
            inherited_summary,
            "inherited",
            source_identity=artifacts_dir,
        )
    try:
        record_clan_attributes(update)
    except Exception:  # noqa: BLE001 - facade already logged in soft mode.
        pass

    parts: list[str] = []
    if inherited_tribe:
        source = inherited_tribe_generation or "an earlier generation"
        parts.append(f"tribe from generation '{source}'")
    if inherited_summary:
        source = summary_generation or script_generation or "an earlier generation"
        parts.append(f"summary from generation '{source}'")
    elif inherited_script:
        source = script_generation or "an earlier generation"
        parts.append(f"summary script from generation '{source}'")
    if parts:
        _append_clan_inheritance_log(
            output_path,
            f"Inherited clan '{clan_name}' defaults for new generation "
            f"'{generation}': {', '.join(parts)}.",
        )
    return (inherited_resolution, inherited_summary, inherited_script)
