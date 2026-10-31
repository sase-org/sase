"""Tests for the cached Agents-tab stranded-work projection."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.bead import stranded as stranded_module
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models import agent_stranded
from sase.bead.stranded import StrandedReport
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict


@pytest.fixture(autouse=True)
def _clear_stranded_cache():
    agent_stranded._STRANDED_REPORT_CACHE.clear()
    yield
    agent_stranded._STRANDED_REPORT_CACHE.clear()


def _snapshot(*verdicts: StrandedWorkVerdict) -> StrandedReport:
    report = StrandedWorkReport(
        verdicts=verdicts,
        stranded_ids=tuple(
            verdict.bead_id for verdict in verdicts if verdict.state == "stranded"
        ),
        blocked_ids=tuple(
            verdict.bead_id for verdict in verdicts if verdict.state == "blocked"
        ),
    )
    return StrandedReport(report=report, titles={}, generated_at=1.0)


def _verdict(bead_id: str, state: str, **fields: object) -> StrandedWorkVerdict:
    payload: dict[str, object] = {
        "bead_id": bead_id,
        "kind": "phase",
        "state": state,
        "blocked_by": ("sase-demo.1",) if state == "blocked" else (),
    }
    payload.update(fields)
    return StrandedWorkVerdict(**payload)  # type: ignore[arg-type]


def test_warm_reports_reuse_ttl_and_invalidate_on_store_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprints = ["store-1"]
    snapshots = iter(
        (
            _snapshot(_verdict("sase-demo.1", "stranded")),
            _snapshot(_verdict("sase-demo.1", "blocked")),
        )
    )
    loads: list[str] = []

    monkeypatch.setattr(
        agent_stranded, "_project_fingerprint", lambda _project: fingerprints[0]
    )

    def load(project_key: str) -> StrandedReport:
        loads.append(project_key)
        return next(snapshots)

    monkeypatch.setattr(stranded_module, "load_stranded_report", load)

    first = agent_stranded.warm_stranded_work_reports(("demo",))
    cached = agent_stranded.warm_stranded_work_reports(("demo",))
    fingerprints[0] = "store-2"
    refreshed = agent_stranded.warm_stranded_work_reports(("demo",))

    assert first == {"demo": frozenset({"sase-demo.1"})}
    assert cached == {}
    assert refreshed == {"demo": frozenset({"sase-demo.1"})}
    assert loads == ["demo", "demo"]


def test_stranded_report_ttl_expires_after_60_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(agent_stranded, "monotonic", lambda: now[0])
    agent_stranded._STRANDED_REPORT_CACHE.set("demo", _snapshot(), "store")

    assert agent_stranded._CACHE_TTL_SECONDS == 60.0
    assert agent_stranded.should_resolve_stranded_report("demo") is False
    now[0] += 59.999
    assert agent_stranded.should_resolve_stranded_report("demo") is False
    now[0] += 0.001
    assert agent_stranded.should_resolve_stranded_report("demo") is True


def test_forced_warmup_has_30_second_floor_and_resolve_bypasses_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    loads: list[str] = []
    monkeypatch.setattr(agent_stranded, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        agent_stranded, "_project_fingerprint", lambda _project: "store"
    )

    def load(project_key: str) -> StrandedReport:
        loads.append(project_key)
        return _snapshot(_verdict("sase-demo.1", "stranded"))

    monkeypatch.setattr(stranded_module, "load_stranded_report", load)

    agent_stranded.warm_stranded_work_reports(("demo",))
    now[0] = 129.999
    agent_stranded.warm_stranded_work_reports(("demo",), force=True)
    assert loads == ["demo"]

    now[0] = 130.0
    agent_stranded.warm_stranded_work_reports(("demo",), force=True)
    assert loads == ["demo", "demo"]

    now[0] = 131.0
    agent_stranded.warm_stranded_work_reports(
        ("demo",), force=True, force_immediate=True
    )
    assert loads == ["demo", "demo", "demo"]


def test_verdict_index_is_built_once_per_stored_report() -> None:
    first = _snapshot(_verdict("sase-demo.1", "stranded"))
    agent_stranded._STRANDED_REPORT_CACHE.set("demo", first, "store-1")

    index = agent_stranded._verdict_index("demo")
    assert index is agent_stranded._verdict_index("demo")
    assert index["sase-demo.1"].state == "stranded"

    second = _snapshot(_verdict("sase-demo.2", "blocked"))
    agent_stranded._STRANDED_REPORT_CACHE.set("demo", second, "store-2")
    refreshed_index = agent_stranded._verdict_index("demo")
    assert refreshed_index is not index
    assert tuple(refreshed_index) == ("sase-demo.2",)


def test_stranded_count_is_memoized_and_new_report_invalidates_it() -> None:
    class TrackedReport:
        def __init__(self, stranded_ids: tuple[str, ...]) -> None:
            self._stranded_ids = stranded_ids
            self.reads = 0
            self.verdicts = ()

        @property
        def stranded_ids(self) -> tuple[str, ...]:
            self.reads += 1
            return self._stranded_ids

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-agent",
        project_file="/tmp/demo/demo.sase",
        status="RUNNING",
        start_time=datetime(2026, 10, 1, 12, 0),
    )
    first_report = TrackedReport(("sase-demo.1",))
    first_snapshot = StrandedReport(
        report=first_report,  # type: ignore[arg-type]
        titles={},
        generated_at=1.0,
    )
    agent_stranded._STRANDED_REPORT_CACHE.set("demo", first_snapshot, "store-1")

    assert agent_stranded.stranded_count_for_agents((agent,)) == 1
    assert agent_stranded.stranded_count_for_agents((agent,)) == 1
    assert first_report.reads == 1

    second_report = TrackedReport(("sase-demo.1", "sase-demo.2"))
    second_snapshot = StrandedReport(
        report=second_report,  # type: ignore[arg-type]
        titles={},
        generated_at=2.0,
    )
    agent_stranded._STRANDED_REPORT_CACHE.set("demo", second_snapshot, "store-2")

    assert agent_stranded.stranded_count_for_agents((agent,)) == 2
    assert second_report.reads == 1


def test_agent_view_resolves_phase_task_and_waiter_states() -> None:
    phase = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-phase",
        project_file="/tmp/demo/demo.sase",
        status="DONE",
        start_time=datetime(2026, 10, 1, 12, 0),
        raw_suffix="phase",
        agent_name="sase-demo.1",
        phase_bead_id="sase-demo.1",
    )
    waiter = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-waiter",
        project_file="/tmp/demo/demo.sase",
        status="WAITING",
        start_time=datetime(2026, 10, 1, 12, 1),
        raw_suffix="waiter",
        agent_name="sase-demo.land",
        waiting_for_beads=["sase-demo.1"],
    )
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo",
        _snapshot(
            _verdict("sase-demo.1", "stranded"),
            _verdict("sase-demo", "blocked"),
        ),
        "store",
    )

    assert agent_stranded._agent_bead_id_for_stranded(phase) == "sase-demo.1"
    assert agent_stranded._stranded_verdict_for_agent(phase).state == "stranded"  # type: ignore[union-attr]
    assert agent_stranded.agent_stranded_view(waiter).waiting_on == (
        ("sase-demo.1", "stranded"),
    )
    assert agent_stranded.stranded_count_for_agents((phase, waiter)) == 1


def _clan_container(*, name: str, members: list[Agent] | None = None) -> Agent:
    container = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/demo/demo.sase",
        status="DONE",
        start_time=datetime(2026, 10, 1, 12, 0),
        raw_suffix="clan",
        agent_name=name,
        is_clan_container=True,
        agent_clan=name,
        agent_clan_generation="g1",
    )
    container.runtime_children = list(members or [])
    return container


def test_ancestor_clan_counts_report_leaves_without_loaded_members() -> None:
    container = _clan_container(name="sase-demo")
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo",
        _snapshot(
            _verdict(
                "sase-nested.1",
                "stranded",
                parent_id="sase-nested",
                blocked_by=(),
            ),
            _verdict(
                "sase-demo",
                "blocked",
                kind="epic",
                blocked_by=("sase-nested.1",),
            ),
        ),
        "store",
    )

    view = agent_stranded.agent_stranded_view(container)

    assert view.clan_stranded_ids == ("sase-nested.1",)
    assert view.clan_leaf_direct is False
    assert view.clan_stranded_member_keys == ()


def test_direct_phase_leaf_uses_leaf_style_and_counts_stranded_epic() -> None:
    leaf = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-phase",
        project_file="/tmp/demo/demo.sase",
        status="DONE",
        start_time=datetime(2026, 10, 1, 12, 0),
        raw_suffix="phase",
        agent_name="sase-demo.1",
        phase_bead_id="sase-demo.1",
        agent_clan="sase-demo",
        agent_clan_generation="g1",
    )
    container = _clan_container(name="sase-demo", members=[leaf])
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo",
        _snapshot(
            _verdict(
                "sase-demo.1",
                "stranded",
                parent_id="sase-demo",
                blocked_by=(),
            ),
            _verdict("sase-demo", "stranded", kind="epic", blocked_by=()),
        ),
        "store",
    )

    view = agent_stranded.agent_stranded_view(container)

    assert view.clan_stranded_ids == ("sase-demo", "sase-demo.1")
    assert view.clan_leaf_direct is True


def test_blocked_member_is_included_in_wave_fold_keys() -> None:
    blocked = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-blocked",
        project_file="/tmp/demo/demo.sase",
        status="WAITING",
        start_time=datetime(2026, 10, 1, 12, 0),
        raw_suffix="blocked",
        agent_name="sase-demo.2",
        phase_bead_id="sase-demo.2",
        agent_clan="sase-demo",
        agent_clan_generation="g1",
    )
    container = _clan_container(name="sase-demo", members=[blocked])
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo",
        _snapshot(_verdict("sase-demo.2", "blocked")),
        "store",
    )

    view = agent_stranded.agent_stranded_view(container)

    assert view.clan_stranded_member_keys == (
        f"{blocked.agent_type.value}:{blocked.cl_name}:"
        f"{blocked.raw_suffix}:{blocked.agent_name}",
    )


def test_waiting_for_agent_name_resolves_against_verdict_index() -> None:
    waiter = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-waiter",
        project_file="/tmp/demo/demo.sase",
        status="WAITING",
        start_time=datetime(2026, 10, 1, 12, 1),
        raw_suffix="waiter",
        agent_name="sase-demo.land",
        waiting_for=["sase-demo.1"],
    )
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo",
        _snapshot(_verdict("sase-demo.1", "stranded", blocked_by=())),
        "store",
    )

    view = agent_stranded.agent_stranded_view(waiter)

    assert view.waiting_on == ()
    assert view.waiting_on_agents == (("sase-demo.1", "stranded"),)
