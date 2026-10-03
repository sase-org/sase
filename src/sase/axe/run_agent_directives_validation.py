"""Launch directive validation for the run agent runner.

Tab (``%tab``) and tribe (``%id tribe=`` / ``%clan tribe=``) directives are
resolved before metadata, store, or name writes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from typing import Any


@dataclass(frozen=True)
class PendingAgentTribeWrite:
    """Resolved standalone tribe assignment to persist after metadata succeeds."""

    identity: tuple[Any, str, str | None]
    tribe: str
    layers: list[dict[str, Any]] | tuple[dict[str, Any], ...]


def _metadata_tribe(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _tab_mismatch_message(root_tab: str | None) -> str:
    root_label = root_tab if root_tab else "main"
    return (
        f"%tab does not match the session root tab '{root_label}'; "
        "use sase agent tab set to move it"
    )


def validate_agent_tab_directives(
    directives: Any,
    *,
    agent_session_attach_plan: Any | None,
    clan_membership_plan: Any | None,
    artifacts_dir: str,
) -> Any:
    """Validate ``%tab`` against session-root and clan-generation tabs."""
    from sase.macro._exceptions import DirectiveError

    explicit = bool(
        getattr(directives, "agent_tab", None) is not None
        or getattr(directives, "agent_tab_explicit_default", False)
    )
    stored = getattr(directives, "agent_tab", None)

    if agent_session_attach_plan is not None:
        from sase.axe.run_agent_directive_metadata import session_root_tab

        try:
            root_tab = session_root_tab(agent_session_attach_plan)
        except Exception:  # noqa: BLE001 - best-effort lookup.
            root_tab = None
        if explicit:
            if stored != root_tab:
                raise DirectiveError(_tab_mismatch_message(root_tab))
        else:
            if root_tab:
                directives = replace(directives, agent_tab=root_tab)
        return directives

    if clan_membership_plan is not None:
        from pathlib import Path

        generation = getattr(clan_membership_plan, "generation", None)
        is_new = bool(
            isinstance(generation, str)
            and generation
            and Path(artifacts_dir).name == generation
        )
        if is_new:
            return directives
        if not isinstance(generation, str) or not generation:
            return directives
        workflow_dir = os.path.dirname(os.path.abspath(artifacts_dir))
        generation_meta = os.path.join(workflow_dir, generation, "agent_meta.json")
        try:
            with open(generation_meta, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return directives
        except (json.JSONDecodeError, OSError):
            data = None
        generation_tab: str | None = None
        if isinstance(data, dict):
            value = data.get("agent_tab")
            generation_tab = value if isinstance(value, str) and value else None
        if explicit:
            if stored != generation_tab:
                root_label = generation_tab if generation_tab else "main"
                raise DirectiveError(
                    f"%tab does not match the clan generation tab "
                    f"'{root_label}'; use sase agent tab set to move it"
                )
        else:
            if generation_tab:
                directives = replace(directives, agent_tab=generation_tab)
    return directives


def _stored_tribes_for_resolution() -> tuple[str, ...]:
    from sase.core.agent_tribe_evidence import stored_tribe_names_for_resolution

    return stored_tribe_names_for_resolution()


def resolve_launch_tribe_directives(
    directives: Any,
    *,
    artifacts_dir: str,
    cl_name: str | None,
    preserved_metadata: dict[str, Any],
) -> tuple[Any, PendingAgentTribeWrite | None]:
    """Resolve public job aliases before metadata, store, or name writes."""
    if directives.tribe is None and directives.clan_tribe is None:
        return directives, None

    from sase.config.inventory import discover_layer_inputs
    from sase.core.agent_tribe import (
        InvalidTribeError,
        canonicalize_public_tribe_name,
    )

    layers = discover_layer_inputs()
    pending: PendingAgentTribeWrite | None = None
    resolved_tribe = directives.tribe
    if directives.tribe is not None:
        try:
            if cl_name:
                from sase.ace.agent_tribes import resolve_agent_tribe_assignment
                from sase.core.agent_types import AgentType

                raw_suffix = os.path.basename(artifacts_dir.rstrip(os.sep)) or None
                identity = (AgentType.WORKFLOW, cl_name, raw_suffix)
                resolved_tribe = resolve_agent_tribe_assignment(
                    identity,
                    directives.tribe,
                    layers=layers,
                )
                pending = PendingAgentTribeWrite(
                    identity=identity,
                    tribe=resolved_tribe,
                    layers=layers,
                )
            else:
                resolved_tribe = canonicalize_public_tribe_name(
                    directives.tribe,
                    layers=layers,
                    stored_tribes=_stored_tribes_for_resolution(),
                    current_tribe=_metadata_tribe(preserved_metadata, "tribe"),
                )
        except InvalidTribeError as exc:
            raise RuntimeError(f"%id tribe={directives.tribe!r}: {exc}") from exc

    resolved_clan_tribe = directives.clan_tribe
    if directives.clan_tribe is not None:
        try:
            resolved_clan_tribe = canonicalize_public_tribe_name(
                directives.clan_tribe,
                layers=layers,
                stored_tribes=_stored_tribes_for_resolution(),
                current_tribe=_metadata_tribe(preserved_metadata, "clan_tribe"),
            )
        except InvalidTribeError as exc:
            raise RuntimeError(f"%clan tribe={directives.clan_tribe!r}: {exc}") from exc

    return (
        replace(
            directives,
            tribe=resolved_tribe,
            clan_tribe=resolved_clan_tribe,
        ),
        pending,
    )


def persist_pending_tribe_write(
    pending: PendingAgentTribeWrite | None,
    tribe: str | None,
) -> None:
    """Persist a resolved ``%id tribe=`` assignment for the Agents tab."""
    if pending is None:
        return
    from sase.ace.agent_tribes import update_agent_tribe
    from sase.core.agent_tribe import InvalidTribeError

    try:
        update_agent_tribe(
            pending.identity,
            pending.tribe,
            layers=pending.layers,
        )
    except InvalidTribeError as exc:
        raise RuntimeError(f"%id tribe={tribe!r}: {exc}") from exc


__all__ = [
    "PendingAgentTribeWrite",
    "persist_pending_tribe_write",
    "resolve_launch_tribe_directives",
    "validate_agent_tab_directives",
]
