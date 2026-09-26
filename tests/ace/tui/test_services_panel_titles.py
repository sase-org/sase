"""Border-title stats and builders for the Services-tab side panels."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.actions.axe_display._panel_titles import (
    ROUTINE_PANEL_LABELS,
    scheduled_routines_panel_stats,
    scheduled_routines_panel_title,
    service_procs_panel_stats,
    service_procs_panel_title,
    source_routine_panel_title,
)


def _proc(
    state: str,
    desired: str = "running",
    *,
    available: bool = True,
    enabled: bool = True,
    name: str = "proc",
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        state=state,
        desired=desired,
        available=available,
        enablement=SimpleNamespace(enabled=enabled),
        restart=None,
    )


def _oneshot_info(
    *, running: bool, exit_code: int | None = 0, status: str = "done"
) -> SimpleNamespace:
    return SimpleNamespace(running=running, exit_code=exit_code, status=status)


def _chop_run(status: str) -> SimpleNamespace:
    return SimpleNamespace(entry=SimpleNamespace(status=status))


def _chop_snapshot(*statuses: str) -> SimpleNamespace:
    return SimpleNamespace(runs=[_chop_run(s) for s in statuses])


def _span_styles(title) -> list[str]:
    return [str(span.style) for span in title.spans]


def test_service_procs_title_grammar() -> None:
    stats = service_procs_panel_stats(
        procs=[_proc("running"), _proc("running")],
        oneshots=[(_oneshot_info(running=True), True)],
        host_state="running",
    )
    assert stats.items == 3
    title = service_procs_panel_title(stats, focused=True)
    assert title.plain == "⚙ Service Procs · 3 [R2] ▷1"


def test_service_procs_chip_letters_use_chrome_and_counts_use_metrics() -> None:
    stats = service_procs_panel_stats(
        procs=[_proc("running"), _proc("crash_loop"), _proc("stopped", "stopped")],
        oneshots=[],
        host_state="running",
    )
    assert (stats.running, stats.warn, stats.fail, stats.muted) == (1, 0, 1, 1)
    title = service_procs_panel_title(stats, focused=True)
    assert title.plain == "⚙ Service Procs · 3 [R1 F1 S1]"
    styles = _span_styles(title)
    assert "bold #00D7AF" in styles  # R count metric
    assert "bold #FF5F5F" in styles  # F count metric


def test_service_procs_focus_chrome() -> None:
    stats = service_procs_panel_stats(procs=[], oneshots=[], host_state="running")
    focused = service_procs_panel_title(stats, focused=True)
    unfocused = service_procs_panel_title(stats, focused=False)
    assert focused.plain == unfocused.plain == "⚙ Service Procs · 0"
    assert "#FFD75F" in _span_styles(focused)
    assert "#FFD75F" not in _span_styles(unfocused)
    assert "#AFAFAF" in _span_styles(unfocused)


def test_service_procs_zero_suppression() -> None:
    stats = service_procs_panel_stats(procs=[], oneshots=[], host_state="running")
    title = service_procs_panel_title(stats, focused=True)
    assert "[" not in title.plain
    for glyph in ("▷", "✓", "✗"):
        assert glyph not in title.plain


def test_service_procs_sum_invariant() -> None:
    stats = service_procs_panel_stats(
        procs=[
            _proc("running"),
            _proc("crash_loop"),
            _proc("stopped", "stopped"),
            _proc("stopped"),
        ],
        oneshots=[
            (_oneshot_info(running=True), True),
            (_oneshot_info(running=False, exit_code=0), False),
            (_oneshot_info(running=False, exit_code=1), False),
            (_oneshot_info(running=False, status="killed"), False),
        ],
        host_state="running",
    )
    chip_total = stats.running + stats.warn + stats.fail + stats.muted
    badge_total = stats.oneshot_running + stats.oneshot_ok + stats.oneshot_failed
    assert chip_total + badge_total == stats.items == 8
    title = service_procs_panel_title(stats, focused=True)
    assert title.plain == "⚙ Service Procs · 8 [R1 F2 S1] ▷1 ✓1 ✗2"


def test_service_procs_badges() -> None:
    stats = service_procs_panel_stats(
        procs=[],
        oneshots=[],
        hidden_oneshots=3,
        host_state="stopped",
        status_unavailable=True,
    )
    title = service_procs_panel_title(stats, focused=False)
    assert title.plain == (
        "⚙ Service Procs · 0 · +3 hidden · host stopped · status unavailable"
    )


def test_service_procs_running_host_has_no_badge() -> None:
    stats = service_procs_panel_stats(procs=[], oneshots=[], host_state="running")
    assert "host" not in service_procs_panel_title(stats, focused=True).plain


def test_routines_title_grammar() -> None:
    stats = scheduled_routines_panel_stats(
        routine_names=["hooks", "mentors", "idle-one"],
        statuses={
            "hooks": SimpleNamespace(status="running"),
            "mentors": SimpleNamespace(status="error"),
            "idle-one": None,
        },
        chop_names={"hooks": ["a", "b"], "mentors": ["c"], "idle-one": []},
        chop_snapshots={
            ("hooks", "a"): _chop_snapshot("running"),
            ("hooks", "b"): _chop_snapshot("failure"),
            ("mentors", "c"): _chop_snapshot("missing_script"),
        },
        overrun_counts={"hooks": 2},
    )
    assert (stats.running, stats.error, stats.idle) == (1, 1, 1)
    assert stats.jobs == 3
    assert (stats.jobs_running, stats.jobs_failed, stats.jobs_missing) == (1, 1, 1)
    assert stats.overruns == 2
    title = scheduled_routines_panel_title(stats, focused=True)
    assert title.plain == "◷ Scheduled Routines · 3 [R1 E1 I1] · 3 jobs ●1 !1 ?1 ⚠2"


def test_routines_sum_invariant() -> None:
    stats = scheduled_routines_panel_stats(
        routine_names=["a", "b"],
        statuses={"a": SimpleNamespace(status="running"), "b": SimpleNamespace()},
        chop_names={},
        chop_snapshots={},
        overrun_counts={},
    )
    assert stats.running + stats.error + stats.idle == stats.routines == 2


def test_routines_jobs_count_includes_jobs_without_snapshots() -> None:
    stats = scheduled_routines_panel_stats(
        routine_names=["hooks"],
        statuses={},
        chop_names={"hooks": ["seen", "unseen"]},
        chop_snapshots={("hooks", "seen"): _chop_snapshot("success")},
        overrun_counts={},
    )
    assert stats.jobs == 2
    assert (stats.jobs_running, stats.jobs_failed, stats.jobs_missing) == (0, 0, 0)
    title = scheduled_routines_panel_title(stats, focused=True)
    assert "2 jobs" in title.plain
    assert "●" not in title.plain


def test_routines_timeout_counts_as_failure() -> None:
    stats = scheduled_routines_panel_stats(
        routine_names=["hooks"],
        statuses={},
        chop_names={"hooks": ["a"]},
        chop_snapshots={("hooks", "a"): _chop_snapshot("timeout")},
        overrun_counts={},
    )
    assert stats.jobs_failed == 1


def test_routines_focus_chrome() -> None:
    stats = scheduled_routines_panel_stats(
        routine_names=[],
        statuses={},
        chop_names={},
        chop_snapshots={},
        overrun_counts={},
    )
    focused = scheduled_routines_panel_title(stats, focused=True)
    unfocused = scheduled_routines_panel_title(stats, focused=False)
    assert focused.plain == unfocused.plain == "◷ Scheduled Routines · 0 · 0 jobs"
    assert "#FFD75F" in _span_styles(focused)
    assert "#FFD75F" not in _span_styles(unfocused)


def test_routines_scheduler_badges() -> None:
    base = {
        "routine_names": [],
        "statuses": {},
        "chop_names": {},
        "chop_snapshots": {},
        "overrun_counts": {},
    }
    stopped = scheduled_routines_panel_stats(
        **base, service_procs={"scheduler": _proc("stopped", name="scheduler")}
    )
    assert stopped.scheduler_badge_text == "scheduler stopped"
    assert (
        "scheduler stopped"
        in scheduled_routines_panel_title(stopped, focused=True).plain
    )

    disabled = scheduled_routines_panel_stats(
        **base,
        service_procs={"scheduler": _proc("stopped", enabled=False, name="scheduler")},
    )
    assert disabled.scheduler_badge_text == "scheduler disabled"

    unavailable = scheduled_routines_panel_stats(
        **base,
        service_procs={
            "scheduler": _proc("stopped", available=False, name="scheduler")
        },
    )
    assert unavailable.scheduler_badge_text == "scheduler unavailable"

    running = scheduled_routines_panel_stats(
        **base, service_procs={"scheduler": _proc("running", name="scheduler")}
    )
    assert running.scheduler_badge_text is None
    assert (
        "scheduler" not in scheduled_routines_panel_title(running, focused=True).plain
    )

    unknown = scheduled_routines_panel_stats(**base, service_procs=None)
    assert unknown.scheduler_badge_text is None


def test_source_titles_use_provenance_labels() -> None:
    base = {
        "routine_names": ["hooks"],
        "statuses": {},
        "chop_names": {"hooks": ["a"]},
        "chop_snapshots": {("hooks", "a"): _chop_snapshot("success")},
        "overrun_counts": {},
    }
    assert ROUTINE_PANEL_LABELS == {
        "user_routines": "User Routines",
        "plugin_routines": "Plugin Routines",
        "builtin_routines": "Builtin Routines",
    }
    for key, label in ROUTINE_PANEL_LABELS.items():
        stats = scheduled_routines_panel_stats(**base)
        title = source_routine_panel_title(stats, focused=True, label=label)
        assert label in title.plain
        assert "Scheduled Routines" not in title.plain


def test_source_title_singular_job() -> None:
    stats = scheduled_routines_panel_stats(
        routine_names=["hooks"],
        statuses={},
        chop_names={"hooks": ["only"]},
        chop_snapshots={},
        overrun_counts={},
    )
    title = source_routine_panel_title(stats, focused=True, label="User Routines")
    assert "1 job" in title.plain
    assert "1 jobs" not in title.plain
