"""Continue prefill, shared close helper, and forced stranded refresh."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions._stranded_resolve_actions import (
    _continue_stranded_leaf,
    open_stranded_resolve_modal,
    schedule_stranded_resolve_refresh,
)
from sase.ace.tui.models import agent_stranded
from sase.ace.tui.models.stranded_resolve import stranded_continue_prompt
from sase.bead.model import Issue, IssueType
from sase.bead.stranded import StrandedReport
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict
from tests.ace.tui._artifacts_beads_stranded_helpers import stranded_snapshot


@pytest.fixture(autouse=True)
def _clear_stranded_cache() -> None:
    agent_stranded._STRANDED_REPORT_CACHE.clear()
    yield
    agent_stranded._STRANDED_REPORT_CACHE.clear()


def _seed() -> None:
    verdict = StrandedWorkVerdict(
        bead_id="sase-demo.1",
        kind="phase",
        state="stranded",
        reason="kept",
        last_turn="sase-demo.1--3",
    )
    report = StrandedWorkReport(verdicts=(verdict,), stranded_ids=("sase-demo.1",))
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo",
        StrandedReport(report=report, titles={}, generated_at=1.0),
        "test",
    )


class _FakeApp:
    def __init__(self) -> None:
        self.screens: list[Any] = []
        self.callbacks: list[Any] = []
        self.prompts: list[dict[str, Any]] = []
        self.notifies: list[tuple[str, str | None]] = []
        self.warmup_sources: list[str] = []
        self.beads_forced: list[bool] = []
        self._agents: list[Any] = []

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifies.append((message, severity))

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self.screens.append(screen)
        self.callbacks.append(callback)

    def _show_prompt_input_bar_for_home(self, **kwargs: Any) -> None:
        self.prompts.append(kwargs)

    def _schedule_bead_confirmation_warmup(self, *, source: str = "unknown") -> None:
        self.warmup_sources.append(source)

    def _beads_pane(self) -> Any:
        return SimpleNamespace(
            _schedule_stranded_refresh=lambda *, force=False: self.beads_forced.append(
                force
            )
        )


def test_open_modal_uses_warm_cache() -> None:
    _seed()
    app = _FakeApp()
    open_stranded_resolve_modal(app, "demo", "sase-demo.1")
    assert len(app.screens) == 1
    assert app.screens[0].view.focus_id == "sase-demo.1"


def test_continue_prefills_fork_prompt() -> None:
    _seed()
    app = _FakeApp()
    _continue_stranded_leaf(app, "demo", "sase-demo.1")
    assert app.prompts
    text = app.prompts[0]["initial_text"]
    expected = stranded_continue_prompt(
        leaf_id="sase-demo.1",
        last_turn="sase-demo.1--3",
        cause="ended with bead_action keep; nothing resumes it",
    )
    assert text == expected
    assert app.warmup_sources == ["stranded_resolve"]
    assert app.beads_forced == [True]


def test_schedule_refresh_expires_and_warms() -> None:
    _seed()
    app = _FakeApp()
    assert agent_stranded.should_resolve_stranded_report("demo") is False
    schedule_stranded_resolve_refresh(app, "demo")
    assert agent_stranded.should_resolve_stranded_report("demo") is True
    assert app.warmup_sources == ["stranded_resolve"]
    assert app.beads_forced == [True]


def test_beads_w_opens_modal_for_stranded_phase(tmp_path, monkeypatch) -> None:
    from sase.ace.tui.actions._artifacts_beads_launch import (
        ArtifactsBeadsLaunchActionsMixin,
    )
    from sase.ace.tui.widgets.artifacts.beads_list import BeadRow

    snapshot, _ = stranded_snapshot(tmp_path, monkeypatch)
    phase = next(
        item
        for item in snapshot.phases_by_epic["alpha", "alpha-1"]
        if item.issue.id == "alpha-1.2"
    )
    row = BeadRow(
        kind="phase",
        row_id="phase:alpha-1.2",
        project="alpha",
        issue=phase.issue,
    )

    class _LaunchApp(ArtifactsBeadsLaunchActionsMixin):
        def __init__(self) -> None:
            self.screens: list[Any] = []
            self.notifies: list[Any] = []

        def notify(self, message: str, severity: str | None = None) -> None:
            self.notifies.append((message, severity))

        def push_screen(self, screen: Any, callback: Any = None) -> None:
            self.screens.append(screen)

        def _selected_bead(self) -> tuple[Any, BeadRow]:
            return SimpleNamespace(snapshot=snapshot), row

    app = _LaunchApp()
    app.action_beads_launch_work()
    assert len(app.screens) == 1
    assert app.screens[0].view.focus_id == "alpha-1.2"


def test_submit_bead_close_accepts_issue_instead_of_row() -> None:
    from sase.ace.tui.actions._artifacts_beads_mutations import (
        ArtifactsBeadsMutationActionsMixin,
    )
    from sase.ace.tui.modals.bead_close_modal import BeadCloseResult

    submitted: list[Any] = []

    class _CloseApp(ArtifactsBeadsMutationActionsMixin):
        def notify(self, message: str, severity: str | None = None) -> None:
            return None

        def _submit_session_worker(self, *args: Any, **kwargs: Any) -> None:
            submitted.append((args, kwargs))

        def _beads_pane(self) -> None:
            return None

        def _schedule_bead_confirmation_warmup(
            self, *, source: str = "unknown"
        ) -> None:
            return None

    issue = Issue("sase-demo.1", "Live proof", issue_type=IssueType.PHASE)
    app = _CloseApp()
    app._submit_bead_close(
        issue,
        "demo",
        "/tmp/demo",
        BeadCloseResult(
            resolution="done",
            reason="Finished",
            note=None,
            force=False,
        ),
    )
    assert submitted
    assert submitted[0][1]["cl_name"] == "sase-demo.1"
    assert submitted[0][1]["dedup_key"] == "beads:close:demo:sase-demo.1"
