import json
from pathlib import Path
from unittest.mock import patch

from sase.core.notification_store_wire import (
    NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
    NotificationUpdateOutcomeWire,
)
from sase.notifications.store import (
    append_notification,
    dismiss_agent_completion_notifications,
    dismiss_notifications_matching_agents,
    load_notifications,
    mark_read,
    rewrite_notifications,
)

from .helpers import make_notification


class TestAppendNotification:
    """Tests for append_notification()."""

    def test_silent_notification_round_trip(self, temp_notifications_dir: Path) -> None:
        """Silent notifications are stored and loaded back with silent=True."""
        n = make_notification(silent=True)
        append_notification(n)
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].silent is True

    def test_non_silent_notification_round_trip(
        self, temp_notifications_dir: Path
    ) -> None:
        """Non-silent notifications default to silent=False after round-trip."""
        n = make_notification()
        append_notification(n)
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].silent is False

    def test_routes_through_rust_facade(self, temp_notifications_dir: Path) -> None:
        import sase.notifications.store as store

        n = make_notification()
        with patch(
            "sase.notifications.store._rust_append_notification",
            wraps=store._rust_append_notification,
        ) as mock_append:
            append_notification(n)

        mock_append.assert_called_once()


class TestLoadNotifications:
    """Tests for load_notifications()."""

    def test_skips_invalid_json(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        jsonl = temp_notifications_dir / "notifications" / "notifications.jsonl"
        with open(jsonl, "a") as f:
            f.write("NOT VALID JSON\n")
        loaded = load_notifications()
        assert len(loaded) == 1

    def test_skips_missing_fields(self, temp_notifications_dir: Path) -> None:
        jsonl = temp_notifications_dir / "notifications" / "notifications.jsonl"
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        with open(jsonl, "w") as f:
            f.write(json.dumps({"id": "abc"}) + "\n")
        loaded = load_notifications()
        assert len(loaded) == 0

    def test_skips_blank_lines(self, temp_notifications_dir: Path) -> None:
        n = make_notification()
        append_notification(n)
        jsonl = temp_notifications_dir / "notifications" / "notifications.jsonl"
        with open(jsonl, "a") as f:
            f.write("\n\n")
        loaded = load_notifications()
        assert len(loaded) == 1


class TestRewriteNotifications:
    """Tests for rewrite_notifications()."""

    def test_routes_through_rust_facade(self, temp_notifications_dir: Path) -> None:
        import sase.notifications.store as store

        n = make_notification()
        with patch(
            "sase.notifications.store._rust_rewrite_notifications",
            wraps=store._rust_rewrite_notifications,
        ) as mock_rewrite:
            rewrite_notifications([n])

        mock_rewrite.assert_called_once()
        assert load_notifications()[0].id == n.id


class TestRustBackedCache:
    """Tests for cache behavior around Rust-backed writes."""

    def test_rust_write_invalidates_cached_snapshot(
        self, temp_notifications_dir: Path
    ) -> None:
        import sase.notifications.store as store

        n = make_notification()
        append_notification(n)
        outcome = NotificationUpdateOutcomeWire(
            schema_version=NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
            matched_count=1,
            changed_count=1,
            rewritten=True,
        )

        with (
            patch(
                "sase.notifications.store._rust_read_notifications_snapshot",
                wraps=store._rust_read_notifications_snapshot,
            ) as mock_read,
            patch(
                "sase.notifications.store._rust_apply_notification_state_update",
                return_value=outcome,
            ),
        ):
            assert load_notifications()[0].id == n.id
            assert load_notifications()[0].id == n.id
            assert mock_read.call_count == 1

            assert mark_read(n.id) is True
            assert load_notifications()[0].id == n.id
            assert mock_read.call_count == 2


class TestDismissNotificationsMatchingAgents:
    """Tests for Rust-backed bulk agent notification dismissal."""

    def test_dismisses_matching_agent_notifications(
        self, temp_notifications_dir: Path
    ) -> None:
        append_notification(
            make_notification(
                id="jump",
                action="JumpToAgent",
                action_data={"cl_name": "cl", "raw_suffix": "20260430120000"},
            )
        )
        append_notification(
            make_notification(
                id="other",
                action="JumpToAgent",
                action_data={"cl_name": "other", "raw_suffix": "20260430120000"},
            )
        )

        count = dismiss_notifications_matching_agents(
            [{"cl_name": "cl", "raw_suffix": "20260430120000"}]
        )

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 1
        assert by_id["jump"].dismissed is True
        assert by_id["other"].dismissed is False

    def test_dismisses_user_agent_view_error_report(
        self, temp_notifications_dir: Path
    ) -> None:
        append_notification(
            make_notification(
                id="err",
                sender="user-agent",
                action="ViewErrorReport",
                action_data={"cl_name": "cl", "raw_suffix": "20260430120000"},
            )
        )
        append_notification(
            make_notification(
                id="axe-err",
                sender="axe",
                action="ViewErrorReport",
                action_data={"error_report_path": "/tmp/x"},
            )
        )

        count = dismiss_notifications_matching_agents(
            [{"cl_name": "cl", "raw_suffix": "20260430120000"}]
        )

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 1
        assert by_id["err"].dismissed is True
        assert by_id["axe-err"].dismissed is False


class TestDismissAgentCompletionNotifications:
    """Tests for bulk dismissal of all agent completion notifications."""

    def test_dismisses_jump_and_error_completions(
        self, temp_notifications_dir: Path
    ) -> None:
        append_notification(
            make_notification(
                id="jump",
                sender="user-agent",
                action="JumpToAgent",
                action_data={"cl_name": "a", "raw_suffix": "20260430120000"},
            )
        )
        append_notification(
            make_notification(
                id="err",
                sender="user-agent",
                action="ViewErrorReport",
                action_data={"cl_name": "b", "raw_suffix": "20260430120001"},
            )
        )

        count = dismiss_agent_completion_notifications()

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 2
        assert by_id["jump"].dismissed is True
        assert by_id["err"].dismissed is True

    def test_leaves_plan_question_and_mentor_review_intact(
        self, temp_notifications_dir: Path
    ) -> None:
        append_notification(
            make_notification(
                id="plan",
                sender="user-agent",
                action="PlanApproval",
                action_data={"agent_cl_name": "a"},
            )
        )
        append_notification(
            make_notification(
                id="question",
                sender="user-agent",
                action="UserQuestion",
                action_data={"agent_cl_name": "b"},
            )
        )
        append_notification(
            make_notification(
                id="mentor",
                sender="user-agent",
                action="JumpToMentorReview",
                action_data={"cl_name": "c"},
            )
        )

        count = dismiss_agent_completion_notifications()

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 0
        assert by_id["plan"].dismissed is False
        assert by_id["question"].dismissed is False
        assert by_id["mentor"].dismissed is False

    def test_skips_other_senders_and_missing_cl_name(
        self, temp_notifications_dir: Path
    ) -> None:
        append_notification(
            make_notification(
                id="axe-error",
                sender="axe",
                action="ViewErrorReport",
                action_data={"error_report_path": "/tmp/x"},
            )
        )
        append_notification(
            make_notification(
                id="crs",
                sender="crs",
                action="JumpToAgent",
                action_data={"cl_name": "f"},
            )
        )
        append_notification(
            make_notification(
                id="no-cl",
                sender="user-agent",
                action="JumpToAgent",
            )
        )

        count = dismiss_agent_completion_notifications()

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 0
        assert by_id["axe-error"].dismissed is False
        assert by_id["crs"].dismissed is False
        assert by_id["no-cl"].dismissed is False

    def test_skips_already_dismissed_rows(self, temp_notifications_dir: Path) -> None:
        append_notification(
            make_notification(
                id="already",
                sender="user-agent",
                action="JumpToAgent",
                action_data={"cl_name": "a"},
                dismissed=True,
            )
        )

        count = dismiss_agent_completion_notifications()

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 0
        assert by_id["already"].dismissed is True

    def test_empty_store(self, temp_notifications_dir: Path) -> None:
        assert dismiss_agent_completion_notifications() == 0

    def test_routes_through_bulk_rust_update(
        self, temp_notifications_dir: Path
    ) -> None:
        import sase.notifications.store as store

        with patch(
            "sase.notifications.store._rust_apply_notification_state_update",
            wraps=store._rust_apply_notification_state_update,
        ) as mock_update:
            dismiss_agent_completion_notifications()

        mock_update.assert_called_once()
        update = mock_update.call_args.args[1]
        assert update.kind == "dismiss_agent_completions"
