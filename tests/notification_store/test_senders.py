from pathlib import Path
from types import SimpleNamespace

from sase.notifications.store import load_notifications


class TestNotifyWorkflowCompleteSilent:
    """Tests for notify_workflow_complete() with silent flag."""

    def test_silent_notification_created(self, temp_notifications_dir: Path) -> None:
        from sase.notifications.senders import notify_workflow_complete

        notify_workflow_complete(
            sender="fix-hook",
            cl_name="test-cl",
            success=True,
            notes=["Fix-hook completed for test-cl"],
            silent=True,
        )
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].silent is True
        assert loaded[0].sender == "fix-hook"

    def test_non_silent_notification_default(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.senders import notify_workflow_complete

        notify_workflow_complete(
            sender="run-agent",
            cl_name="test-cl",
            success=True,
            notes=["Agent completed"],
        )
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].silent is False

    def test_tags_are_normalized(self, temp_notifications_dir: Path) -> None:
        from sase.notifications.senders import notify_workflow_complete

        notify_workflow_complete(
            sender="run-agent",
            cl_name="test-cl",
            success=True,
            notes=["Agent completed"],
            tags=[" Done ", "done", "Review"],
        )
        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].tags == ["done", "review"]


class TestNotifyMonitorFollowupDropped:
    """Tests for notify_monitor_followup_dropped()."""

    def test_emits_alarm_tagged_notification(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.senders import notify_monitor_followup_dropped

        notification_id = notify_monitor_followup_dropped(
            "acme--mon",
            "aaabbbcccddd",
            "workspace #10 with pid 3333672 was not found",
        )

        loaded = load_notifications()
        assert len(loaded) == 1
        n = loaded[0]
        assert n.id == notification_id
        assert n.sender == "monitor"
        assert n.icon == "⚠"
        assert "error" in n.tags
        assert "monitor" in n.tags
        assert any("did not launch" in note for note in n.notes)
        assert "workspace #10 with pid 3333672 was not found" in n.notes
        assert any("aaabbbcccddd" in note for note in n.notes)

    def test_headline_names_the_lane_when_given(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.senders import notify_monitor_followup_dropped

        notify_monitor_followup_dropped(
            "acme--mon",
            "aaabbbcccddd",
            "no lane to launch into",
        )

        notification = load_notifications()[0]
        assert "acme--mon" in notification.notes[0]

    def test_no_cl_name_omits_lane_suffix(self, temp_notifications_dir: Path) -> None:
        from sase.notifications.senders import notify_monitor_followup_dropped

        notify_monitor_followup_dropped(
            None,
            "aaabbbcccddd",
            "no lane to launch into",
        )

        notification = load_notifications()[0]
        assert notification.notes[0] == "Monitor follow-up did not launch"


class TestNotifyMonitorComplete:
    """Tests for settlement.notify_monitor_complete()'s alarm split."""

    def test_dropped_followup_sends_a_separate_alarm_notification(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.monitor.settlement import notify_monitor_complete

        notify_monitor_complete(
            {
                "cl_name": "acme--mon",
                "monitor_id": "aaabbbcccddd",
                "monitor_command": "just check-full",
            },
            monitor_state="completed",
            stop_status="MONITORED",
            followup_error="workspace #10 with pid 3333672 was not found",
        )

        loaded = load_notifications()
        assert len(loaded) == 2
        senders = {n.sender for n in loaded}
        assert senders == {"monitor"}
        alarm = next(n for n in loaded if n.icon == "⚠")
        assert "error" in alarm.tags
        assert "workspace #10 with pid 3333672 was not found" in alarm.notes
        routine = next(n for n in loaded if n.icon != "⚠")
        assert routine.tags == ["monitor"]

    def test_clean_finish_sends_only_the_routine_notification(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.monitor.settlement import notify_monitor_complete

        notify_monitor_complete(
            {
                "cl_name": "acme--mon",
                "monitor_id": "aaabbbcccddd",
                "monitor_command": "just check-full",
            },
            monitor_state="completed",
            stop_status="MONITORED",
            followup_error=None,
        )

        loaded = load_notifications()
        assert len(loaded) == 1
        assert loaded[0].icon != "⚠"


class TestNotifyMentorsComplete:
    """Tests for notify_mentors_complete()."""

    def test_emits_jump_to_mentor_review_action(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.senders import notify_mentors_complete

        notify_mentors_complete(
            cl_name="cl-1",
            project_file="/proj.sase",
            entry_id="2",
            mentor_summary="3/3 mentors finished (1 commented)",
            has_comments=True,
        )
        loaded = load_notifications()
        assert len(loaded) == 1
        n = loaded[0]
        assert n.action == "JumpToMentorReview"
        assert n.action_data == {
            "patch_name": "cl-1",
            "changespec_name": "cl-1",
            "cl_name": "cl-1",
            "project_file": "/proj.sase",
            "stitch_id": "2",
            "entry_id": "2",
            "commit_entry_id": "2",
        }
        assert n.sender == "mentors"
        assert n.files == ["/proj.sase"]
        assert any("cl-1" in note and "entry 2" in note for note in n.notes)
        assert "3/3 mentors finished (1 commented)" in n.notes

    def test_no_match_summary(self, temp_notifications_dir: Path) -> None:
        from sase.notifications.senders import notify_mentors_complete

        notify_mentors_complete(
            cl_name="cl-1",
            project_file="/proj.sase",
            entry_id="1",
            mentor_summary="no mentor profiles matched",
            has_comments=False,
        )
        loaded = load_notifications()
        assert len(loaded) == 1
        assert "no mentor profiles matched" in loaded[0].notes

    def test_humanizes_note_but_keeps_jump_identity(
        self, temp_notifications_dir: Path, monkeypatch
    ) -> None:
        from sase.notifications import senders

        canonical = "gh_acme__widgets_review"
        monkeypatch.setattr(
            senders,
            "humanize_cl_name",
            lambda value: "widgets_review" if value == canonical else value,
        )

        senders.notify_mentors_complete(
            cl_name=canonical,
            project_file="/canonical/project.sase",
            entry_id="3",
            mentor_summary="done",
            has_comments=False,
        )

        notification = load_notifications()[0]
        assert "widgets_review" in notification.notes[0]
        assert canonical not in notification.notes[0]
        assert notification.action_data["patch_name"] == canonical
        assert notification.action_data["changespec_name"] == canonical
        assert notification.action_data["project_file"] == "/canonical/project.sase"


class TestNotifyMemoryProposed:
    def test_emits_memory_review_action_data(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.senders import notify_memory_proposed

        proposal = SimpleNamespace(
            proposal_id="mem-20260523-120000-1234abcd",
            title="Generated skills",
            author_name="agent-a",
            target_path="generated_skills.md",
            evidence=(
                SimpleNamespace(resolved_path="/tmp/evidence.md"),
                SimpleNamespace(resolved_path=None),
            ),
        )

        notification_id = notify_memory_proposed(proposal)

        loaded = load_notifications()
        assert len(loaded) == 1
        notification = loaded[0]
        assert notification.id == notification_id
        assert notification.sender == "memory.proposed"
        assert notification.action == "memory_review"
        assert notification.action_data == {
            "proposal_id": "mem-20260523-120000-1234abcd"
        }
        assert notification.files == ["/tmp/evidence.md"]
        assert notification.tags == ["memory"]
        assert "Memory proposal ready: Generated skills" in notification.notes
