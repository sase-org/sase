"""Tests for automatic ACE update checks."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sase.ace.tui.actions import update_toast
from sase.updates import ProviderUpdateCandidate, UpdateStatus

from tests.ace.tui._update_toast_helpers import (
    _AutomaticCheckApp,
    _core_status,
    _status,
)


def test_startup_registers_one_default_interval_and_off_thread_worker() -> None:
    app = _AutomaticCheckApp()

    app._schedule_startup_update_toast_check()
    app._schedule_startup_update_toast_check()

    assert len(app.intervals) == 1
    interval, callback, name = app.intervals[0]
    assert interval == 600.0
    assert callback == app._on_periodic_update_check
    assert name == "automatic-update-check"
    assert len(app.workers) == 1
    assert app.workers[0][0] == app._run_startup_update_toast_check
    assert app.workers[0][1]["thread"] is True


def test_timer_registration_uses_in_memory_interval_without_loading_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _AutomaticCheckApp()
    app._automatic_update_check_interval_seconds = 90.0
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: pytest.fail("timer registration must not reload config"),
    )

    app._start_periodic_update_checks()
    app._start_periodic_update_checks()

    assert [(interval, name) for interval, _callback, name in app.intervals] == [
        (90.0, "automatic-update-check")
    ]


def test_periodic_tick_checks_positive_indicator_but_skips_in_flight_check() -> None:
    app = _AutomaticCheckApp(indicator_count=2)

    app._on_periodic_update_check()
    assert len(app.workers) == 1

    app._on_periodic_update_check()
    assert len(app.workers) == 1


def test_periodic_tick_schedules_clear_indicator_off_thread() -> None:
    app = _AutomaticCheckApp()

    app._on_periodic_update_check()

    assert len(app.workers) == 1
    assert app.workers[0][1] == {
        "name": "automatic-update-check",
        "thread": True,
        "exclusive": False,
        "group": "startup-loads",
    }
    assert app._automatic_update_check_in_flight is True


def test_automatic_update_worker_scheduling_failure_releases_guard() -> None:
    class _App(_AutomaticCheckApp):
        def run_worker(
            self,
            callback: Callable[[], None],
            **kwargs: object,
        ) -> None:
            del callback, kwargs
            raise RuntimeError("worker unavailable")

    app = _App()

    app._on_periodic_update_check()

    assert app._automatic_update_check_in_flight is False


def test_periodic_update_check_releases_guard_on_no_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(),
    )
    monkeypatch.setattr(update_toast, "get_cached_update_status", lambda **_kw: None)
    app = _AutomaticCheckApp()

    app._on_periodic_update_check()
    app.workers[0][0]()

    assert app._automatic_update_check_in_flight is False


def test_periodic_update_check_releases_guard_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(),
    )

    def fail_status(**_kwargs: object) -> None:
        raise RuntimeError("status failed")

    monkeypatch.setattr(update_toast, "get_cached_update_status", fail_status)
    app = _AutomaticCheckApp()

    app._on_periodic_update_check()
    app.workers[0][0]()

    assert app._automatic_update_check_in_flight is False


def test_periodic_update_revalidates_each_tick_but_shows_toast_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(
            recompute_interval_seconds=10**12,
        ),
    )

    def get_status(**_kwargs: object) -> UpdateStatus:
        nonlocal calls
        calls += 1
        return _status()

    monkeypatch.setattr(update_toast, "get_cached_update_status", get_status)
    monkeypatch.setattr(update_toast, "_build_startup_toast_sections", lambda *_a: ())

    class _App(_AutomaticCheckApp):
        def run_worker(
            self,
            callback: Callable[[], None],
            **kwargs: object,
        ) -> None:
            super().run_worker(callback, **kwargs)
            callback()

    app = _App()

    app._on_periodic_update_check()
    app._on_periodic_update_check()

    assert calls == 2
    assert len(app.workers) == 2
    assert app.indicator.count == 2
    assert len(app.notifications) == 1
    assert app._automatic_update_check_in_flight is False


def test_periodic_update_threads_core_state_to_indicator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(startup_toast=False),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: _core_status(),
    )
    app = _AutomaticCheckApp()

    app._on_periodic_update_check()
    app.workers[0][0]()

    assert app.indicator.count == 2
    assert app.indicator.core is True


def test_periodic_update_threads_composite_aggregate_to_indicator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(),
        provider_candidates=(
            ProviderUpdateCandidate(
                "claude",
                "Claude Code",
                "1.0.0",
                "1.1.0",
                manual_only=True,
            ),
        ),
    )
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(startup_toast=False),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: status,
    )
    app = _AutomaticCheckApp()

    app._on_periodic_update_check()
    app.workers[0][0]()

    assert app.indicator.count == 1
    assert app.indicator.sase_count == 0
    assert app.indicator.agent_cli_count == 1
    assert app.indicator.manual_agent_cli_count == 1
    assert app.indicator.core is False


def test_completed_automatic_results_atomically_replace_provider_projection() -> None:
    app = _AutomaticCheckApp()
    config = update_toast._UpdateToastConfig(
        startup_toast=False,
        indicator=False,
    )
    first = UpdateStatus(
        checked_at=100.0,
        components=(),
        provider_candidates=(
            ProviderUpdateCandidate("claude", "Claude Code", "1.0", "1.1"),
            ProviderUpdateCandidate("codex", "Codex CLI", "0.9", "1.0"),
        ),
    )

    app._apply_startup_update_status(first, config)
    assert app._automatic_update_provider_names == ("claude", "codex")

    app._complete_automatic_update_check(None)
    assert app._automatic_update_provider_names == ("claude", "codex")

    app._apply_startup_update_status(
        UpdateStatus(checked_at=200.0, components=()),
        config,
    )
    assert app._automatic_update_provider_names == ()


def test_provider_only_status_updates_indicator_and_provider_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(),
        provider_candidates=(
            ProviderUpdateCandidate("claude", "Claude Code", "1.0.0", "1.1.0"),
        ),
    )
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: status,
    )
    monkeypatch.setattr(
        update_toast,
        "_build_startup_toast_sections",
        lambda *_args: pytest.fail("provider toast presentation is a later phase"),
    )
    app = _AutomaticCheckApp()

    app._on_periodic_update_check()
    app.workers[0][0]()

    assert app.indicator.count == 1
    assert len(app.notifications) == 1
    assert "CLI Claude Code" in str(app.notifications[0]["message"])
    assert "eligible set" in str(app.notifications[0]["message"])


def test_cached_revalidation_threads_core_state_to_indicator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **kwargs: (
            _core_status()
            if kwargs == {"revalidate_only": True}
            else pytest.fail(f"unexpected cache args: {kwargs}")
        ),
    )
    app = _AutomaticCheckApp()

    app._run_updates_indicator_revalidation()

    assert app.indicator.count == 2
    assert app.indicator.core is True


def test_cached_revalidation_clears_state_when_indicator_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(indicator=False),
    )
    app = _AutomaticCheckApp(indicator_count=2)
    app.indicator.core = True

    app._run_updates_indicator_revalidation(_core_status())

    assert app.indicator.count == 0
    assert app.indicator.core is False


def test_indicator_disabled_skips_periodic_status_but_keeps_startup_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_calls = 0
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(indicator=False),
    )

    def get_status(**_kwargs: object) -> UpdateStatus:
        nonlocal status_calls
        status_calls += 1
        return _status(count=1)

    monkeypatch.setattr(update_toast, "get_cached_update_status", get_status)
    monkeypatch.setattr(update_toast, "_build_startup_toast_sections", lambda *_a: ())
    app = _AutomaticCheckApp()

    app._schedule_startup_update_toast_check()
    app.workers.pop()[0]()
    assert status_calls == 1
    assert len(app.notifications) == 1

    app._update_toast_shown = False
    app._on_periodic_update_check()
    app.workers.pop()[0]()
    assert status_calls == 1
    assert app._automatic_update_check_in_flight is False


def test_check_ttl_is_passed_without_changing_configured_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(
            startup_toast=False,
            check_ttl_seconds=0.0,
        ),
    )

    def get_status(**kwargs: object) -> None:
        captured.update(kwargs)
        return None

    monkeypatch.setattr(update_toast, "get_cached_update_status", get_status)
    app = _AutomaticCheckApp()
    app._automatic_update_check_interval_seconds = 1800.0

    app._schedule_startup_update_toast_check()
    app.workers[0][0]()

    assert app.intervals[0][0] == 1800.0
    assert captured == {"ttl_seconds": 0.0}
    assert app._automatic_update_check_in_flight is False


def test_periodic_check_revalidates_stale_ttl_snapshot_without_compute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = _status(count=0)
    calls: list[dict[str, object]] = []

    def get_status(**kwargs: object) -> UpdateStatus:
        calls.append(dict(kwargs))
        return status

    monkeypatch.setattr(update_toast, "get_cached_update_status", get_status)

    result = update_toast._get_automatic_update_status(
        update_toast._UpdateToastConfig(
            check_ttl_seconds=600.0,
            recompute_interval_seconds=3600.0,
        ),
        periodic=True,
        now=700.0,
    )

    assert result == status
    assert calls == [{"revalidate_only": True}]


def test_periodic_check_recomputes_when_configured_interval_elapses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached = _status(count=0)
    recomputed = UpdateStatus(checked_at=700.0, components=())
    calls: list[dict[str, object]] = []

    def get_status(**kwargs: object) -> UpdateStatus:
        calls.append(dict(kwargs))
        return cached if len(calls) == 1 else recomputed

    monkeypatch.setattr(update_toast, "get_cached_update_status", get_status)

    result = update_toast._get_automatic_update_status(
        update_toast._UpdateToastConfig(recompute_interval_seconds=600.0),
        periodic=True,
        now=700.0,
    )

    assert result == recomputed
    assert calls == [
        {"revalidate_only": True},
        {"ttl_seconds": 0.0},
    ]
