"""Selection and failure accounting tests for publication recovery."""

from __future__ import annotations

from sase.core.agent_publication_recovery import (
    PUBLICATION_ERROR_LOCK_BUSY,
    PUBLICATION_ERROR_TIMEOUT,
    PUBLICATION_FAILURE_SCOPE_HOOD,
    PUBLICATION_FAILURE_SCOPE_REPOSITORY,
    PUBLICATION_LIFECYCLE_ACTIVE,
    classify_publication_error,
    classify_stale_publication_request,
    decide_publication_failure_accounting,
    select_publication_drain,
    select_publication_retries,
)


def test_select_publication_retries_revives_only_requested_classes() -> None:
    selected = select_publication_retries(
        (
            {
                "global_agent": "alice.athena.foo",
                "primary_revision": "a" * 40,
                "terminal": True,
                "quarantined": False,
                "last_error": "legacy mismatch",
                "terminal_reason": "legacy mismatch",
            },
            {
                "global_agent": "alice.athena.bar",
                "primary_revision": "b" * 40,
                "terminal": False,
                "quarantined": True,
                "last_error": "push rejected",
                "terminal_reason": None,
            },
            {
                "global_agent": "alice.athena.live",
                "primary_revision": "c" * 40,
                "terminal": False,
                "quarantined": False,
                "last_error": None,
                "terminal_reason": None,
            },
        ),
        retry_retired=True,
        retry_quarantined=False,
    )

    assert len(selected) == 1
    assert selected[0].global_agent == "alice.athena.foo"
    assert selected[0].prior_class == "retired"
    assert selected[0].prior_failure == "legacy mismatch"
    assert selected[0].error_class == "other"


def test_select_publication_retries_applies_limit_after_error_class_filter() -> None:
    selected = select_publication_retries(
        (
            {
                "global_agent": "alice.athena.timeout",
                "primary_revision": "a" * 40,
                "terminal": False,
                "quarantined": True,
                "last_error": "agent-hood publication did not complete within 120s",
                "created_at": 2.0,
            },
            {
                "global_agent": "alice.athena.other",
                "primary_revision": "b" * 40,
                "terminal": True,
                "quarantined": False,
                "last_error": "legacy mismatch",
                "terminal_reason": "legacy mismatch",
                "created_at": 1.0,
            },
            {
                "global_agent": "alice.athena.lock",
                "primary_revision": "c" * 40,
                "terminal": False,
                "quarantined": True,
                "last_error": "agents sync lock is busy",
                "created_at": 3.0,
            },
        ),
        retry_retired=True,
        retry_quarantined=True,
        limit=1,
        error_classes=(PUBLICATION_ERROR_TIMEOUT, PUBLICATION_ERROR_LOCK_BUSY),
    )
    assert len(selected) == 1
    assert selected[0].global_agent == "alice.athena.timeout"
    assert selected[0].error_class == PUBLICATION_ERROR_TIMEOUT


def test_classify_publication_error_covers_uncommitted_index_changes() -> None:
    assert classify_publication_error(None) == "unknown"
    assert (
        classify_publication_error("error: Your index contains uncommitted changes.")
        == "unstaged_changes"
    )
    assert (
        classify_publication_error("could not stage: .git/index.lock exists")
        == "index_lock"
    )


def test_repository_scope_does_not_charge_attempted_keys() -> None:
    decision = decide_publication_failure_accounting(
        scope=PUBLICATION_FAILURE_SCOPE_REPOSITORY,
        error="agents sync lock is busy",
        attempted_keys=(("alice.athena.foo", "a" * 40),),
        rows=(
            {
                "global_agent": "alice.athena.foo",
                "primary_revision": "a" * 40,
                "attempts": 2,
                "last_error": "prior",
            },
        ),
        quarantine_threshold=3,
    )
    assert decision.scope == PUBLICATION_FAILURE_SCOPE_REPOSITORY
    assert not decision.charge
    assert decision.charges == ()
    assert decision.error_class == PUBLICATION_ERROR_LOCK_BUSY


def test_hood_scope_charges_only_supplied_keys() -> None:
    error = "hood 'foo' has no publishable runs"
    decision = decide_publication_failure_accounting(
        scope=PUBLICATION_FAILURE_SCOPE_HOOD,
        error=error,
        format_error=True,
        attempted_keys=(("alice.athena.foo", "a" * 40),),
        rows=(
            {
                "global_agent": "alice.athena.foo",
                "primary_revision": "a" * 40,
                "attempts": 1,
                "last_error": error,
            },
            {
                "global_agent": "alice.athena.other",
                "primary_revision": "b" * 40,
                "attempts": 2,
                "last_error": error,
            },
        ),
        quarantine_threshold=3,
    )
    assert decision.charge
    assert len(decision.charges) == 1
    assert decision.charges[0].retire
    assert not decision.charges[0].quarantine
    assert decision.charges[0].attempts == 2


