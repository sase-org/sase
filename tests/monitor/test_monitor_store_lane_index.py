"""Lane-scoped monitor reads against a real artifact index."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    rebuild_agent_artifact_index,
)
from sase.core.agent_scan_wire import (
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.core.paths import sase_projects_dir
from sase.monitor import store

from tests.main.monitor_handler_helpers import make_monitor
from ._fixtures import make_starter_agent


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def test_lane_monitor_records_push_the_lane_into_the_index_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane_a_first = make_monitor(
        "proj", "20260812120000", "lane-a--mon", lane="lane-a", monitor_id="aaa111"
    )
    lane_a_second = make_monitor(
        "proj",
        "20260812130000",
        "lane-a--mon-0",
        lane="lane-a",
        monitor_id="aaa222",
        monitor_state="completed",
    )
    make_monitor(
        "proj", "20260812140000", "lane-b--mon", lane="lane-b", monitor_id="bbb111"
    )
    make_starter_agent(
        "proj", "20260812150000", "lane-a--code", agent_session="lane-a", model="m"
    )
    for index in range(5):
        make_starter_agent(
            "proj", f"2026081216{index:02d}00", f"bystander-{index}", model="m"
        )
    rebuild_agent_artifact_index(
        default_agent_artifact_index_path(),
        sase_projects_dir(),
        AgentArtifactScanOptionsWire(),
    )
    scans: list[AgentArtifactScanWire] = []
    real_query = store.query_agent_artifact_index

    def spying_query(*args: object, **kwargs: object) -> AgentArtifactScanWire:
        scan = real_query(*args, **kwargs)  # type: ignore[arg-type]
        scans.append(scan)
        return scan

    monkeypatch.setattr(store, "query_agent_artifact_index", spying_query)

    records = store.lane_monitor_records("proj", "lane-a")

    assert sorted(record.artifact_dir for record in records) == sorted(
        [lane_a_first, lane_a_second]
    )
    assert len(scans) == 1
    # Only the lane's own rows (two monitors and the lane's code agent) were
    # hydrated, not the bystanders or the other lane.
    assert scans[0].stats.record_json_decoded == 3
    assert store.lane_monitor_records("proj", "lane-missing") == []
