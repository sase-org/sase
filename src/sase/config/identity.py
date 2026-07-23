"""Immutable models for selected-overlay owner identity configuration."""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.core.agent_identity_facade import AgentOwnerIdentity

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


__all__ = [
    "AgentOwnerConfigSnapshot",
    "AgentOwnerConfigStatus",
    "MACHINE_NAME_PATTERN",
    "RawOverlayIdentity",
    "is_valid_machine_name",
    "read_machine_name_selector",
    "read_machine_name_selector_text",
]
