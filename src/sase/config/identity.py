"""Immutable models for selected-overlay owner identity configuration."""

from __future__ import annotations

import re
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    validate_agent_owner,
    validate_agent_username,
)

log = logging.getLogger(__name__)

MACHINE_NAME_PATTERN = r"^[a-z_]+$"
_MACHINE_NAME_RE = re.compile(MACHINE_NAME_PATTERN)

AgentOwnerConfigStatus = Literal[
    "complete",
    "legacy",
    "partial",
    "missing_selector",
    "invalid_selector",
    "missing_overlay",
    "selector_mismatch",
    "duplicate",
    "conflict",
    "invalid",
]


@dataclass(frozen=True, slots=True)
class RawOverlayIdentity:
    """Identity-shaped values read directly from one user overlay.

    The nested machine name is always the discriminator when the key is
    present. The deprecated top-level value is consulted only when the nested
    key is absent, which prevents a malformed or conflicting nested identity
    from silently selecting an overlay through its legacy value.
    """

    path: Path
    yaml_valid: bool
    id_present: bool
    id_mapping: bool
    username_present: bool
    username: str | None
    machine_name_present: bool
    machine_name: str | None
    legacy_machine_name_present: bool
    legacy_machine_name: str | None

    @property
    def discriminator(self) -> str | None:
        if self.machine_name_present:
            return self.machine_name
        if self.legacy_machine_name_present:
            return self.legacy_machine_name
        return None

    @property
    def declares_machine_overlay(self) -> bool:
        return self.machine_name_present or self.legacy_machine_name_present

    @property
    def nested_legacy_conflict(self) -> bool:
        return (
            self.machine_name_present
            and self.legacy_machine_name_present
            and self.machine_name != self.legacy_machine_name
        )


@dataclass(frozen=True, slots=True)
class AgentOwnerConfigSnapshot:
    """Cached, immutable view of machine selection and raw overlay identity."""

    selector: str | None
    selector_text: str | None
    status: AgentOwnerConfigStatus
    detail: str
    owner: AgentOwnerIdentity | None
    selected_overlay: Path | None
    matching_overlays: tuple[Path, ...]
    overlays: tuple[RawOverlayIdentity, ...]
    existing_usernames: tuple[str, ...]

    @property
    def repairable(self) -> bool:
        return self.status not in {"duplicate", "conflict"}


def is_valid_machine_name(value: object) -> bool:
    """Return whether *value* satisfies the public machine-name contract."""
    return isinstance(value, str) and _MACHINE_NAME_RE.fullmatch(value) is not None


