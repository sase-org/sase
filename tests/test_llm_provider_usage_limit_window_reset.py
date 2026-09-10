"""Tests for the collected-usage-window disable-expiry fallback.

``usage_window_expires_at`` is the glue ``detect_usage_limit`` consults when a
usage-limit error carries no parseable reset hint (see
``tests/test_llm_provider_usage_limit_detect.py`` for that integration).
"""

from __future__ import annotations

from typing import Any

import pytest

from sase.llm_provider.usage.store import ProviderUsageStoreRead
from sase.llm_provider.usage_limit_window_reset import usage_window_expires_at
from tests._usage_view_helpers import FROZEN_NOW, usage_provider, usage_window


def _patch_read(monkeypatch: pytest.MonkeyPatch, *providers: dict[str, Any]) -> None:
    read = ProviderUsageStoreRead(
        version=1,
        snapshot={"providers": list(providers), "generated_at": FROZEN_NOW},
        diagnostics=(),
    )
    monkeypatch.setattr(
        "sase.llm_provider.usage_limit_window_reset.load_provider_usage",
        lambda **_kw: read,
    )


class TestUsageWindowExpiresAt:
    def test_corroborated_fresh_window_returns_its_reset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = usage_provider("grok", used_percent=95.0, remaining_percent=5.0)
        _patch_read(monkeypatch, provider)

        result = usage_window_expires_at("grok", None, now=FROZEN_NOW)

        assert result == FROZEN_NOW + 7_200.0

    def test_unknown_provider_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_read(monkeypatch, usage_provider("grok"))
        assert usage_window_expires_at("codex", None, now=FROZEN_NOW) is None

    def test_missing_summary_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = usage_provider("grok", used_percent=None, remaining_percent=None)
        _patch_read(monkeypatch, provider)
        assert usage_window_expires_at("grok", None, now=FROZEN_NOW) is None

    def test_below_critical_percent_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = usage_provider("grok", used_percent=50.0, remaining_percent=50.0)
        _patch_read(monkeypatch, provider)
        assert usage_window_expires_at("grok", None, now=FROZEN_NOW) is None

    def test_missing_resets_at_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window = usage_window(resets_at=None)
        provider = usage_provider(
            "grok", used_percent=95.0, remaining_percent=5.0, windows=[window]
        )
        _patch_read(monkeypatch, provider)
        assert usage_window_expires_at("grok", None, now=FROZEN_NOW) is None

    def test_resets_at_in_the_past_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window = usage_window(resets_at=FROZEN_NOW - 100.0)
        provider = usage_provider(
            "grok", used_percent=95.0, remaining_percent=5.0, windows=[window]
        )
        _patch_read(monkeypatch, provider)
        assert usage_window_expires_at("grok", None, now=FROZEN_NOW) is None

    def test_load_provider_usage_raising_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(**_kw: object) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "sase.llm_provider.usage_limit_window_reset.load_provider_usage", _boom
        )
        assert usage_window_expires_at("grok", None, now=FROZEN_NOW) is None

    def test_model_scoping_selects_the_applicable_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The default window applies only to "gpt-5"; the account-scope
        # summary is left absent so only the model-scoped path can succeed.
        window = usage_window(used_percent=95.0, remaining_percent=5.0)
        provider = usage_provider(
            "codex",
            used_percent=None,
            remaining_percent=None,
            windows=[window],
        )
        _patch_read(monkeypatch, provider)

        result = usage_window_expires_at("codex", "codex/gpt-5", now=FROZEN_NOW)

        assert result == FROZEN_NOW + 7_200.0

    def test_model_not_applicable_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window = usage_window(used_percent=95.0, remaining_percent=5.0)
        provider = usage_provider(
            "codex",
            used_percent=None,
            remaining_percent=None,
            windows=[window],
        )
        _patch_read(monkeypatch, provider)

        assert usage_window_expires_at("codex", "codex/sonnet", now=FROZEN_NOW) is None

    def test_account_scope_used_when_model_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The window itself is only model-applicable, but the account-scope
        # "summary" field still corroborates and is used when model is None.
        window = usage_window(used_percent=95.0, remaining_percent=5.0)
        provider = usage_provider(
            "codex",
            used_percent=95.0,
            remaining_percent=5.0,
            windows=[window],
        )
        _patch_read(monkeypatch, provider)

        result = usage_window_expires_at("codex", None, now=FROZEN_NOW)

        assert result == FROZEN_NOW + 7_200.0

    def test_ties_across_limiting_windows_use_the_max_reset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window_a = usage_window(
            key="a",
            resets_at=FROZEN_NOW + 1_000.0,
            applicability={"kind": "account"},
        )
        window_b = usage_window(
            key="b",
            resets_at=FROZEN_NOW + 5_000.0,
            applicability={"kind": "account"},
        )
        provider = usage_provider(
            "grok",
            used_percent=95.0,
            remaining_percent=5.0,
            windows=[window_a, window_b],
        )
        # The helper's summary always names "shared"; override to exercise
        # the tie-break across both limiting windows.
        assert provider["summary"] is not None
        provider["summary"]["limiting_window_keys"] = ["a", "b"]
        _patch_read(monkeypatch, provider)

        result = usage_window_expires_at("grok", None, now=FROZEN_NOW)

        assert result == FROZEN_NOW + 5_000.0
