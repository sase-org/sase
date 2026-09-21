"""Tests for the app-scoped LaunchContextSource and its render-only views.

Polling and resolution used to live inside :class:`LLMOverrideIndicator` and
:class:`CurrentProjectIndicator`; it now lives here. Polling assertions target
the source below, while rendering assertions stay on the view test modules.
"""

from __future__ import annotations

from typing import Literal

import pytest
from textual.worker import WorkerState

from sase.ace.testing import AcePage
from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.ace.tui.project_styles import project_accent
from sase.ace.tui.widgets import launch_context_source as source_module
from sase.ace.tui.widgets.current_project_indicator import CurrentProjectIndicator
from sase.ace.tui.widgets.launch_context_source import (
    LaunchContextSource,
    LaunchContextState,
)
from sase.ace.tui.widgets.llm_override_indicator import LLMOverrideIndicator
from sase.current_project import CurrentProject
from sase.llm_provider.model_launch_settings import (
    DEFAULT_MODEL_FIELD,
    LaunchModelSettingSnapshot,
    launch_model_setting_override_key,
)
from sase.llm_provider.temporary_override import TemporaryLLMOverride


def _snapshot(
    *,
    provider: str = "claude",
    model: str = "opus",
    effort: str | None = None,
    referenced_alias: str | None = None,
    selector_mode: str | None = None,
    selector_members: tuple = (),
) -> LaunchModelSettingSnapshot:
    """Build a minimal launch-model setting snapshot for resolver stubs."""
    return LaunchModelSettingSnapshot(
        field=DEFAULT_MODEL_FIELD,
        config_path="llm_provider.default_model",
        raw_value=f"{provider}/{model}",
        provider=provider,
        model=model,
        effort=effort,
        provenance="configured",
        referenced_alias=referenced_alias,
        override_key=launch_model_setting_override_key(DEFAULT_MODEL_FIELD),
        selector_mode=selector_mode,
        selector_members=selector_members,
    )


def _project(
    *,
    origin: Literal["project", "patch"] = "project",
    origin_ref: str = "sase",
    display_name: str = "sase",
) -> CurrentProject:
    return CurrentProject(
        project_key="gh_sase-org__sase",
        display_name=display_name,
        origin=origin,
        origin_ref=origin_ref,
        workflow_type="gh",
    )


def _override(
    *,
    provider: str = "codex",
    model: str = "o3",
    expires_at: float | None = 1_000.0,
    effort: str | None = None,
) -> TemporaryLLMOverride:
    """Build a test override."""
    return TemporaryLLMOverride(
        provider=provider,
        model=model,
        raw_model=f"{provider}/{model}",
        created_at=100.0,
        expires_at=expires_at,
        source="test",
        effort=effort,
    )


