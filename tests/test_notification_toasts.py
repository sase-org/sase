"""Tests for per-notification toast formatting."""

from __future__ import annotations

from sase.ace.tui.actions.agents._toasts import (
    format_batch_toasts,
    _format_notification_toast,
)

from tests._notification_toasts_helpers import _make, _plain


class TestFormatNotificationToast:
    def test_plan_approval_uses_original_plan_file_basename(self) -> None:
        n = _make(
            action="PlanApproval",
            notes=["Plan ready for review: plan.md"],
            action_data={
                "agent_name": "sase-n.4",
                "original_plan_file": (
                    "~/.sase/plans/202607/agent_group_clan_collapse_precedence.md"
                ),
            },
            files=["/path/to/gate-bundle/plan.md"],
        )
        msg, sev = _format_notification_toast(n)
        assert _plain(msg) == (
            "Tale ready for @sase-n.4: agent_group_clan_collapse_precedence.md"
        )
        assert sev == "warning"
        assert "plan.md" not in _plain(msg)

    def test_epic_approval_uses_original_plan_file_basename(self) -> None:
        n = _make(
            action="EpicApproval",
            action_data={
                "agent_name": "sase-n.5",
                "original_plan_file": "~/.sase/plans/202607/epic_rollout.md",
            },
            files=["/path/to/gate-bundle/plan.md"],
        )
        msg, sev = _format_notification_toast(n)
        assert _plain(msg) == "Epic ready for @sase-n.5: epic_rollout.md"
        assert sev == "warning"

    def test_legacy_plan_approval_uses_first_file_basename(self) -> None:
        n = _make(
            action="PlanApproval",
            action_data={"agent_name": "sase-n.4"},
            files=["/path/to/sase_plan_foo.md"],
        )
        msg, sev = _format_notification_toast(n)
        assert _plain(msg) == "Tale ready for @sase-n.4: sase_plan_foo.md"
        assert sev == "warning"

    def test_blank_original_plan_file_uses_first_file_basename(self) -> None:
        n = _make(
            action="PlanApproval",
            action_data={
                "agent_name": "sase-n.4",
                "original_plan_file": "   ",
            },
            files=["/path/to/sase_plan_foo.md"],
        )
        msg, sev = _format_notification_toast(n)
        assert _plain(msg) == "Tale ready for @sase-n.4: sase_plan_foo.md"
        assert sev == "warning"

    def test_plan_approval_missing_agent_name_uses_basename(self) -> None:
        n = _make(
            action="PlanApproval",
            notes=["Plan ready for review: sase_plan_foo.md"],
            files=["/path/to/sase_plan_foo.md"],
        )
        msg, sev = _format_notification_toast(n)
        assert _plain(msg) == "Tale ready for review: sase_plan_foo.md"
        assert sev == "warning"

    def test_plan_approval_no_basename_falls_back_to_note(self) -> None:
        n = _make(
            action="PlanApproval",
            notes=["Plan ready for review: a.md"],
        )
        msg, sev = _format_notification_toast(n)
        assert _plain(msg) == "Plan ready for review: a.md"
        assert sev == "warning"

    def test_plan_approval_empty_notes_uses_placeholder(self) -> None:
        n = _make(action="PlanApproval")
        msg, sev = _format_notification_toast(n)
        assert _plain(msg) == "Tale ready for review"
        assert sev == "warning"

    def test_epic_approval_appends_phase_wave_size_counts(self) -> None:
        n = _make(
            action="EpicApproval",
            action_data={
                "agent_name": "y4",
                "original_plan_file": "/plans/agent_group_clan_collapse.md",
                "plan_tier": "epic",
                "plan_phase_count": "7",
                "plan_wave_count": "3",
                "plan_phase_sizes": "xsmall=1,small=2,medium=3,large=1",
            },
        )
        msg, sev = _format_notification_toast(n)
        assert _plain(msg) == (
            "Epic ready for @y4: agent_group_clan_collapse.md\n"
            "7 phases · 3 waves · 1 XS · 2 S · 3 M · 1 L"
        )
        assert sev == "warning"

    def test_epic_approval_singular_counts(self) -> None:
        n = _make(
            action="EpicApproval",
            action_data={
                "original_plan_file": "/plans/x.md",
                "plan_tier": "epic",
                "plan_phase_count": "1",
                "plan_wave_count": "1",
                "plan_phase_sizes": "medium=1",
            },
        )
        msg, sev = _format_notification_toast(n)
        assert _plain(msg) == "Epic ready for review: x.md\n1 phase · 1 wave · 1 M"
        assert sev == "warning"

    def test_epic_approval_omits_wave_group_when_unavailable(self) -> None:
        n = _make(
            action="EpicApproval",
            action_data={
                "original_plan_file": "/plans/x.md",
                "plan_tier": "epic",
                "plan_phase_count": "4",
            },
        )
        msg, _sev = _format_notification_toast(n)
        assert _plain(msg) == "Epic ready for review: x.md\n4 phases"

    def test_epic_approval_without_stored_counts_omits_detail_line(self) -> None:
        n = _make(
            action="EpicApproval",
            action_data={
                "agent_name": "y4",
                "original_plan_file": "/plans/legacy.md",
                "request_kind": "epic_plan",
            },
        )
        msg, _sev = _format_notification_toast(n)
        assert _plain(msg) == "Epic ready for @y4: legacy.md"
        assert "\n" not in _plain(msg)

    def test_tale_approval_never_shows_detail_line(self) -> None:
        n = _make(
            action="PlanApproval",
            action_data={
                "agent_name": "y4",
                "original_plan_file": "/plans/x.md",
                "plan_tier": "tale",
            },
        )
        msg, _sev = _format_notification_toast(n)
        assert _plain(msg) == "Tale ready for @y4: x.md"

    def test_tier_accent_colors_in_markup(self) -> None:
        tale = _make(
            action="PlanApproval",
            action_data={"agent_name": "y4", "original_plan_file": "/x.md"},
        )
        epic = _make(
            action="EpicApproval",
            action_data={"agent_name": "y4", "original_plan_file": "/x.md"},
        )
        tale_msg, _sev = _format_notification_toast(tale)
        epic_msg, _sev = _format_notification_toast(epic)
        assert "#FFD75F" in tale_msg
        assert "#AF87FF" in epic_msg

    def test_phase_size_accent_colors_in_markup(self) -> None:
        n = _make(
            action="EpicApproval",
            action_data={
                "original_plan_file": "/x.md",
                "plan_tier": "epic",
                "plan_phase_count": "5",
                "plan_phase_sizes": "xsmall=1,small=1,medium=1,large=1,xlarge=1",
            },
        )
        msg, _sev = _format_notification_toast(n)
        assert "#5FD7AF" in msg  # xsmall
        assert "#87D7FF" in msg  # small
        assert "#FFD75F" in msg  # medium
        assert "#D75F87" in msg  # large
        assert "#AF5FFF" in msg  # xlarge

    def test_basename_with_bracket_survives_markup_round_trip(self) -> None:
        n = _make(
            action="PlanApproval",
            action_data={
                "agent_name": "y4",
                "original_plan_file": "/plans/plan[v2].md",
            },
        )
        msg, _sev = _format_notification_toast(n)
        assert "\\[v2]" in msg
        assert _plain(msg) == "Tale ready for @y4: plan[v2].md"

    def test_user_question_with_agent_name(self) -> None:
        n = _make(
            action="UserQuestion",
            notes=["Should I use option A or B?"],
            action_data={"agent_name": "sase-n.4"},
        )
        msg, sev = _format_notification_toast(n)
        assert msg == "Question from @sase-n.4: Should I use option A or B?"
        assert sev == "warning"

    def test_user_question_note_with_bracket_survives(self) -> None:
        n = _make(
            action="UserQuestion",
            notes=["[URGENT] pick a direction"],
            action_data={"agent_name": "sase-n.4"},
        )
        msg, sev = _format_notification_toast(n)
        assert _plain(msg) == "Question from @sase-n.4: [URGENT] pick a direction"
        assert sev == "warning"

    def test_user_question_truncates_long_notes(self) -> None:
        long = "x" * 200
        n = _make(
            action="UserQuestion",
            notes=[long],
            action_data={"agent_name": "sase-n.4"},
        )
        msg, sev = _format_notification_toast(n)
        assert len(msg) < 100
        assert sev == "warning"
        assert msg.startswith("Question from @sase-n.4:")

    def test_user_question_missing_agent(self) -> None:
        n = _make(action="UserQuestion", notes=["What color?"])
        msg, sev = _format_notification_toast(n)
        assert msg == "What color?"
        assert sev == "warning"

    def test_user_question_no_notes(self) -> None:
        n = _make(action="UserQuestion")
        msg, sev = _format_notification_toast(n)
        assert msg == "Claude is asking a question"
        assert sev == "warning"

    def test_hitl(self) -> None:
        n = _make(action="HITL", notes=["HITL waiting: step 'confirm' in deploy"])
        msg, sev = _format_notification_toast(n)
        assert msg == "HITL waiting: step 'confirm' in deploy"
        assert sev == "warning"

    def test_hitl_empty_notes(self) -> None:
        n = _make(action="HITL")
        msg, sev = _format_notification_toast(n)
        assert msg == "HITL waiting for input"
        assert sev == "warning"

    def test_view_error_report(self) -> None:
        n = _make(
            action="ViewErrorReport",
            notes=["3 error(s) in the last hour"],
        )
        msg, sev = _format_notification_toast(n)
        assert msg == "Axe: 3 error(s) in the last hour"
        assert sev == "error"

    def test_view_error_report_no_notes(self) -> None:
        n = _make(action="ViewErrorReport")
        msg, sev = _format_notification_toast(n)
        assert msg == "Axe errors"
        assert sev == "error"

    def test_view_report(self) -> None:
        n = _make(action="ViewReport", notes=["Release report updated"])
        msg, sev = _format_notification_toast(n)
        assert msg == "Release report updated"
        assert sev == "information"

    def test_view_report_no_notes(self) -> None:
        n = _make(action="ViewReport")
        msg, sev = _format_notification_toast(n)
        assert msg == "Report available"
        assert sev == "information"

    def test_jump_to_patch_success(self) -> None:
        n = _make(
            action="JumpToChangeSpec", notes=["Sync success for bar"]
        )  # legacy notification action
        msg, sev = _format_notification_toast(n)
        assert msg == "Sync success for bar"
        assert sev == "information"

    def test_jump_to_patch_failure(self) -> None:
        n = _make(
            action="JumpToChangeSpec", notes=["Sync fail for feature/bar"]
        )  # legacy notification action
        msg, sev = _format_notification_toast(n)
        assert msg == "Sync fail for feature/bar"
        assert sev == "error"

    def test_jump_to_agent_success_keyword(self) -> None:
        n = _make(action="JumpToAgent", notes=["Agent finished: success"])
        _, sev = _format_notification_toast(n)
        assert sev == "information"

    def test_jump_to_agent_failure_keyword(self) -> None:
        n = _make(action="JumpToAgent", notes=["Agent failed hard"])
        _, sev = _format_notification_toast(n)
        assert sev == "error"

    def test_jump_to_agent_no_notes(self) -> None:
        n = _make(action="JumpToAgent")
        msg, sev = _format_notification_toast(n)
        assert msg == "Agent update"
        assert sev == "information"

    def test_jump_to_agent_completion_with_agent_name(self) -> None:
        n = _make(
            action="JumpToAgent",
            notes=["CLAUDE(opus) @sase-q.land completed: ace(run)-260425_161716"],
            action_data={"agent_name": "sase-q.land"},
        )
        msg, sev = _format_notification_toast(n)
        assert msg == "CLAUDE(opus) @sase-q.land completed: ace(run)-260425_161716"
        assert sev == "information"

    def test_jump_to_agent_completion_without_agent_name(self) -> None:
        n = _make(
            action="JumpToAgent",
            notes=["CLAUDE(opus) completed: ace(run)-260425_161716"],
        )
        msg, sev = _format_notification_toast(n)
        assert msg == "CLAUDE(opus) completed: ace(run)-260425_161716"
        assert sev == "information"

    def test_tmux(self) -> None:
        n = _make(action="Tmux", notes=["Focus pane"])
        msg, sev = _format_notification_toast(n)
        assert msg == "Focus pane"
        assert sev == "information"

    def test_none_action(self) -> None:
        n = _make(action=None, notes=[])
        msg, sev = _format_notification_toast(n)
        assert msg == "New notification"
        assert sev == "information"

    def test_unknown_action(self) -> None:
        n = _make(action="WhoKnows", notes=["Something happened"])
        msg, sev = _format_notification_toast(n)
        assert msg == "Something happened"
        assert sev == "information"


