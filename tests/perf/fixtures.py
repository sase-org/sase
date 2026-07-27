"""Synthetic-data fixture builders for the TUI performance harness.

Phase 1 of sdd/plans/202604/tui_perf_overhaul_1.md (bead sase-w.1). Generates
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

# View-hints scenario sizing. 100 KB matches the observed p99/max of real
# ``live_reply.md`` files, and five members is a plausible family width.
HINT_REPLY_SIZE_KB: int = 100
HINT_FAMILY_MEMBER_COUNT: int = 5


def make_changespec(name: str, file_path: Path, *, status: str = "WIP") -> ChangeSpec:
    """Return a minimal :class:`ChangeSpec` suitable for harness fixtures."""
    return ChangeSpec(
        name=name,
        description=f"synthetic {name}",
        parent=None,
        cl=None,
        status=status,
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


def make_hinted_reply(kb: int) -> str:
    """Return a synthetic reply whose file-path density matches real replies.

    Unlike :func:`make_large_reply`, this deliberately seeds paths the hint
    scanner recognizes (``FILE_PATH_RE``), so the ``view_hints`` scenarios
    measure a document with hints in it rather than a plain-prose wall.
    """
    block = (
        "Inspected src/sase/ace/tui/widgets/prompt_panel/_agent_display.py and\n"
        "tests/ace/tui/widgets/test_agent_display.py for the render path.\n"
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit sed do.\n"
        "Wrote the summary to ~/.sase/perf/tui_trace.jsonl for later diffing.\n"
        "Eiusmod tempor incididunt ut labore et dolore magna aliqua enim.\n"
    )
    target_bytes = kb * 1024
    repeats = (target_bytes // len(block)) + 1
    return (block * repeats)[:target_bytes]


def write_agent_artifacts(
    artifacts_root: Path,
    name: str,
    *,
    reply: str,
    prompt: str | None = None,
    xprompt: str | None = None,
) -> Path:
    """Materialize a minimal on-disk agent artifacts dir and return its path.

    The view-hints keypath reads ``raw_xprompt.md``, ``*_prompt.md``, and
    ``live_reply.md`` off disk, so these scenarios cannot use the disk-free
    agent rows the other benches share.
    """
    artifacts_dir = artifacts_root / name
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "raw_xprompt.md").write_text(
        xprompt or "#gh:sase Review src/sase/ace/tui/util/trace.py and report back.\n"
    )
    (artifacts_dir / f"{name}_prompt.md").write_text(
        prompt or "Review the hint render path in src/sase/ace/tui/widgets/.\n"
    )
    (artifacts_dir / "live_reply.md").write_text(reply)
    return artifacts_dir


def make_hint_agent(
    idx: int,
    *,
    artifacts_root: Path,
    project_file: str,
    reply_kb: int = HINT_REPLY_SIZE_KB,
    status: str = "RUNNING",
    parent_timestamp: str | None = None,
    agent_family_role: str | None = None,
) -> Agent:
    """Return one agent row backed by real artifact files on disk."""
    suffix = f"2026072712{idx:04d}"
    artifacts_dir = write_agent_artifacts(
        artifacts_root,
        f"hint_agent_{idx:03d}",
        reply=make_hinted_reply(reply_kb),
    )
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="hint_bench",
        project_file=project_file,
        status=status,
        start_time=None,
        raw_suffix=suffix,
        artifacts_dir=str(artifacts_dir),
        parent_timestamp=parent_timestamp,
        agent_family_role=agent_family_role,
    )


def make_hint_family_container(
    *,
    artifacts_root: Path,
    project_file: str,
    members: int = HINT_FAMILY_MEMBER_COUNT,
    reply_kb: int = HINT_REPLY_SIZE_KB,
) -> Agent:
    """Return a family-container row with ``members`` on-disk family members.

    The family hint path renders every member's reply, so this row is the
    scenario that exposes cost scaling with family width.
    """
    root = make_hint_agent(
        900,
        artifacts_root=artifacts_root,
        project_file=project_file,
        reply_kb=reply_kb,
        agent_family_role="root",
    )
    root.followup_agents = [
        make_hint_agent(
            901 + i,
            artifacts_root=artifacts_root,
            project_file=project_file,
            reply_kb=reply_kb,
            parent_timestamp=root.raw_suffix,
            agent_family_role="phase",
        )
        for i in range(members)
    ]
    return root


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