@pytest.fixture(autouse=True)
def _bare_directive_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the pill subject to the bare model name, independent of plugins.

    The real formatter consults installed provider plugins' model metadata;
    tests that care about a specific spelling re-patch it themselves.
    """
    monkeypatch.setattr(
        source_module,
        "format_model_directive_label",
        lambda provider=None, model=None: model or "",
    )


class _FakeWorker:
    """Duck-typed stand-in for ``textual.worker.Worker`` in unit tests."""

    def __init__(self, group: str, result: object) -> None:
        self.group = group
        self.result = result


class _FakeStateChanged:
    """Duck-typed stand-in for ``Worker.StateChanged`` in unit tests."""

    def __init__(self, worker: _FakeWorker, state: WorkerState) -> None:
        self.worker = worker
        self.state = state


def _prepare_source(
    monkeypatch: pytest.MonkeyPatch,
    *,
    override: TemporaryLLMOverride | None = None,
    default_token: tuple[object, ...] = ("token-0",),
    project_token: tuple[object, ...] = ("project-token-0",),
) -> tuple[LaunchContextSource, list[tuple[object, dict]]]:
    """Build an unmounted source with worker spawning stubbed out.

    ``run_worker`` requires an active Textual app, which these synchronous
    unit tests do not mount. Stubbing it lets tests assert *whether* a
    re-resolve was scheduled without needing a live worker thread.
    """
    monkeypatch.setattr(
        source_module, "peek_active_temporary_override", lambda *a, **k: override
    )
    monkeypatch.setattr(
        source_module, "peek_launch_default_change_token", lambda: default_token
    )
    monkeypatch.setattr(
        source_module, "peek_current_project_change_token", lambda: project_token
    )
    source = LaunchContextSource()
    scheduled: list[tuple[object, dict]] = []
    monkeypatch.setattr(
        source, "run_worker", lambda task, **kwargs: scheduled.append((task, kwargs))
    )
    return source, scheduled


def _scheduled_groups(scheduled: list[tuple[object, dict]]) -> list[str]:
    return [kwargs["group"] for _task, kwargs in scheduled]


def _resolved_state(
    *,
    default_token: tuple[object, ...] = ("token-a",),
    project_token: tuple[object, ...] = ("project-token-a",),
) -> LaunchContextState:
    """Build a fully resolved source state for broadcast tests."""
    return LaunchContextState(
        default_snapshot=source_module.LaunchDefaultSnapshot(
            provider="claude",
            model="opus",
            referenced_alias=None,
            selector_mode=None,
            member_count=0,
            effort="high",
            directive_label="opus",
        ),
        default_failed=False,
        default_token=default_token,
        project_snapshot=source_module.CurrentProjectSnapshot(
            project=_project(), accent="#fff"
        ),
        project_failed=False,
        project_token=project_token,
        override=None,
    )


def test_cold_start_schedules_both_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    source, scheduled = _prepare_source(monkeypatch)

    source.refresh()

    assert _scheduled_groups(scheduled) == [
        source_module._DEFAULT_WORKER_GROUP,
        source_module._PROJECT_WORKER_GROUP,
    ]


def test_unchanged_tokens_schedule_no_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, scheduled = _prepare_source(
        monkeypatch,
        default_token=("token-a",),
        project_token=("project-token-a",),
    )
    source._state = _resolved_state()
    source._override_active_last_tick = False

    source.refresh()

    assert scheduled == []


def test_default_token_change_schedules_only_default_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, scheduled = _prepare_source(
        monkeypatch,
        default_token=("token-b",),
        project_token=("project-token-a",),
    )
    source._state = _resolved_state()

    source.refresh()

    assert _scheduled_groups(scheduled) == [source_module._DEFAULT_WORKER_GROUP]


def test_project_token_change_schedules_only_project_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, scheduled = _prepare_source(
        monkeypatch,
        default_token=("token-a",),
        project_token=("project-token-b",),
    )
    source._state = _resolved_state()

    source.refresh()

    assert _scheduled_groups(scheduled) == [source_module._PROJECT_WORKER_GROUP]


def test_second_tick_while_project_in_flight_schedules_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, scheduled = _prepare_source(
        monkeypatch, default_token=("token-a",), project_token=("project-token-b",)
    )
    source._state = _resolved_state()

    source.refresh()
    source.refresh()

    assert _scheduled_groups(scheduled) == [source_module._PROJECT_WORKER_GROUP]


def test_failed_flags_retry_on_next_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    source, scheduled = _prepare_source(
        monkeypatch,
        default_token=("token-a",),
        project_token=("project-token-a",),
    )
    source._state = _resolved_state()
    source._state = LaunchContextState(
        default_snapshot=source._state.default_snapshot,
        default_failed=True,
        default_token=source._state.default_token,
        project_snapshot=source._state.project_snapshot,
        project_failed=True,
        project_token=source._state.project_token,
        override=None,
    )

    source.refresh()

    assert _scheduled_groups(scheduled) == [
        source_module._DEFAULT_WORKER_GROUP,
        source_module._PROJECT_WORKER_GROUP,
    ]


def test_active_override_skips_default_resolve_but_records_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override = _override()
    source, scheduled = _prepare_source(monkeypatch, override=override)
    source._state = _resolved_state()

    source.refresh()

    assert _scheduled_groups(scheduled) == [source_module._PROJECT_WORKER_GROUP]
    assert source.state.override is override


def test_override_lapse_rearms_default_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, scheduled = _prepare_source(
        monkeypatch, override=None, default_token=("token-a",)
    )
    source._state = _resolved_state()
    source._override_active_last_tick = True

    source.refresh()

    assert source_module._DEFAULT_WORKER_GROUP in _scheduled_groups(scheduled)
    assert source.state.override is None


def test_disabled_project_indicator_schedules_no_project_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    peek_calls: list[None] = []

    def peek() -> tuple[object, ...]:
        peek_calls.append(None)
        return ("project-token-b",)

    monkeypatch.setattr(source_module, "peek_current_project_change_token", peek)
    source, scheduled = _prepare_source(monkeypatch, default_token=("token-a",))
    source._state = _resolved_state()
    monkeypatch.setattr(
        source, "_project_settings", lambda: CurrentProjectSettings(indicator=False)
    )

    source.refresh()

    assert [kwargs["group"] for _task, kwargs in scheduled] == []
    assert peek_calls == []


def test_refresh_never_calls_resolvers_synchronously(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both resolvers must only ever run inside off-thread worker tasks."""

    def fail_default(*args: object, **kwargs: object) -> LaunchModelSettingSnapshot:
        raise AssertionError("default resolver must not run on the UI thread")

    def fail_project(**kwargs: object) -> CurrentProject | None:
        raise AssertionError("project resolver must not run on the UI thread")

    monkeypatch.setattr(
        source_module, "build_launch_model_setting_snapshot", fail_default
    )
    monkeypatch.setattr(source_module, "resolve_current_project", fail_project)
    source, scheduled = _prepare_source(
        monkeypatch, default_token=("token-b",), project_token=("project-token-b",)
    )
    source._state = _resolved_state()

    source.refresh()

    assert len(scheduled) == 2


