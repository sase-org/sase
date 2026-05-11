"""Tests for client-scoped notification suppression filters."""

from dataclasses import dataclass

import pytest

from sase.notifications.filters import (
    ClientNotificationSnapshot,
    KNOWN_SEMANTIC_TYPES,
    NotificationCounts,
    SuppressionRule,
    classify_notification,
    compute_counts,
    filter_notifications_for_client,
    is_suppressed_for_client,
    parse_suppression_rules,
    read_notification_snapshot_for_client,
    suppressed_types_for_client,
)
from sase.notifications.models import Notification


def _n(
    *,
    sender: str = "user-agent",
    action: str | None = "JumpToAgent",
    read: bool = False,
    silent: bool = False,
    muted: bool = False,
    notif_id: str = "i",
) -> Notification:
    return Notification(
        id=notif_id,
        timestamp="t",
        sender=sender,
        action=action,
        read=read,
        silent=silent,
        muted=muted,
    )


# ---------- classify_notification / type table ---------------------------


def test_known_semantic_types_covers_initial_table() -> None:
    expected = {
        "agent_completion",
        "agent_failure",
        "plan_approval",
        "user_question",
        "mentor_review",
        "hitl",
        "sync_result",
        "axe_error_digest",
    }
    assert KNOWN_SEMANTIC_TYPES == expected


def test_classify_agent_completion() -> None:
    assert classify_notification(_n(sender="user-agent", action="JumpToAgent")) == {
        "agent_completion"
    }


def test_classify_agent_failure_is_distinct_from_axe_error_digest() -> None:
    failed = _n(sender="user-agent", action="ViewErrorReport")
    assert classify_notification(failed) == {"agent_failure"}
    axe = _n(sender="axe", action="ViewErrorReport")
    assert classify_notification(axe) == {"axe_error_digest"}


def test_classify_plan_approval_and_user_question() -> None:
    assert classify_notification(_n(sender="x", action="PlanApproval")) == {
        "plan_approval"
    }
    assert classify_notification(_n(sender="x", action="UserQuestion")) == {
        "user_question"
    }


def test_classify_sync_result_requires_sender_sync() -> None:
    assert classify_notification(_n(sender="sync", action="JumpToChangeSpec")) == {
        "sync_result"
    }
    # Same action, different sender — should not classify as sync_result.
    assert classify_notification(_n(sender="crs", action="JumpToChangeSpec")) == set()


def test_classify_unknown_action_returns_empty() -> None:
    assert classify_notification(_n(sender="random", action=None)) == set()


# ---------- parse_suppression_rules --------------------------------------


def test_parse_full_config_with_one_rule() -> None:
    rules = parse_suppression_rules(
        {
            "notifications": {
                "suppress": [
                    {"client": "tui", "types": ["agent_completion"]},
                ]
            }
        }
    )
    assert rules == [
        SuppressionRule(client="tui", types=frozenset({"agent_completion"}))
    ]


def test_parse_accepts_pre_extracted_section() -> None:
    rules = parse_suppression_rules(
        {"suppress": [{"client": "TUI", "types": ["Agent_Completion"]}]}
    )
    assert rules == [
        SuppressionRule(client="tui", types=frozenset({"agent_completion"}))
    ]


def test_parse_returns_empty_when_none_or_missing() -> None:
    assert parse_suppression_rules(None) == []
    assert parse_suppression_rules({}) == []
    assert parse_suppression_rules({"notifications": {}}) == []
    assert parse_suppression_rules({"notifications": {"suppress": None}}) == []


def test_parse_skips_malformed_entries_without_raising() -> None:
    rules = parse_suppression_rules(
        {
            "suppress": [
                "not a mapping",
                {"client": "tui"},  # no types
                {"client": "tui", "types": []},  # empty types
                {"types": ["agent_completion"]},  # no client
                {"client": "  ", "types": ["agent_completion"]},  # blank client
                {"client": "tui", "types": ["totally_unknown"]},  # unknown type only
                {"client": "tui", "types": ["agent_completion"]},  # valid
            ]
        }
    )
    assert rules == [
        SuppressionRule(client="tui", types=frozenset({"agent_completion"}))
    ]


def test_parse_keeps_unknown_clients() -> None:
    """Unknown client names parse fine — future clients work without code changes."""
    rules = parse_suppression_rules(
        {"suppress": [{"client": "smartwatch", "types": ["agent_completion"]}]}
    )
    assert rules == [
        SuppressionRule(client="smartwatch", types=frozenset({"agent_completion"}))
    ]


