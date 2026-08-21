"""Ledger invariants for aggregate_finalizer_outcomes.

Kept off the contract set: published sase-core-rs 0.29.9 exports the
binding but does not reject duplicate or terminal-mismatched attempts.
Release-core-floor-smoke installs that wheel, so this stays a local/dev
gate until a floor that enforces the ledger ships.
"""

from __future__ import annotations

import pytest

from sase.core.finalizer_facade import aggregate_finalizer_outcomes
from sase.core.finalizer_wire import FinalizerAttemptWire, FinalizerInstanceResultWire


def test_finalizer_facade_rejects_incoherent_attempt_ledgers() -> None:
    with pytest.raises(ValueError, match="unique and increasing"):
        aggregate_finalizer_outcomes(
            [
                FinalizerInstanceResultWire(
                    instance_id="lint",
                    status="failed",
                    attempts=[
                        FinalizerAttemptWire(attempt=1, status="failed"),
                        FinalizerAttemptWire(attempt=1, status="failed"),
                    ],
                )
            ]
        )
    with pytest.raises(ValueError, match="terminal status"):
        aggregate_finalizer_outcomes(
            [
                FinalizerInstanceResultWire(
                    instance_id="lint",
                    status="failed",
                    attempts=[FinalizerAttemptWire(attempt=1, status="success")],
                )
            ]
        )
    with pytest.raises(ValueError, match="skipped status cannot record attempts"):
        aggregate_finalizer_outcomes(
            [
                FinalizerInstanceResultWire(
                    instance_id="lint",
                    status="skipped",
                    attempts=[FinalizerAttemptWire(attempt=1, status="skipped")],
                )
            ]
        )