def test_default_worker_success_commits_pending_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _scheduled = _prepare_source(monkeypatch)
    source._pending_default_token = ("pending-token",)
    source._default_in_flight = True
    snapshot = source_module.LaunchDefaultSnapshot(
        provider="claude",
        model="opus",
        referenced_alias=None,
        selector_mode=None,
        member_count=0,
        effort="high",
    )

    source.on_worker_state_changed(
        _FakeStateChanged(
            _FakeWorker(source_module._DEFAULT_WORKER_GROUP, snapshot),
            WorkerState.SUCCESS,
        )
    )

    assert source.state.default_snapshot is snapshot
    assert source.state.default_token == ("pending-token",)
    assert source._default_in_flight is False
    assert source.state.default_failed is False


def test_default_worker_error_marks_failed_without_committing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _scheduled = _prepare_source(monkeypatch)
    source._pending_default_token = ("pending-token",)
    source._default_in_flight = True

    source.on_worker_state_changed(
        _FakeStateChanged(
            _FakeWorker(source_module._DEFAULT_WORKER_GROUP, None),
            WorkerState.ERROR,
        )
    )

    assert source.state.default_token is None
    assert source.state.default_failed is True
    assert source._default_in_flight is False


def test_project_worker_success_commits_pending_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _scheduled = _prepare_source(monkeypatch)
    source._pending_project_token = ("pending-token",)
    source._project_in_flight = True
    snapshot = source_module.CurrentProjectSnapshot(project=_project(), accent="#abc")

    source.on_worker_state_changed(
        _FakeStateChanged(
            _FakeWorker(source_module._PROJECT_WORKER_GROUP, snapshot),
            WorkerState.SUCCESS,
        )
    )

    assert source.state.project_snapshot is snapshot
    assert source.state.project_token == ("pending-token",)
    assert source._project_in_flight is False
    assert source.state.project_failed is False


def test_worker_cancelled_clears_in_flight_without_changing_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _scheduled = _prepare_source(monkeypatch)
    before = _resolved_state()
    source._state = before
    source._default_in_flight = True
    source._project_in_flight = True

    source.on_worker_state_changed(
        _FakeStateChanged(
            _FakeWorker(source_module._DEFAULT_WORKER_GROUP, None),
            WorkerState.CANCELLED,
        )
    )
    source.on_worker_state_changed(
        _FakeStateChanged(
            _FakeWorker(source_module._PROJECT_WORKER_GROUP, None),
            WorkerState.CANCELLED,
        )
    )

    assert source.state is before
    assert source._default_in_flight is False
    assert source._project_in_flight is False


