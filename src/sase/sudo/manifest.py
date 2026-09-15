"""Reviewed command-subset helpers for sudo manifests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.notification_gates.models import GateError
from sase.sudo.core import DEFAULT_SUDO_CORE, SudoCoreBinding


def _manifest_command_ids(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    """Return command ids from a sudo manifest in reviewed order."""
    commands = manifest.get("commands")
    if not isinstance(commands, list):
        raise GateError(
            "invalid_sudo_manifest",
            "manifest.commands",
            "sudo manifest commands must be an array",
        )
    command_ids: list[str] = []
    for index, command in enumerate(commands):
        if not isinstance(command, Mapping):
            raise GateError(
                "invalid_sudo_manifest",
                f"manifest.commands[{index}]",
                "sudo manifest command must be an object",
            )
        command_id = command.get("id")
        if not isinstance(command_id, str) or not command_id:
            raise GateError(
                "invalid_sudo_manifest",
                f"manifest.commands[{index}].id",
                "sudo manifest command id is required",
            )
        command_ids.append(command_id)
    return tuple(command_ids)


def selected_sudo_manifest(
    manifest: Mapping[str, Any],
    requested_command_ids: Sequence[str] | None,
    *,
    core: SudoCoreBinding = DEFAULT_SUDO_CORE,
) -> tuple[dict[str, Any], tuple[str, ...], str]:
    """Return ``(manifest, command_ids, sha256)`` for a reviewed command subset.

    ``requested_command_ids=None`` or an empty sequence means every command is
    selected.  When ids are provided by a surface, they are validated for
    uniqueness but the materialized manifest always preserves the original
    reviewed order from the gate bundle.
    """
    commands = manifest.get("commands")
    if not isinstance(commands, list):
        raise GateError(
            "invalid_sudo_manifest",
            "manifest.commands",
            "sudo manifest commands must be an array",
        )
    all_ids = _manifest_command_ids(manifest)
    requested = _normalize_requested_ids(requested_command_ids, allowed=all_ids)
    selected_ids = (
        all_ids
        if requested is None
        else tuple(command_id for command_id in all_ids if command_id in requested)
    )
    if not selected_ids:
        raise GateError(
            "empty_sudo_selection",
            "command_ids",
            "select at least one sudo command to run",
        )
    selected_set = set(selected_ids)
    subset = dict(manifest)
    subset["commands"] = [
        dict(command)
        for command in commands
        if isinstance(command, Mapping) and command.get("id") in selected_set
    ]
    subset["resume_from"] = None
    normalized = core.validate_manifest(subset)
    return normalized, selected_ids, core.manifest_sha256(normalized)


def _normalize_requested_ids(
    requested_command_ids: Sequence[str] | None,
    *,
    allowed: tuple[str, ...],
) -> set[str] | None:
    if requested_command_ids is None or len(requested_command_ids) == 0:
        return None
    requested: list[str] = []
    for index, command_id in enumerate(requested_command_ids):
        if not isinstance(command_id, str) or not command_id.strip():
            raise GateError(
                "invalid_sudo_selection",
                f"command_ids[{index}]",
                "sudo command ids must be non-empty strings",
            )
        requested.append(command_id.strip())
    duplicates = sorted({item for item in requested if requested.count(item) > 1})
    if duplicates:
        raise GateError(
            "duplicate_identifier",
            "command_ids",
            f"duplicate command id(s): {', '.join(duplicates)}",
        )
    allowed_set = set(allowed)
    unknown = sorted(set(requested) - allowed_set)
    if unknown:
        raise GateError(
            "unknown_sudo_command",
            "command_ids",
            f"unknown sudo command id(s): {', '.join(unknown)}",
        )
    return set(requested)


__all__ = [
    "selected_sudo_manifest",
]
