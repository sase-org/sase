"""Create-stage types and first-use defaults for the New Project wizard."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Literal

from .new_project_configure_model import ConfigureDraft

FIRST_USE_VISIBILITY = "private"

CreateAvailability = Literal["checking", "available", "taken", "unavailable"]
CreateFormStatus = Literal["loading", "ready", "unavailable"]


@dataclass(frozen=True, slots=True)
class CreateAvailabilityInfo:
    """Remote-name verdict for the canonical create target."""

    status: CreateAvailability
    reason: str = ""


@dataclass(frozen=True, slots=True)
class CreateIdentity:
    """Pure ``parse_repo_ref`` normalization of the typed create target."""

    valid: bool
    error: str = ""
    canonical_ref: str = ""
    identity_key: str = ""
    display: str = ""
    host: str = ""
    owner: str = ""
    name: str = ""
    checkout_dir: str = ""
    project_key_base: str = ""
    project_name_base: str = ""
    web_url: str = ""
    normalized_from: str = ""

    @property
    def normalized_label(self) -> str:
        """Render ``raw → canonical`` when normalization changed the text."""
        if not self.valid or not self.normalized_from:
            return ""
        return f"{self.normalized_from} → {self.canonical_ref}"


@dataclass(frozen=True, slots=True)
class CreateDraft:
    """Editable create-Configure values for one namespace owner.

    Provider form README and other option defaults stay owned by the provider
    form widget; this draft only carries the raw value map across navigation.
    SASE setup stays ``auto`` so the core create-auto recommendation applies.
    """

    owner: str = ""
    raw_name: str = ""
    visibility: str = FIRST_USE_VISIBILITY
    provider_values: dict[str, str] = dc_field(default_factory=dict)
    project: ConfigureDraft = dc_field(default_factory=ConfigureDraft)
    project_name_edited: bool = False


__all__ = [
    "FIRST_USE_VISIBILITY",
    "CreateAvailability",
    "CreateAvailabilityInfo",
    "CreateDraft",
    "CreateFormStatus",
    "CreateIdentity",
]
