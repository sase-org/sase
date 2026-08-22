"""Headless ``sase agent kill`` stops live monitors instead of killpg."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.agent.names._common import NamedAgent
from sase.agent.running import kill_named_agent
from tests._kill_named_agent_dismiss_helpers import (
    patch_home as _patch_home,
    setup_nonhome_agent,
    successful_user_kill,
)


def _running_record(
    monitor_id: str, artifacts_dir: str, member: str, lane: str
) -> object:
    return type(
        "Monitor",
        (),
        {
            "monitor_id": monitor_id,
            "monitor_state": "running",
            "project_name": "proj",
            "artifacts_dir": artifacts_dir,
            "member_agent_name": member,
            "lane": lane,
        },
    )()


def _stopped_record(
    monitor_id: str, artifacts_dir: str, member: str, lane: str
) -> object:
    return type(
        "Monitor",
        (),
        {
            "monitor_id": monitor_id,
            "monitor_state": "stopped",
            "project_name": "proj",
            "artifacts_dir": artifacts_dir,
            "member_agent_name": member,
            "lane": lane,
        },
    )()


def test_kill_named_monitor_member_uses_canonical_stop(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = setup_nonhome_agent(tmp_path)
    found = NamedAgent(
        name="sase-ru.6--mon-1",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )
    running = _running_record(
        "0fmbm91hgytw", str(artifacts_dir), "sase-ru.6--mon-1", "sase-ru.6"
    )
    stopped = _stopped_record(
        "0fmbm91hgytw", str(artifacts_dir), "sase-ru.6--mon-1", "sase-ru.6"
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.monitor.cleanup.owned_live_monitors_for_name",
            return_value=[running],
        ),
        patch("sase.monitor.store.stop_monitor", return_value=stopped) as stop,
        patch("sase.monitor.store.read_monitor_marker", return_value=stopped),
        patch("sase.agent.running.request_user_kill") as kill_proc,
        patch("sase.running_field.release_workspace"),
    ):
        result = kill_named_agent("sase-ru.6--mon-1")

    assert result.success is True
    assert result.status == "stopped"
    stop.assert_called_once()
    kill_proc.assert_not_called()


def test_kill_named_family_stops_lane_monitor_without_killpg(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = setup_nonhome_agent(tmp_path)
    found = NamedAgent(
        name="sase-ru.6",
        artifacts_dir=str(artifacts_dir),
        is_done=True,
        outcome="monitored",
    )
    running = _running_record(
        "0fmbm91hgytw", str(artifacts_dir), "sase-ru.6--mon-1", "sase-ru.6"
    )
    stopped = _stopped_record(
        "0fmbm91hgytw", str(artifacts_dir), "sase-ru.6--mon-1", "sase-ru.6"
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.monitor.cleanup.owned_live_monitors_for_name",
            return_value=[running],
        ),
        patch("sase.monitor.store.stop_monitor", return_value=stopped) as stop,
        patch("sase.monitor.store.read_monitor_marker", return_value=stopped),
        patch("sase.agent.running.request_user_kill") as kill_proc,
        patch("sase.running_field.release_workspace"),
    ):
        result = kill_named_agent("sase-ru.6")

    assert result.success is True
    stop.assert_called_once()
    kill_proc.assert_not_called()


def test_kill_named_monitor_stop_failure_leaves_agent_visible(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = setup_nonhome_agent(tmp_path)
    found = NamedAgent(
        name="sase-ru.6--mon-1",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )
    running = _running_record(
        "0fmbm91hgytw", str(artifacts_dir), "sase-ru.6--mon-1", "sase-ru.6"
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.monitor.cleanup.owned_live_monitors_for_name",
            return_value=[running],
        ),
        patch("sase.monitor.store.stop_monitor", return_value=running),
        patch("sase.monitor.store.read_monitor_marker", return_value=running),
        patch("sase.agent.running.request_user_kill") as kill_proc,
        patch("sase.running_field.release_workspace") as release,
    ):
        result = kill_named_agent("sase-ru.6--mon-1")

    assert result.success is False
    assert result.reason == "monitor_stop_failed"
    kill_proc.assert_not_called()
    release.assert_not_called()


def test_mobile_exact_name_kill_inherits_monitor_stop(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = setup_nonhome_agent(tmp_path)
    found = NamedAgent(
        name="sase-ru.6--mon-1",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )
    running = _running_record(
        "0fmbm91hgytw", str(artifacts_dir), "sase-ru.6--mon-1", "sase-ru.6"
    )
    stopped = _stopped_record(
        "0fmbm91hgytw", str(artifacts_dir), "sase-ru.6--mon-1", "sase-ru.6"
    )
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta_path.write_text(
        '{"name": "sase-ru.6--mon-1", "agent_family_role": "monitor", '
        '"monitor_id": "0fmbm91hgytw"}',
        encoding="utf-8",
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch(
            "sase.monitor.cleanup.owned_live_monitors_for_name",
            return_value=[running],
        ),
        patch("sase.monitor.store.stop_monitor", return_value=stopped),
        patch("sase.monitor.store.read_monitor_marker", return_value=stopped),
        patch(
            "sase.agent.running.request_user_kill",
            return_value=successful_user_kill(),
        ) as kill_proc,
        patch("sase.running_field.release_workspace"),
    ):
        result = kill_named_agent("sase-ru.6--mon-1", exact_name=True)

    assert result.success is True
    kill_proc.assert_not_called()
