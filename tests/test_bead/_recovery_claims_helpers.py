"""Shared fixtures and builders for recovery-claim publication tests.

Split from ``tests.test_bead.test_recovery_claims``; the original module
re-exports its tests so its import path keeps working.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_recovery_claims_*`` split modules can share them
without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import json
import threading
from typing import Any

import pytest

from sase.core.recovery_facade import (
    RecoveryActivation,
    RecoveryActivationInspect,
    RecoveryArmResult,
    RecoveryClaim,
    RecoveryClaimCreateResult,
    RecoveryClaimInspect,
)


def claim_key(project_id: str, epic_id: str, close_token: str) -> str:
    digest = sha256()
    digest.update(project_id.encode())
    digest.update(b"\x00")
    digest.update(epic_id.encode())
    digest.update(b"\x00")
    digest.update(close_token.encode())
    return digest.hexdigest()


class FakeRecoveryCore:
    """In-process create-if-absent store matching the Rust recovery layout."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def inspect_activation(
        self, beads_dir: str, project_id: str
    ) -> RecoveryActivationInspect:
        path = Path(beads_dir) / "recovery" / "activation.json"
        if not path.exists():
            return RecoveryActivationInspect(
                project_id=project_id, state="absent", recovery_enabled=False
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            activation = RecoveryActivation(
                project_id=payload["project_id"],
                armed_at=payload["armed_at"],
                generation=int(payload["generation"]),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return RecoveryActivationInspect(
                project_id=project_id,
                state="malformed",
                recovery_enabled=False,
                diagnostic=str(exc),
            )
        if activation.project_id != project_id:
            return RecoveryActivationInspect(
                project_id=project_id,
                state="malformed",
                recovery_enabled=False,
                diagnostic="project mismatch",
            )
        return RecoveryActivationInspect(
            project_id=project_id,
            state="armed",
            recovery_enabled=True,
            activation=activation,
        )

    def arm(self, beads_dir: str, request: dict[str, Any]) -> RecoveryArmResult:
        with self._lock:
            inspect = self.inspect_activation(beads_dir, str(request["project_id"]))
            if inspect.state == "malformed":
                return RecoveryArmResult(
                    state="malformed",
                    created=False,
                    recovery_enabled=False,
                    diagnostic=inspect.diagnostic,
                )
            if inspect.activation is not None:
                return RecoveryArmResult(
                    state="existing",
                    created=False,
                    recovery_enabled=True,
                    activation=inspect.activation,
                )
            activation = RecoveryActivation(
                project_id=str(request["project_id"]),
                armed_at=str(request.get("armed_at") or "2026-11-28T00:00:00Z"),
                generation=int(request.get("generation") or 1),
            )
            path = Path(beads_dir) / "recovery" / "activation.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(asdict(activation), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return RecoveryArmResult(
                state="created",
                created=True,
                recovery_enabled=True,
                activation=activation,
            )

    def inspect_claim(
        self, beads_dir: str, request: dict[str, Any]
    ) -> RecoveryClaimInspect:
        key = claim_key(
            str(request.get("project_id") or ""),
            str(request.get("epic_id") or ""),
            str(request.get("close_token") or ""),
        )
        path = Path(beads_dir) / "recovery" / "claims" / f"{key}.json"
        if not path.exists():
            return RecoveryClaimInspect(
                claim_key=key,
                project_id=str(request.get("project_id") or ""),
                epic_id=str(request.get("epic_id") or ""),
                close_token=str(request.get("close_token") or ""),
                state="absent",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            claim = RecoveryClaim(
                project_id=payload["project_id"],
                epic_id=payload["epic_id"],
                close_token=payload["close_token"],
                owner_machine=payload["owner_machine"],
                proc_id=payload["proc_id"],
                request_fingerprint=payload["request_fingerprint"],
                activation_generation=int(payload["activation_generation"]),
                created_at=payload["created_at"],
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return RecoveryClaimInspect(
                claim_key=key,
                project_id=str(request.get("project_id") or ""),
                epic_id=str(request.get("epic_id") or ""),
                close_token=str(request.get("close_token") or ""),
                state="malformed",
                diagnostic=str(exc),
            )
        return RecoveryClaimInspect(
            claim_key=key,
            project_id=claim.project_id,
            epic_id=claim.epic_id,
            close_token=claim.close_token,
            state="present",
            claim=claim,
        )

    def create(
        self, beads_dir: str, request: dict[str, Any]
    ) -> RecoveryClaimCreateResult:
        if not str(request.get("close_token") or "").strip():
            return RecoveryClaimCreateResult(
                claim_key="",
                state="refused",
                created=False,
                local_winner=False,
                diagnostic="recovery close_token must be a non-empty string",
            )
        with self._lock:
            activation = self.inspect_activation(beads_dir, str(request["project_id"]))
            if not activation.recovery_enabled or activation.activation is None:
                return RecoveryClaimCreateResult(
                    claim_key="",
                    state="refused",
                    created=False,
                    local_winner=False,
                    diagnostic="recovery activation is absent",
                )
            existing = self.inspect_claim(beads_dir, request)
            if existing.state == "malformed":
                return RecoveryClaimCreateResult(
                    claim_key=existing.claim_key,
                    state="malformed",
                    created=False,
                    local_winner=False,
                    diagnostic=existing.diagnostic,
                )
            if existing.claim is not None:
                winner = (
                    existing.claim.owner_machine == request["owner_machine"]
                    and existing.claim.proc_id == request["proc_id"]
                    and existing.claim.request_fingerprint
                    == request["request_fingerprint"]
                )
                return RecoveryClaimCreateResult(
                    claim_key=existing.claim_key,
                    state="existing",
                    created=False,
                    local_winner=winner,
                    claim=existing.claim,
                )
            claim = RecoveryClaim(
                project_id=str(request["project_id"]),
                epic_id=str(request["epic_id"]),
                close_token=str(request["close_token"]),
                owner_machine=str(request["owner_machine"]),
                proc_id=str(request["proc_id"]),
                request_fingerprint=str(request["request_fingerprint"]),
                activation_generation=activation.activation.generation,
                created_at=str(request.get("created_at") or "2026-11-28T12:00:00Z"),
            )
            key = claim_key(claim.project_id, claim.epic_id, claim.close_token)
            path = Path(beads_dir) / "recovery" / "claims" / f"{key}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(asdict(claim), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return RecoveryClaimCreateResult(
                claim_key=key,
                state="created",
                created=True,
                local_winner=True,
                claim=claim,
            )


@pytest.fixture(name="fake_core")
def recovery_fake_core(monkeypatch: pytest.MonkeyPatch) -> FakeRecoveryCore:
    core = FakeRecoveryCore()
    monkeypatch.setattr("sase.bead.recovery.arm_recovery_activation", core.arm)
    monkeypatch.setattr(
        "sase.bead.recovery.inspect_recovery_activation",
        core.inspect_activation,
    )
    monkeypatch.setattr("sase.bead.recovery.create_recovery_claim", core.create)
    monkeypatch.setattr("sase.bead.recovery.inspect_recovery_claim", core.inspect_claim)
    return core


def claim_request(
    *,
    project_id: str = "alpha",
    epic_id: str = "demo-1",
    close_token: str = "demo-1.1:evt-1",
    owner: str = "athena",
    proc_id: str = "proc-a",
) -> dict[str, str]:
    return {
        "project_id": project_id,
        "epic_id": epic_id,
        "close_token": close_token,
        "owner_machine": owner,
        "proc_id": proc_id,
        "request_fingerprint": f"fp-{proc_id}",
    }
