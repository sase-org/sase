from pathlib import Path
from types import SimpleNamespace

import pytest

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


def _usage_limit_detection(
    *,
    provider: str = "claude",
    disable_seconds: float = 3660.0,
    expires_at: float | None = None,
    used_reset_hint: bool = False,
):
    from sase.llm_provider.usage_limit_config import UsageLimitDetection

    return UsageLimitDetection(
        provider=provider,
        matched_pattern="you've hit your weekly limit",
        message="you've hit your weekly limit",
        raw_message="You've hit your weekly limit · resets 8pm (America/New_York)",
        disable_seconds=disable_seconds,
        expires_at=expires_at,
        reset_hint=None,
        used_reset_hint=used_reset_hint,
    )


class TestNotifyProviderUsageLimitDisabled:
    """Tests for notify_provider_usage_limit_disabled()."""

    @pytest.fixture(autouse=True)
    def _provider_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "sase.llm_provider.registry.get_llm_metadata_payload",
            lambda: {"providers": {"claude": {"display_name": "Claude Code"}}},
        )

    def test_composes_notes_and_tags(self, temp_notifications_dir: Path) -> None:
        from sase.notifications.senders import notify_provider_usage_limit_disabled

        notify_provider_usage_limit_disabled(_usage_limit_detection())

        loaded = load_notifications()
        assert len(loaded) == 1
        n = loaded[0]
        assert n.sender == "llm.usage_limit"
        assert n.icon == "⛔"
        assert n.tags == ["llm", "usage-limit", "claude"]
        assert "Claude Code disabled for 1h 1m" in n.notes[0]
        assert "you've hit your weekly limit" in n.notes[0]
        assert "Disabled until cleared." in n.notes
        assert any("Provider said:" in note for note in n.notes)
        assert any("route to the next enabled provider" in note for note in n.notes)

    def test_falls_back_to_provider_key_without_display_name(
        self, temp_notifications_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.notifications.senders import notify_provider_usage_limit_disabled

        monkeypatch.setattr(
            "sase.llm_provider.registry.get_llm_metadata_payload",
            lambda: {"providers": {}},
        )

        notify_provider_usage_limit_disabled(_usage_limit_detection(provider="grok"))

        n = load_notifications()[0]
        assert n.notes[0].startswith("grok disabled for")
        assert n.tags == ["llm", "usage-limit", "grok"]

    def test_expiry_notes_reset_hint_provenance(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.senders import notify_provider_usage_limit_disabled

        notify_provider_usage_limit_disabled(
            _usage_limit_detection(
                expires_at=1_800_003_600.0,
                used_reset_hint=True,
            )
        )

        n = load_notifications()[0]
        reenable_note = next(note for note in n.notes if note.startswith("Re-enables"))
        assert "as reported by the provider" in reenable_note

    def test_expiry_without_reset_hint_omits_provenance(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.senders import notify_provider_usage_limit_disabled

        notify_provider_usage_limit_disabled(
            _usage_limit_detection(
                expires_at=1_800_003_600.0,
                used_reset_hint=False,
            )
        )

        n = load_notifications()[0]
        reenable_note = next(note for note in n.notes if note.startswith("Re-enables"))
        assert "as reported by the provider" not in reenable_note

    def test_agent_and_model_note(self, temp_notifications_dir: Path) -> None:
        from sase.notifications.senders import notify_provider_usage_limit_disabled

        notify_provider_usage_limit_disabled(
            _usage_limit_detection(),
            agent_name="bbugyi200.athena.03j",
            model="claude-sonnet-5",
        )

        n = load_notifications()[0]
        assert "Triggered by agent bbugyi200.athena.03j on claude-sonnet-5." in n.notes

    def test_no_agent_context_omits_triggered_note(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.senders import notify_provider_usage_limit_disabled

        notify_provider_usage_limit_disabled(_usage_limit_detection())

        n = load_notifications()[0]
        assert not any(note.startswith("Triggered") for note in n.notes)

    def test_provider_said_note_uses_raw_message_not_normalized(
        self, temp_notifications_dir: Path
    ) -> None:
        from sase.notifications.senders import notify_provider_usage_limit_disabled

        notify_provider_usage_limit_disabled(_usage_limit_detection())

        n = load_notifications()[0]
        assert any("You've hit your weekly limit" in note for note in n.notes)

    def test_returns_the_notification_id(self, temp_notifications_dir: Path) -> None:
        from sase.notifications.senders import notify_provider_usage_limit_disabled

        notification_id = notify_provider_usage_limit_disabled(_usage_limit_detection())

        loaded = load_notifications()
        assert loaded[0].id == notification_id


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
