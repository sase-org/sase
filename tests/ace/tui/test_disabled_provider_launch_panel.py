"""ACE disabled-provider launch panel: fast path, keys, and sequential units."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.modals.disabled_provider_launch_modal import (
    DisabledProviderLaunchDecision,
    DisabledProviderLaunchModal,
)
from sase.ace.tui.modals.model_picker_modal import ModelPickerModal
from sase.ace.tui.actions.agent_workflow._types import invalidate_prompt_session
from sase.agent.launch_guard import LaunchUnit, LaunchUnitCandidate
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from tests.ace.tui._agent_launch_helpers import _FakeApp
from tests.agent._launch_guard_helpers import (
    disable,
    install_disables,
    pin_cli_available,
    pin_default_codex,
)


def _bind_disables(
    monkeypatch: pytest.MonkeyPatch,
    disables: dict[str, TemporaryProviderDisable],
) -> dict[str, TemporaryProviderDisable]:
    state = dict(disables)
    install_disables(monkeypatch, state)

    def _refresh() -> None:
        install_disables(monkeypatch, state)

    def enable_provider(provider: str) -> bool:
        state.pop(provider, None)
        _refresh()
        return True

    def disable_provider(
        provider: str,
        duration_seconds: float | None,
        *,
        source: str,
        mode: str,
        now: float | None = None,
    ) -> TemporaryProviderDisable:
        del duration_seconds, now
        record = disable(provider, mode=mode, expires_at=None, source=source)
        state[provider] = record
        _refresh()
        return record

    def disable_provider_until(
        provider: str,
        expires_at: float,
        *,
        source: str,
        mode: str,
        now: float | None = None,
    ) -> TemporaryProviderDisable:
        del now
        record = disable(provider, mode=mode, expires_at=expires_at, source=source)
        state[provider] = record
        _refresh()
        return record

    _guard = "sase.ace.tui.actions.agent_workflow._launch_provider_guard"
    monkeypatch.setattr(f"{_guard}.enable_provider", enable_provider)
    monkeypatch.setattr(f"{_guard}.disable_provider", disable_provider)
    monkeypatch.setattr(f"{_guard}.disable_provider_until", disable_provider_until)
    return state


def _candidate(
    prompt: str,
    *,
    provider: str = "claude",
    model: str = "opus",
    blocked: TemporaryProviderDisable | None = None,
) -> LaunchUnitCandidate:
    return LaunchUnitCandidate(
        slot_index=0,
        prompt=prompt,
        provider=provider,
        model=model,
        blocked_by=blocked,
        unavailable=False,
    )


def _unit(
    prompt: str,
    *,
    index: int = 1,
    total: int = 1,
    candidates: tuple[LaunchUnitCandidate, ...] | None = None,
    blocking: tuple[TemporaryProviderDisable, ...] = (),
) -> LaunchUnit:
    if candidates is None:
        blocked = blocking[0] if blocking else None
        candidates = (_candidate(prompt, blocked=blocked),)
    return LaunchUnit(
        index=index,
        total=total,
        prompt=prompt,
        template_group=None,
        swarm_xprompts=(),
        candidates=candidates,
        _blocking_disables=blocking,
    )


def _panel(app: _FakeApp) -> DisabledProviderLaunchModal:
    assert app.pushed_screens
    screen, _callback = app.pushed_screens[-1]
    assert isinstance(screen, DisabledProviderLaunchModal)
    return screen


def _decide(app: _FakeApp, decision: DisabledProviderLaunchDecision) -> None:
    _screen, callback = app.pushed_screens[-1]
    callback(decision)


def _modal_rows(unit: LaunchUnit) -> list[str]:
    snapshot = {
        record.provider: record
        for record in unit._blocking_disables
        if record is not None
    }
    modal = DisabledProviderLaunchModal(unit, now=100.0, snapshot=snapshot)
    return [row.key for row in modal._rows]


def test_choice_rows_omit_digits_and_abort_all_for_a_single_agent() -> None:
    record = disable("claude")
    unit = _unit(
        "%model:claude/opus Fix the flaky selector",
        blocking=(record,),
    )
    assert _modal_rows(unit) == ["e", "s", "m", "a"]


def test_choice_rows_include_digits_and_abort_all_for_a_swarm_pool() -> None:
    claude = disable("claude")
    codex = disable("codex")
    prompt = "%model:@large do the work"
    unit = _unit(
        prompt,
        index=2,
        total=4,
        candidates=(
            _candidate(prompt, provider="claude", model="opus", blocked=claude),
        ),
        blocking=(claude, codex),
    )
    modal = DisabledProviderLaunchModal(
        unit,
        now=100.0,
        snapshot={"claude": claude, "codex": codex},
    )
    keys = [row.key for row in modal._rows]
    assert keys[:4] == ["e", "s", "1", "2"]
    assert "m" in keys
    assert keys[-2:] == ["a", "A"]
    abort_all = next(row for row in modal._rows if row.key == "A")
    assert abort_all.title == "Abort all 4 agents"


def test_choice_rows_replace_model_pick_when_the_unit_fans_out() -> None:
    claude = disable("claude")
    codex = disable("codex")
    unit = _unit(
        "%{%m:claude/opus | %m:codex/gpt-5.5}\nReview the patch",
        candidates=(
            _candidate(
                "%model:claude/opus\nReview the patch",
                provider="claude",
                model="opus",
                blocked=claude,
            ),
            _candidate(
                "%model:codex/gpt-5.5\nReview the patch",
                provider="codex",
                model="gpt-5.5",
                blocked=codex,
            ),
        ),
        blocking=(claude, codex),
    )
    modal = DisabledProviderLaunchModal(
        unit,
        now=100.0,
        snapshot={"claude": claude, "codex": codex},
    )
    keys = [row.key for row in modal._rows]
    assert "m" not in keys
    dim = next(row for row in modal._rows if row.result is None)
    assert "fans out models" in dim.title


def test_no_hard_disable_skips_panel_and_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_disables(monkeypatch, {})

    def _boom(*_args: Any, **_kwargs: Any) -> object:
        raise AssertionError("planning must not run on the empty hard-disable path")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._launch_provider_guard.plan_launch_units",
        _boom,
    )
    app = _FakeApp()
    app._finish_agent_launch("the prompt")

    assert app.workers == []
    assert app.pushed_screens == []
    assert len(app.launch_tasks) == 1
    task = app.launch_tasks[0]
    assert task["prompt"] == "the prompt"
    assert task["submitted_prompt"] == "the prompt"
    extra = task["extra_payload"]
    assert extra["display_name"] == "test"
    assert extra["project_name"] == "test"
    assert "launch_units" not in extra
    assert app.unmount_calls == ["submit"]


def test_explicit_model_enable_submits_the_original_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    _bind_disables(monkeypatch, {"claude": disable("claude")})
    prompt = "%model:claude/opus Fix the flaky selector"
    app = _FakeApp()
    app._finish_agent_launch(prompt)

    panel = _panel(app)
    assert panel._unit.blocking_providers == ("claude",)
    keys = [row.key for row in panel._rows]
    assert "1" not in keys
    assert "A" not in keys
    assert app.unmount_calls == []
    _decide(app, DisabledProviderLaunchDecision(action="enable"))

    assert len(app.launch_tasks) == 1
    assert app.launch_tasks[0]["prompt"] == prompt
    assert "launch_units" not in app.launch_tasks[0]["extra_payload"]
    assert app.unmount_calls == ["submit"]


def test_stale_provider_guard_decision_does_not_launch_later_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    _bind_disables(monkeypatch, {"claude": disable("claude")})
    app = _FakeApp()
    app._finish_agent_launch("%model:claude/opus Fix the flaky selector")
    assert isinstance(_panel(app), DisabledProviderLaunchModal)

    invalidate_prompt_session(app)
    _decide(app, DisabledProviderLaunchDecision(action="enable"))

    assert app.launch_tasks == []
    assert app._provider_guard_session is None
    assert any("prompt bar was closed" in message for message, _ in app.notifications)


def test_soft_enable_preserves_expires_at_and_submits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    record = disable("claude", expires_at=12_345.0)
    state = _bind_disables(monkeypatch, {"claude": record})
    writes: list[tuple[str, float, str]] = []

    def disable_provider_until(
        provider: str,
        expires_at: float,
        *,
        source: str,
        mode: str,
        now: float | None = None,
    ) -> TemporaryProviderDisable:
        del now
        writes.append((provider, expires_at, mode))
        updated = disable(provider, mode=mode, expires_at=expires_at, source=source)
        state[provider] = updated
        install_disables(monkeypatch, state)
        return updated

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._launch_provider_guard.disable_provider_until",
        disable_provider_until,
    )
    prompt = "%model:claude/opus Fix the flaky selector"
    app = _FakeApp()
    app._finish_agent_launch(prompt)
    _decide(app, DisabledProviderLaunchDecision(action="soft_enable"))

    assert writes == [("claude", 12_345.0, "soft")]
    assert len(app.launch_tasks) == 1
    assert app.launch_tasks[0]["prompt"] == prompt


def test_pick_model_replaces_existing_model_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    pin_default_codex(monkeypatch)
    _bind_disables(monkeypatch, {"claude": disable("claude")})
    prompt = "%model:claude/opus Fix the flaky selector"
    app = _FakeApp()
    app._finish_agent_launch(prompt)
    _decide(app, DisabledProviderLaunchDecision(action="pick_model"))

    picker, on_picked = app.pushed_screens[-1]
    assert isinstance(picker, ModelPickerModal)
    assert picker._title == "Model for this agent"
    on_picked("codex/gpt-5.5")

    assert len(app.launch_tasks) == 1
    submitted = app.launch_tasks[0]["prompt"]
    assert "%model:codex/gpt-5.5" in submitted
    assert submitted.count("%model:") == 1
    assert "launch_units" not in app.launch_tasks[0]["extra_payload"]


def test_four_unit_swarm_abort_then_abort_submits_remaining_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    pin_default_codex(monkeypatch)
    _bind_disables(monkeypatch, {"claude": disable("claude")})
    prompt = (
        "first agent\n---\n"
        "%model:claude/opus second agent\n---\n"
        "third agent\n---\n"
        "%model:claude/opus fourth agent"
    )
    app = _FakeApp()
    app._finish_agent_launch(prompt)

    first = _panel(app)
    assert first._unit.index == 2
    assert first._original_total == 4
    assert any(row.key == "A" for row in first._rows)
    _decide(app, DisabledProviderLaunchDecision(action="abort_unit"))

    second = _panel(app)
    assert second._unit.index == 4
    _decide(app, DisabledProviderLaunchDecision(action="abort_unit"))

    assert len(app.launch_tasks) == 1
    task = app.launch_tasks[0]
    extra = task["extra_payload"]
    units = extra["launch_units"]
    assert len(units) == 2
    assert (
        units[0]["prompt"].endswith("first agent")
        or "first agent" in units[0]["prompt"]
    )
    assert "third agent" in units[1]["prompt"]
    assert "---" in task["prompt"]


def test_abort_all_on_first_panel_submits_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    pin_default_codex(monkeypatch)
    _bind_disables(monkeypatch, {"claude": disable("claude")})
    prompt = (
        "first agent\n---\n"
        "%model:claude/opus second agent\n---\n"
        "third agent\n---\n"
        "%model:claude/opus fourth agent"
    )
    app = _FakeApp()
    app._finish_agent_launch(prompt)
    _decide(app, DisabledProviderLaunchDecision(action="abort_all"))

    assert app.launch_tasks == []
    assert app.unmount_calls == []
    assert app._prompt_context is not None
    assert any("still here" in message for message, _severity in app.notifications)


def test_enabling_one_of_two_providers_rechecks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    _bind_disables(
        monkeypatch,
        {"claude": disable("claude"), "codex": disable("codex")},
    )
    app = _FakeApp()
    app._finish_agent_launch("%model:@large do the work")
    panel = _panel(app)
    digit_keys = [row.key for row in panel._rows if row.key in {"1", "2"}]
    assert digit_keys == ["1", "2"]
    first_provider = panel._unit.blocking_providers[0]
    screens_before = len(app.pushed_screens)
    _decide(
        app,
        DisabledProviderLaunchDecision(
            action="enable_provider",
            provider=first_provider,
        ),
    )

    assert len(app.launch_tasks) == 1
    assert app.launch_tasks[0]["prompt"] == "%model:@large do the work"
    assert "launch_units" not in app.launch_tasks[0]["extra_payload"]
    assert len(app.pushed_screens) == screens_before


def test_model_fanout_unit_has_no_model_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    _bind_disables(
        monkeypatch,
        {"claude": disable("claude"), "codex": disable("codex")},
    )
    app = _FakeApp()
    app._finish_agent_launch("%{%m:claude/opus | %m:codex/gpt-5.5}\nReview the patch")
    panel = _panel(app)
    keys = [row.key for row in panel._rows]
    assert "m" not in keys
    assert any("fans out models" in row.title for row in panel._rows)


def test_aborting_every_unit_leaves_the_prompt_bar_mounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    _bind_disables(monkeypatch, {"claude": disable("claude")})
    app = _FakeApp()
    app._finish_agent_launch("%model:claude/opus Fix the flaky selector")
    _decide(app, DisabledProviderLaunchDecision(action="abort_unit"))

    assert app.launch_tasks == []
    assert app.unmount_calls == []
    assert app._prompt_context is not None
    assert any("still here" in message for message, _severity in app.notifications)


def test_relaunch_entry_hits_the_same_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.agent_workflow import AgentWorkflowMixin
    from sase.ace.tui.actions.agent_workflow._entry_relaunch import EntryRelaunchMixin
    from sase.ace.tui.actions.agent_workflow._launch_start import AgentLaunchStartMixin

    assert issubclass(AgentWorkflowMixin, EntryRelaunchMixin)
    assert issubclass(AgentWorkflowMixin, AgentLaunchStartMixin)

    pin_cli_available(monkeypatch)
    _bind_disables(monkeypatch, {"claude": disable("claude")})
    app = _FakeApp()
    app._finish_agent_launch("%id:!retry\n%model:claude/opus Fix the flaky selector")
    panel = _panel(app)
    assert isinstance(panel, DisabledProviderLaunchModal)
    assert app.unmount_calls == []
