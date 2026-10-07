"""fs-trigger fire/skip coverage for the shipped ``hooks``/``waits`` chop defaults.

Verifies the pre-spawn guards wired into ``default_config.yml`` against each
chop's real input surface: Patch (ProjectSpec) files back every hooks-lane
chop except ``pending_checks_poll`` (the sharded ``~/.sase/checks/`` output
directory) and ``stale_running_cleanup`` (no fs-observable input at all - see
below); the per-project completion pulse
(``artifacts/.ace_refresh_pulse``) backs ``bead_claim_checks``/``wait_checks``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.chop_policy import (
    ChopPreflight,
    evaluate_chop_preflight,
    record_chop_checkpoint_event,
)
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig, load_axe_config
from sase.axe.lumberjack import Lumberjack
from sase.core.paths import sase_home
from sase.core.time import get_timezone

from tests._axe_lumberjack_fixtures import streamed_ok

# Every chop in the hooks lane that shares the Patch (ProjectSpec) fs trigger.
_PATCH_GLOB_CHOPS = (
    "hook_checks",
    "mentor_checks",
    "workflow_checks",
    "comment_zombie_checks",
    "suffix_transforms",
    "orphan_cleanup",
)

# waits-lane chops that share the per-project completion-pulse fs trigger.
# Per-agent pulses written inside run directories never match this
# project-level glob; only the project ``artifacts/.ace_refresh_pulse`` does.
_PULSE_CHOPS = ("bead_claim_checks", "wait_checks")

# Every shipped chop that got an fs trigger this phase, and the lane each
# lives in - used by the shared max_quiet sweep and the shipped-defaults
# contract test below.
_ALL_GUARDED_CHOPS = (
    ("hooks", "hook_checks"),
    ("hooks", "mentor_checks"),
    ("hooks", "workflow_checks"),
    ("hooks", "pending_checks_poll"),
    ("hooks", "comment_zombie_checks"),
    ("hooks", "suffix_transforms"),
    ("hooks", "orphan_cleanup"),
    ("waits", "bead_claim_checks"),
    ("waits", "wait_checks"),
)


def _default_chop(lane: str, name: str) -> ChopConfig:
    """Return the real shipped ``ChopConfig`` for one ``default_config.yml`` chop."""
    cfg = load_axe_config()
    for chop in cfg.lumberjacks[lane].chops:
        if chop.name == name:
            return chop
    raise AssertionError(f"{name!r} not found in the shipped {lane!r} lane")


def _tick(lane: str, chop: ChopConfig, *, now: datetime) -> ChopPreflight:
    return evaluate_chop_preflight(
        lumberjack_name=lane, chop=chop, context_file=None, scheduled=True, now=now
    )


def _fire_and_record(lane: str, chop: ChopConfig, *, now: datetime) -> ChopPreflight:
    """Bootstrap a chop's fs checkpoint: the first-ever observation always fires."""
    preflight = _tick(lane, chop, now=now)
    assert preflight.outcome == "fire", preflight.reason
    record_chop_checkpoint_event(lane, chop.name, preflight, "observed", now=now)
    return preflight


@pytest.mark.parametrize("chop_name", _PATCH_GLOB_CHOPS)
def test_patch_glob_chops_skip_idle_and_fire_on_project_spec_change(
    chop_name: str,
) -> None:
    chop = _default_chop("hooks", chop_name)
    tz = get_timezone()
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=tz)

    _fire_and_record("hooks", chop, now=t0)

    idle = _tick("hooks", chop, now=t0 + timedelta(seconds=5))
    assert idle.outcome == "skip", idle.reason

    project_dir = sase_home() / "projects" / "demo"
    project_dir.mkdir(parents=True)
    (project_dir / "demo.sase").write_text("PROJECT_NAME: demo\n", encoding="utf-8")

    changed = _tick("hooks", chop, now=t0 + timedelta(seconds=10))
    assert changed.outcome == "fire"
    assert "changed" in changed.reason


def test_patch_glob_chop_also_observes_legacy_gp_extension() -> None:
    """Legacy ``.gp`` ProjectSpec files (pre-``.sase`` migration) stay watched too."""
    chop = _default_chop("hooks", "hook_checks")
    tz = get_timezone()
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=tz)

    _fire_and_record("hooks", chop, now=t0)

    project_dir = sase_home() / "projects" / "legacy-demo"
    project_dir.mkdir(parents=True)
    (project_dir / "legacy-demo.gp").write_text(
        "PROJECT_NAME: legacy-demo\n", encoding="utf-8"
    )

    changed = _tick("hooks", chop, now=t0 + timedelta(seconds=5))
    assert changed.outcome == "fire"


