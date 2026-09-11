"""The provider_drain-gated ownership decision: drain vs inline notify.

Every branch covers both the ``provider_drain`` flag and the
``relaunch``/hard-disable preconditions the plan requires before a drain
is ever attempted, and confirms exactly one notification path fires. The
best-effort usage-refresh limit-event trigger is orthogonal to drain
ownership (covered by test_usage_refresh.py) and is patched out here so
it does not add an unrelated ``submit_proc_request`` call to assert on.
Enforcement (detect -> disable) behavior lives in the sibling
``test_llm_provider_usage_limit_disable_enforcement.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sase.feature_flags import override_flags
from sase.llm_provider.usage_limit_disable import handle_possible_usage_limit
from tests._llm_provider_usage_limit_disable_helpers import (
    _NOW,
    _detection,
    _sase_home,  # noqa: F401 (registers the autouse fixture)
)


@pytest.fixture
def registered_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names",
        lambda: ["claude", "codex", "fakey", "grok", "agy"],
    )


class TestUsageLimitDrainSubmission:
    @pytest.fixture(autouse=True)
    def _no_usage_refresh_trigger(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "sase.llm_provider.usage_limit_disable._trigger_usage_refresh_after_limit",
            lambda provider, outcome: None,
        )

    @patch("sase.procs.submit_proc_request")
    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_flag_on_submits_drain_and_skips_inline_notify(
        self,
        mock_detect: MagicMock,
        mock_notify: MagicMock,
        mock_submit: MagicMock,
        registered_providers: None,
    ) -> None:
        mock_detect.return_value = _detection()
        with override_flags(provider_drain=True):
            result = handle_possible_usage_limit(
                provider="claude", error_text="usage limit reached"
            )
        assert result is not None
        mock_submit.assert_called_once()
        request = mock_submit.call_args.args[0]
        assert request.argv == [
            "sase",
            "agent",
            "drain",
            "claude",
            "--yes",
            "--json",
            "--limit",
            "20",
        ]
        assert request.operation == "agent.drain"
        assert request.operation_payload["notify"] is True
        assert request.operation_payload["provider"] == "claude"
        assert request.operation_payload["trigger_artifacts_dir"] is None
        assert request.concurrency_keys == ["provider-drain:claude"]
        mock_notify.assert_not_called()

    @patch("sase.procs.submit_proc_request")
    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_flag_on_submits_drain_with_trigger_artifacts_dir(
        self,
        mock_detect: MagicMock,
        mock_notify: MagicMock,
        mock_submit: MagicMock,
        registered_providers: None,
        tmp_path,
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "agent_meta.json").write_text(
            '{"name": "sase-mf"}', encoding="utf-8"
        )
        mock_detect.return_value = _detection()

        with override_flags(provider_drain=True):
            result = handle_possible_usage_limit(
                provider="claude",
                error_text="usage limit reached",
                artifacts_dir=str(artifacts_dir),
            )

        assert result is not None
        mock_submit.assert_called_once()
        payload = mock_submit.call_args.args[0].operation_payload
        assert payload["trigger_agent"] == "sase-mf"
        assert payload["trigger_artifacts_dir"] == str(artifacts_dir)
        mock_notify.assert_not_called()

    @patch("sase.procs.submit_proc_request")
    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_flag_off_notifies_inline_and_never_submits(
        self,
        mock_detect: MagicMock,
        mock_notify: MagicMock,
        mock_submit: MagicMock,
        registered_providers: None,
    ) -> None:
        mock_detect.return_value = _detection()
        with override_flags(provider_drain=False):
            handle_possible_usage_limit(
                provider="claude", error_text="usage limit reached"
            )
        mock_submit.assert_not_called()
        mock_notify.assert_called_once()

    @patch("sase.procs.submit_proc_request")
    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_relaunch_false_notifies_inline_even_with_flag_on(
        self,
        mock_detect: MagicMock,
        mock_notify: MagicMock,
        mock_submit: MagicMock,
        registered_providers: None,
    ) -> None:
        from sase.llm_provider.usage_limit_config import UsageLimitSettings

        mock_detect.return_value = _detection()
        with (
            override_flags(provider_drain=True),
            patch(
                "sase.llm_provider.usage_limit_disable.get_usage_limit_settings",
                return_value=UsageLimitSettings(relaunch=False),
            ),
        ):
            handle_possible_usage_limit(
                provider="claude", error_text="usage limit reached"
            )
        mock_submit.assert_not_called()
        mock_notify.assert_called_once()

    @patch("sase.procs.submit_proc_request")
    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.try_disable_provider")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_soft_disable_record_notifies_inline(
        self,
        mock_detect: MagicMock,
        mock_try_disable: MagicMock,
        mock_notify: MagicMock,
        mock_submit: MagicMock,
        registered_providers: None,
    ) -> None:
        from sase.llm_provider.provider_disable import (
            ProviderDisableWriteOutcome,
            TemporaryProviderDisable,
        )

        mock_detect.return_value = _detection()
        mock_try_disable.return_value = ProviderDisableWriteOutcome(
            inserted=True,
            record=TemporaryProviderDisable(
                version=2,
                provider="claude",
                created_at=_NOW,
                expires_at=_NOW + 100,
                source="usage_limit",
                mode="soft",
            ),
        )
        with override_flags(provider_drain=True):
            handle_possible_usage_limit(
                provider="claude", error_text="usage limit reached"
            )
        mock_submit.assert_not_called()
        mock_notify.assert_called_once()

    @patch("sase.procs.submit_proc_request", side_effect=RuntimeError("boom"))
    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_submission_failure_falls_back_to_inline_notify(
        self,
        mock_detect: MagicMock,
        mock_notify: MagicMock,
        mock_submit: MagicMock,
        registered_providers: None,
    ) -> None:
        mock_detect.return_value = _detection()
        with override_flags(provider_drain=True):
            result = handle_possible_usage_limit(
                provider="claude", error_text="usage limit reached"
            )
        assert result is not None
        mock_submit.assert_called_once()
        mock_notify.assert_called_once()

    @patch("sase.procs.submit_proc_request")
    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_drain_payload_includes_reset_source(
        self,
        mock_detect: MagicMock,
        mock_notify: MagicMock,
        mock_submit: MagicMock,
        registered_providers: None,
    ) -> None:
        mock_detect.return_value = _detection(
            expires_at=_NOW + 100.0, reset_source="usage_window"
        )
        with override_flags(provider_drain=True):
            handle_possible_usage_limit(
                provider="claude", error_text="usage limit reached"
            )
        request = mock_submit.call_args.args[0]
        assert request.operation_payload["reset_source"] == "usage_window"

    @patch("sase.procs.submit_proc_request")
    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_flag_on_but_notify_disabled_sends_nothing(
        self,
        mock_detect: MagicMock,
        mock_notify: MagicMock,
        mock_submit: MagicMock,
        registered_providers: None,
    ) -> None:
        from sase.llm_provider.usage_limit_config import UsageLimitSettings

        mock_detect.return_value = _detection()
        with (
            override_flags(provider_drain=True),
            patch(
                "sase.llm_provider.usage_limit_disable.get_usage_limit_settings",
                return_value=UsageLimitSettings(notify=False),
            ),
        ):
            handle_possible_usage_limit(
                provider="claude", error_text="usage limit reached"
            )
        mock_submit.assert_not_called()
        mock_notify.assert_not_called()
