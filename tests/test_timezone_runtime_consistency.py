"""Regression tests for configured-vs-system timezone consistency.

These pin the behavior fixed by the ``timezone_runtime_consistency`` plan: every
wall-clock generation, reference-now comparison, and aware→display conversion
resolves to the *configured* timezone, never the host system clock. The
``tz_divergence`` fixture (see ``tests/conftest.py``) forces configured tz
(``America/New_York``) ≠ system tz (``UTC``) so the bug class is visible; each
test below fails when a site falls back to the system clock.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from sase.core import time as core_time
from sase.core.time import (
    generate_timestamp,
    get_timezone,
    local_now,
    local_timezone_name,
    to_local,
)


def _reset_tz_cache() -> None:
    """Force the next :func:`get_timezone` to re-resolve (poke the cache global)."""
    core_time._cached_timezone = None


def _compact_to_seconds(text: str) -> int:
    """Parse a ``format_compact_duration`` string (``4m32s``/``1h5m``) to seconds."""
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text)
    assert match is not None, text
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _running_agent(
    *,
    start: datetime,
    run_start: datetime | None = None,
    status: str = "RUNNING",
    raw_suffix: str = "20260425143000",
):
    from sase.ace.tui.models.agent import Agent, AgentType

    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/tmp/p.sase",
        status=status,
        start_time=start,
        run_start_time=start if run_start is None else run_start,
        stop_time=None,
        raw_suffix=raw_suffix,
    )


# --- Part A: core helpers ------------------------------------------------


def test_to_local_converts_aware_utc_to_configured_tz() -> None:
    dt = datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC)
    assert to_local(dt) == datetime(2026, 7, 3, 6, 24, 49)


def test_to_local_leaves_naive_unchanged() -> None:
    dt = datetime(2026, 7, 3, 6, 24, 49)
    assert to_local(dt) == dt


def test_local_timezone_name_returns_iana_key() -> None:
    assert local_timezone_name() == "America/New_York"


def test_local_now_tracks_configured_tz_under_divergence(tz_divergence: None) -> None:
    # local_now() (Eastern) trails the naive system clock (UTC) by the EDT/EST
    # offset (4–5h); a system-clock local_now() would show ~0 delta.
    delta = (datetime.now() - local_now()).total_seconds()
    assert 3.5 * 3600 < delta < 5.5 * 3600


def test_get_timezone_defaults_to_system_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.config.core.load_merged_config", lambda: {})
    original_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()
        _reset_tz_cache()
        assert get_timezone() == ZoneInfo("Europe/Berlin")
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()
        _reset_tz_cache()


def test_get_timezone_config_wins_over_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {"timezone": "America/New_York"},
    )
    original_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()
        _reset_tz_cache()
        assert get_timezone() == ZoneInfo("America/New_York")
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()
        _reset_tz_cache()


# --- Part B: the screenshot runtime bug ----------------------------------


def test_compute_row_runtime_under_tz_divergence(tz_divergence: None) -> None:
    """A 2-minute-old RUNNING agent shows ~2m runtime, not the ~4h tz offset."""
    from sase.ace.tui.models._loaders._meta_enrichment_common import parse_utc_to_local
    from sase.ace.tui.models.agent import compute_row_runtime

    started_iso = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
    run_start = parse_utc_to_local(started_iso)
    agent = _running_agent(start=run_start, run_start=run_start)

    # now=None exercises the production default reference (local_now()), which
    # the live-row patch path (_display_panel_patches) also passes in.
    ts, elapsed = compute_row_runtime(agent)

    assert ts is None
    assert elapsed is not None
    assert 100 <= _compact_to_seconds(elapsed) <= 140


def test_by_date_agent_grouping_reference_uses_configured_tz(
    tz_divergence: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.tui.models.agent_groups import _keys

    captured: dict[str, datetime] = {}
    real = _keys.date_bucket_for

    def spy(agent, now):  # type: ignore[no-untyped-def]
        captured["now"] = now
        return real(agent, now)

    monkeypatch.setattr(_keys, "date_bucket_for", spy)
    agent = _running_agent(start=datetime(2026, 4, 25, 14, 0, 0))
    _keys.grouping_keys_for(agent, {}, _keys.GroupingMode.BY_DATE)

    reference = captured["now"]
    assert abs((reference - local_now()).total_seconds()) < 5
    assert abs((reference - datetime.now()).total_seconds()) > 3000


def test_by_date_patch_grouping_reference_uses_configured_tz(
    tz_divergence: None,
    monkeypatch: pytest.MonkeyPatch,
    make_patch,  # type: ignore[no-untyped-def]
) -> None:
    from sase.ace.tui.models.patch_groups import _tree as cs_tree
    from sase.ace.tui.models.patch_groups._buckets import PatchGroupingMode

    captured: dict[str, datetime] = {}
    real = cs_tree.keys_for_patches

    def spy(patches, mode, reference, latest_map=None):  # type: ignore[no-untyped-def]
        captured["reference"] = reference
        return real(patches, mode, reference, latest_map=latest_map)

    monkeypatch.setattr(cs_tree, "keys_for_patches", spy)
    cs = make_patch.create(name="demo")
    cs_tree.enumerate_patch_group_keys([cs], PatchGroupingMode.BY_DATE)

    reference = captured["reference"]
    assert abs((reference - local_now()).total_seconds()) < 5
    assert abs((reference - datetime.now()).total_seconds()) > 3000


def test_age_query_filter_uses_configured_now(tz_divergence: None) -> None:
    from sase.ace.agent_query import parse_agent_query
    from sase.ace.tui.actions.agents._loading_compute_finalize import (
        _filter_agents_by_query,
    )

    start = local_now() - timedelta(minutes=3)
    agent = _running_agent(start=start)

    assert _filter_agents_by_query([agent], parse_agent_query("age>2m"), None) == [
        agent
    ]
    # A system-clock reference would inflate the age to ~4h and wrongly match.
    assert _filter_agents_by_query([agent], parse_agent_query("age>10m"), None) == []


# --- Part C: display conversions -----------------------------------------


def test_render_timestamp_divider_uses_configured_tz(tz_divergence: None) -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_content import (
        render_timestamp_divider,
    )

    divider = render_timestamp_divider("2026-07-03T10:24:49+00:00")
    assert "06:24:49" in divider.plain


def test_render_phase_divider_shows_naive_start_verbatim(tz_divergence: None) -> None:
    """A naive configured-tz start time renders as-is, not shifted by system tz."""
    from sase.ace.tui.widgets.prompt_panel._agent_display_content import (
        render_phase_divider,
    )

    divider = render_phase_divider("PLANNER", datetime(2026, 7, 3, 6, 24, 49))
    assert "06:24:49" in divider.plain


def test_attempt_start_hhmmss_uses_configured_tz(tz_divergence: None) -> None:
    from sase.ace.tui.models.agent_attempt import AttemptRecord

    epoch = datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC).timestamp()
    record = AttemptRecord(
        attempt_number=1,
        status="failed",
        start_epoch=epoch,
        end_epoch=epoch,
        model=None,
        used_fallback=False,
        error_snippet="",
        error_full="",
        live_reply_path="",
        timestamps_path="",
    )
    assert record.start_hhmmss == "06:24:49"


# --- Part D: wall-clock generation ---------------------------------------


def test_workflow_duration_display_under_divergence(tz_divergence: None) -> None:
    from sase.ace.tui.models.workflow import WorkflowEntry

    start = local_now() - timedelta(minutes=5, seconds=12)
    entry = WorkflowEntry(
        workflow_name="wf",
        cl_name="demo",
        project_file="/tmp/p.sase",
        status="RUNNING",
        current_step=0,
        total_steps=1,
        steps=[],
        start_time=start,
        artifacts_dir="/tmp",
    )
    assert 300 <= _compact_to_seconds(entry.duration_display) <= 360


def test_wait_absolute_time_uses_configured_clock(tz_divergence: None) -> None:
    from sase.axe.run_agent_wait import remaining_until
    from sase.xprompt._directive_time import parse_absolute_time

    iso = parse_absolute_time("1430")
    assert iso is not None
    target = datetime.fromisoformat(iso)
    assert (target.hour, target.minute) == (14, 30)

    # remaining_until's naive branch references the configured (Eastern) clock.
    remaining = remaining_until(iso)
    expected = (target - local_now()).total_seconds()
    assert abs(remaining - expected) < 5

    eastern_today = local_now().date()
    assert target.date() in (eastern_today, eastern_today + timedelta(days=1))


def test_generate_timestamp_uses_configured_tz(tz_divergence: None) -> None:
    stamp = generate_timestamp()
    parsed = datetime.strptime(stamp, "%y%m%d_%H%M%S")
    # Minted in Eastern, so it trails the system (UTC) wall clock.
    assert abs((parsed - local_now()).total_seconds()) < 5
    assert abs((parsed - datetime.now()).total_seconds()) > 3000


# --- Part E: hook wrapper script -----------------------------------------


def test_hook_wrapper_embeds_configured_timezone(
    tz_divergence: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    from sase.ace.patch.models import HookEntry
    from sase.ace.hooks import execution

    captured: dict[str, str] = {}

    class _FakeProc:
        pid = 4242

    def _fake_popen(args, **kwargs):  # type: ignore[no-untyped-def]
        with open(args[0]) as f:
            captured["script"] = f.read()
        return _FakeProc()

    monkeypatch.setattr(execution.subprocess, "Popen", _fake_popen)

    patch = types.SimpleNamespace(name="demo")
    hook = HookEntry(command="echo hi")
    execution.start_hook_background(patch, hook, "/tmp", "1")

    assert 'TZ="America/New_York" date +"%y%m%d_%H%M%S"' in captured["script"]
    assert "America/New_York timezone" not in captured["script"]


def test_hook_duration_roundtrips_under_divergence(tz_divergence: None) -> None:
    from sase.ace.hooks.timestamps import (
        calculate_duration_from_timestamps,
        get_current_timestamp,
    )

    start = get_current_timestamp()
    end = subprocess.run(
        ["bash", "-c", 'TZ="America/New_York" date +"%y%m%d_%H%M%S"'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    duration = calculate_duration_from_timestamps(start, end)
    assert duration is not None
    assert 0 <= duration < 120

    # Without the TZ override the end timestamp would be system-tz (UTC), which
    # is why the wrapper must pin the configured zone.
    end_system = subprocess.run(
        ["bash", "-c", 'date +"%y%m%d_%H%M%S"'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    duration_system = calculate_duration_from_timestamps(start, end_system)
    assert duration_system is not None
    assert duration_system > 3000


# --- Part F: latent crash + hardening ------------------------------------


def test_iter_revive_events_since_does_not_crash_on_naive_event(
    tz_divergence: None, tmp_path
) -> None:
    from sase.logs.daterange import parse_daterange
    from sase.logs.run_log import iter_revive_events

    events_file = tmp_path / "events.jsonl"
    stamp = local_now().strftime("%y%m%d_%H%M%S")
    events_file.write_text(
        json.dumps({"timestamp": stamp, "event": "agent_revived", "outcome": "success"})
        + "\n",
        encoding="utf-8",
    )

    since, _ = parse_daterange("-1d")
    results = list(iter_revive_events(since=since, events_file=str(events_file)))
    assert len(results) == 1