def test_pending_checks_poll_skips_idle_and_fires_on_new_check_result() -> None:
    chop = _default_chop("hooks", "pending_checks_poll")
    tz = get_timezone()
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=tz)

    _fire_and_record("hooks", chop, now=t0)

    idle = _tick("hooks", chop, now=t0 + timedelta(seconds=5))
    assert idle.outcome == "skip", idle.reason

    shard = sase_home() / "checks" / "202601"
    shard.mkdir(parents=True)
    (shard / "demo_pr.txt").write_text("===CHECK_COMPLETE=== 0\n", encoding="utf-8")

    changed = _tick("hooks", chop, now=t0 + timedelta(seconds=10))
    assert changed.outcome == "fire"
    assert "changed" in changed.reason


def _real_run_dir(artifacts: Path, timestamp: str) -> Path:
    """Create a run dir on the real day-sharded ``ace-run/YYYYMM/DD/<run>`` layout."""
    run_dir = artifacts / "ace-run" / timestamp[:6] / timestamp[6:8] / timestamp
    run_dir.mkdir(parents=True)
    return run_dir


def _pulse_baseline(chop_name: str) -> tuple[ChopConfig, datetime, Path, Path]:
    """Record the pulse trigger checkpoint for one waits-lane chop.

    Returns the chop, the baseline instant, the project's artifacts dir, and
    one pre-existing real-layout run dir. The project pulse file does not
    exist yet, so the baseline token is the stable no-pulse state.
    """
    chop = _default_chop("waits", chop_name)
    tz = get_timezone()
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=tz)

    artifacts = sase_home() / "projects" / "demo" / "artifacts"
    run_dir = _real_run_dir(artifacts, "20260101120500")

    _fire_and_record("waits", chop, now=t0)
    return chop, t0, artifacts, run_dir


@pytest.mark.parametrize("chop_name", _PULSE_CHOPS)
def test_pulse_chops_skip_idle(chop_name: str) -> None:
    chop, t0, _, _ = _pulse_baseline(chop_name)

    idle = _tick("waits", chop, now=t0 + timedelta(seconds=10))
    assert idle.outcome == "skip", idle.reason


@pytest.mark.parametrize("chop_name", _PULSE_CHOPS)
def test_pulse_chops_fire_on_done_marker(chop_name: str) -> None:
    """A completion written through ``write_done_marker_and_update_index`` fires."""
    from sase.axe.run_agent_exec_markers import (  # noqa: PLC0415
        write_done_marker_and_update_index,
    )

    chop, t0, _, run_dir = _pulse_baseline(chop_name)

    idle = _tick("waits", chop, now=t0 + timedelta(seconds=10))
    assert idle.outcome == "skip", idle.reason

    write_done_marker_and_update_index(
        str(run_dir),
        {"patch_name": "dep", "cl_name": "dep", "outcome": "completed"},
    )

    changed = _tick("waits", chop, now=t0 + timedelta(seconds=20))
    assert changed.outcome == "fire"
    assert "changed" in changed.reason


@pytest.mark.parametrize("chop_name", _PULSE_CHOPS)
def test_pulse_chops_fire_on_dependency_waiting_marker(chop_name: str) -> None:
    """A dependency ``write_waiting_marker`` touches the pulse and fires."""
    from sase.axe.run_agent_wait_markers import write_waiting_marker  # noqa: PLC0415

    chop, t0, artifacts, _ = _pulse_baseline(chop_name)

    waiter_dir = _real_run_dir(artifacts, "20260101120600")
    write_waiting_marker(
        str(waiter_dir),
        {
            "waiting_for": ["dep"],
            "patch_name": "waiter",
            "cl_name": "waiter",
            "timestamp": "20260101120600",
        },
    )

    changed = _tick("waits", chop, now=t0 + timedelta(seconds=10))
    assert changed.outcome == "fire"
    assert "changed" in changed.reason


@pytest.mark.parametrize("chop_name", _PULSE_CHOPS)
def test_pulse_chops_skip_slot_queue_marker(chop_name: str) -> None:
    """A slot-queue-style marker (no dependency fields) neither pulses nor fires."""
    from sase.axe.run_agent_wait_markers import write_waiting_marker  # noqa: PLC0415

    chop, t0, artifacts, _ = _pulse_baseline(chop_name)

    queued_dir = _real_run_dir(artifacts, "20260101120700")
    write_waiting_marker(
        str(queued_dir),
        {
            "patch_name": "queued",
            "cl_name": "queued",
            "timestamp": "20260101120700",
            "queue_capacity": 0,
            "queue_capacity_explicit": True,
            "slot_requested_at": "2026-01-01T12:07:00+00:00",
        },
    )

    assert not (artifacts / ".ace_refresh_pulse").exists()
    skipped = _tick("waits", chop, now=t0 + timedelta(seconds=10))
    assert skipped.outcome == "skip", skipped.reason


