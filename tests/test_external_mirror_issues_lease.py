"""Tests for issue-mirror degradation when the write-stage lease cannot be taken."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.core.retryability_facade import classify_failure_retryability
from sase.core.retryability_wire import RETRY_OPERATION_GIT
from sase.external_mirror.auth import read_tracker_probes
from sase.external_mirror.state import (
    ISSUE_MAX_BACKOFF_SECONDS,
    mirror_state_document_path,
    read_mirror_state,
)
from sase.vcs_provider.testing import FakeIssueProvider
from sase.workspace_provider.lease import OperationalLeaseError

from tests.external_mirror_issue_helpers import (
    beads,
    install_provider,
    issue,
    provider,
    run_mirror,
)
from tests.test_bead.claims_test_helpers import install_writable_bead_store

pytest_plugins = ["tests.external_mirror_issue_fixtures"]

_PUBLICKEY_DENIAL = (
    "git@ssh.github.com: Permission denied (publickey).\n"
    "fatal: Could not read from remote repository."
)


def _credential_lease_failure() -> OperationalLeaseError:
    verdict = classify_failure_retryability(
        RETRY_OPERATION_GIT, exit_status=128, stderr=_PUBLICKEY_DENIAL
    )
    return OperationalLeaseError("preparation", _PUBLICKEY_DENIAL, retryability=verdict)


def _contention_lease_failure() -> OperationalLeaseError:
    return OperationalLeaseError("allocation", "all axe workspaces are already claimed")


def _state():
    return read_mirror_state(
        mirror_state_document_path("issues", "sase"), project="sase"
    )


def _install_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    install_provider(monkeypatch, provider(FakeIssueProvider([issue(42)])))


def test_credential_lease_failure_degrades_to_auth_error_and_backs_off(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_listing(monkeypatch)
    install_writable_bead_store(
        monkeypatch, bead_store, error=_credential_lease_failure()
    )

    report = run_mirror()

    assert report.degraded == "auth_error"
    assert "Permission denied (publickey)" in report.degraded_detail
    assert report.beads_created == 0
    assert report.issues_seen == 1
    assert beads(bead_store) == []
    state = _state()
    assert state.failures == 1
    next_attempt_at = datetime.fromisoformat(state.next_attempt_at)
    assert next_attempt_at > datetime.now(UTC)
    assert not state.backfill_complete
    assert state.watermark_updated_at == ""


def test_lease_failure_is_not_recorded_as_a_tracker_probe(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_listing(monkeypatch)
    install_writable_bead_store(
        monkeypatch, bead_store, error=_credential_lease_failure()
    )

    run_mirror()

    # The listing itself succeeded; a dead SSH agent says nothing about the
    # tracker, so the probe record that drives tracker health stays "ok".
    assert read_tracker_probes()["sase"].outcome == "ok"


def test_other_lease_failure_degrades_to_lease_unavailable_and_backs_off(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_listing(monkeypatch)
    install_writable_bead_store(
        monkeypatch, bead_store, error=_contention_lease_failure()
    )

    report = run_mirror()

    assert report.degraded == "lease_unavailable"
    assert "already claimed" in report.degraded_detail
    state = _state()
    assert state.failures == 1
    assert state.next_attempt_at


def test_next_tick_after_lease_failure_short_circuits_to_backoff(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_listing(monkeypatch)
    install_writable_bead_store(
        monkeypatch, bead_store, error=_credential_lease_failure()
    )
    run_mirror()

    second = run_mirror()

    assert second.degraded == "backoff"
    assert second.provider_calls == 0
    assert _state().failures == 1


def test_repeated_lease_failures_grow_the_delay_up_to_the_cap(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_listing(monkeypatch)
    install_writable_bead_store(
        monkeypatch, bead_store, error=_credential_lease_failure()
    )

    run_mirror(full=True)
    first_delay = datetime.fromisoformat(_state().next_attempt_at) - datetime.now(UTC)
    run_mirror(full=True)
    second = _state()
    second_delay = datetime.fromisoformat(second.next_attempt_at) - datetime.now(UTC)

    assert second.failures == 2
    assert second_delay > first_delay
    assert second_delay.total_seconds() <= ISSUE_MAX_BACKOFF_SECONDS


def test_recovered_lease_creates_beads_and_clears_the_failure_streak(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_listing(monkeypatch)
    install_writable_bead_store(
        monkeypatch, bead_store, error=_credential_lease_failure()
    )
    run_mirror()
    assert _state().failures == 1

    install_writable_bead_store(monkeypatch, bead_store)
    report = run_mirror(full=True)

    assert report.degraded == ""
    assert report.beads_created == 1
    state = _state()
    assert state.failures == 0
    assert state.next_attempt_at == ""


def test_dry_run_never_reaches_the_lease_or_persists_anything(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_listing(monkeypatch)
    install_writable_bead_store(
        monkeypatch, bead_store, error=_credential_lease_failure()
    )

    report = run_mirror(dry_run=True)

    assert report.degraded == ""
    assert report.created_refs == ("bug:sase#42",)
    assert not mirror_state_document_path("issues", "sase").exists()