def test_parse_drops_unknown_types_but_keeps_known() -> None:
    rules = parse_suppression_rules(
        {"suppress": [{"client": "tui", "types": ["agent_completion", "bogus_type"]}]}
    )
    assert rules == [
        SuppressionRule(client="tui", types=frozenset({"agent_completion"}))
    ]


def test_parse_rejects_non_list_suppress() -> None:
    assert parse_suppression_rules({"suppress": "agent_completion"}) == []
    assert parse_suppression_rules({"suppress": {"client": "tui"}}) == []


# ---------- client matching / case handling ------------------------------


def test_suppressed_types_for_client_case_insensitive() -> None:
    rules = [SuppressionRule(client="tui", types=frozenset({"agent_completion"}))]
    assert suppressed_types_for_client(rules, "TUI") == frozenset({"agent_completion"})
    assert suppressed_types_for_client(rules, "tui") == frozenset({"agent_completion"})
    assert suppressed_types_for_client(rules, "telegram") == frozenset()


def test_suppressed_types_unions_multiple_rules_for_same_client() -> None:
    rules = [
        SuppressionRule(client="tui", types=frozenset({"agent_completion"})),
        SuppressionRule(client="tui", types=frozenset({"hitl"})),
        SuppressionRule(client="telegram", types=frozenset({"sync_result"})),
    ]
    assert suppressed_types_for_client(rules, "tui") == frozenset(
        {"agent_completion", "hitl"}
    )


# ---------- is_suppressed_for_client -------------------------------------


def test_is_suppressed_only_removes_matching_type() -> None:
    config = {
        "notifications": {
            "suppress": [{"client": "tui", "types": ["agent_completion"]}]
        }
    }
    completion = _n(sender="user-agent", action="JumpToAgent")
    failure = _n(sender="user-agent", action="ViewErrorReport")
    plan = _n(sender="x", action="PlanApproval")

    assert is_suppressed_for_client(completion, "tui", config=config)
    # Failed-agent rows must remain visible — agent_failure is a separate type.
    assert not is_suppressed_for_client(failure, "tui", config=config)
    assert not is_suppressed_for_client(plan, "tui", config=config)
    # Non-tui clients see everything.
    assert not is_suppressed_for_client(completion, "telegram", config=config)


def test_is_suppressed_with_empty_rules() -> None:
    completion = _n(sender="user-agent", action="JumpToAgent")
    assert not is_suppressed_for_client(completion, "tui", rules=[])


# ---------- filter_notifications_for_client ------------------------------


def test_filter_keeps_failure_drops_completion() -> None:
    rules = [SuppressionRule(client="tui", types=frozenset({"agent_completion"}))]
    completion = _n(sender="user-agent", action="JumpToAgent", notif_id="c")
    failure = _n(sender="user-agent", action="ViewErrorReport", notif_id="f")
    plan = _n(sender="x", action="PlanApproval", notif_id="p")

    filtered = filter_notifications_for_client(
        [completion, failure, plan], "tui", rules=rules
    )
    assert [n.id for n in filtered] == ["f", "p"]


def test_filter_no_rules_returns_copy_of_input() -> None:
    n = _n()
    filtered = filter_notifications_for_client([n], "tui", rules=[])
    assert filtered == [n]


# ---------- compute_counts -----------------------------------------------


def test_compute_counts_matches_rust_classification() -> None:
    rows = [
        _n(sender="x", action="PlanApproval", notif_id="p1"),  # priority
        _n(sender="x", action="UserQuestion", notif_id="p2"),  # priority
        _n(sender="axe", action="ViewErrorReport", notif_id="e1"),  # error
        _n(sender="user-agent", action="ViewErrorReport", notif_id="e2"),  # error
        _n(sender="user-agent", action="JumpToAgent", notif_id="r1"),  # rest
        _n(sender="hitl", action="HITL", notif_id="r2"),  # rest
        _n(sender="x", action=None, muted=True, notif_id="m1"),  # muted
        _n(sender="x", action="PlanApproval", read=True, notif_id="hr"),  # read → skip
        _n(
            sender="x", action="PlanApproval", silent=True, notif_id="hs"
        ),  # silent → skip
    ]
    assert compute_counts(rows) == NotificationCounts(
        priority=2, errors=2, rest=2, muted=1
    )