@pytest.mark.parametrize("chop_name", _PULSE_CHOPS)
def test_pulse_chops_skip_lock_files_and_new_day_dir(chop_name: str) -> None:
    """Leaked scheduler lock files and new (empty) day shards do not fire."""
    chop, t0, artifacts, _ = _pulse_baseline(chop_name)

    ace_run = artifacts / "ace-run"
    (ace_run / "..gate-shell-abc123.lock").write_text("locked", encoding="utf-8")
    (ace_run / "..monitor-start-xyz.lock").write_text("locked", encoding="utf-8")
    (ace_run / "202601" / "02").mkdir(parents=True)

    skipped = _tick("waits", chop, now=t0 + timedelta(seconds=10))
    assert skipped.outcome == "skip", skipped.reason


@pytest.mark.parametrize(("lane", "chop_name"), _ALL_GUARDED_CHOPS)
def test_max_quiet_fires_even_with_no_watched_change(lane: str, chop_name: str) -> None:
    """A missed/unobservable change only delays a fire by ``max_quiet``, never loses it."""
    chop = _default_chop(lane, chop_name)
    assert chop.trigger.get("max_quiet") == "120s"
    tz = get_timezone()
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=tz)

    _fire_and_record(lane, chop, now=t0)

    idle = _tick(lane, chop, now=t0 + timedelta(seconds=30))
    assert idle.outcome == "skip", idle.reason

    quiet = _tick(lane, chop, now=t0 + timedelta(seconds=130))
    assert quiet.outcome == "fire"
    assert "max_quiet" in quiet.reason


def test_stale_running_cleanup_keeps_the_always_trigger_in_both_lanes() -> None:
    """No fs proxy exists for a dead PID; this chop is deliberately left unguarded."""
    hooks_chop = _default_chop("hooks", "stale_running_cleanup")
    checks_cfg = load_axe_config()
    checks_chop = next(
        chop
        for chop in checks_cfg.lumberjacks["checks"].chops
        if chop.name == "stale_running_cleanup"
    )
    assert hooks_chop.trigger == {"provider": "always"}
    assert checks_chop.trigger == {"provider": "always"}


def test_epic_launch_flush_and_sidecar_auto_sync_are_unaffected() -> None:
    """These already gate on ``run_every``; this phase does not touch them."""
    epic_launch_flush = _default_chop("waits", "epic_launch_flush")
    sidecar_auto_sync = _default_chop("waits", "sidecar_auto_sync")
    assert epic_launch_flush.trigger == {"provider": "always"}
    assert epic_launch_flush.run_every == 30
    assert sidecar_auto_sync.trigger == {"provider": "always"}
    assert sidecar_auto_sync.run_every == 30


def test_shipped_hooks_lane_has_exactly_seven_fs_guarded_chops() -> None:
    """Living contract: 8 hooks-lane chops, all but ``stale_running_cleanup`` guarded."""
    cfg = load_axe_config()
    hooks_lane = cfg.lumberjacks["hooks"]
    fs_guarded = [c.name for c in hooks_lane.chops if c.trigger.get("provider") == "fs"]
    always = [c.name for c in hooks_lane.chops if c.trigger.get("provider") == "always"]
    assert sorted(fs_guarded) == sorted(_PATCH_GLOB_CHOPS + ("pending_checks_poll",))
    assert always == ["stale_running_cleanup"]


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_patches", return_value=[])
def test_idle_tick_spawns_nothing_for_fs_guarded_hooks_lane_chops(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
) -> None:
    """An idle lumberjack tick performs zero ``Popen`` calls once warmed up.

    Uses the real shipped hooks-lane chop configs (minus ``stale_running_cleanup``,
    which has no fs proxy and is exempt by design - see
    ``test_stale_running_cleanup_keeps_the_always_trigger_in_both_lanes``).
    """
    axe_cfg = load_axe_config()
    guarded_chops = [
        chop
        for chop in axe_cfg.lumberjacks["hooks"].chops
        if chop.trigger.get("provider") == "fs"
    ]
    assert len(guarded_chops) == 7

    config = LumberjackConfig(
        name="hooks",
        description="Fast lane fixture",
        interval=5,
        chops=guarded_chops,
    )
    axe_config = AxeConfig(
        max_hook_runners=3, max_agent_runners=3, zombie_timeout_seconds=3600, query=""
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()

    lumberjack = Lumberjack("hooks", config, axe_config)

    lumberjack._run_tick()
    assert mock_run.call_count == len(guarded_chops)

    mock_run.reset_mock()
    lumberjack._run_tick()
    assert mock_run.call_count == 0
