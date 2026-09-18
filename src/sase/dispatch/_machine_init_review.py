"""Local review-state storage for machine-init onboarding prompts."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
from typing import Any

from sase.core.machine_setup_facade import (
    assess_machine_init_review,
    merge_machine_init_review,
)
from sase.core.paths import sase_home
from sase.core.state_write_guard import assert_test_state_write_isolated
from sase.memory.locks import locked_file

from .models import DiscoveryCandidate, MachineDiagnostic, MachineRecord

MACHINE_INIT_REVIEW_SCHEMA_VERSION = 1
_MAX_REVIEW_STATE_BYTES = 256 * 1024


class _MachineInitReviewStoreError(RuntimeError):
    """Raised when machine-init review metadata cannot be persisted."""


@dataclass(frozen=True)
class _MachineInitReviewRead:
    """Validated review state plus a user-facing warning, if any."""

    state: Mapping[str, Any] | None = None
    warning: str = ""


@dataclass(frozen=True)
class _MachineInitReviewAssessment:
    """Onboarding offer decision from persisted review state."""

    offer_enrollment: bool
    initial_review_required: bool
    unreviewed_candidates: tuple[DiscoveryCandidate, ...] = ()


def _machine_init_review_path(home: Path | None = None) -> Path:
    """Return the machine-local review-state path."""
    root = home if home is not None else sase_home()
    return root / "fleet" / "machine_init_review.json"


class MachineInitReviewStore:
    """Small locked JSON store for completed machine-init reviews."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _machine_init_review_path()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def read(self) -> _MachineInitReviewRead:
        """Read and validate state without creating files or lock paths."""
        if not self.path.exists():
            return _MachineInitReviewRead()
        try:
            state = self._read_state_unlocked()
        except _MachineInitReviewStoreError as exc:
            return _MachineInitReviewRead(
                warning=(
                    "machine init review state could not be used; "
                    f"a catch-up review is required ({exc})"
                )
            )
        return _MachineInitReviewRead(state=state)

    def assess(
        self,
        *,
        state: Mapping[str, Any] | None,
        candidates: Sequence[DiscoveryCandidate],
        enrolled: Sequence[MachineRecord],
    ) -> _MachineInitReviewAssessment:
        """Assess observed candidates through shared Rust policy."""
        result = assess_machine_init_review(
            {
                "schema_version": MACHINE_INIT_REVIEW_SCHEMA_VERSION,
                "state": dict(state) if state is not None else None,
                "candidates": [_candidate_wire(item) for item in candidates],
                "enrolled": [_enrolled_wire(item) for item in enrolled],
            }
        )
        return _MachineInitReviewAssessment(
            offer_enrollment=bool(result.get("offer_enrollment")),
            initial_review_required=bool(result.get("initial_review_required")),
            unreviewed_candidates=tuple(
                _candidate_from_wire(item)
                for item in result.get("unreviewed_candidates") or ()
                if isinstance(item, Mapping)
            ),
        )

    def record_completed_review(
        self,
        candidates: Sequence[DiscoveryCandidate],
    ) -> MachineDiagnostic | None:
        """Merge candidates from one successful review into the local record."""
        try:
            with locked_file(self.lock_path, fcntl.LOCK_EX, timeout=2.0):
                existing_state: Mapping[str, Any] | None = None
                invalid_existing = False
                if self.path.exists():
                    try:
                        existing_state = self._read_state_unlocked()
                    except _MachineInitReviewStoreError:
                        invalid_existing = True
                merged = merge_machine_init_review(
                    {
                        "schema_version": MACHINE_INIT_REVIEW_SCHEMA_VERSION,
                        "existing_state": (
                            dict(existing_state) if existing_state is not None else None
                        ),
                        "presented_candidates": [
                            _candidate_wire(item) for item in candidates
                        ],
                    }
                )
                if invalid_existing:
                    self._backup_invalid_existing()
                self._write_state(merged)
        except Exception as exc:  # noqa: BLE001 - metadata must not fail enrollment.
            return MachineDiagnostic(
                code="machine_init_review_persist_failed",
                severity="warning",
                message=(
                    "machine init review metadata could not be saved; "
                    f"future init may offer review again ({type(exc).__name__}: {exc})"
                ),
            )
        return None

    def _read_state_unlocked(self) -> Mapping[str, Any]:
        try:
            if self.path.stat().st_size > _MAX_REVIEW_STATE_BYTES:
                raise _MachineInitReviewStoreError("review state exceeds size limit")
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except _MachineInitReviewStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize parse details.
            raise _MachineInitReviewStoreError(
                f"review state could not be loaded: {type(exc).__name__}"
            ) from exc
        if not isinstance(payload, MutableMapping):
            raise _MachineInitReviewStoreError(
                "review state root must be a JSON object"
            )
        try:
            result = assess_machine_init_review(
                {
                    "schema_version": MACHINE_INIT_REVIEW_SCHEMA_VERSION,
                    "state": dict(payload),
                    "candidates": [],
                    "enrolled": [],
                }
            )
        except Exception as exc:  # noqa: BLE001 - Rust policy owns validation text.
            raise _MachineInitReviewStoreError(str(exc)) from exc
        normalized = result.get("normalized_state")
        if not isinstance(normalized, Mapping):
            raise _MachineInitReviewStoreError("review state did not validate")
        return dict(normalized)

    def _backup_invalid_existing(self) -> None:
        backup = self.path.with_name(f"{self.path.name}.invalid.{os.getpid()}.bak")
        backup.write_bytes(self.path.read_bytes())
        os.chmod(backup, 0o600)

    def _write_state(self, payload: Mapping[str, Any]) -> None:
        assert_test_state_write_isolated(
            self.path,
            category="machine init review",
        )
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        text = json.dumps(payload, indent=2, sort_keys=True)
        tmp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(f"{text}\n", encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self.path)
        os.chmod(self.path, 0o600)


def _candidate_wire(candidate: DiscoveryCandidate) -> dict[str, str]:
    return {
        "provider_ref": candidate.provider_ref,
        "endpoint": candidate.endpoint,
        "display_name": candidate.display_name,
        "machine_selector": candidate.machine_selector,
        "installation_pin": candidate.installation_pin,
        "detail": candidate.detail,
    }


def _candidate_from_wire(raw: Mapping[str, Any]) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        provider_ref=str(raw.get("provider_ref") or ""),
        endpoint=str(raw.get("endpoint") or ""),
        display_name=str(raw.get("display_name") or ""),
        machine_selector=str(raw.get("machine_selector") or ""),
        installation_pin=str(raw.get("installation_pin") or ""),
        detail=str(raw.get("detail") or ""),
    )


def _enrolled_wire(record: MachineRecord) -> dict[str, str]:
    return {
        "alias": record.alias,
        "provider_ref": record.provider_ref,
        "endpoint": record.endpoint,
        "pinned_installation_id": record.pinned_installation_id,
    }


__all__ = [
    "MACHINE_INIT_REVIEW_SCHEMA_VERSION",
    "MachineInitReviewStore",
]
