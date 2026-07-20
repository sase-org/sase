"""Editing persisted chop output from the AXE tab."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin
from sase.ace.tui.actions.axe_chop_run import AxeChopRunMixin
from sase.ace.tui.actions.axe_display import ChopRunSnapshot, ChopSnapshot
from sase.ace.tui.actions.changespec._core import ChangeSpecMixin
from sase.ace.tui.widgets.bgcmd_list import BgCmdItem, ChopItem, LumberjackItem
from sase.axe.state import ChopRunEntry, chop_run_log_path


def _entry(run_id: str) -> ChopRunEntry:
    return ChopRunEntry(
        run_id=run_id,
        lumberjack_name="hooks",
        chop_name="fast",
        started_at="2026-06-01T00:00:00",
        finished_at="2026-06-01T00:00:01",
        duration_ms=1000,
        status="success",
    )


def _make_runs(*run_ids: str) -> list[ChopRunSnapshot]:
    return [ChopRunSnapshot(entry=_entry(rid), output_tail="") for rid in run_ids]


class _SuspendRecorder:
    def __init__(self) -> None:
        self.entered_count = 0

    def __enter__(self) -> None:
        self.entered_count += 1

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeAxeEditApp(AgentPanelDetailMixin, AxeChopRunMixin):
    def __init__(self, runs: list[ChopRunSnapshot]) -> None:
        self.current_tab: Any = "axe"
        self.current_idx = 1
        self._axe_items = [
            LumberjackItem(name="hooks"),
            ChopItem(lumberjack_name="hooks", chop_name="fast"),
            BgCmdItem(slot=1),
        ]
        self._axe_chop_snapshots = {
            ("hooks", "fast"): ChopSnapshot(
                lumberjack_name="hooks",
                chop_name="fast",
                description="",
                runs=runs,
            ),
        }
        self._axe_chop_run_offsets: dict[tuple[str, str], int] = {}
        self._axe_chop_selection: tuple[str, str] | None = None
        self.notifications: list[tuple[str, str]] = []
        self.suspend_recorder = _SuspendRecorder()
        self.derive_calls = 0

    def _derive_axe_view_from_selection(self) -> None:
        self.derive_calls += 1
        if not (0 <= self.current_idx < len(self._axe_items)):
            self._axe_chop_selection = None
            return
        item = self._axe_items[self.current_idx]
        if isinstance(item, ChopItem):
            self._axe_chop_selection = (item.lumberjack_name, item.chop_name)
        else:
            self._axe_chop_selection = None

    def _axe_resolve_chop_run_offset(self, chop_key: tuple[str, str]) -> int:
        snap = self._axe_chop_snapshots.get(chop_key)
        run_total = len(snap.runs) if snap is not None else 0
        if run_total <= 0:
            return 0
        raw = self._axe_chop_run_offsets.get(chop_key, 0)
        return max(0, min(raw, run_total - 1))

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def suspend(self) -> _SuspendRecorder:
        return self.suspend_recorder


@contextmanager
def _patched_axe_state(tmp_path: Path) -> Iterator[Path]:
    state_dir = tmp_path / "axe"
    jack_dir = state_dir / "lumberjacks"
    with (
        patch("sase.axe.state.axe_state_dir", return_value=state_dir),
        patch("sase.axe.state.jack_state_dir", return_value=jack_dir),
    ):
        yield state_dir


def _write_log(run_id: str, content: str = "output\n") -> Path:
    path = chop_run_log_path("hooks", "fast", run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_edit_spec_on_axe_chop_opens_newest_run_log(tmp_path: Path) -> None:
    app = _FakeAxeEditApp(_make_runs("new", "old"))

    with (
        _patched_axe_state(tmp_path),
        patch.dict("os.environ", {"EDITOR": "test-editor"}, clear=False),
        patch("sase.ace.tui.actions.axe_chop_run.subprocess.run") as mock_run,
    ):
        newest_log = _write_log("new")
        _write_log("old")
        app.action_edit_spec()

    mock_run.assert_called_once_with(["test-editor", str(newest_log)], check=False)
    assert app.suspend_recorder.entered_count == 1
    assert app.derive_calls == 1
    assert app.notifications == []


def test_edit_spec_on_axe_chop_opens_offset_selected_run_log(
    tmp_path: Path,
) -> None:
    app = _FakeAxeEditApp(_make_runs("new", "old"))
    app._axe_chop_run_offsets[("hooks", "fast")] = 1

    with (
        _patched_axe_state(tmp_path),
        patch.dict("os.environ", {"EDITOR": "test-editor"}, clear=False),
        patch("sase.ace.tui.actions.axe_chop_run.subprocess.run") as mock_run,
    ):
        _write_log("new")
        old_log = _write_log("old")
        app.action_edit_spec()

    mock_run.assert_called_once_with(["test-editor", str(old_log)], check=False)
    assert app.suspend_recorder.entered_count == 1
    assert app.notifications == []


def test_edit_spec_on_axe_non_chop_row_warns_without_crashing(
    tmp_path: Path,
) -> None:
    app = _FakeAxeEditApp(_make_runs("new"))
    app.current_idx = 0

    with (
        _patched_axe_state(tmp_path),
        patch("sase.ace.tui.actions.axe_chop_run.subprocess.run") as mock_run,
    ):
        app.action_edit_spec()

    mock_run.assert_not_called()
    assert app.notifications == [("No chop output selected", "warning")]


def test_edit_spec_on_axe_chop_with_no_runs_warns(tmp_path: Path) -> None:
    app = _FakeAxeEditApp(_make_runs())

    with (
        _patched_axe_state(tmp_path),
        patch("sase.ace.tui.actions.axe_chop_run.subprocess.run") as mock_run,
    ):
        app.action_edit_spec()

    mock_run.assert_not_called()
    assert app.notifications == [("No runs recorded for chop 'fast'", "warning")]


def test_edit_spec_on_axe_missing_log_warns(tmp_path: Path) -> None:
    app = _FakeAxeEditApp(_make_runs("new"))

    with (
        _patched_axe_state(tmp_path),
        patch("sase.ace.tui.actions.axe_chop_run.subprocess.run") as mock_run,
    ):
        app.action_edit_spec()

    mock_run.assert_not_called()
    assert app.notifications == [("No output log found for chop 'fast'", "warning")]


class _FakeChangeSpecApp(ChangeSpecMixin):
    def __init__(self) -> None:
        self.changespecs = [
            ChangeSpec(
                name="test",
                description="",
                parent=None,
                cl=None,
                status="WIP",
                bug=None,
                commits=None,
                hooks=None,
                comments=None,
                mentors=None,
                file_path="/tmp/test.gp",
                line_number=1,
            )
        ]
        self.current_idx = 10
        self.opened = False

    def _open_spec_in_editor(self, changespec: ChangeSpec) -> None:
        self.opened = True


def test_changespec_edit_spec_ignores_stale_current_idx() -> None:
    app = _FakeChangeSpecApp()

    app.action_edit_spec()

    assert app.opened is False