class TestFormatBatchToasts:
    def test_empty(self) -> None:
        assert format_batch_toasts([]) == []

    def test_single_toast_per_notification_under_threshold(self) -> None:
        notifs = [
            _make(action="PlanApproval", notes=["Plan ready for review: a.md"]),
            _make(action="UserQuestion", notes=["What?"]),
            _make(
                action="JumpToChangeSpec", notes=["Sync success for x"]
            ),  # legacy notification action
        ]
        toasts = format_batch_toasts(notifs)
        assert len(toasts) == 3

    def test_groups_large_batches_by_severity(self) -> None:
        notifs = [
            _make(action="PlanApproval", notes=["Plan ready for review: a.md"]),
            _make(action="PlanApproval", notes=["Plan ready for review: b.md"]),
            _make(action="UserQuestion", notes=["What?"]),
            _make(action="ViewErrorReport", notes=["1 error"]),
            _make(
                action="JumpToChangeSpec", notes=["Sync success for x"]
            ),  # legacy notification action
        ]
        toasts = format_batch_toasts(notifs)
        # One per severity bucket that has entries: error, warning, information.
        severities = [sev for _, sev in toasts]
        assert severities == ["error", "warning", "information"]
        # Warning bucket: 2 tales + 1 question = 3 warnings.
        warning_msg = next(msg for msg, sev in toasts if sev == "warning")
        assert warning_msg.startswith("3 warnings")
        assert "2 tales" in warning_msg
        assert "1 question" in warning_msg
        # Error bucket: one axe error.
        error_msg = next(msg for msg, sev in toasts if sev == "error")
        assert error_msg.startswith("1 errors")

    def test_groups_tale_and_epic_labels(self) -> None:
        notifs = [_make(action="PlanApproval", notes=[f"t{i}"]) for i in range(2)] + [
            _make(action="EpicApproval", notes=[f"e{i}"]) for i in range(3)
        ]

        assert format_batch_toasts(notifs) == [
            ("5 warnings: 2 tales, 3 epics", "warning")
        ]

    def test_groups_view_reports_with_report_label(self) -> None:
        notifs = [_make(action="ViewReport") for _ in range(4)]

        assert format_batch_toasts(notifs) == [("4 updates: 4 reports", "information")]

    def test_exactly_three_emits_per_notification(self) -> None:
        notifs = [
            _make(action="PlanApproval", notes=["a"]),
            _make(action="PlanApproval", notes=["b"]),
            _make(action="PlanApproval", notes=["c"]),
        ]
        toasts = format_batch_toasts(notifs)
        assert len(toasts) == 3

    def test_four_triggers_grouping(self) -> None:
        notifs = [_make(action="PlanApproval", notes=[f"n{i}"]) for i in range(4)]
        toasts = format_batch_toasts(notifs)
        assert len(toasts) == 1
        assert toasts[0][1] == "warning"
