"""Data model shared by ACE update-receipt helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.dev_update.models import RepoDiffStat

FORMAT_VERSION = 2
LEGACY_FORMAT_VERSION = 1
MAX_PLUGIN_LINES = 3
MAX_PROVIDER_LINES = 8

ReceiptKind = Literal["managed", "dev", "mode_switch_dev", "mode_switch_pypi"]
ProviderReceiptStatus = Literal[
    "updated",
    "already_current",
    "failed",
    "skipped",
]


@dataclass(frozen=True)
class UpdateVersionTransition:
    """A package version transition rendered by the post-update toast."""

    name: str
    old: str | None
    new: str | None
    diffstat: RepoDiffStat | None = None


@dataclass(frozen=True)
class ProviderUpdateReceiptResult:
    """Bounded provider outcome retained across an ACE code restart."""

    name: str
    display_name: str
    status: ProviderReceiptStatus
    old_version: str | None = None
    new_version: str | None = None
    reason: str | None = None
    docs_url: str | None = None
    command: tuple[str, ...] | None = None
    suggested_command: tuple[str, ...] | None = None


@dataclass(frozen=True)
class UpdateToastReceipt:
    """Serializable receipt consumed once by the restarted ACE process."""

    kind: ReceiptKind
    created_at: float
    primary: UpdateVersionTransition | None
    plugins: tuple[UpdateVersionTransition, ...] = ()
    plugin_overflow: int = 0
    plugin_overflow_diffstat: RepoDiffStat | None = None
    dependency_count: int = 0
    provider_results: tuple[ProviderUpdateReceiptResult, ...] = ()
    provider_overflow: int = 0
    format: int = FORMAT_VERSION
