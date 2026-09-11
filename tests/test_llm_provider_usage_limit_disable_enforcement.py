"""Tests for the usage-limit-detection-to-disable enforcement path.

``handle_possible_usage_limit`` is called from the LLM invocation error
paths and from the workflow-error backstop; see
``tests/test_llm_provider_invoke.py`` and
``tests/test_axe_run_agent_exec_retry_usage_limits.py`` for the call-site
wiring. Notification wiring lives in the sibling
``test_llm_provider_usage_limit_disable_notification.py``, and the
provider_drain-gated ownership decision lives in
``test_llm_provider_usage_limit_disable_drain.py``.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from sase.llm_provider.model_alias_policy import XSMALL_MODEL_ALIAS_NAME
from sase.llm_provider.provider_disable import (
    disable_provider,
    get_active_provider_disable,
)
from sase.llm_provider.usage_limit_disable import handle_possible_usage_limit
from sase.notifications.store import load_notifications
from tests._llm_provider_usage_limit_disable_helpers import (
    _NOW,
    _detection,
    _sase_home,  # noqa: F401 (registers the autouse fixture)
)

_AGY_INDIVIDUAL_QUOTA_REACHED = (
    "Error: Individual quota reached. Please upgrade your subscription to increase\n"
    "your limits. Resets in 4h14m50s."
)

# Verbatim failure from the sase-o8.2 agent that motivated the absolute-
# reset-timestamp parser fix (see the plan's Background section).
_CODEX_TRY_AGAIN_AT_DATE = (
    "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to "
    "purchase more credits or try again at Aug 20th, 2026 6:38 AM."
)

# Verbatim 083 wrapper: ``_invoke`` CalledProcessError text plus the
# workflow ``Step 'main' failed:`` prefix. Compact ``8pm``.
_CLAUDE_WEEKLY_LIMIT_083_WRAPPER = (
    "Step 'main' failed: Error running LLM provider command (exit code 1)\n"
    "stderr: [result] You've hit your weekly limit · resets Aug 22, 8pm "
    "(America/New_York)\n"
    "output: I'll start by exploring the codebase ...\n"
    "You've hit your weekly limit · resets Aug 22, 8pm (America/New_York)"
)

# Verbatim stderr from the three 2026-08-18 grok agent failures that
# motivated this plan (see the plan's Background section).
_GROK_USAGE_BALANCE_EXHAUSTED = """\
Error running LLM provider command (exit code 1)
stderr: Error: Internal error: {
  "message": "API error (status 402 Payment Required): Grok Build usage balance exhausted",
  "http_status": 402,
  "promptUsage": { ... }
}"""


@pytest.fixture
def registered_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names",
        lambda: ["claude", "codex", "fakey", "grok", "agy"],
    )


class TestHandlePossibleUsageLimit:
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_returns_none_when_no_match(
        self, mock_detect: MagicMock, registered_providers: None
    ) -> None:
        mock_detect.return_value = None
        result = handle_possible_usage_limit(provider="claude", error_text="all good")
        assert result is None
        assert get_active_provider_disable("claude") is None

    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_writes_flat_disable_when_no_expiry(
        self, mock_detect: MagicMock, registered_providers: None
    ) -> None:
        mock_detect.return_value = _detection(disable_seconds=120.0)
        result = handle_possible_usage_limit(
            provider="claude", error_text="usage limit reached"
        )
        assert result is not None
        disable = get_active_provider_disable("claude")
        assert disable is not None
        assert disable.source == "usage_limit"
        assert disable.expires_at is not None

    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_writes_until_disable_when_expiry_present(
        self, mock_detect: MagicMock, registered_providers: None
    ) -> None:
        mock_detect.return_value = _detection(expires_at=_NOW + 3600.0)
        handle_possible_usage_limit(provider="claude", error_text="usage limit reached")
        disable = get_active_provider_disable("claude", now=_NOW)
        assert disable is not None
        assert disable.expires_at == _NOW + 3600.0
        assert disable.source == "usage_limit"

    def test_codex_reset_at_date_failure_writes_until_disable_at_parsed_instant(
        self, monkeypatch: pytest.MonkeyPatch, registered_providers: None
    ) -> None:
        # Enforcement, not just parsing: the absolute reset instant the
        # Codex failure names must reach the store via try_disable_provider_
        # until, not the flat now+86400 branch.
        tz = ZoneInfo("UTC")
        fixed_now = datetime(2026, 8, 17, 6, 38, 0, tzinfo=tz).timestamp()
        monkeypatch.setattr(
            "sase.llm_provider.usage_limit_disable.time.time", lambda: fixed_now
        )
        monkeypatch.setattr("sase.core.time.get_timezone", lambda: tz)

        result = handle_possible_usage_limit(
            provider="codex", error_text=_CODEX_TRY_AGAIN_AT_DATE
        )

        assert result is not None
        assert result.used_reset_hint is True
        assert result.expires_at is not None

        disable = get_active_provider_disable("codex", now=fixed_now)
        assert disable is not None
        assert disable.source == "usage_limit"
        expected_expires_at = (
            datetime(2026, 8, 20, 6, 38, 0, tzinfo=tz).timestamp() + 60
        )
        assert disable.expires_at == pytest.approx(expected_expires_at, abs=1)
        assert disable.expires_at != pytest.approx(fixed_now + 86400, abs=3600)

    def test_claude_083_weekly_limit_writes_until_disable_at_parsed_instant(
        self, monkeypatch: pytest.MonkeyPatch, registered_providers: None
    ) -> None:
        tz = ZoneInfo("America/New_York")
        fixed_now = datetime(2026, 8, 19, 15, 43, 56, tzinfo=tz).timestamp()
        monkeypatch.setattr(
            "sase.llm_provider.usage_limit_disable.time.time", lambda: fixed_now
        )
        monkeypatch.setattr(
            "sase.llm_provider.usage_limit_config.load_merged_config",
            lambda: {},
        )

        result = handle_possible_usage_limit(
            provider="claude", error_text=_CLAUDE_WEEKLY_LIMIT_083_WRAPPER
        )

        assert result is not None
        assert result.used_reset_hint is True
        assert result.expires_at is not None

        disable = get_active_provider_disable("claude", now=fixed_now)
        assert disable is not None
        assert disable.source == "usage_limit"
        expected_expires_at = (
            datetime(2026, 8, 22, 20, 0, 0, tzinfo=tz).timestamp() + 60
        )
        assert disable.expires_at == pytest.approx(expected_expires_at, abs=1)
        assert disable.expires_at != pytest.approx(fixed_now + 86400, abs=3600)

        notifications = [
            note for note in load_notifications() if note.sender == "llm.usage_limit"
        ]
        assert len(notifications) == 1

    def test_grok_usage_balance_exhausted_writes_flat_48h_disable(
        self, registered_providers: None
    ) -> None:
        # Enforcement, not just detection: Grok Build reports no reset
        # instant, so this must exercise the flat try_disable_provider
        # branch at the plan's 48h duration — not the reset-hint-derived
        # try_disable_provider_until branch the codex test above exercises.
        # try_disable_provider's expiry is computed store-side against the
        # caller's sampled clock, so the duration is asserted from the stored
        # created_at/expires_at pair rather than a pinned Python-side clock.
        result = handle_possible_usage_limit(
            provider="grok", error_text=_GROK_USAGE_BALANCE_EXHAUSTED
        )

        assert result is not None
        assert result.used_reset_hint is False
        assert result.expires_at is None

        disable = get_active_provider_disable("grok")
        assert disable is not None
        assert disable.source == "usage_limit"
        assert disable.expires_at is not None
        duration = disable.expires_at - disable.created_at
        assert duration == pytest.approx(172800, abs=5)
        assert duration != pytest.approx(86400, abs=5)

    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_skips_write_when_already_disabled(
        self,
        mock_detect: MagicMock,
        mock_notify: MagicMock,
        registered_providers: None,
    ) -> None:
        existing = disable_provider("claude", 999.0, source="usage_limit", now=_NOW)
        mock_detect.return_value = _detection()
        mock_counter = MagicMock()

        with patch(
            "sase.llm_provider.usage_limit_disable.LLM_PROVIDER_AUTO_DISABLES",
            mock_counter,
        ):
            result = handle_possible_usage_limit(
                provider="claude", error_text="usage limit reached"
            )

        assert result is not None
        stored = get_active_provider_disable("claude", now=_NOW)
        assert stored == existing
        mock_counter.labels.assert_not_called()
        mock_notify.assert_not_called()

    @patch(
        "sase.llm_provider.usage_limit_disable.detect_usage_limit",
        side_effect=RuntimeError("boom"),
    )
    def test_never_raises_on_internal_error(
        self, _mock_detect: MagicMock, registered_providers: None
    ) -> None:
        result = handle_possible_usage_limit(
            provider="claude", error_text="usage limit reached"
        )
        assert result is None

    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_increments_telemetry_counter_on_write(
        self, mock_detect: MagicMock, registered_providers: None
    ) -> None:
        mock_detect.return_value = _detection()
        mock_counter = MagicMock()
        with patch(
            "sase.llm_provider.usage_limit_disable.LLM_PROVIDER_AUTO_DISABLES",
            mock_counter,
        ):
            handle_possible_usage_limit(
                provider="claude", error_text="usage limit reached"
            )
        mock_counter.labels.assert_called_once_with(provider="claude")
        mock_counter.labels.return_value.inc.assert_called_once()

    def test_end_to_end_with_fakey_trigger(self, registered_providers: None) -> None:
        """The fakey provider's deterministic trigger exercises real detection."""
        result = handle_possible_usage_limit(
            provider="fakey",
            error_text="stderr: FAKEY-USAGE-LIMIT hit",
        )
        assert result is not None
        assert result.provider == "fakey"
        disable = get_active_provider_disable("fakey")
        assert disable is not None
        assert disable.source == "usage_limit"

    def test_end_to_end_no_match_leaves_provider_enabled(
        self, registered_providers: None
    ) -> None:
        result = handle_possible_usage_limit(
            provider="fakey",
            error_text="some unrelated transient error",
        )
        assert result is None
        assert get_active_provider_disable("fakey") is None

    def test_agy_captured_failure_disables_xsmall_pool_member(
        self,
        monkeypatch: pytest.MonkeyPatch,
        registered_providers: None,
        real_model_alias_defaults: None,
    ) -> None:
        from sase.llm_provider import registry
        from sase.llm_provider.config import model_alias_selector_details
        from sase.llm_provider.model_alias_resolution import (
            resolved_target_is_available,
        )

        monkeypatch.setattr(registry, "_provider_cli_available", lambda _provider: True)
        details = model_alias_selector_details(XSMALL_MODEL_ALIAS_NAME)
        assert details is not None
        agy_member = next(
            member for member in details.members if member.provider == "agy"
        )
        agy_target = agy_member.target
        assert resolved_target_is_available(agy_target) is True

        result = handle_possible_usage_limit(
            provider="agy",
            error_text=_AGY_INDIVIDUAL_QUOTA_REACHED,
        )

        assert result is not None
        disable = get_active_provider_disable("agy")
        assert disable is not None
        assert disable.source == "usage_limit"
        assert resolved_target_is_available(agy_target) is False

        details = model_alias_selector_details(XSMALL_MODEL_ALIAS_NAME)
        assert details is not None
        agy_member = next(
            member for member in details.members if member.target == agy_target
        )
        assert agy_member.available is False
