"""The publication cleanup cap is Rust-owned and its binding is required.

Regression coverage for the sase-1qt landing: a missing or raising
``default_publication_cleanup_timeout`` binding used to fall back to an
invented Python ``1.0`` at two layers, and an explicit Python timeout could
exceed a smaller Rust cap.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import time
from typing import Any

import pytest

from sase.agents_sync import (
    _commit_publication_drain as publication_drain,
    _commit_publication_locked as publication_locked,
    _commit_publication_support as publication_support,
    git_sync,
    git_sync_transaction,
)
from sase.agents_sync.commit_publication import publish_committed_agent_hood
from sase.agents_sync.git import run_git
from sase.agents_sync.models import TargetSelection
from sase.agents_sync.publication_cleanup import PublicationCleanupBudget
from sase.agents_sync.publication_outbox import list_agent_publications
from sase.core import agent_publication_recovery as recovery
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.commit_publication_fixtures import setup_target

_BINDING = "default_publication_cleanup_timeout"
_MISSING = (
    "sase_core_rs is importable but does not expose binding "
    f"{_BINDING!r}; the installed wheel is stale"
)


def _patch_cleanup_binding(
    monkeypatch: pytest.MonkeyPatch,
    behavior: Callable[[], Any],
) -> list[str]:
    """Replace only the cleanup-policy binding; every other binding stays real."""
    real = recovery.require_rust_binding
    lookups: list[str] = []

    def fake(name: str) -> Any:
        if name != _BINDING:
            return real(name)
        lookups.append(name)
        return behavior

    monkeypatch.setattr(recovery, "require_rust_binding", fake)
    return lookups


def _raise_missing(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    real = recovery.require_rust_binding
    lookups: list[str] = []

    def fake(name: str) -> Any:
        if name != _BINDING:
            return real(name)
        lookups.append(name)
        raise AttributeError(_MISSING)

    monkeypatch.setattr(recovery, "require_rust_binding", fake)
    return lookups


def _configure_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    owner: AgentOwnerIdentity,
):
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = setup_target(tmp_path)
    monkeypatch.setattr(
        publication_support,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        publication_support,
        "require_agent_owner_identity",
        lambda: owner,
    )
    return target, remote


def _assert_sidecar_lock_released(target) -> None:
    lock_path = (
        git_sync.agents_git_dir(target.sidecar_path, run_git) / "sase-agents-sync.lock"
    )
    with git_sync.bounded_agents_lock(lock_path, 1.0) as acquired:
        assert acquired, "the drain must release sase-agents-sync.lock"


def test_the_real_binding_supplies_the_one_second_cap() -> None:
    assert recovery.default_publication_cleanup_timeout() == 1.0
    assert PublicationCleanupBudget().timeout == 1.0


def test_missing_binding_is_exposed_by_the_adapter_and_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups = _raise_missing(monkeypatch)

    with pytest.raises(AttributeError, match="does not expose binding"):
        recovery.default_publication_cleanup_timeout()
    # No invented Python default at either layer, with or without an override.
    with pytest.raises(AttributeError, match="does not expose binding"):
        PublicationCleanupBudget()
    with pytest.raises(AttributeError, match="does not expose binding"):
        PublicationCleanupBudget(0.5)

    assert len(lookups) == 3


def test_raising_binding_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> float:
        raise RuntimeError("binding exploded")

    _patch_cleanup_binding(monkeypatch, boom)

    with pytest.raises(RuntimeError, match="binding exploded"):
        recovery.default_publication_cleanup_timeout()
    with pytest.raises(RuntimeError, match="binding exploded"):
        PublicationCleanupBudget()


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("1.0", "non-numeric"),
        (None, "non-numeric"),
        (True, "non-numeric"),
        (0.0, "invalid"),
        (-1.0, "invalid"),
        (float("nan"), "invalid"),
        (float("inf"), "invalid"),
    ],
)
def test_malformed_binding_values_are_rejected_not_defaulted(
    monkeypatch: pytest.MonkeyPatch,
    value: object,
    message: str,
) -> None:
    _patch_cleanup_binding(monkeypatch, lambda: value)

    with pytest.raises(RuntimeError, match=message):
        recovery.default_publication_cleanup_timeout()
    with pytest.raises(RuntimeError, match=message):
        PublicationCleanupBudget()


def test_an_override_can_shorten_but_never_exceed_the_rust_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cleanup_binding(monkeypatch, lambda: 0.25)

    assert PublicationCleanupBudget().timeout == 0.25
    assert PublicationCleanupBudget(0.8).timeout == 0.25
    assert PublicationCleanupBudget(0.1).timeout == 0.1
    assert PublicationCleanupBudget(float("inf")).timeout == 0.25
    # An absolute deadline is the caller's, but the reported timeout stays capped.
    budget = PublicationCleanupBudget(5.0, deadline=time.monotonic() + 0.05)
    assert budget.timeout == 0.25
    assert budget.remaining() <= 0.05


@pytest.mark.parametrize("override", [0.0, -1.0, float("nan")])
def test_a_non_positive_override_is_refused_instead_of_replaced_by_a_default(
    monkeypatch: pytest.MonkeyPatch,
    override: float,
) -> None:
    _patch_cleanup_binding(monkeypatch, lambda: 0.25)

    with pytest.raises(ValueError, match="must be positive"):
        PublicationCleanupBudget(override)


def test_policy_lookup_failure_keeps_the_original_publication_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = _configure_target(monkeypatch, tmp_path, owner)
    cleanup_calls = 0
    real_clean = git_sync.clean_publication_worktree

    def counting_clean(*args: Any, **kwargs: Any):
        nonlocal cleanup_calls
        cleanup_calls += 1
        return real_clean(*args, **kwargs)

    def fail_publish(*_args: Any, **_kwargs: Any):
        raise RuntimeError("original publication failure")

    monkeypatch.setattr(git_sync, "clean_publication_worktree", counting_clean)
    monkeypatch.setattr(publication_locked, "publish_queued_transaction", fail_publish)
    lookups = _raise_missing(monkeypatch)

    with pytest.raises(RuntimeError, match="original publication failure") as caught:
        publish_committed_agent_hood(
            "foo--code",
            "a" * 40,
            project="Project",
            git_runner=run_git,
        )

    notes = "\n".join(caught.value.__notes__)
    assert "publication cleanup also failed" in notes
    assert "does not expose binding" in notes
    # Only the pre-transaction payload clean ran: no exception cleanup ran with
    # an invented default budget.
    assert lookups == [_BINDING]
    assert cleanup_calls == 1
    assert len(list_agent_publications("proj")) == 1
    _assert_sidecar_lock_released(target)


def test_policy_lookup_failure_preserves_drain_timeout_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = _configure_target(monkeypatch, tmp_path, owner)
    timings: list = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)

    def blocked_render(*_args: Any, **_kwargs: Any):
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout

    monkeypatch.setattr(publication_locked, "publish_agent_hood", blocked_render)
    monkeypatch.setattr(
        publication_drain,
        "_configured_publication_drain_timeout",
        lambda: 1.0,
    )
    lookups = _raise_missing(monkeypatch)

    started = time.perf_counter()
    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0
    assert lookups == [_BINDING]
    assert outcome.queued and not outcome.published
    # The drain timeout stays the primary error; the lookup failure rides along
    # as cleanup diagnostics instead of replacing it.
    assert outcome.error is not None
    assert outcome.error.startswith("agent-hood publication did not complete within")
    assert "publication cleanup also failed" in outcome.error
    assert "does not expose binding" in outcome.error
    assert timings and timings[-1].alarm_fired
    assert timings[-1].outcome == "timeout"
    queued = list_agent_publications("proj")
    assert len(queued) == 1
    assert queued[0].attempts == 1
    _assert_sidecar_lock_released(target)


def test_a_smaller_rust_cap_bounds_a_stalled_cleanup_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared deadline follows the Rust cap, not a Python-side one second."""
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = _configure_target(monkeypatch, tmp_path, owner)
    timings: list = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)
    _patch_cleanup_binding(monkeypatch, lambda: 0.25)

    def blocked_render(*_args: Any, **_kwargs: Any):
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout

    calls = {"count": 0}

    def stalled_agents_cleanup(_repo: Path, _runner: Any, **_kwargs: Any):
        calls["count"] += 1
        if calls["count"] == 1:
            return None  # the pre-transaction payload clean
        time.sleep(5)  # sase-test-wait: stalled cleanup must be bounded
        return "agents cleanup stalled"

    monkeypatch.setattr(publication_locked, "publish_agent_hood", blocked_render)
    monkeypatch.setattr(
        git_sync_transaction,
        "clean_agents_payload_worktree",
        stalled_agents_cleanup,
    )
    monkeypatch.setattr(
        publication_drain,
        "_configured_publication_drain_timeout",
        lambda: 1.0,
    )

    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )

    assert outcome.queued and not outcome.published
    assert outcome.error is not None and "did not complete within" in outcome.error
    assert timings and timings[-1].alarm_fired
    assert timings[-1].outcome == "timeout"
    cleanup_seconds = timings[-1].stage_durations.get("cleanup", 0.0)
    assert cleanup_seconds < 0.9, (
        f"cleanup ignored the 0.25s Rust cap: {cleanup_seconds:.2f}s"
    )
    assert len(list_agent_publications("proj")) == 1
    _assert_sidecar_lock_released(target)
