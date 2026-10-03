"""Tests for `<space>` and MRU-head entry points from the snapshot.

Epic sase-1ex, phase space-prefill: the `<space>` prefill, the `,.`
history entry, and the editor entry resolve from the app-owned
launchable-MRU snapshot without I/O. A cold or launch-pending snapshot
opens a blank bar at once and applies a late prefill only to an
untouched session.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow._entry_custom import (
    resolve_vcs_xprompt_mru_head,
)
from sase.ace.tui.actions.agent_workflow._entry_points import EntryPointsMixin
from sase.ace.tui.actions.agent_workflow._space_prefill import (
    peek_ready_mru_pairs,
    peek_space_prefill_pairs,
    record_pending_space_prefill,
    try_apply_pending_space_prefill,
)
from sase.ace.tui.actions.agent_workflow._types import (
    PromptContext,
    begin_prompt_session,
    current_prompt_session,
)
from sase.ace.tui.launchable_mru import LaunchableMruSnapshot

from ._entry_points_vcs_prefix_helpers import _patch_tag_peek, _tag_catalog


def _ready(pairs: list[tuple[str, str]], **kwargs: Any) -> LaunchableMruSnapshot:
    return LaunchableMruSnapshot(state="ready", pairs=tuple(pairs), **kwargs)


class _SpaceApp(EntryPointsMixin):
    """Stub host serving a canned snapshot like ``AceApp`` does."""

    def __init__(self, snapshot: LaunchableMruSnapshot | None) -> None:
        self._snapshot = snapshot
        self.notifications: list[tuple[str, str | None]] = []
        self.prompt_launches: list[dict[str, Any]] = []
        self.editor_launches: list[dict[str, Any]] = []
        self.editor_prompts: list[str] = []
        self.finished_prompts: list[str] = []
        self.refresh_requests: list[str] = []
        self._prompt_context: PromptContext | None = None
        self._prompt_session: Any = None
        self._pending_space_prefill: Any = None
        self._bar: Any = None

    def peek_launchable_mru_snapshot(self) -> LaunchableMruSnapshot | None:
        return self._snapshot

    def request_launchable_mru_refresh(
        self, *, reason: str, force: bool = False
    ) -> bool:
        self.refresh_requests.append(reason)
        return True

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _mounted_prompt_bar(self) -> Any:
        return self._bar

    def _show_prompt_input_bar_for_home(self, **kwargs: Any) -> None:
        self.prompt_launches.append(kwargs)
        from sase.ace.patch.project_spec_path import preferred_project_spec_path
        from sase.core.paths import sase_projects_dir
        from sase.core.time import generate_timestamp

        timestamp = generate_timestamp()
        begin_prompt_session(
            self,
            PromptContext(
                project_name="home",
                cl_name=None,
                project_file=preferred_project_spec_path(
                    str(sase_projects_dir() / "home"), "home"
                ),
                workspace_dir="",
                workspace_num=0,
                workflow_name=f"ace(run)-{timestamp}",
                timestamp=timestamp,
                history_sort_key=kwargs.get("history_sort_key", "home"),
                display_name=kwargs.get("display_name", "~"),
                update_target="",
                is_home_mode=True,
            ),
        )

    def _select_and_open_editor_for_home(self, **kwargs: Any) -> None:
        self.editor_launches.append(kwargs)
        from sase.ace.patch.project_spec_path import preferred_project_spec_path
        from sase.core.paths import sase_projects_dir
        from sase.core.time import generate_timestamp

        timestamp = generate_timestamp()
        begin_prompt_session(
            self,
            PromptContext(
                project_name="home",
                cl_name=None,
                project_file=preferred_project_spec_path(
                    str(sase_projects_dir() / "home"), "home"
                ),
                workspace_dir="",
                workspace_num=0,
                workflow_name=f"ace(run)-{timestamp}",
                timestamp=timestamp,
                history_sort_key=kwargs.get("history_sort_key", "home"),
                display_name=kwargs.get("display_name", "~"),
                update_target="",
                is_home_mode=True,
            ),
        )
        prompt = self._open_editor_for_agent_prompt(kwargs.get("initial_text", ""))
        if prompt:
            self._finish_agent_launch(prompt)
        else:
            from sase.ace.tui.actions.agent_workflow._types import (
                invalidate_prompt_session,
            )

            self.notify("No prompt from editor - cancelled", severity="warning")
            invalidate_prompt_session(self)

    def _open_editor_for_agent_prompt(self, prompt: str) -> str:
        self.editor_prompts.append(prompt)
        return f"edited: {prompt}"

    def _finish_agent_launch(self, prompt: str, **_kwargs: object) -> None:
        self.finished_prompts.append(prompt)


class _FakeHistory:
    def __init__(self, depth: int = 0) -> None:
        self._undo_stack: list[Any] = [object()] * depth


class _FakeArea:
    def __init__(
        self, text: str = "", cursor: tuple[int, int] = (0, 0), history_depth: int = 0
    ) -> None:
        self.text = text
        self.cursor_location = cursor
        self.history = _FakeHistory(history_depth)
        self.loaded: list[str] = []

    def load_text(self, text: str) -> None:
        self.text = text
        self.loaded.append(text)


class _FakeStack:
    def __init__(self, panes: int = 1, selected: int = 0) -> None:
        self._panes = panes
        self.selected_index = selected

    def __len__(self) -> int:
        return self._panes


class _FakeBar:
    def __init__(
        self,
        area: _FakeArea,
        *,
        panes: int = 1,
        selected: int = 0,
        mode: str = "prompt",
        mounted: bool = True,
    ) -> None:
        self._area = area
        self._stack = _FakeStack(panes, selected)
        self._mode = mode
        self.is_mounted = mounted
        self.refreshed: list[str] = []

    def active_text_area(self) -> _FakeArea:
        return self._area

    def _sync_state_from_widgets(self) -> None:
        return None

    def _cursor_to_end(self, area: _FakeArea) -> None:
        area.cursor_location = (0, len(area.text))

    def _refresh_title(self) -> None:
        self.refreshed.append("title")

    def insert_mode_subtitle(self) -> str:
        return "insert"

    def set_prompt_mode_subtitle(self, subtitle: str) -> None:
        self.refreshed.append(f"subtitle:{subtitle}")

    def _refresh_dispatch_context_line(self) -> None:
        self.refreshed.append("dispatch")


def _pending_for(
    app: _SpaceApp,
    bar: _FakeBar,
    *,
    cursor: tuple[int, int] | None = (0, 0),
    pane: int | None = 0,
    history: int = 0,
) -> None:
    session = current_prompt_session(app)
    assert session is not None
    app._pending_space_prefill = {
        "session_id": session.session_id,
        "cursor": cursor,
        "pane_index": pane,
        "history_len": history,
    }
    app._bar = bar


# -- head resolution ----------------------------------------------------------


def test_resolve_head_prefills_alias_display_with_canonical_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tag_peek(monkeypatch, _tag_catalog("widgets"))
    resolved = resolve_vcs_xprompt_mru_head([("#gh:gh_acme__widgets", "#gh:widgets")])
    assert resolved == ("+widgets ", "widgets", "gh_acme__widgets")


def test_resolve_head_keeps_patch_ref_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    resolved = resolve_vcs_xprompt_mru_head([("#gh:fix_bug", "#gh:fix_bug")])
    assert resolved is not None
    initial_text, display_name, history_sort_key = resolved
    assert initial_text == "#gh:fix_bug "
    assert display_name == "fix_bug"
    assert history_sort_key == "fix_bug"


def test_resolve_head_empty_and_none_are_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    assert resolve_vcs_xprompt_mru_head([]) is None
    assert resolve_vcs_xprompt_mru_head(None) is None


# -- warm `<space>` -----------------------------------------------------------


def test_space_warm_prefill_comes_from_snapshot_without_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("warm <space> must not load")

    monkeypatch.setattr(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru_pairs", _boom
    )
    _patch_tag_peek(monkeypatch, _tag_catalog("widgets"))
    app = _SpaceApp(_ready([("#gh:gh_acme__widgets", "#gh:widgets")]))

    app.action_start_agent_from_patch()

    assert app.prompt_launches == [
        {
            "initial_text": "+widgets ",
            "display_name": "widgets",
            "history_sort_key": "gh_acme__widgets",
        }
    ]
    assert app.refresh_requests == []
    assert app._pending_space_prefill is None


def test_space_warm_empty_snapshot_opens_blank_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("warm <space> must not load")

    monkeypatch.setattr(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru_pairs", _boom
    )
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(_ready([]))

    app.action_start_agent_from_patch()

    assert app.prompt_launches == [{}]
    assert app._pending_space_prefill is None


def test_space_warm_performs_zero_main_thread_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.ace.tui._prompt_key_io_probes import prompt_key_io_probe

    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(_ready([("#gh:sase", "#gh:sase")]))

    with prompt_key_io_probe() as counts:
        app.action_start_agent_from_patch()

    counts.assert_quiet()
    assert app.prompt_launches[0]["initial_text"] == "+sase "


# -- cold / pending `<space>` -------------------------------------------------


def test_space_cold_opens_blank_and_records_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.launchable_mru import COLD_LAUNCHABLE_MRU_SNAPSHOT

    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(COLD_LAUNCHABLE_MRU_SNAPSHOT)

    app.action_start_agent_from_patch()

    assert app.prompt_launches == [{}]
    assert app._pending_space_prefill is not None
    assert app.refresh_requests == ["space-cold"]


def test_space_pending_snapshot_opens_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(_ready([("#gh:sase", "#gh:sase")], refresh_pending=True))

    app.action_start_agent_from_patch()

    assert app.prompt_launches == [{}]
    assert app._pending_space_prefill is not None


def test_space_without_snapshot_host_falls_back_to_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ._entry_points_vcs_prefix_helpers import _App

    monkeypatch.setattr(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru_pairs",
        lambda *a, **k: [("#gh:sase", "#gh:sase")],
    )
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _App()

    app.action_start_agent_from_patch()

    assert app.prompt_launches == [
        {
            "initial_text": "+sase ",
            "display_name": "sase",
            "history_sort_key": "sase",
        }
    ]


# -- late prefill -------------------------------------------------------------


def test_late_prefill_lands_on_untouched_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(_ready([("#gh:old", "#gh:old")]))
    app._show_prompt_input_bar_for_home()
    area = _FakeArea()
    bar = _FakeBar(area)
    _pending_for(app, bar)

    landed = try_apply_pending_space_prefill(app, [("#gh:sase", "#gh:sase")])

    assert landed is True
    assert area.text == "+sase "
    assert area.cursor_location == (0, len("+sase "))
    assert app._prompt_context is not None
    assert app._prompt_context.display_name == "sase"
    assert app._prompt_context.history_sort_key == "sase"
    assert "title" in bar.refreshed
    assert "dispatch" in bar.refreshed
    assert app._pending_space_prefill is None


def test_late_prefill_empty_snapshot_leaves_blank_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(_ready([]))
    app._show_prompt_input_bar_for_home()
    area = _FakeArea()
    _pending_for(app, _FakeBar(area))

    assert try_apply_pending_space_prefill(app, []) is False
    assert area.text == ""


def test_late_prefill_dropped_after_typing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(_ready([]))
    app._show_prompt_input_bar_for_home()
    area = _FakeArea(text="x", history_depth=1)
    _pending_for(app, _FakeBar(area))

    assert try_apply_pending_space_prefill(app, [("#gh:sase", "#gh:sase")]) is False
    assert area.text == "x"


def test_late_prefill_dropped_after_cursor_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(_ready([]))
    app._show_prompt_input_bar_for_home()
    area = _FakeArea(cursor=(0, 1))
    _pending_for(app, _FakeBar(area), cursor=(0, 0))

    assert try_apply_pending_space_prefill(app, [("#gh:sase", "#gh:sase")]) is False
    assert area.text == ""


def test_late_prefill_dropped_after_pane_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(_ready([]))
    app._show_prompt_input_bar_for_home()
    area = _FakeArea()
    _pending_for(app, _FakeBar(area, panes=1, selected=1), pane=0)

    assert try_apply_pending_space_prefill(app, [("#gh:sase", "#gh:sase")]) is False


def test_late_prefill_dropped_after_dismissal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.agent_workflow._types import invalidate_prompt_session

    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(_ready([]))
    app._show_prompt_input_bar_for_home()
    _pending_for(app, _FakeBar(_FakeArea()))
    invalidate_prompt_session(app)

    assert app._pending_space_prefill is None
    assert try_apply_pending_space_prefill(app, [("#gh:sase", "#gh:sase")]) is False


def test_reopened_bar_never_receives_previous_prefill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.launchable_mru import COLD_LAUNCHABLE_MRU_SNAPSHOT

    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(COLD_LAUNCHABLE_MRU_SNAPSHOT)
    app.action_start_agent_from_patch()
    first = dict(app._pending_space_prefill or {})

    app.action_start_agent_from_patch()
    second = dict(app._pending_space_prefill or {})

    assert first and second
    assert first["session_id"] != second["session_id"]
    area = _FakeArea()
    app._bar = _FakeBar(area)
    assert try_apply_pending_space_prefill(app, [("#gh:sase", "#gh:sase")]) is True
    assert area.text == "+sase "


def test_launch_then_space_shows_just_launched_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tag_peek(monkeypatch, _tag_catalog("projB", "projA"))
    app = _SpaceApp(_ready([("#gh:projA", "#gh:projA")], refresh_pending=True))

    app.action_start_agent_from_patch()
    assert app.prompt_launches == [{}]

    area = _FakeArea()
    app._bar = _FakeBar(area)
    # The pending entry was recorded against the blank session; the
    # launch rebuild publishes the just-launched project next.
    assert (
        try_apply_pending_space_prefill(
            app, [("#gh:projB", "#gh:projB"), ("#gh:projA", "#gh:projA")]
        )
        is True
    )
    assert area.text == "+projB "
    assert app._prompt_context is not None
    assert app._prompt_context.history_sort_key == "projB"


def test_record_pending_is_noop_without_session() -> None:
    app = _SpaceApp(_ready([]))
    assert current_prompt_session(app) is None
    record_pending_space_prefill(app)
    assert app._pending_space_prefill is None


# -- snapshot selectors -------------------------------------------------------


def test_space_prefill_pairs_require_no_pending_flag() -> None:
    app = _SpaceApp(_ready([("#gh:sase", "#gh:sase")], refresh_pending=True))
    assert peek_space_prefill_pairs(app) is None
    assert peek_ready_mru_pairs(app) == [("#gh:sase", "#gh:sase")]


def test_snapshot_selectors_tolerate_hosts_without_snapshot() -> None:
    from ._entry_points_vcs_prefix_helpers import _App

    assert peek_space_prefill_pairs(_App()) is None
    assert peek_ready_mru_pairs(_App()) is None


# -- editor entry -------------------------------------------------------------


def test_editor_uses_snapshot_when_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("warm editor entry must not load")

    monkeypatch.setattr(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru_pairs", _boom
    )
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(_ready([("#gh:sase", "#gh:sase")]))

    app.action_start_last_vcs_xprompt_in_editor()

    assert app.editor_prompts == ["+sase "]


def test_editor_falls_back_to_loader_when_cold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.launchable_mru import COLD_LAUNCHABLE_MRU_SNAPSHOT

    monkeypatch.setattr(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru_pairs",
        lambda *a, **k: [("#gh:sase", "#gh:sase")],
    )
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _SpaceApp(COLD_LAUNCHABLE_MRU_SNAPSHOT)

    app.action_start_last_vcs_xprompt_in_editor()

    assert app.editor_prompts == ["+sase "]


def test_editor_cold_never_writes_mru(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.launchable_mru import COLD_LAUNCHABLE_MRU_SNAPSHOT
    from tests.ace.tui._prompt_key_io_probes import prompt_key_io_probe

    monkeypatch.setattr(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru_pairs",
        lambda *a, **k: [],
    )
    app = _SpaceApp(COLD_LAUNCHABLE_MRU_SNAPSHOT)

    with prompt_key_io_probe() as counts:
        app.action_start_last_vcs_xprompt_in_editor()

    assert counts.mru_writes == 0
    assert app.notifications == [("No previous VCS xprompt", "warning")]


# -- `,.` history entry --------------------------------------------------------


class _HistoryApp(EntryPointsMixin):
    """Stub `,.` host: snapshot-aware, modal machinery captured, never run."""

    def __init__(self, snapshot: LaunchableMruSnapshot | None) -> None:
        self._snapshot = snapshot
        self.notifications: list[tuple[str, str | None]] = []
        self.spawned: list[Any] = []
        self.overlay_kwargs: dict[str, Any] | None = None
        self._prompt_context: PromptContext | None = None
        self._prompt_session: Any = None

    def peek_launchable_mru_snapshot(self) -> LaunchableMruSnapshot | None:
        return self._snapshot

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _spawn_prompt_stash_task(self, coro: Any) -> None:
        self.spawned.append(coro)

    def _open_prompts_overlay_async(self, **kwargs: Any) -> Any:
        self.overlay_kwargs = kwargs
        return ("overlay", kwargs)


def test_dot_history_uses_snapshot_when_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("warm `,.` must not load")

    monkeypatch.setattr(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru_pairs", _boom
    )
    app = _HistoryApp(_ready([("#gh:gh_acme__widgets", "#gh:widgets")]))

    app._start_prompt_history_from_last_selection()

    assert len(app.spawned) == 1
    assert app._prompt_context is not None
    assert app._prompt_context.display_name == "widgets"
    assert app._prompt_context.history_sort_key == "gh_acme__widgets"
    assert app.overlay_kwargs is not None
    assert app.overlay_kwargs["initial_tab"] == "history"


def test_dot_history_falls_back_to_loader_when_cold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.launchable_mru import COLD_LAUNCHABLE_MRU_SNAPSHOT

    monkeypatch.setattr(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru_pairs",
        lambda *a, **k: [("#gh:sase", "#gh:sase")],
    )
    app = _HistoryApp(COLD_LAUNCHABLE_MRU_SNAPSHOT)

    app._start_prompt_history_from_last_selection()

    assert len(app.spawned) == 1
    assert app._prompt_context is not None
    assert app._prompt_context.display_name == "sase"
