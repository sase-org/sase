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

# Pulse-triggered chops and the lane each lives in. Per-agent pulses written
# inside run directories never match this project-level glob; only the
# project ``artifacts/.ace_refresh_pulse`` does.
_PULSE_CHOPS = (
    ("waits", "bead_claim_checks"),
    ("agent_waits", "wait_checks"),
)

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
    ("agent_waits", "wait_checks"),
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


def _pulse_baseline(
    lane: str, chop_name: str
) -> tuple[ChopConfig, datetime, Path, Path]:
    """Record the pulse trigger checkpoint for one pulse-triggered chop.

    Returns the chop, the baseline instant, the project's artifacts dir, and
    one pre-existing real-layout run dir. The project pulse file does not
    exist yet, so the baseline token is the stable no-pulse state.
    """
    chop = _default_chop(lane, chop_name)
    tz = get_timezone()
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=tz)

    artifacts = sase_home() / "projects" / "demo" / "artifacts"
    run_dir = _real_run_dir(artifacts, "20260101120500")

    _fire_and_record(lane, chop, now=t0)
    return chop, t0, artifacts, run_dir


@pytest.mark.parametrize(("lane", "chop_name"), _PULSE_CHOPS)
def test_pulse_chops_skip_idle(lane: str, chop_name: str) -> None:
    chop, t0, _, _ = _pulse_baseline(lane, chop_name)

    idle = _tick(lane, chop, now=t0 + timedelta(seconds=10))
    assert idle.outcome == "skip", idle.reason


@pytest.mark.parametrize(("lane", "chop_name"), _PULSE_CHOPS)
def test_pulse_chops_fire_on_done_marker(lane: str, chop_name: str) -> None:
    """A completion written through ``write_done_marker_and_update_index`` fires."""
    from sase.axe.run_agent_exec_markers import (  # noqa: PLC0415
        write_done_marker_and_update_index,
    )

    chop, t0, _, run_dir = _pulse_baseline(lane, chop_name)

    idle = _tick(lane, chop, now=t0 + timedelta(seconds=10))
    assert idle.outcome == "skip", idle.reason

    write_done_marker_and_update_index(
        str(run_dir),
        {"patch_name": "dep", "cl_name": "dep", "outcome": "completed"},
    )

    changed = _tick(lane, chop, now=t0 + timedelta(seconds=20))
    assert changed.outcome == "fire"
    assert "changed" in changed.reason


@pytest.mark.parametrize(("lane", "chop_name"), _PULSE_CHOPS)
def test_pulse_chops_fire_on_dependency_waiting_marker(
    lane: str, chop_name: str
) -> None:
    """A dependency ``write_waiting_marker`` touches the pulse and fires."""
    from sase.axe.run_agent_wait_markers import write_waiting_marker  # noqa: PLC0415

    chop, t0, artifacts, _ = _pulse_baseline(lane, chop_name)

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

    changed = _tick(lane, chop, now=t0 + timedelta(seconds=10))
    assert changed.outcome == "fire"
    assert "changed" in changed.reason


@pytest.mark.parametrize(("lane", "chop_name"), _PULSE_CHOPS)
def test_pulse_chops_skip_slot_queue_marker(lane: str, chop_name: str) -> None:
    """A slot-queue-style marker (no dependency fields) neither pulses nor fires."""
    from sase.axe.run_agent_wait_markers import write_waiting_marker  # noqa: PLC0415

    chop, t0, artifacts, _ = _pulse_baseline(lane, chop_name)

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
    skipped = _tick(lane, chop, now=t0 + timedelta(seconds=10))
    assert skipped.outcome == "skip", skipped.reason


@pytest.mark.parametrize(("lane", "chop_name"), _PULSE_CHOPS)
def test_pulse_chops_skip_lock_files_and_new_day_dir(lane: str, chop_name: str) -> None:
    """Leaked scheduler lock files and new (empty) day shards do not fire."""
    chop, t0, artifacts, _ = _pulse_baseline(lane, chop_name)

    ace_run = artifacts / "ace-run"
    (ace_run / "..gate-shell-abc123.lock").write_text("locked", encoding="utf-8")
    (ace_run / "..monitor-start-xyz.lock").write_text("locked", encoding="utf-8")
    (ace_run / "202601" / "02").mkdir(parents=True)

    skipped = _tick(lane, chop, now=t0 + timedelta(seconds=10))
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


def test_orphan_agent_scope_reap_keeps_the_always_trigger() -> None:
    """Process death leaves no fs event; the scope reaper stays unguarded."""
    chop = _default_chop("checks", "orphan_agent_scope_reap")
    assert chop.script == "sase_job_orphan_agent_scope_reap"
    assert chop.trigger == {"provider": "always"}
    assert chop.timeout == 120