def read_machine_name_selector_text(path: Path) -> str | None:
    """Read the selector text without treating invalid input as configured."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        log.warning("Failed to read machine-name selector: %s", path, exc_info=True)
        return None


def read_machine_name_selector(path: Path) -> str | None:
    """Read and validate the one-line machine-local identity selector."""
    text = read_machine_name_selector_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    if len(lines) != 1 or not is_valid_machine_name(lines[0]):
        log.warning("Ignoring invalid machine-name selector at %s", path)
        return None
    return lines[0]


def _raw_overlay_identity(
    path: Path,
    data: dict[str, Any] | None,
) -> RawOverlayIdentity:
    """Project identity-shaped fields from one unmerged overlay."""
    if data is None:
        return RawOverlayIdentity(
            path=path,
            yaml_valid=False,
            id_present=False,
            id_mapping=False,
            username_present=False,
            username=None,
            machine_name_present=False,
            machine_name=None,
            legacy_machine_name_present=False,
            legacy_machine_name=None,
        )

    id_present = "id" in data
    id_value = data.get("id")
    nested: dict[Any, Any] = id_value if isinstance(id_value, dict) else {}
    username_value = nested.get("username")
    machine_name_value = nested.get("machine_name")
    legacy_value = data.get("machine_name")
    return RawOverlayIdentity(
        path=path,
        yaml_valid=True,
        id_present=id_present,
        id_mapping=isinstance(id_value, dict),
        username_present="username" in nested,
        username=username_value if isinstance(username_value, str) else None,
        machine_name_present="machine_name" in nested,
        machine_name=(
            machine_name_value if isinstance(machine_name_value, str) else None
        ),
        legacy_machine_name_present="machine_name" in data,
        legacy_machine_name=legacy_value if isinstance(legacy_value, str) else None,
    )


def _declared_machine_names(
    overlays: tuple[RawOverlayIdentity, ...],
) -> tuple[str, ...]:
    """Return the valid machine names declared by the local overlays."""
    return tuple(
        sorted(
            {
                value
                for overlay in overlays
                if (value := overlay.discriminator) is not None
                and is_valid_machine_name(value)
            }
        )
    )


def _valid_existing_usernames(
    overlays: tuple[RawOverlayIdentity, ...],
) -> tuple[str, ...]:
    usernames: set[str] = set()
    for overlay in overlays:
        if overlay.username is None:
            continue
        try:
            validate_agent_username(overlay.username)
        except (RuntimeError, ValueError):
            continue
        usernames.add(overlay.username)
    return tuple(sorted(usernames))


def _owner_for_overlay(
    overlay: RawOverlayIdentity,
    selector: str,
) -> tuple[AgentOwnerIdentity | None, str | None]:
    """Validate a complete nested identity from the selected overlay."""
    if not overlay.id_mapping:
        return None, "selected overlay has no nested `id` object"
    if not overlay.username_present:
        return None, "selected overlay is missing `id.username`"
    if overlay.username is None:
        return None, "selected overlay has an invalid `id.username` value"
    if not overlay.machine_name_present:
        return None, "selected overlay is missing `id.machine_name`"
    if overlay.machine_name is None:
        return None, "selected overlay has an invalid `id.machine_name` value"
    if overlay.machine_name != selector:
        return (
            None,
            f"selector '{selector}' does not match "
            f"`id.machine_name: {overlay.machine_name}` in {overlay.path}",
        )
    owner = AgentOwnerIdentity(
        username=overlay.username,
        machine_name=overlay.machine_name,
    )
    try:
        validate_agent_owner(owner)
    except (RuntimeError, ValueError) as exc:
        return None, f"invalid owner identity in {overlay.path}: {exc}"
    return owner, None


def build_agent_owner_config_snapshot(
    *,
    config_dir: Path,
    overlay_paths: list[Path],
    yaml_loader: Callable[[Path], dict[str, Any] | None],
    selector_path: Path,
    selector_text: str | None,
    selector: str | None,
) -> AgentOwnerConfigSnapshot:
    """Build the identity view from the selector and raw user overlays."""
    overlays = tuple(
        _raw_overlay_identity(path, yaml_loader(path)) for path in overlay_paths
    )
    existing_usernames = _valid_existing_usernames(overlays)

    def snapshot(
        *,
        status: AgentOwnerConfigStatus,
        detail: str,
        owner: AgentOwnerIdentity | None = None,
        selected_overlay: Path | None = None,
        matching_overlays: tuple[Path, ...] = (),
    ) -> AgentOwnerConfigSnapshot:
        return AgentOwnerConfigSnapshot(
            selector=selector,
            selector_text=selector_text,
            status=status,
            detail=detail,
            owner=owner,
            selected_overlay=selected_overlay,
            matching_overlays=matching_overlays,
            overlays=overlays,
            existing_usernames=existing_usernames,
        )

    declared = _declared_machine_names(overlays)
    declared_hint = f"; declared machines: {', '.join(declared)}" if declared else ""

    if selector_text is None:
        return snapshot(
            status="missing_selector",
            detail=f"the machine selector {selector_path} is missing{declared_hint}",
        )
    if selector is None:
        return snapshot(
            status="invalid_selector",
            detail=(
                f"the selector at {selector_path} must contain one machine "
                f"name matching {MACHINE_NAME_PATTERN}{declared_hint}"
            ),
        )

    matching = tuple(
        overlay for overlay in overlays if overlay.discriminator == selector
    )
    matching_paths = tuple(overlay.path for overlay in matching)
    if len(matching) > 1:
        paths = ", ".join(str(path) for path in matching_paths)
        usernames = {
            overlay.username for overlay in matching if overlay.username is not None
        }
        status: AgentOwnerConfigStatus = (
            "conflict" if len(usernames) > 1 else "duplicate"
        )
        label = "conflicting" if status == "conflict" else "duplicate"
        return snapshot(
            status=status,
            detail=(
                f"{label} identity overlays declare machine '{selector}': {paths}; "
                "keep exactly one machine overlay"
            ),
            matching_overlays=matching_paths,
        )

    conventional_path = config_dir / f"sase_{selector}.yml"
    conventional = next(
        (overlay for overlay in overlays if overlay.path == conventional_path),
        None,
    )
    selected = matching[0] if matching else conventional
    if selected is None:
        if declared:
            return snapshot(
                status="selector_mismatch",
                detail=(
                    f"selector '{selector}' matches no machine overlay; declared "
                    f"machines: {', '.join(declared)}"
                ),
            )
        return snapshot(
            status="missing_overlay",
            detail=f"selector '{selector}' has no machine overlay",
            selected_overlay=conventional_path,
        )

    if not selected.yaml_valid:
        return snapshot(
            status="invalid",
            detail=f"selected overlay {selected.path} is not a valid YAML mapping",
            selected_overlay=selected.path,
            matching_overlays=matching_paths,
        )
    if selected.nested_legacy_conflict:
        return snapshot(
            status="conflict",
            detail=(
                f"{selected.path} declares conflicting nested "
                f"`id.machine_name: {selected.machine_name}` and legacy "
                f"`machine_name: {selected.legacy_machine_name}` values"
            ),
            selected_overlay=selected.path,
            matching_overlays=matching_paths,
        )
    if (
        selected.machine_name_present
        and selected.machine_name is not None
        and selected.machine_name != selector
    ):
        return snapshot(
            status="selector_mismatch",
            detail=(
                f"selector '{selector}' does not match "
                f"`id.machine_name: {selected.machine_name}` in {selected.path}"
            ),
            selected_overlay=selected.path,
            matching_overlays=matching_paths,
        )

    owner, owner_error = _owner_for_overlay(selected, selector)
    if owner is not None:
        status = "legacy" if selected.legacy_machine_name_present else "complete"
        detail = (
            f"{selected.path} still contains deprecated top-level `machine_name`"
            if status == "legacy"
            else f"owner identity is configured by {selected.path}"
        )
        return snapshot(
            status=status,
            detail=detail,
            owner=owner,
            selected_overlay=selected.path,
            matching_overlays=matching_paths,
        )

    invalid_username = selected.username_present and selected.username is None
    if selected.username is not None:
        try:
            validate_agent_username(selected.username)
        except (RuntimeError, ValueError):
            invalid_username = True

    legacy = (
        selected.legacy_machine_name_present
        and selected.legacy_machine_name == selector
    )
    if invalid_username:
        status = "invalid"
        detail = f"selected overlay {selected.path} has an invalid `id.username`"
    elif legacy:
        status = "legacy"
        detail = (
            f"selected overlay {selected.path} uses deprecated top-level "
            "`machine_name` and must add `id.username`"
        )
    elif selected.id_present:
        invalid = (
            (selected.username_present and selected.username is None)
            or (selected.machine_name_present and selected.machine_name is None)
            or (
                owner_error is not None
                and owner_error.startswith("invalid owner identity")
            )
        )
        status = "invalid" if invalid else "partial"
        detail = owner_error or f"selected overlay {selected.path} is incomplete"
    else:
        status = "missing_overlay"
        detail = f"{selected.path} has no owner identity"
    return snapshot(
        status=status,
        detail=detail,
        selected_overlay=selected.path,
        matching_overlays=matching_paths,
    )


__all__ = [
    "AgentOwnerConfigSnapshot",
    "AgentOwnerConfigStatus",
    "MACHINE_NAME_PATTERN",
    "RawOverlayIdentity",
    "build_agent_owner_config_snapshot",
    "is_valid_machine_name",
    "read_machine_name_selector",
    "read_machine_name_selector_text",
]
