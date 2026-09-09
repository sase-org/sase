"""Shared types for remote-machine initialization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Literal

from sase.dispatch.models import (
    DiscoveryCandidate,
    EnrollmentResult,
    MachineDiagnostic,
    MachineRecord,
)

InputFunc = Callable[[str], str]
GetPassFunc = Callable[[str], str]
ApplyChezmoiFn = Callable[[Path | str], subprocess.CompletedProcess[str]]
CandidateDisposition = Literal["new", "enrolled", "repair"]


@dataclass(frozen=True)
class MachineInitPlan:
    """Offline machine-initialization plan (no provider or network IO)."""

    summary: str
    offer_enrollment: bool
    warnings: tuple[str, ...] = ()
    enrolled: tuple[MachineRecord, ...] = ()


@dataclass(frozen=True)
class ReconciledCandidate:
    """One discovery candidate classified against the local registry."""

    candidate: DiscoveryCandidate
    status: CandidateDisposition
    alias: str = ""
    reason: str = ""


@dataclass(frozen=True)
class MachineInitApplyResult:
    """Outcome of an explicit machine-init apply."""

    exit_code: int
    enrollments: tuple[EnrollmentResult, ...] = ()
    skipped: tuple[ReconciledCandidate, ...] = ()
    repair: tuple[ReconciledCandidate, ...] = ()
    recovery_messages: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    diagnostics: tuple[MachineDiagnostic, ...] = ()
    cancelled: bool = False
    nothing_to_enroll: bool = False
    chezmoi_proc_id: str = ""
    chezmoi_in_progress: bool = False
