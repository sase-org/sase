"""Shared object builders for axe collector tests."""

from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.axe.config import ChopConfig, LumberjackConfig
from sase.axe.chop_overrun import ChopOverrun
from sase.axe.state import ChopRunEntry, LumberjackMetrics, LumberjackStatus


class FakeAxeConfig:
    def __init__(self, lumberjacks: dict[str, LumberjackConfig]) -> None:
        self.lumberjacks = lumberjacks


def make_status(name: str, *, interval: int = 60) -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=123,
        started_at="2026-04-23T00:00:00",
        status="running",
        interval=interval,
    )


def make_metrics() -> LumberjackMetrics:
    return LumberjackMetrics(
        cycles_run=4,
        chops_executed=7,
        total_updates=2,
        errors_encountered=0,
    )


def make_bgcmd_info() -> BackgroundCommandInfo:
    return BackgroundCommandInfo(
        command="sleep 1",
        project="proj",
        workspace_num=1,
        workspace_dir="/tmp/ws",
        started_at="2026-04-23T00:00:00",
    )


def lumberjack_config(
    name: str, chop_names: list[str], *, interval: int = 60
) -> LumberjackConfig:
    return LumberjackConfig(
        name=name,
        description=f"{name} lane description\n\n{name} lane body",
        description_summary=f"{name} lane description",
        description_body=f"{name} lane body",
        interval=interval,
        chops=[
            ChopConfig(
                name=chop,
                description=f"{chop} desc\n\n{chop} body",
                description_summary=f"{chop} desc",
                description_body=f"{chop} body",
            )
            for chop in chop_names
        ],
    )


def make_run_entry(lumberjack: str, chop: str, run_id: str) -> ChopRunEntry:
    return ChopRunEntry(
        run_id=run_id,
        lumberjack_name=lumberjack,
        chop_name=chop,
        started_at="2026-05-11T10:00:00",
        finished_at="2026-05-11T10:00:01",
        duration_ms=1000,
        status="success",
        exit_code=0,
        output_bytes=10,
        output_log=f"{run_id}.log",
    )


def fast_overrun() -> ChopOverrun:
    return ChopOverrun(
        level="over",
        sampled_runs=1,
        over_runs=1,
        worst_ratio=1.5,
        worst_blocking_ms=90000,
        latest_ratio=1.5,
        run_ratios=(1.5,),
    )
