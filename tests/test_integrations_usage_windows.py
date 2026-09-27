"""Tests for the presentation-neutral usage-windows integration facade."""

from __future__ import annotations

import pytest

from sase.integrations import usage_windows
from sase.integrations.usage_windows import (
    USAGE_WINDOWS_REFRESH_TIMEOUT_SECONDS,
    live_usage_refresh_operations,
    request_usage_windows_refresh,
    resolve_usage_provider,
    usage_windows_report,
)
from sase.llm_provider.usage._refresh_model import (
    USAGE_REFRESH_BATCH_DEADLINE_SECONDS,
)
from tests._usage_view_helpers import FROZEN_NOW, usage_provider, usage_window


def _snapshot(*providers: dict) -> dict:
    return {
        "schema_version": 1,
        "generated_at": FROZEN_NOW,
        "collection_health": "ok" if providers else "empty",
        "providers": list(providers),
        "attention": None,
    }


class _Read:
    def __init__(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        self.diagnostics: tuple = ()
        self.version = 1


def _install_report_fakes(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict,
    *,
    eligible: tuple[str, ...] = ("codex",),
    captured: dict | None = None,
) -> None:
    from sase.llm_provider.usage import config as usage_config
    from sase.llm_provider.usage import refresh as usage_refresh
    from sase.llm_provider.usage import store as usage_store

    monkeypatch.setattr(
        usage_config,
        "get_usage_metrics_settings",
        lambda: usage_config.UsageMetricsSettings(
            enabled=True,
            refresh_seconds=300.0,
            active_refresh_seconds=120.0,
            warn_percent=75.0,
            critical_percent=90.0,
            providers={},
        ),
    )
    monkeypatch.setattr(
        usage_refresh, "eligible_usage_providers", lambda **kwargs: eligible
    )
    monkeypatch.setattr(
        usage_store, "load_provider_usage", lambda **kwargs: _Read(snapshot)
    )
    if captured is not None:
        real_project = usage_store.provider_usage_project_indicator

        def _capture(
            snapshot_arg,
            *,
            indicator=None,
            eligible_providers=None,
            **kwargs,
        ):
            captured["indicator"] = indicator
            captured["eligible_providers"] = eligible_providers
            return real_project(
                snapshot_arg,
                indicator=indicator,
                eligible_providers=eligible_providers,
                **kwargs,
            )

        monkeypatch.setattr(usage_store, "provider_usage_project_indicator", _capture)


def test_refresh_timeout_adds_thirty_seconds() -> None:
    assert (
        USAGE_WINDOWS_REFRESH_TIMEOUT_SECONDS
        == USAGE_REFRESH_BATCH_DEADLINE_SECONDS + 30.0
    )


def test_select_everything_returns_header_never_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = usage_window(key="session", label="Session 5h")
    window["applicability"] = {"kind": "account"}
    snapshot = _snapshot(usage_provider("codex", windows=[window]))
    captured: dict = {}
    _install_report_fakes(monkeypatch, snapshot, captured=captured)
    report = usage_windows_report(now=FROZEN_NOW)
    assert captured["indicator"] == {
        "enabled": True,
        "default": "always",
        "weekly_all": "always",
    }
    assert [row.provider for row in report.providers] == ["codex"]
    assert [w.key for w in report.providers[0].windows] == ["session"]
    assert report.configured_providers == ("codex",)
    assert report.collection_enabled is True


def test_joins_plan_status_and_retry_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = usage_provider(
        "codex",
        plan="Plus",
        collector_health={
            "state": "degraded",
            "last_failure_reason": "rate_limited",
            "retry_at": FROZEN_NOW + 3120.0,
            "consecutive_failures": 2,
        },
    )
    _install_report_fakes(monkeypatch, _snapshot(provider))
    report = usage_windows_report(now=FROZEN_NOW)
    row = report.providers[0]
    assert row.plan == "Plus"
    assert row.collector_state == "degraded"
    assert row.retry_label is not None and "rate limited" in row.retry_label
    assert "retry in" in row.retry_label
    assert row.status_label
    assert row.windows[0].remaining_text.endswith("left")
    assert row.windows[0].scope_models


def test_requested_but_missing_provider_gets_no_observations_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_report_fakes(
        monkeypatch,
        _snapshot(),
        eligible=("codex",),
    )
    report = usage_windows_report(("grok",), now=FROZEN_NOW)
    assert [row.provider for row in report.providers] == ["grok"]
    assert report.providers[0].collection_status == "no_observations"
    assert report.providers[0].windows == ()


def test_disabled_collection_returns_empty_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider.usage import config as usage_config

    monkeypatch.setattr(
        usage_config,
        "get_usage_metrics_settings",
        lambda: usage_config.UsageMetricsSettings(
            enabled=False,
            refresh_seconds=300.0,
            active_refresh_seconds=120.0,
            warn_percent=75.0,
            critical_percent=90.0,
            providers={},
        ),
    )
    report = usage_windows_report(now=FROZEN_NOW)
    assert report.collection_enabled is False
    assert report.providers == ()


def test_resolve_usage_provider_matches_key_and_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider import registry as registry

    monkeypatch.setattr(registry, "registered_provider_names", lambda: ["codex", "agy"])
    monkeypatch.setattr(
        registry,
        "get_llm_metadata_payload",
        lambda: {
            "providers": {
                "codex": {"display_name": "Codex"},
                "agy": {"display_name": "Antigravity"},
            }
        },
    )
    assert resolve_usage_provider("codex") == "codex"
    assert resolve_usage_provider("CODEX") == "codex"
    assert resolve_usage_provider("antigravity") == "agy"
    assert resolve_usage_provider("Antigravity") == "agy"
    assert resolve_usage_provider("bogus") is None


def test_live_operations_reports_live_settled_and_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider.usage import store as usage_store

    class _Reservation:
        def __init__(self, operation_id: str) -> None:
            self.operation_id = operation_id

    monkeypatch.setattr(
        usage_store,
        "list_provider_usage_refresh_reservations",
        lambda **kwargs: (_Reservation("op1"),),
    )
    assert live_usage_refresh_operations(("op1", "op2")) == frozenset({"op1"})
    assert live_usage_refresh_operations(()) == frozenset()

    def _fail(**kwargs):
        raise OSError("store gone")

    monkeypatch.setattr(usage_store, "list_provider_usage_refresh_reservations", _fail)
    assert live_usage_refresh_operations(("op1",)) == frozenset({"op1"})


def test_request_refresh_uses_chat_origin_and_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider.usage import refresh as usage_refresh
    from sase.llm_provider.usage._refresh_model import (
        UsageRefreshProviderResult,
        UsageRefreshReceipt,
    )

    calls: dict = {}

    def _submit(providers, *, explicit, origin, **kwargs):
        calls["providers"] = providers
        calls["explicit"] = explicit
        calls["origin"] = origin
        return UsageRefreshReceipt(
            schema_version=1,
            origin=origin,
            operation_ids=("op1",),
            providers=(
                UsageRefreshProviderResult(
                    provider="codex",
                    status="reserved",
                    reason="cadence",
                    operation_id="op1",
                ),
            ),
        )

    monkeypatch.setattr(usage_refresh, "submit_usage_refresh", _submit)
    result = request_usage_windows_refresh(("codex",))
    assert calls == {"providers": ("codex",), "explicit": True, "origin": "chat"}
    assert result.started is True
    assert result.operation_ids == ("op1",)
    assert result.providers == ("codex",)
    assert "codex" in result.summary


def test_facade_functions_carry_telegram_symvision_pragmas() -> None:
    import pathlib

    path = (
        pathlib.Path(usage_windows.__file__).with_name("usage_windows.py").read_text()
    )
    for name in (
        "def usage_windows_report",
        "def resolve_usage_provider",
        "def request_usage_windows_refresh",
        "def live_usage_refresh_operations",
    ):
        index = path.index(name)
        pragma_window = path[max(0, index - 300) : index]
        assert "https://github.com/sase-org/sase-telegram.git" in pragma_window