def test_select_publication_drain_prefers_new_then_active_then_stopped() -> None:
    selected = select_publication_drain(
        (
            {
                "global_agent": "alice.athena.old",
                "primary_revision": "a" * 40,
                "terminal": False,
                "quarantined": False,
                "last_error": None,
                "created_at": 1.0,
            },
            {
                "global_agent": "alice.athena.new",
                "primary_revision": "b" * 40,
                "terminal": False,
                "quarantined": False,
                "last_error": None,
                "created_at": 5.0,
            },
            {
                "global_agent": "alice.athena.retired",
                "primary_revision": "c" * 40,
                "terminal": True,
                "quarantined": False,
                "last_error": "legacy mismatch",
                "terminal_reason": "legacy mismatch",
                "created_at": 0.5,
            },
        ),
        limit=2,
        preferred_key=("alice.athena.new", "b" * 40),
        retry_retired=True,
        retry_quarantined=True,
    )
    assert [item.global_agent for item in selected.active] == [
        "alice.athena.new",
        "alice.athena.old",
    ]
    assert selected.revive == ()
    assert selected.active[0].prior_class == PUBLICATION_LIFECYCLE_ACTIVE


def test_select_publication_drain_exact_key_ignores_unrelated_active_rows() -> None:
    target_revision = "c" * 40
    selected = select_publication_drain(
        (
            {
                "global_agent": "alice.athena.active",
                "primary_revision": "a" * 40,
                "terminal": False,
                "quarantined": False,
                "last_error": "agents sync lock is busy",
                "created_at": 2.0,
            },
            {
                "global_agent": "alice.athena.target",
                "primary_revision": target_revision,
                "terminal": False,
                "quarantined": True,
                "last_error": "agent-hood publication did not complete within 120s",
                "created_at": 1.0,
            },
        ),
        limit=2,
        exact_key=("alice.athena.target", target_revision),
        retry_quarantined=True,
        error_classes=(PUBLICATION_ERROR_TIMEOUT,),
    )
    assert [item.global_agent for item in selected.revive] == ["alice.athena.target"]
    assert selected.active == ()


def test_select_publication_drain_missing_exact_key_is_empty() -> None:
    selected = select_publication_drain(
        (
            {
                "global_agent": "alice.athena.active",
                "primary_revision": "a" * 40,
                "terminal": False,
                "quarantined": False,
                "last_error": None,
                "created_at": 1.0,
            },
        ),
        limit=1,
        exact_key=("alice.athena.gone", "b" * 40),
        retry_quarantined=True,
        retry_retired=True,
    )
    assert selected.active == ()
    assert selected.revive == ()


def test_select_publication_drain_no_match_is_empty() -> None:
    selected = select_publication_drain(
        (
            {
                "global_agent": "alice.athena.bar",
                "primary_revision": "b" * 40,
                "terminal": False,
                "quarantined": True,
                "last_error": "push rejected",
            },
        ),
        limit=25,
        retry_retired=True,
        error_classes=(PUBLICATION_ERROR_TIMEOUT,),
    )
    assert selected.active == ()
    assert selected.revive == ()


def test_stale_repair_classifies_parent_rebased_linked_and_unknown() -> None:
    repaired = classify_stale_publication_request(
        requested_revision="a" * 40,
        scope="revision",
        run_commit_shas=["b" * 40, "c" * 40],
        ancestor_commit_shas=["c" * 40],
    )
    assert repaired.action == "repaired"
    assert repaired.fulfilling_revision == "c" * 40
    assert repaired.evidence_commit == "c" * 40

    assert (
        classify_stale_publication_request(
            requested_revision="b" * 40,
            scope="revision",
            run_commit_shas=["b" * 40],
        ).action
        == "unchanged"
    )
    assert (
        classify_stale_publication_request(
            requested_revision="c" * 40,
            scope="linked",
        ).action
        == "unchanged"
    )
    assert (
        classify_stale_publication_request(
            requested_revision="c" * 40,
            scope="revision",
            run_commit_shas=["b" * 40],
            linked_revision=True,
        ).action
        == "linked"
    )
    unknown = classify_stale_publication_request(
        requested_revision="d" * 40,
        scope="revision",
        run_commit_shas=["b" * 40],
    )
    assert unknown.action == "unresolved"
    assert unknown.fulfilling_revision is None
