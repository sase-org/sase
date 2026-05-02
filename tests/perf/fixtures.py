"""Synthetic-data fixture builders for the TUI performance harness.

Phase 1 of sdd/tales/202604/tui_perf_overhaul_1.md (bead sase-w.1). Generates
in-memory ``ChangeSpec`` and ``Agent`` lists at the sizes the perf runbook
expects (100 / 500 / 2,000 ChangeSpecs, 50 / 200 / 1,000 agents) plus
helpers for synthetic large-reply payloads (1 MB / 5 MB / 20 MB). Kept
disk-free so the bench can isolate UI-thread cost from disk I/O cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.models.agent import Agent, AgentType


CHANGESPEC_SIZES: tuple[int, ...] = (100, 500, 2000)
AGENT_SIZES: tuple[int, ...] = (50, 200, 1000)
LARGE_REPLY_SIZES_MB: tuple[int, ...] = (1, 5, 20)


def make_changespec(name: str, file_path: Path, *, status: str = "WIP") -> ChangeSpec:
    """Return a minimal :class:`ChangeSpec` suitable for harness fixtures."""
    return ChangeSpec(
        name=name,
        description=f"synthetic {name}",
        parent=None,
        cl=None,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path=str(file_path),
        line_number=1,
    )


def make_changespec_list(
    n: int, *, gp_file: Path, status_cycle: tuple[str, ...] = ("WIP", "Draft", "Ready")
) -> list[ChangeSpec]:
    """Return ``n`` synthetic ChangeSpecs cycling statuses for fold variety."""
    return [
        make_changespec(
            f"cs_{i:05d}",
            gp_file,
            status=status_cycle[i % len(status_cycle)],
        )
        for i in range(n)
    ]


def make_agent(idx: int, *, status: str = "DONE", project_file: str = "") -> Agent:
    """Return a minimal :class:`Agent` row.

    The harness only needs enough state for the AgentList renderer to lay
    out a row — full artifact dirs are out of scope (see Phase 5 for the
    incremental loader).
    """
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"cs_{idx % 100:05d}",
        project_file=project_file,
        status=status,
        start_time=None,
        raw_suffix=f"agent_{idx:05d}",
    )


def make_agent_list(n: int, *, project_file: str = "") -> list[Agent]:
    """Return ``n`` synthetic agents with a realistic status mix."""
    statuses = ("DONE", "RUNNING", "FAILED", "WAITING", "WAITING INPUT")
    return [
        make_agent(i, status=statuses[i % len(statuses)], project_file=project_file)
        for i in range(n)
    ]


def make_large_reply(mb: int) -> str:
    """Return a synthetic markdown reply of ``mb`` megabytes.

    Intentionally formed from short repeating lines so Rich's markdown lexer
    has plausible work to do on each row. Keeping each line under 80 chars
    keeps wrap behavior comparable across terminal widths.
    """
    line = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Sed do eiusmod tempor.\n"
    )
    target_bytes = mb * 1024 * 1024
    repeats = (target_bytes // len(line)) + 1
    return (line * repeats)[:target_bytes]


@dataclass(frozen=True)
class FixtureSet:
    """A bundle of fixtures pinned to one scenario size."""

    changespecs: list[ChangeSpec]
    agents: list[Agent]


def build_fixture(cs_count: int, agent_count: int, *, gp_file: Path) -> FixtureSet:
    return FixtureSet(
        changespecs=make_changespec_list(cs_count, gp_file=gp_file),
        agents=make_agent_list(agent_count, project_file=str(gp_file)),
    )