def test_refresh_keeps_stale_default_while_rearming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token-triggered re-arm must not flash the state back to resolving."""
    source, scheduled = _prepare_source(monkeypatch, default_token=("token-b",))
    snapshot = source_module.LaunchDefaultSnapshot(
        provider="claude",
        model="opus",
        referenced_alias=None,
        selector_mode=None,
        member_count=0,
        directive_label="opus",
    )
    source._state = LaunchContextState(
        default_snapshot=snapshot,
        default_failed=False,
        default_token=("token-a",),
    )

    source.refresh()

    assert scheduled
    assert source.state.default_snapshot is snapshot


def test_invalidate_launch_default_clears_default_but_keeps_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, scheduled = _prepare_source(
        monkeypatch,
        default_token=("token-a",),
        project_token=("project-token-a",),
    )
    source._state = _resolved_state()

    source.invalidate_launch_default()

    assert source.state.default_snapshot is None
    assert source.state.default_failed is False
    assert source.state.default_token is None
    assert source.state.project_snapshot is not None
    assert source.state.project_token == ("project-token-a",)
    assert _scheduled_groups(scheduled) == [source_module._DEFAULT_WORKER_GROUP]


def test_invalidate_current_project_forces_resolve_when_refresh_would_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, scheduled = _prepare_source(
        monkeypatch,
        default_token=("token-a",),
        project_token=("project-token-a",),
    )
    source._state = _resolved_state()

    source.refresh()
    assert scheduled == []

    source.invalidate_current_project()

    assert _scheduled_groups(scheduled) == [source_module._PROJECT_WORKER_GROUP]
    assert source.state.project_token is None
    assert source._project_in_flight is True

    source.refresh()
    assert len(scheduled) == 1


def test_invalidate_current_project_is_noop_while_resolve_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, scheduled = _prepare_source(monkeypatch, project_token=("project-token-b",))
    source._state = _resolved_state()
    source._project_in_flight = True

    source.invalidate_current_project()

    assert scheduled == []
    assert source.state.project_token == ("project-token-a",)
    assert source._project_in_flight is True


def test_default_worker_task_computes_directive_label_off_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, object]] = []

    def fake_label(provider: str | None = None, model: str | None = None) -> str:
        calls.append((provider, model))
        return f"{provider}/{model}"

    monkeypatch.setattr(
        source_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="codex", model="o3"),
    )
    monkeypatch.setattr(source_module, "format_model_directive_label", fake_label)
    source, scheduled = _prepare_source(
        monkeypatch, default_token=("token-b",), project_token=("project-token-a",)
    )
    source._state = _resolved_state(
        default_token=("token-a",), project_token=("project-token-a",)
    )

    source.refresh()
    assert calls == []
    (task, _kwargs), *_rest = scheduled
    assert task is source_module._resolve_default_snapshot
    snapshot = task()

    assert isinstance(snapshot, source_module.LaunchDefaultSnapshot)
    assert snapshot.directive_label == "codex/o3"
    assert calls == [("codex", "o3")]


async def test_source_resolution_broadcasts_to_mounted_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The async resolver path paints the mounted view once it lands."""
    monkeypatch.setattr(
        source_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="claude", model="sonnet"),
    )

    async with AcePage() as page:
        source = page.query_one_widget("#launch-context-source", LaunchContextSource)
        indicator = page.app.query(LLMOverrideIndicator).first()
        await page.wait_for(lambda _state: source.state.default_snapshot is not None)

    assert indicator._cached_default == ("claude", "sonnet")
    assert indicator._build_cached_default_content().plain == "sonnet"


async def test_one_resolve_per_token_change_with_two_views_mounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One token change resolves once no matter how many views are mounted."""
    resolve_calls: list[None] = []

    def counting_snapshot(
        *args: object, **kwargs: object
    ) -> LaunchModelSettingSnapshot:
        resolve_calls.append(None)
        return _snapshot(provider="claude", model="sonnet")

    monkeypatch.setattr(
        source_module, "build_launch_model_setting_snapshot", counting_snapshot
    )
    project_calls: list[None] = []

    def counting_project(**kwargs: object) -> CurrentProject | None:
        project_calls.append(None)
        return _project()

    monkeypatch.setattr(source_module, "resolve_current_project", counting_project)
    monkeypatch.setattr(source_module, "_enabled_project_keys", lambda: ("k1",))

    async with AcePage() as page:
        source = page.query_one_widget("#launch-context-source", LaunchContextSource)
        first = page.app.query(LLMOverrideIndicator).first()
        second = LLMOverrideIndicator(id="llm-override-indicator-second")
        await page.app.mount(second)
        await page.wait_for(lambda _state: source.state.default_snapshot is not None)
        await page.wait_for(lambda _state: source.state.project_snapshot is not None)

        assert first._build_cached_default_content().plain == (
            second._build_cached_default_content().plain
        )
        assert len(resolve_calls) == 1
        assert len(project_calls) == 1


async def test_late_mounted_view_paints_resolved_content_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A view mounted after resolution never flashes a placeholder."""
    monkeypatch.setattr(
        source_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="claude", model="sonnet"),
    )
    monkeypatch.setattr(
        source_module, "resolve_current_project", lambda **_k: _project()
    )
    monkeypatch.setattr(source_module, "_enabled_project_keys", lambda: ("k1",))

    async with AcePage() as page:
        source = page.query_one_widget("#launch-context-source", LaunchContextSource)
        await page.wait_for(lambda _state: source.state.default_snapshot is not None)
        await page.wait_for(lambda _state: source.state.project_snapshot is not None)

        late_model = LLMOverrideIndicator()
        await page.app.mount(late_model)
        late_project = CurrentProjectIndicator()
        await page.app.mount(late_project)

        assert late_model._cached_default == ("claude", "sonnet")
        assert late_model._build_cached_default_content().plain == "sonnet"
        assert late_project.render().plain == "+sase"


async def test_every_tick_rebroadcasts_to_mounted_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ticks rebroadcast even with no state change (override countdowns)."""
    async with AcePage() as page:
        source = page.query_one_widget("#launch-context-source", LaunchContextSource)
        indicator = page.app.query(LLMOverrideIndicator).first()
        calls: list[LaunchContextState] = []
        monkeypatch.setattr(
            indicator,
            "apply_launch_context",
            lambda state: (calls.append(state), indicator._apply_content()),
        )

        source.refresh()
        await page.pause()

    assert calls and all(state is source.state for state in calls)
