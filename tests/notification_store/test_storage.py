import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.core.notification_store_wire import (
    NOTIFICATION_STORE_WIRE_SCHEMA_VERSION,
    NotificationUpdateOutcomeWire,
)
from sase.notifications.store import (
    append_notification,
    append_notification_strict,
    compact_notification_store,
    dismiss_agent_completion_notifications_matching_agents,
    dismiss_notifications_matching_agents,
    load_notifications,
    mark_read,
    reconcile_notification_rows,
    rewrite_notifications,
    upsert_notification,
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

    def test_tagged_notification_round_trip(self, temp_notifications_dir: Path) -> None:
        """Tags are stored and loaded back unchanged."""
        n = make_notification(tags=["done", "review"])
        append_notification(n)
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].tags == ["done", "review"]

    def test_action_data_dual_reads_patch_metadata(
        self, temp_notifications_dir: Path
    ) -> None:
        n = make_notification(
            action="JumpToMentorReview",
            action_data={"changespec_name": "cl", "entry_id": "2a"},
        )
        append_notification(n)

        loaded = load_notifications()

        assert loaded[0].action_data["patch_name"] == "cl"
        assert loaded[0].action_data["changespec_name"] == "cl"
        assert loaded[0].action_data["stitch_id"] == "2a"
        assert loaded[0].action_data["entry_id"] == "2a"

    def test_routes_through_rust_facade(self, temp_notifications_dir: Path) -> None:
        import sase.notifications.store as store

        n = make_notification()
        with patch(
            "sase.notifications.store._rust_append_notification",
            wraps=store._rust_append_notification,
        ) as mock_append:
            append_notification(n)

        mock_append.assert_called_once()

    def test_routes_through_counts_only_binding(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.core import notification_store_facade

        captured: list[Any] = []
        real_with_options = notification_store_facade.append_notification_with_options

        def spy(path: Any, request: Any, *, counts_only: bool = False) -> Any:
            outcome = real_with_options(path, request, counts_only=counts_only)
            captured.append((request, outcome, counts_only))
            return outcome

        n = make_notification()
        with patch.object(
            notification_store_facade,
            "append_notification_with_options",
            side_effect=spy,
        ) as mock_counts:
            append_notification(n)

        mock_counts.assert_called_once()
        assert len(captured) == 1
        request, outcome, counts_only = captured[0]
        assert request.externalize_limit_bytes == 8 * 1024
        assert outcome.appended_count == 1
        assert outcome.notifications == []
        assert counts_only is True

    def test_default_externalizes_oversized_values_and_resolves_them(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.payloads import (
            resolve_notification_action_data,
            resolve_notification_notes,
        )

        payload = "large notification payload " * 8_000
        append_notification(
            make_notification(notes=[payload], action_data={"prompt": payload})
        )

        path = temp_notifications_dir / "notifications" / "notifications.jsonl"
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert path.stat().st_size < 8 * 1024
        assert stored["action_data"]["prompt"].startswith("sase-notification-blob:v1:")
        assert "sase-notification-blob:v1:" in stored["notes"][0]
        assert resolve_notification_action_data(path, stored["action_data"]) == {
            "prompt": payload
        }
        assert resolve_notification_notes(path, stored["notes"]) == [payload]

    def test_compaction_migrates_live_oversized_rows_once(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.store import append_notification

        payload = "legacy inline payload " * 500
        append_notification(
            make_notification(notes=[payload], action_data={"prompt": payload}),
            externalize_limit_bytes=None,
        )

        migrated = compact_notification_store()
        migrated_again = compact_notification_store()

        path = temp_notifications_dir / "notifications" / "notifications.jsonl"
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert migrated.externalized_count == 2
        assert migrated_again.externalized_count == 0
        assert stored["action_data"]["prompt"].startswith("sase-notification-blob:v1:")

    @pytest.mark.parametrize("writer", ["upsert", "reconcile", "strict"])
    def test_other_store_wrappers_externalize_by_default(
        self, temp_notifications_dir: Path, writer: str
    ) -> None:
        payload = "large writer payload " * 500
        notification = make_notification(action_data={"payload": payload})
        if writer == "upsert":
            upsert_notification(notification)
        elif writer == "reconcile":
            reconcile_notification_rows([notification])
        else:
            append_notification_strict(notification)

        stored = json.loads(
            (
                temp_notifications_dir / "notifications" / "notifications.jsonl"
            ).read_text(encoding="utf-8")
        )
        assert stored["action_data"]["payload"].startswith("sase-notification-blob:v1:")


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

    def test_legacy_missing_tags_loads_empty(
        self, temp_notifications_dir: Path
    ) -> None:
        jsonl = temp_notifications_dir / "notifications" / "notifications.jsonl"
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        with open(jsonl, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "legacy",
                        "timestamp": "2025-01-01T00:00:00",
                        "sender": "test",
                    }
                )
                + "\n"
            )
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].tags == []

    def test_cache_hit_returns_fresh_top_level_notification(
        self, temp_notifications_dir: Path
    ) -> None:
        append_notification(
            make_notification(
                id="cached",
                notes=["initial"],
                action_data={"kind": "demo"},
            )
        )

        first = load_notifications()
        second = load_notifications()

        assert first[0] is not second[0]
        first[0].read = True
        assert load_notifications()[0].read is False

        first[0].notes.append("nested-shallow-copy")
        assert load_notifications()[0].notes == ["initial", "nested-shallow-copy"]


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

    def test_routes_through_counts_only_binding(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.core import notification_store_facade

        existing = make_notification(id="existing")
        append_notification(existing)

        captured: list[Any] = []
        real_counts = notification_store_facade.rewrite_notifications_counts

        def spy(path: Any, notifications: Any) -> Any:
            outcome = real_counts(path, notifications)
            captured.append(outcome)
            return outcome

        with patch.object(
            notification_store_facade,
            "rewrite_notifications_counts",
            side_effect=spy,
        ) as mock_counts:
            rewrite_notifications([make_notification(id="replacement")])

        mock_counts.assert_called_once()
        assert len(captured) == 1
        assert captured[0].rewritten is True
        assert captured[0].matched_count == 1
        assert captured[0].notifications == []
        assert load_notifications()[0].id == "replacement"


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


class TestNotificationPlusOneOutcomes:
    def test_coalesced_plus_one_does_not_invalidate_cache(
        self, temp_notifications_dir: Path
    ) -> None:
        from types import SimpleNamespace

        from sase.core import notification_store_facade
        from sase.notifications.store import append_notification_plus_one

        del temp_notifications_dir
        with (
            patch.object(
                notification_store_facade,
                "append_notification_plus_one",
                return_value=SimpleNamespace(action="coalesced"),
            ) as rust_append,
            patch("sase.notifications.store._invalidate_load_cache") as invalidate,
        ):
            outcome = append_notification_plus_one(
                note="same note",
                sender="test-sender",
                timestamp="2026-05-01T03:00:00+00:00",
                notification_id="existing",
                plus_one_dismissed=True,
                coalesce_window_seconds=600,
            )

        assert outcome.action == "coalesced"
        request = rust_append.call_args.args[1]
        assert request.plus_one_dismissed is True
        assert request.coalesce_window_seconds == 600
        invalidate.assert_not_called()

    @pytest.mark.parametrize("action", ["coalesced", "skipped_dismissed"])
    def test_upsert_noop_skips_cache_and_pending_registration(
        self, temp_notifications_dir: Path, action: str
    ) -> None:
        from sase.core import notification_store_facade
        from sase.notifications.store import upsert_notification

        del temp_notifications_dir
        notification = make_notification()
        notification.dedup_key = "dismissed-key"
        with (
            patch.object(
                notification_store_facade,
                "upsert_notification",
                return_value=SimpleNamespace(action=action),
            ) as rust_upsert,
            patch("sase.notifications.store._invalidate_load_cache") as invalidate,
            patch(
                "sase.notifications.pending_actions.register_notification"
            ) as register,
        ):
            outcome = upsert_notification(
                notification,
                plus_one_note="same note",
                plus_one_dismissed=False,
                coalesce_window_seconds=0,
            )

        assert outcome.action == action
        request = rust_upsert.call_args.args[1]
        assert request.plus_one_dismissed is False
        assert request.coalesce_window_seconds == 0
        invalidate.assert_not_called()
        register.assert_not_called()


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


class TestDismissAgentCompletionNotificationsMatchingAgents:
    """Tests for completion-only bulk agent notification dismissal."""

    def test_routes_through_completion_only_rust_update(
        self, temp_notifications_dir: Path
    ) -> None:
        import sase.notifications.store as store

        append_notification(
            make_notification(
                id="jump",
                sender="user-agent",
                action="JumpToAgent",
                action_data={"cl_name": "cl", "raw_suffix": "20260430120000"},
            )
        )

        with patch(
            "sase.notifications.store._rust_apply_notification_state_update",
            wraps=store._rust_apply_notification_state_update,
        ) as mock_update:
            count = dismiss_agent_completion_notifications_matching_agents(
                [{"cl_name": "cl", "raw_suffix": "20260430120000"}]
            )

        assert count == 1
        mock_update.assert_called_once()
        update = mock_update.call_args.args[1]
        assert update.kind == "dismiss_agent_completions_matching_agents"
        assert update.agents[0].cl_name == "cl"
        assert update.agents[0].raw_suffix == "20260430120000"

    def test_dismisses_completion_notifications_without_plan_or_question(
        self, temp_notifications_dir: Path
    ) -> None:
        append_notification(
            make_notification(
                id="jump",
                sender="user-agent",
                action="JumpToAgent",
                action_data={"cl_name": "cl", "raw_suffix": "20260430120000"},
            )
        )
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
                id="plan",
                sender="plan",
                action="PlanApproval",
                action_data={
                    "agent_cl_name": "cl",
                    "agent_timestamp": "20260430120000",
                },
            )
        )
        append_notification(
            make_notification(
                id="question",
                sender="question",
                action="UserQuestion",
                action_data={
                    "agent_cl_name": "cl",
                    "agent_timestamp": "20260430120000",
                },
            )
        )

        count = dismiss_agent_completion_notifications_matching_agents(
            [{"cl_name": "cl", "raw_suffix": "20260430120000"}]
        )

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 2
        assert by_id["jump"].dismissed is True
        assert by_id["err"].dismissed is True
        assert by_id["plan"].dismissed is False
        assert by_id["question"].dismissed is False

    def test_empty_raw_suffix_matches_on_cl_name_only(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.ace.tui.actions.agents._notification_matching import (
            agent_completion_notification_matches_agent,
        )

        append_notification(
            make_notification(
                id="empty-suffix",
                sender="user-agent",
                action="JumpToAgent",
                action_data={"cl_name": "cl", "raw_suffix": ""},
            )
        )
        append_notification(
            make_notification(
                id="other-cl",
                sender="user-agent",
                action="JumpToAgent",
                action_data={"cl_name": "other", "raw_suffix": ""},
            )
        )

        # The Python cache-removal predicate matches on cl_name alone.
        [cached] = [
            n
            for n in load_notifications(include_dismissed=True)
            if n.id == "empty-suffix"
        ]
        assert (
            agent_completion_notification_matches_agent(
                cached, cl_name="cl", raw_suffix="20260430120000"
            )
            is True
        )

        count = dismiss_agent_completion_notifications_matching_agents(
            [{"cl_name": "cl", "raw_suffix": "20260430120000"}]
        )

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 1
        assert by_id["empty-suffix"].dismissed is True
        assert by_id["other-cl"].dismissed is False
