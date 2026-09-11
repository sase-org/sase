"""Notification wiring for ``handle_possible_usage_limit``.

Fired on write, never on skip, isolated failures. Enforcement (detect ->
disable) behavior lives in the sibling
``test_llm_provider_usage_limit_disable_enforcement.py``.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.provider_disable import (
    disable_provider,
    get_active_provider_disable,
    get_active_provider_disables,
)
from sase.llm_provider.usage_limit_disable import handle_possible_usage_limit
from sase.notifications.store import load_notifications
from tests._llm_provider_usage_limit_disable_helpers import (
    _detection,
    _sase_home,  # noqa: F401 (registers the autouse fixture)
)


@pytest.fixture
def registered_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names",
        lambda: ["claude", "codex", "fakey", "grok", "agy"],
    )


class TestUsageLimitNotification:
    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_notifies_once_on_new_disable(
        self,
        mock_detect: MagicMock,
        mock_notify: MagicMock,
        registered_providers: None,
    ) -> None:
        mock_detect.return_value = _detection()
        result = handle_possible_usage_limit(
            provider="claude", error_text="usage limit reached"
        )
        assert result is not None
        mock_notify.assert_called_once()
        assert mock_notify.call_args.args[0] is result

    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_contending_detections_notify_and_increment_exactly_once(
        self,
        mock_detect: MagicMock,
        registered_providers: None,
    ) -> None:
        sibling = disable_provider("codex", 1_200.0, source="sibling")
        mock_detect.return_value = _detection()
        increments: list[str] = []
        lock = threading.Lock()
        errors: list[BaseException] = []
        worker_count = 8
        barrier = threading.Barrier(worker_count)

        class _Counter:
            def labels(self, **kwargs: object) -> object:
                provider = str(kwargs.get("provider"))

                class _Labeled:
                    def inc(self) -> None:
                        with lock:
                            increments.append(provider)

                return _Labeled()

        def worker() -> None:
            try:
                barrier.wait(timeout=5)
                handle_possible_usage_limit(
                    provider="claude", error_text="usage limit reached"
                )
            except BaseException as exc:  # noqa: BLE001 - collected for the parent
                errors.append(exc)

        with patch(
            "sase.llm_provider.usage_limit_disable.LLM_PROVIDER_AUTO_DISABLES",
            _Counter(),
        ):
            threads = [
                threading.Thread(target=worker, name=f"usage-limit-{index}")
                for index in range(worker_count)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
                assert not thread.is_alive()

        assert errors == []
        stored = get_active_provider_disables()
        assert stored["codex"].provider == sibling.provider
        assert stored["codex"].source == sibling.source
        assert stored["codex"].created_at == pytest.approx(sibling.created_at)
        assert stored["codex"].expires_at == pytest.approx(sibling.expires_at)
        assert stored["claude"].source == "usage_limit"
        assert increments == ["claude"]
        notifications = [
            note for note in load_notifications() if note.sender == "llm.usage_limit"
        ]
        assert len(notifications) == 1
        assert "claude" in notifications[0].tags

    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch(
        "sase.llm_provider.usage_limit_disable.get_usage_limit_settings",
    )
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_respects_notify_setting(
        self,
        mock_detect: MagicMock,
        mock_settings: MagicMock,
        mock_notify: MagicMock,
        registered_providers: None,
    ) -> None:
        from sase.llm_provider.usage_limit_config import UsageLimitSettings

        mock_detect.return_value = _detection()
        mock_settings.return_value = UsageLimitSettings(notify=False)

        result = handle_possible_usage_limit(
            provider="claude", error_text="usage limit reached"
        )

        assert result is not None
        mock_notify.assert_not_called()

    @patch(
        "sase.notifications.senders.notify_provider_usage_limit_disabled",
        side_effect=RuntimeError("boom"),
    )
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_notification_failure_does_not_mask_the_detection(
        self,
        mock_detect: MagicMock,
        _mock_notify: MagicMock,
        registered_providers: None,
    ) -> None:
        mock_detect.return_value = _detection()
        result = handle_possible_usage_limit(
            provider="claude", error_text="usage limit reached"
        )
        assert result is not None
        assert get_active_provider_disable("claude") is not None

    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_no_notification_when_no_match(
        self,
        mock_detect: MagicMock,
        mock_notify: MagicMock,
        registered_providers: None,
    ) -> None:
        mock_detect.return_value = None
        handle_possible_usage_limit(provider="claude", error_text="all good")
        mock_notify.assert_not_called()

    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_passes_agent_name_read_from_artifacts_dir(
        self,
        mock_detect: MagicMock,
        mock_notify: MagicMock,
        registered_providers: None,
        tmp_path,
    ) -> None:
        import json

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps({"name": "bbugyi200.athena.03j"})
        )
        mock_detect.return_value = _detection()

        handle_possible_usage_limit(
            provider="claude",
            error_text="usage limit reached",
            artifacts_dir=str(artifacts_dir),
        )

        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["agent_name"] == "bbugyi200.athena.03j"

    @patch("sase.notifications.senders.notify_provider_usage_limit_disabled")
    @patch("sase.llm_provider.usage_limit_disable.detect_usage_limit")
    def test_agent_name_none_when_meta_file_missing(
        self,
        mock_detect: MagicMock,
        mock_notify: MagicMock,
        registered_providers: None,
        tmp_path,
    ) -> None:
        mock_detect.return_value = _detection()

        handle_possible_usage_limit(
            provider="claude",
            error_text="usage limit reached",
            artifacts_dir=str(tmp_path / "does-not-exist"),
        )

        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["agent_name"] is None
