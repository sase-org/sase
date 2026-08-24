"""Trigger-agent settle and notification ownership for an automatic drain."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sase.agent.wait_watch import WaitTarget, WaitTargetKind, WaitTargetResolutionError
from sase.ops.commands._agent_drain_notify import (
    send_usage_limit_drain_notification,
    settle_drain_trigger_agent,
)

_TARGET = WaitTarget(raw_name="sase-mf", name="sase-mf", kind=WaitTargetKind.AGENT)


class TestSettleDrainTriggerAgent:
    @patch("sase.agent.wait_watch.resolve_wait_targets")
    def test_no_name_is_a_no_op(self, mock_resolve: MagicMock) -> None:
        settle_drain_trigger_agent(None)
        mock_resolve.assert_not_called()

    @patch("sase.agent.wait_watch.watch_wait_targets")
    @patch("sase.core.paths.sase_projects_dir")
    @patch("sase.core.agent_scan_facade.scan_agent_artifacts")
    @patch("sase.agent.wait_watch.wait_scan_options")
    @patch("sase.agent.wait_watch.resolve_wait_targets")
    def test_no_matching_target_skips_watching(
        self,
        mock_resolve: MagicMock,
        mock_options: MagicMock,
        mock_scan: MagicMock,
        mock_root: MagicMock,
        mock_watch: MagicMock,
    ) -> None:
        mock_resolve.return_value = ()
        settle_drain_trigger_agent("sase-mf")
        mock_resolve.assert_called_once()
        mock_watch.assert_not_called()

    @patch("sase.agent.wait_watch.watch_wait_targets")
    @patch("sase.core.paths.sase_projects_dir")
    @patch("sase.core.agent_scan_facade.scan_agent_artifacts")
    @patch("sase.agent.wait_watch.wait_scan_options")
    @patch("sase.agent.wait_watch.resolve_wait_targets")
    def test_watches_until_settled_with_bounded_timeout(
        self,
        mock_resolve: MagicMock,
        mock_options: MagicMock,
        mock_scan: MagicMock,
        mock_root: MagicMock,
        mock_watch: MagicMock,
    ) -> None:
        mock_resolve.return_value = (_TARGET,)
        tick_running = MagicMock(settled=False)
        tick_failed = MagicMock(settled=True)
        mock_watch.return_value = iter([tick_running, tick_failed])

        settle_drain_trigger_agent("sase-mf", timeout_seconds=45.0)

        mock_watch.assert_called_once()
        config = mock_watch.call_args.args[0]
        assert config.timeout_seconds == 45.0
        assert config.targets == (_TARGET,)

    @patch(
        "sase.agent.wait_watch.resolve_wait_targets",
        side_effect=WaitTargetResolutionError("nope"),
    )
    def test_resolution_error_is_swallowed(self, _mock_resolve: MagicMock) -> None:
        settle_drain_trigger_agent("sase-mf")

    @patch(
        "sase.core.paths.sase_projects_dir",
        side_effect=RuntimeError("boom"),
    )
    def test_never_raises_on_unexpected_error(self, _mock_root: MagicMock) -> None:
        settle_drain_trigger_agent("sase-mf")


class TestSendUsageLimitDrainNotification:
    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    def test_builds_detection_and_forwards_drain_notes(
        self, mock_notify: MagicMock
    ) -> None:
        trigger = {
            "provider": "claude",
            "matched_pattern": "usage limit reached",
            "raw_message": "usage limit reached, resets 8pm",
            "disable_seconds": 3600.0,
            "expires_at": 1_800_003_600.0,
            "used_reset_hint": True,
            "trigger_agent": "sase-mf",
            "trigger_model": "opus@high",
        }
        result = MagicMock(
            payload={"moves": [], "skips": [], "results": []},
        )

        send_usage_limit_drain_notification(trigger, result)

        mock_notify.assert_called_once()
        detection = mock_notify.call_args.args[0]
        assert detection.provider == "claude"
        assert detection.matched_pattern == "usage limit reached"
        assert detection.disable_seconds == 3600.0
        assert detection.expires_at == 1_800_003_600.0
        assert detection.used_reset_hint is True
        assert mock_notify.call_args.kwargs["agent_name"] == "sase-mf"
        assert mock_notify.call_args.kwargs["model"] == "opus@high"
        assert mock_notify.call_args.kwargs["drain_notes"] == [
            "Drain found no agents on this provider to relaunch or leave alone."
        ]

    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    def test_none_result_still_notifies_with_a_fallback_note(
        self, mock_notify: MagicMock
    ) -> None:
        trigger = {"provider": "claude", "matched_pattern": "usage limit reached"}

        send_usage_limit_drain_notification(trigger, None)

        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["drain_notes"] == [
            "Drain did not finish; see the drain proc log for details."
        ]

    @patch(
        "sase.notifications.senders.notify_provider_usage_limit_disabled",
        side_effect=RuntimeError("boom"),
    )
    def test_never_raises_when_notification_fails(
        self, _mock_notify: MagicMock
    ) -> None:
        send_usage_limit_drain_notification({"provider": "claude"}, None)
