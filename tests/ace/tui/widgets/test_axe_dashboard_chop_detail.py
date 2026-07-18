"""Phase 4: AXE dashboard renders chop detail via ``update_chop_run_display``."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.actions.axe_display._data import ChopRunSnapshot
from sase.ace.tui.util import axe_log_renderer
from sase.ace.tui.widgets import axe_dashboard
from sase.ace.tui.widgets.axe_dashboard import AxeDashboard

from ._axe_dashboard_helpers import _entry, _snapshot_with_runs


def test_update_chop_run_display_empty_state() -> None:
    """A configured chop with no recorded runs paints an empty-state panel."""
    snap = _snapshot_with_runs()  # no runs

    captured: dict[str, object] = {}

    class _Section:
        def update(self, content: object) -> None:
            captured["content"] = content

        def update_display(self, *args: object, **kwargs: object) -> None:
            captured.setdefault("display_called", True)

    class _StatusSection:
        def update_chop_display(self, *args: object, **kwargs: object) -> None:
            captured["status"] = (args, kwargs)

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return _StatusSection()
        return _Section()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    rendered = captured["content"]
    assert isinstance(rendered, Text)
    plain = rendered.plain
    assert "No runs recorded" in plain
    assert "fast description" in plain  # description shown in empty state


def test_update_chop_run_display_renders_newest_run_by_default() -> None:
    """Default run_idx=0 shows the newest run's output via per-run source id."""
    axe_log_renderer._render_cache.clear()
    newest = ChopRunSnapshot(
        entry=_entry("20260511T123500_000000"),
        output_tail="newest output\n",
    )
    older = ChopRunSnapshot(
        entry=_entry("20260511T120000_000000"),
        output_tail="older output\n",
    )
    snap = _snapshot_with_runs(newest, older)

    output_calls: list[tuple[str, str]] = []
    status_calls: list[tuple[tuple, dict]] = []

    class _OutputSection:
        def update_display(
            self,
            output: str,
            source_id: str = "axe-output",
            source_type: str = "ansi",
        ) -> None:
            output_calls.append((output, source_id))

        def update(self, *_: object, **__: object) -> None:
            output_calls.append(("__update__", "__update__"))

    class _StatusSection:
        def update_chop_display(self, *args: object, **kwargs: object) -> None:
            status_calls.append((args, kwargs))

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return _StatusSection()
        return _OutputSection()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    assert output_calls == [
        ("newest output\n", f"chop:hooks:fast:{newest.entry.run_id}"),
    ]
    # Status section gets the newest run with Run 1/2.
    args, _kwargs = status_calls[0]
    # update_chop_display(lumberjack_name, chop_name, run, run_idx, run_total, countdown)
    assert args[0] == "hooks"
    assert args[1] == "fast"
    assert args[2] is newest
    assert args[3] == 0
    assert args[4] == 2


def test_update_chop_run_display_clamps_out_of_range_idx() -> None:
    """Out-of-range run_idx clamps into the available history range."""
    only = ChopRunSnapshot(
        entry=_entry("only_run"),
        output_tail="only run output\n",
    )
    snap = _snapshot_with_runs(only)

    selected: list[ChopRunSnapshot] = []
    output_payloads: list[str] = []

    class _OutputSection:
        def update_display(
            self,
            output: str,
            source_id: str = "axe-output",
            source_type: str = "ansi",
        ) -> None:
            output_payloads.append(source_id)

        def update(self, *_: object, **__: object) -> None:
            pass

    class _StatusSection:
        def update_chop_display(
            self,
            lumberjack_name: str,
            chop_name: str,
            run: ChopRunSnapshot | None,
            run_idx: int,
            run_total: int,
            countdown: int,
        ) -> None:
            selected.append(run)  # type: ignore[arg-type]
            assert run_idx == 0  # clamped
            assert run_total == 1

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return _StatusSection()
        return _OutputSection()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_chop_run_display(snapshot=snap, run_idx=99, countdown=0)

    assert selected == [only]
    assert output_payloads == [f"chop:hooks:fast:{only.entry.run_id}"]


def test_chop_status_label_mapping() -> None:
    """Each chop run status maps to a non-empty label."""
    for status in (
        "success",
        "failure",
        "timeout",
        "missing_script",
        "running",
    ):
        label, style = axe_dashboard._chop_status_label(status)
        assert label
        assert style


def test_format_duration_ms_buckets() -> None:
    """Sub-second, sub-minute, and minute durations format distinctly."""
    assert axe_dashboard._format_duration_ms(250).endswith("ms")
    assert axe_dashboard._format_duration_ms(2_500).endswith("s")
    assert "m" in axe_dashboard._format_duration_ms(75_000)


def test_chop_status_running_label_style() -> None:
    """The running status renders as a non-empty live label."""
    label, style = axe_dashboard._chop_status_label("running")
    assert "running" in label.lower()
    assert "green" in style


def test_update_chop_run_display_script_run_stays_on_ansi() -> None:
    """Script chop runs keep the ANSI fallback — their output is arbitrary."""
    script_run = ChopRunSnapshot(
        entry=_entry("run-script", status="success"),
        output_tail="\x1b[32mall good\x1b[0m\n",
    )
    snap = _snapshot_with_runs(script_run)

    captured: dict[str, object] = {}

    class _OutputSection:
        def update_display(
            self,
            output: str,
            source_id: str = "axe-output",
            source_type: str = "ansi",
        ) -> None:
            captured["source_type"] = source_type

        def update(self, *_: object, **__: object) -> None:
            pass

    class _StatusSection:
        def update_chop_display(self, *_a: object, **_kw: object) -> None:
            pass

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return _StatusSection()
        return _OutputSection()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    assert captured["source_type"] == "ansi"


def test_render_chop_display_running_with_no_output_shows_waiting() -> None:
    """An active run with no output yet shows a 'Waiting…' placeholder."""
    running = ChopRunSnapshot(
        entry=_entry(
            "live",
            status="running",
            finished_at=None,
            duration_ms=0,
            exit_code=None,
        ),
        output_tail="",
    )
    snap = _snapshot_with_runs(running)

    captured: dict[str, object] = {}

    class _OutputSection:
        def update_display(self, *args: object, **kwargs: object) -> None:
            captured.setdefault("display", (args, kwargs))

        def update(self, content: object) -> None:
            captured["update"] = content

    class _StatusSection:
        def update_chop_display(self, *args: object, **kwargs: object) -> None:
            captured.setdefault("status", (args, kwargs))

    dashboard = AxeDashboard.__new__(AxeDashboard)
    dashboard.query_one = lambda sel, _cls: (  # type: ignore[assignment]
        _StatusSection() if "status" in sel else _OutputSection()
    )
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    rendered = captured["update"]
    assert isinstance(rendered, Text)
    assert "waiting" in rendered.plain.lower()
    # Output section's update_display path (for non-empty output) is unused.
    assert "display" not in captured
