"""Tests for the ACE startup update toast."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.tui.actions.update_toast import (
    UpdateToastMixin,
)
from sase.updates import (
    CommitSourceSpec,
    CommitSummary,
    IncomingCommits,
    OutdatedComponent,
    UpdateStatus,
)
from sase.updates.status import ComponentRole

from tests.ace.tui.visual._ace_png_snapshot_helpers import patch_startup_loaders


def _status(count: int = 2) -> UpdateStatus:
    components = [
        OutdatedComponent(
            display_name="sase",
            role="host",
            installed_version="1.0.0",
            latest_version="1.1.0",
            distribution_name="sase",
        ),
        OutdatedComponent(
            display_name="github",
            role="plugin",
            installed_version="0.5.0",
            latest_version="0.6.0",
            distribution_name="sase-github",
        ),
        OutdatedComponent(
            display_name="telegram",
            role="plugin",
            installed_version="0.1.0",
            latest_version="0.2.0",
            distribution_name="sase-telegram",
        ),
        OutdatedComponent(
            display_name="nvim",
            role="plugin",
            installed_version="0.3.0",
            latest_version="0.4.0",
            distribution_name="sase-nvim",
        ),
    ]
    return UpdateStatus(checked_at=100.0, components=tuple(components[:count]))


def _editable_component(
    name: str,
    *,
    role: ComponentRole = "plugin",
    root: str | None = None,
) -> OutdatedComponent:
    return OutdatedComponent(
        display_name=name,
        role=role,
        installed_version="1.0.0",
        latest_version="1.1.0",
        distribution_name=name,
        install_type="editable",
        source_root=root or f"/repo/{name}",
        upstream_ref="origin/main",
    )


def _incoming(prefix: str, total: int) -> IncomingCommits:
    return IncomingCommits(
        total=total,
        commits=tuple(
            CommitSummary(f"{prefix}{idx:06d}"[:7], f"{prefix} commit {idx}")
            for idx in range(total)
        ),
        source="git",
    )


class _Indicator:
    def __init__(self, count: int = 0) -> None:
        self.count = count

    def set_available(self, count: int) -> None:
        self.count = count


class _AutomaticCheckApp(UpdateToastMixin):
    def __init__(self, *, indicator_count: int = 0) -> None:
        self._automatic_update_check_in_flight = False
        self._automatic_update_check_timer = None
        self._update_toast_shown = False
        self.indicator = _Indicator(indicator_count)
        self.workers: list[tuple[Callable[[], None], dict[str, object]]] = []
        self.intervals: list[tuple[float, Callable[[], None], str]] = []
        self.notifications: list[dict[str, object]] = []

    def set_interval(
        self,
        interval: float,
        callback: Callable[[], None],
        *,
        name: str,
    ) -> object:
        self.intervals.append((interval, callback, name))
        return object()

    def run_worker(self, callback: Callable[[], None], **kwargs: object) -> None:
        self.workers.append((callback, kwargs))

    def query_one(self, *_args: object) -> _Indicator:
        return self.indicator

    def call_from_thread(self, callback: Callable[..., None], *args: object) -> None:
        callback(*args)

    def notify(self, message: str, **kwargs: object) -> None:
        self.notifications.append({"message": message, **kwargs})


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


def test_periodic_tick_skips_positive_indicator_and_in_flight_check() -> None:
    app = _AutomaticCheckApp(indicator_count=2)

    app._on_periodic_update_check()
    assert app.workers == []

    app.indicator.count = 0
    app._automatic_update_check_in_flight = True
    app._on_periodic_update_check()
    assert app.workers == []


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


def test_periodic_update_sets_surfaces_once_then_stops_status_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(),
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

    assert calls == 1
    assert len(app.workers) == 1
    assert app.indicator.count == 2
    assert len(app.notifications) == 1
    assert app._automatic_update_check_in_flight is False


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


def test_update_toast_message_recommends_update_keymap() -> None:
    message = update_toast._format_update_toast_message(_status())

    assert "2 updates" in message
    assert "sase" in message
    assert "1.0.0 → 1.1.0" in message
    assert "],U[/]" in message
    assert "update sase, core & plugins" in message


def test_update_toast_message_lists_all_component_headers() -> None:
    message = update_toast._format_update_toast_message(_status(count=4))

    assert "…and 1 more" not in message
    assert "nvim" in message
    assert "0.3.0 → 0.4.0" in message


def test_build_toast_commit_sections_fetches_git_before_github() -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase",
            ),
            _editable_component("github"),
        ),
    )
    calls: list[str] = []

    def fake_fetch(
        spec: CommitSourceSpec,
        *,
        limit: int,
        offline: bool,
    ) -> IncomingCommits:
        calls.append(f"{spec.source}:{spec.repo_full_name}")
        assert limit == 20
        assert offline is False
        if spec.source == "git":
            return IncomingCommits(
                total=1,
                commits=(CommitSummary("abc1234", "plugin change"),),
                source="git",
            )
        return IncomingCommits(
            total=1,
            commits=(CommitSummary("def5678", "host change"),),
            source="github",
        )

    sections = update_toast._build_toast_commit_sections(
        status.components,
        fetch_fn=fake_fetch,
        max_total=20,
        offline=False,
        deadline=10**12,
    )

    assert calls == ["git:github", "github:sase-org/sase"]
    assert [section.label for section in sections] == ["sase", "github"]
    assert sections[0].commits[0].subject == "host change"
    assert sections[1].commits[0].subject == "plugin change"


def test_update_toast_message_renders_grouped_commits_and_overflow() -> None:
    status = _status(count=1)
    sections = (
        update_toast._ToastRepoSection(
            label="sase",
            installed_version="1.0.0",
            latest_version="1.1.0",
            commits=(
                CommitSummary("abc1234", "fix: escape [toast] markup"),
                CommitSummary("def5678", ""),
            ),
            total=3,
        ),
    )

    message = update_toast._format_update_toast_message(status, sections)

    assert "1 update" in message
    assert "↑ sase" in message
    assert "1.0.0 → 1.1.0" in message
    assert "abc1234" in message
    assert "fix: escape \\[toast] markup" in message
    assert "def5678" in message
    assert "+1 more…" in message
    assert message.endswith("update sase, core & plugins")


def test_build_toast_commit_sections_fairly_truncates_to_global_budget() -> None:
    components = (
        _editable_component("sase", role="host"),
        _editable_component("github"),
    )

    def fake_fetch(
        spec: CommitSourceSpec,
        *,
        limit: int,
        offline: bool,
    ) -> IncomingCommits:
        del limit, offline
        return _incoming(spec.repo_full_name[:1], 20)

    sections = update_toast._build_toast_commit_sections(
        components,
        fetch_fn=fake_fetch,
        max_total=20,
        offline=False,
        deadline=10**12,
    )

    assert [len(section.commits) for section in sections] == [10, 10]
    assert [section.total for section in sections] == [20, 20]
    message = update_toast._format_update_toast_message(
        UpdateStatus(checked_at=100.0, components=components),
        sections,
    )
    assert message.count("+10 more…") == 2


def test_build_toast_commit_sections_degrades_to_header_only() -> None:
    components = (
        _editable_component("github"),
        OutdatedComponent(
            display_name="telegram",
            role="plugin",
            installed_version="0.1.0",
            latest_version="0.2.0",
            distribution_name="sase-telegram",
        ),
    )

    def fake_fetch(
        spec: CommitSourceSpec,
        *,
        limit: int,
        offline: bool,
    ) -> IncomingCommits:
        del spec, limit, offline
        return IncomingCommits(0, (), "unavailable", error="offline")

    sections = update_toast._build_toast_commit_sections(
        components,
        fetch_fn=fake_fetch,
        max_total=20,
        offline=False,
        deadline=10**12,
    )

    assert [section.label for section in sections] == ["github", "telegram"]
    assert [section.total for section in sections] == [0, 0]
    assert all(not section.commits for section in sections)
    message = update_toast._format_update_toast_message(
        UpdateStatus(checked_at=100.0, components=components),
        sections,
    )
    assert "offline" not in message
    assert "github" in message
    assert "telegram" in message


def test_build_toast_commit_sections_skips_fetch_after_deadline() -> None:
    calls = 0

    def fake_fetch(
        spec: CommitSourceSpec,
        *,
        limit: int,
        offline: bool,
    ) -> IncomingCommits:
        nonlocal calls
        del spec, limit, offline
        calls += 1
        return _incoming("x", 1)

    sections = update_toast._build_toast_commit_sections(
        (_editable_component("github"),),
        fetch_fn=fake_fetch,
        max_total=20,
        offline=False,
        deadline=0.0,
    )

    assert calls == 0
    assert sections[0].label == "github"
    assert sections[0].total == 0
    assert sections[0].commits == ()


def test_show_startup_update_toast_is_once_per_session() -> None:
    class _App(UpdateToastMixin):
        def __init__(self) -> None:
            self._update_toast_shown = False
            self.calls: list[dict[str, Any]] = []

        def notify(self, message: str, **kwargs: Any) -> None:
            self.calls.append({"message": message, **kwargs})

    app = _App()

    app._show_startup_update_toast(_status())
    app._show_startup_update_toast(_status())

    assert len(app.calls) == 1
    assert app.calls[0]["severity"] == "information"
    assert app.calls[0]["title"] == "↑ Updates available"


def test_startup_update_check_respects_disabled_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _App(UpdateToastMixin):
        def __init__(self) -> None:
            self.called = False

        def call_from_thread(self, callback: object, *args: object) -> None:
            self.called = True

    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(
            startup_toast=False,
            indicator=False,
        ),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: _status(),
    )
    app = _App()

    app._run_startup_update_toast_check()

    assert app.called is False


def test_startup_update_check_updates_indicator_when_toast_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Indicator:
        def __init__(self) -> None:
            self.count = 0

        def set_available(self, count: int) -> None:
            self.count = count

    class _App(UpdateToastMixin):
        def __init__(self) -> None:
            self.indicator = _Indicator()
            self.toast_calls = 0

        def call_from_thread(self, callback: Any, *args: object) -> None:
            callback(*args)

        def query_one(self, *_args: object) -> _Indicator:
            return self.indicator

        def notify(self, *_args: object, **_kwargs: object) -> None:
            self.toast_calls += 1

    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(
            startup_toast=False,
            indicator=True,
        ),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: _status(count=2),
    )
    app = _App()

    app._run_startup_update_toast_check()

    assert app.indicator.count == 2
    assert app.toast_calls == 0


def test_load_update_toast_config_defaults_to_ten_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(update_toast, "load_merged_config", dict)

    config = update_toast._load_update_toast_config()

    assert config.startup_toast is True
    assert config.indicator is True
    assert config.post_update_toast_diffstat is True
    assert config.check_ttl_seconds == 600.0
    assert config.incoming_commits_enabled is True
    assert config.startup_toast_max_commits == 20


def test_load_update_toast_config_post_update_diffstat_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"post_update_toast_diffstat": False}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.post_update_toast_diffstat is False


def test_load_update_toast_config_indicator_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"indicator": False}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.indicator is False


def test_load_update_toast_config_incoming_commits_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {
            "ace": {
                "updates": {
                    "startup_toast_max_commits": 8,
                    "incoming_commits": {"enabled": False},
                }
            }
        },
    )

    config = update_toast._load_update_toast_config()

    assert config.incoming_commits_enabled is False
    assert config.startup_toast_max_commits == 8


def test_load_update_toast_config_minutes_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"check_ttl_minutes": 5}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.check_ttl_seconds == 300.0


def test_load_update_toast_config_legacy_hours_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"check_ttl_hours": 2}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.check_ttl_seconds == 7200.0


def test_load_update_toast_config_minutes_take_precedence_over_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_toast,
        "load_merged_config",
        lambda: {"ace": {"updates": {"check_ttl_minutes": 10, "check_ttl_hours": 24}}},
    )

    config = update_toast._load_update_toast_config()

    assert config.check_ttl_seconds == 600.0


@pytest.mark.parametrize(
    ("minutes", "expected_seconds"),
    [(30, 1800.0), (0.25, 15.0)],
)
def test_resolve_check_interval_seconds_converts_positive_minutes(
    minutes: object,
    expected_seconds: float,
) -> None:
    assert (
        update_toast.resolve_check_interval_seconds({"check_interval_minutes": minutes})
        == expected_seconds
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "not-a-number",
        "30",
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        0,
        -1,
        10**400,
        [],
        {},
    ],
)
def test_resolve_check_interval_seconds_falls_back_for_invalid_values(
    value: object,
) -> None:
    assert (
        update_toast.resolve_check_interval_seconds({"check_interval_minutes": value})
        == 600.0
    )


def test_resolve_check_interval_seconds_falls_back_when_missing() -> None:
    assert update_toast.resolve_check_interval_seconds({}) == 600.0


def test_startup_update_check_passes_default_ttl_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(),
    )

    def _fake_get(**kwargs: object) -> None:
        captured.update(kwargs)
        return None

    monkeypatch.setattr(update_toast, "get_cached_update_status", _fake_get)

    class _App(UpdateToastMixin):
        def call_from_thread(self, callback: object, *args: object) -> None:
            raise AssertionError("no toast should be shown when status is None")

    _App()._run_startup_update_toast_check()

    assert captured["ttl_seconds"] == 600.0


async def test_startup_update_toast_appears_once_in_tui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    status = _status()
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(startup_toast=True),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: status,
    )

    async with AcePage(query='"toast"') as page:
        await page.wait_for(lambda _s: bool(list(page.app._notifications)))
        notifications = list(page.app._notifications)
        assert len(notifications) == 1
        assert notifications[0].title == "↑ Updates available"
        assert "Press" in notifications[0].message

        page.app._show_startup_update_toast(status)
        await page.pause()
        assert len(list(page.app._notifications)) == 1
