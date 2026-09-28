"""Quit-time prompt-draft stash coverage (phase quit-preserves-draft)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow._prompt_bar_stash import PromptBarStashMixin
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.actions.axe import AxeMixin
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.quit_impact import collect_tui_exit_impact
from sase.ace.tui.widgets.prompt_input_bar import StashedPromptPane
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


def _skip_without_prompt_stash_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "append_prompt_stash"):
        pytest.skip("sase_core_rs is too old (no append_prompt_stash binding).")


def _point_store_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("sase.core.paths.prompt_stash_path", lambda: path, raising=True)


def _entries(path: Path) -> list[Any]:
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    return list(read_prompt_stash_snapshot(path).entries)


def _prompt_context() -> PromptContext:
    return PromptContext(
        project_name="sase",
        cl_name=None,
        project_file="/tmp/sase.gp",
        workspace_dir="/tmp",
        workspace_num=11,
        workflow_name="default",
        timestamp="260629-000000",
        history_sort_key="260629-000000",
        display_name="sase",
        update_target="",
    )


class _FakeBar:
    def __init__(
        self,
        panes: list[StashedPromptPane],
        *,
        mode: str = "prompt",
    ) -> None:
        self._mode = mode
        self._panes = panes

    def capture_stashable_panes(self) -> list[StashedPromptPane]:
        return list(self._panes)


class _QuitStashApp(LifecycleMixin, PromptBarStashMixin):
    def __init__(self, bar: _FakeBar | None) -> None:
        self._bar = bar
        self._prompt_context = _prompt_context()
        self.notices: list[tuple[str, str]] = []
        self.did_quit = False

    def _mounted_prompt_bar(self) -> Any:
        return self._bar

    def notify(self, message: object, *, severity: str = "information") -> None:
        self.notices.append((str(message), severity))

    def _do_quit(self) -> None:
        self.did_quit = True


@pytest.mark.asyncio
async def test_quit_with_prompt_draft_stashes_with_quit_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)
    frontmatter = "---\ndescription: draft\n---"
    bar = _FakeBar(
        [
            StashedPromptPane("alpha", frontmatter=frontmatter, pane_index=0),
            StashedPromptPane("beta", frontmatter=frontmatter, pane_index=1),
        ]
    )
    app = _QuitStashApp(bar)

    await app._begin_controlled_exit()

    assert app.did_quit is True
    entries = _entries(stash_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.text == "alpha\n---\nbeta"
    assert entry.frontmatter == frontmatter
    assert entry.project == "sase"
    assert entry.source == "quit"
    assert entry.pane_index == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("bar", [None, _FakeBar([])])
async def test_quit_without_draft_appends_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bar: _FakeBar | None
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)
    app = _QuitStashApp(bar)

    await app._begin_controlled_exit()

    assert app.did_quit is True
    assert not stash_path.exists()


@pytest.mark.asyncio
async def test_quit_stash_failure_cancels_exit_and_toasts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)
    app = _QuitStashApp(_FakeBar([StashedPromptPane("alpha")]))

    def _boom(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("write failed")

    monkeypatch.setattr("sase.core.prompt_stash_facade.append_prompt_stash", _boom)

    await app._begin_controlled_exit()

    assert app.did_quit is False
    assert getattr(app, "_controlled_exit_started", False) is False
    # The flag stays clear so the next quit retries the write.
    assert app._quit_draft_stash_attempted is False
    assert any(
        severity == "error" and "Failed to stash prompt draft" in message
        for message, severity in app.notices
    )
    assert not stash_path.exists()


def test_quit_confirm_path_stashes_before_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)
    app = _QuitStashApp(_FakeBar([StashedPromptPane("alpha")]))

    # The confirm-then-exit path goes through the sync _request_controlled_exit.
    app._request_controlled_exit()

    assert app.did_quit is True
    entries = _entries(stash_path)
    assert len(entries) == 1
    assert entries[0].source == "quit"


def test_quit_after_restart_stash_does_not_stash_twice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)
    app = _QuitStashApp(_FakeBar([StashedPromptPane("alpha")]))

    assert app._stash_prompt_bar_before_restart() is True
    # _restart_tui marks the attempt done before the controlled exit, so the
    # quit-source stash below must skip the already-stashed draft.
    app._quit_draft_stash_attempted = True
    app._request_controlled_exit()

    assert app.did_quit is True
    entries = _entries(stash_path)
    assert len(entries) == 1
    assert entries[0].source == "restart"


def test_quit_impact_mentions_open_draft_without_forcing_confirm() -> None:
    app = _QuitStashApp(_FakeBar([StashedPromptPane("alpha")]))

    impact = collect_tui_exit_impact(app)

    assert impact.has_prompt_draft is True
    assert impact.is_empty is True
    assert "Your unsent prompt draft will be stashed" in impact.summary_lines()


def test_quit_impact_without_draft_reports_no_draft() -> None:
    app = _QuitStashApp(None)

    impact = collect_tui_exit_impact(app)

    assert impact.has_prompt_draft is False
    assert "Your unsent prompt draft will be stashed" not in impact.summary_lines()


class _StopAxeQuitStashApp(AxeMixin, LifecycleMixin, PromptBarStashMixin):
    """Drive `_stop_axe_and_quit` with quit-draft stash tracking."""

    def __init__(self, bar: _FakeBar | None) -> None:
        self._bar = bar
        self._prompt_context = _prompt_context()
        self.notices: list[tuple[str, str]] = []
        self.did_quit = False
        self.watchdog_stops = 0
        self.controlled_exit_calls = 0

    def _mounted_prompt_bar(self) -> Any:
        return self._bar

    def notify(self, message: object, *, severity: str = "information") -> None:
        self.notices.append((str(message), severity))

    def _do_quit(self) -> None:
        self.did_quit = True

    def _stop_tui_stall_watchdog(self) -> None:
        self.watchdog_stops += 1

    async def _begin_controlled_exit(self) -> None:
        self.controlled_exit_calls += 1


@pytest.mark.asyncio
async def test_stop_axe_and_quit_stash_failure_keeps_scheduler_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failing quit-draft stash cancels `_stop_axe_and_quit` before teardown."""
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)
    app = _StopAxeQuitStashApp(_FakeBar([StashedPromptPane("alpha")]))

    def _boom(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("write failed")

    monkeypatch.setattr("sase.core.prompt_stash_facade.append_prompt_stash", _boom)

    import sase.service.actions as service_actions

    stop_calls: list[tuple[str, dict[str, Any]]] = []

    def fake_stop(name: str, **kwargs: Any) -> None:
        stop_calls.append((name, kwargs))

    monkeypatch.setattr(service_actions, "stop_service_proc", fake_stop)

    await app._stop_axe_and_quit()

    assert stop_calls == []
    assert app.watchdog_stops == 0
    assert app.controlled_exit_calls == 0
    assert app.did_quit is False
    assert any(
        severity == "error" and "Failed to stash prompt draft" in message
        for message, severity in app.notices
    )