def test_compute_counts_after_suppression_drops_those_rows() -> None:
    rows = [
        _n(sender="user-agent", action="JumpToAgent", notif_id="c"),
        _n(sender="user-agent", action="ViewErrorReport", notif_id="f"),
        _n(sender="x", action="PlanApproval", notif_id="p"),
    ]
    rules = [SuppressionRule(client="tui", types=frozenset({"agent_completion"}))]
    filtered = filter_notifications_for_client(rows, "tui", rules=rules)
    # Completion was a "rest" row; after filtering it should not contribute.
    assert compute_counts(filtered) == NotificationCounts(
        priority=1, errors=1, rest=0, muted=0
    )
    # Raw counts without filtering would include the completion as rest=1.
    assert compute_counts(rows) == NotificationCounts(
        priority=1, errors=1, rest=1, muted=0
    )


# ---------- read_notification_snapshot_for_client ------------------------


@dataclass
class _FakeSnapshot:
    notifications: list[Notification]
    expired_ids: list[str]
    counts: object = None
    stats: object = None
    schema_version: int = 1


def test_snapshot_reader_filters_and_recomputes_counts() -> None:
    completion = _n(sender="user-agent", action="JumpToAgent", notif_id="c")
    failure = _n(sender="user-agent", action="ViewErrorReport", notif_id="f")
    plan = _n(sender="x", action="PlanApproval", notif_id="p")
    captured: dict[str, object] = {}

    def fake_reader(
        *, include_dismissed: bool, expire_due_snoozes: bool
    ) -> _FakeSnapshot:
        captured["include_dismissed"] = include_dismissed
        captured["expire_due_snoozes"] = expire_due_snoozes
        return _FakeSnapshot(
            notifications=[completion, failure, plan], expired_ids=["snz-1"]
        )

    rules = [SuppressionRule(client="tui", types=frozenset({"agent_completion"}))]
    result = read_notification_snapshot_for_client(
        "tui",
        include_dismissed=True,
        expire_due_snoozes=True,
        rules=rules,
        snapshot_reader=fake_reader,
    )
    assert isinstance(result, ClientNotificationSnapshot)
    assert [n.id for n in result.notifications] == ["f", "p"]
    assert result.counts == NotificationCounts(priority=1, errors=1, rest=0, muted=0)
    assert result.expired_ids == ["snz-1"]
    # Snooze-expiry args propagate to the underlying reader.
    assert captured == {"include_dismissed": True, "expire_due_snoozes": True}


def test_snapshot_reader_preserves_all_rows_for_unfiltered_client() -> None:
    completion = _n(sender="user-agent", action="JumpToAgent", notif_id="c")

    def fake_reader(
        *, include_dismissed: bool = False, expire_due_snoozes: bool = False
    ) -> _FakeSnapshot:
        del include_dismissed, expire_due_snoozes
        return _FakeSnapshot(notifications=[completion], expired_ids=[])

    rules = [SuppressionRule(client="tui", types=frozenset({"agent_completion"}))]
    # Telegram has no suppression rules — should see everything.
    result = read_notification_snapshot_for_client(
        "telegram", rules=rules, snapshot_reader=fake_reader
    )
    assert [n.id for n in result.notifications] == ["c"]
    assert result.counts == NotificationCounts(rest=1)


def test_counts_to_wire_matches_wire_dataclass() -> None:
    from sase.core.notification_store_wire import NotificationCountsWire

    counts = NotificationCounts(priority=3, errors=1, rest=2, muted=4)
    wire = counts.to_wire()
    assert isinstance(wire, NotificationCountsWire)
    assert wire == NotificationCountsWire(priority=3, errors=1, rest=2, muted=4)


# ---------- regression markers ------------------------------------------


@pytest.mark.parametrize(
    "sender,action,expected_type",
    [
        ("user-agent", "JumpToAgent", "agent_completion"),
        ("user-agent", "ViewErrorReport", "agent_failure"),
        ("plan", "PlanApproval", "plan_approval"),
        ("q", "UserQuestion", "user_question"),
        ("m", "JumpToMentorReview", "mentor_review"),
        ("h", "HITL", "hitl"),
        ("sync", "JumpToChangeSpec", "sync_result"),
        ("axe", "ViewErrorReport", "axe_error_digest"),
    ],
)
def test_type_table_matches_design_doc(
    sender: str, action: str, expected_type: str
) -> None:
    assert expected_type in classify_notification(_n(sender=sender, action=action))