def test_waits_lane_holds_only_bead_claim_checks_and_epic_launch_flush() -> None:
    """``wait_checks`` moved to ``agent_waits``; ``sidecar_auto_sync`` to ``sidecar_sync``."""
    cfg = load_axe_config()
    assert sorted(c.name for c in cfg.lumberjacks["waits"].chops) == [
        "bead_claim_checks",
        "epic_launch_flush",
    ]
    epic_launch_flush = _default_chop("waits", "epic_launch_flush")
    assert epic_launch_flush.trigger == {"provider": "always"}
    assert epic_launch_flush.run_every == 30


def test_shipped_lane_split_config() -> None:
    """Living contract: ``agent_waits`` = wait_checks @ 2s; ``sidecar_sync`` = sidecar @ 30s."""
    cfg = load_axe_config()
    agent_waits = cfg.lumberjacks["agent_waits"]
    assert agent_waits.interval == 2
    assert [c.name for c in agent_waits.chops] == ["wait_checks"]
    wait_checks = _default_chop("agent_waits", "wait_checks")
    assert wait_checks.trigger.get("provider") == "fs"
    assert wait_checks.trigger.get("max_quiet") == "120s"

    sidecar_sync = cfg.lumberjacks["sidecar_sync"]
    assert sidecar_sync.interval == 30
    assert [c.name for c in sidecar_sync.chops] == ["sidecar_auto_sync"]
    sync_chop = _default_chop("sidecar_sync", "sidecar_auto_sync")
    assert sync_chop.trigger == {"provider": "always"}
    assert sync_chop.run_every is None
    assert sync_chop.timeout == 120


def test_runner_ready_poll_interval_is_half_second() -> None:
    """The parked runner stats ``ready.json`` every 0.5 s; fallback cadence is unchanged."""
    from sase.axe import run_agent_wait  # noqa: PLC0415

    assert run_agent_wait._WAIT_READY_POLL_INTERVAL == 0.5
    assert run_agent_wait._WAIT_DEPENDENCY_FALLBACK_INTERVAL == 60.0


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


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_patches", return_value=[])
def test_idle_agent_waits_tick_spawns_nothing_once_warmed(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
) -> None:
    """An idle ``agent_waits`` tick spawns nothing once the pulse checkpoint warms up."""
    axe_cfg = load_axe_config()
    wait_chops = list(axe_cfg.lumberjacks["agent_waits"].chops)
    assert [c.name for c in wait_chops] == ["wait_checks"]

    config = LumberjackConfig(
        name="agent_waits",
        description="Wait lane fixture",
        interval=2,
        chops=wait_chops,
    )
    axe_config = AxeConfig(
        max_hook_runners=3, max_agent_runners=3, zombie_timeout_seconds=3600, query=""
    )
    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()

    lumberjack = Lumberjack("agent_waits", config, axe_config)

    lumberjack._run_tick()
    assert mock_run.call_count == len(wait_chops)

    mock_run.reset_mock()
    lumberjack._run_tick()
    assert mock_run.call_count == 0


def test_post_sync_pulse_fires_only_for_refreshed_beads_role(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only a refreshed beads-role sync touches the project completion pulse."""
    import sase.scripts.sase_chop_sidecar_auto_sync as sidecar_sync_chop  # noqa: PLC0415
    from sase.sdd._store_types import BEADS_SIDECAR_ROLE  # noqa: PLC0415
    from tests._axe_chop_sidecar_auto_sync_support import (  # noqa: PLC0415
        configure_sidecar_sync,
        make_project,
        make_runtime,
    )

    record = make_project(tmp_path, name="proj")
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[record],
        roles_by_project={"proj": (BEADS_SIDECAR_ROLE,)},
        hinted_by_project={"proj": (BEADS_SIDECAR_ROLE,)},
    )

    touched: list[str] = []
    monkeypatch.setattr(
        "sase.turns.settlement.touch_turn_refresh_pulse",
        lambda project: touched.append(project),
    )

    def refreshed_beads(*_a: object, **_k: object) -> MagicMock:
        return MagicMock(status="refreshed", skipped=False, clone_dir=None)

    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", refreshed_beads)
    monkeypatch.setattr(
        sidecar_sync_chop, "_publish_pending_goals_outboxes", lambda *a, **k: 0
    )
    sidecar_sync_chop._run(make_runtime(tmp_path))
    assert touched == ["proj"]

    touched.clear()

    def up_to_date_beads(*_a: object, **_k: object) -> MagicMock:
        return MagicMock(status="up_to_date", skipped=False, clone_dir=None)

    monkeypatch.setattr(
        sidecar_sync_chop, "sync_primary_sidecar_role", up_to_date_beads
    )
    sidecar_sync_chop._run(make_runtime(tmp_path))
    assert touched == []
