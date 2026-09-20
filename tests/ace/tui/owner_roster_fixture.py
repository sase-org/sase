"""On-disk production fixture for owner-roster presentation parity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path
import json
import os

from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_scan_facade import (
    rebuild_agent_artifact_index,
    replace_agent_artifact_index_dismissed_agents,
)


@dataclass(frozen=True)
class OwnerRosterFixture:
    """Hermetic SASE home with a modern family lifecycle on disk."""

    home: Path
    observations: dict[str, str]
    # Injected owner-side observations equivalent to the files on disk.
    answered_agents: tuple[str, ...] = ()
    plan_tiers: dict[str, str] | None = None


def write_owner_roster_fixture(
    root: Path, *, now: datetime | None = None
) -> OwnerRosterFixture:
    """Seed one shared on-disk lifecycle matching current persisted shape.

    ``now`` pins every persisted time (directory stamps, run starts, finish
    times) so a caller can render the fixture at a fixed clock.
    """
    home = root / ".sase"
    projects = home / "projects"
    project = projects / "proj"
    artifacts = project / "artifacts" / "ace-run"
    artifacts.mkdir(parents=True)
    now = now or datetime.now()
    pid = os.getpid()

    def ts(minutes: int) -> str:
        return (now - timedelta(minutes=minutes)).strftime("%Y%m%d%H%M%S")

    root_ts = ts(20)
    plan_ts = ts(18)
    code_ts = ts(16)
    monitor_ts = ts(14)
    gate_ts = ts(12)
    proc_ts = ts(10)
    pending_gate_ts = ts(8)
    done_root_ts = ts(40)
    done_member_ts = ts(38)
    dismissed_ts = ts(6)
    recycled_ts = ts(4)
    fresh_ts = ts(2)
    _write_project(project, pid=pid, timestamp=fresh_ts)
    _write_alive(artifacts / root_ts, "lane", family="lane", role="root", pid=pid)
    _write_plan_shell(artifacts / plan_ts, "lane--plan", family="lane")
    _write_alive(
        artifacts / code_ts,
        "lane--code",
        family="lane",
        role="code",
        pid=pid,
    )
    _write_monitor(
        artifacts / monitor_ts,
        "lane--mon",
        family="lane",
        finished_at=(now - timedelta(minutes=14)).timestamp(),
    )
    _write_gate(
        artifacts / gate_ts,
        "lane--gate",
        family="lane",
        pending=False,
        finished_at=(now - timedelta(minutes=12)).timestamp(),
    )
    _write_proc(artifacts / proc_ts, "lane--proc", family="lane")
    _write_gate(
        artifacts / pending_gate_ts,
        "lane--gate-pending",
        family="lane",
        pending=True,
    )
    _write_done(
        artifacts / done_root_ts,
        "settled",
        family="settled",
        finished_at=(now - timedelta(minutes=40)).timestamp(),
    )
    _write_done(
        artifacts / done_member_ts,
        "settled--code",
        family="settled",
        finished_at=(now - timedelta(minutes=38)).timestamp(),
        parent=done_root_ts,
    )
    _write_fact_families(artifacts, root, now=now, pid=pid, ts=ts)
    _write_dead(artifacts / dismissed_ts, "dismissed-old")
    _write_dead(artifacts / recycled_ts, "recycled")
    _write_alive(artifacts / fresh_ts, "fresh-launch", pid=pid)

    _sync_stopped_at(artifacts)
    index = home / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index, projects)
    replace_agent_artifact_index_dismissed_agents(
        index,
        [
            AgentCleanupIdentityWire(
                agent_type="run",
                cl_name="unknown",
                raw_suffix=dismissed_ts,
            )
        ],
    )
    observations = {
        "lane": "alive",
        "lane--plan": "dead",
        "lane--code": "alive",
        "lane--mon": "dead",
        "lane--gate": "dead",
        "lane--proc": "dead",
        "lane--gate-pending": "dead",
        "settled": "dead",
        "settled--code": "dead",
        "dismissed-old": "alive",
        "recycled": "identity_mismatch",
        "fresh-launch": "alive",
        **FACT_FAMILY_OBSERVATIONS,
    }
    return OwnerRosterFixture(
        home=home,
        observations=observations,
        answered_agents=("answering",),
        plan_tiers={"review-plan": "tale"},
    )


def _write_project(project: Path, *, pid: int, timestamp: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "proj.sase").write_text(
        "\n".join(
            [
                "NAME: proj",
                f"WORKSPACE_DIR: {project}",
                "PROJECT_STATE: enabled",
                "RUNNING:",
                f"  #1 | {pid} | ace(run)-fresh | proj | {timestamp} | PINNED",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_workflow_state(artifact: Path, name: str, *, pid: int, status: str) -> None:
    _write_json(
        artifact / "workflow_state.json",
        {
            "workflow_name": name,
            "status": status,
            "pid": pid,
            "appears_as_agent": True,
        },
    )


def _write_alive(
    artifact: Path,
    name: str,
    *,
    family: str | None = None,
    role: str | None = None,
    pid: int,
) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {
        "name": name,
        "run_started_at": _stamp_iso(artifact.name),
    }
    if "--" in name:
        meta["role_suffix"] = _role_suffix(name)
    if family:
        meta["agent_family"] = family
    if role:
        meta["agent_family_role"] = role
    _write_json(artifact / "agent_meta.json", meta)
    _write_json(artifact / "running.json", {"pid": pid})
    _write_workflow_state(artifact, name, pid=pid, status="running")


def _write_dead(artifact: Path, name: str) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    _write_json(artifact / "agent_meta.json", {"name": name})
    _write_json(artifact / "running.json", {"pid": 0})


def _write_plan_shell(artifact: Path, name: str, *, family: str) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    _write_json(
        artifact / "agent_meta.json",
        {
            "name": name,
            "agent_family": family,
            "agent_family_role": "gate",
            "role_suffix": _role_suffix(name),
            **_gate_meta("plan-gate", "pending", "PLAN REVIEW"),
        },
    )
    _write_json(artifact / "running.json", {"pid": 0})
    _write_workflow_state(artifact, name, pid=0, status="running")


def _write_monitor(
    artifact: Path, name: str, *, family: str, finished_at: float
) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    _write_json(
        artifact / "agent_meta.json",
        {
            "name": name,
            "agent_family": family,
            "agent_family_role": "monitor",
            "role_suffix": _role_suffix(name),
            "monitor_id": "mon-1",
            "monitor_state": "completed",
            "monitor_label": "watch build",
            "monitor_command": "just check",
        },
    )
    _write_json(
        artifact / "done.json",
        {"outcome": "completed", "name": name, "finished_at": finished_at},
    )


def _write_gate(
    artifact: Path,
    name: str,
    *,
    family: str,
    pending: bool,
    finished_at: float | None = None,
) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    _write_json(
        artifact / "agent_meta.json",
        {
            "name": name,
            "agent_family": family,
            "agent_family_role": "gate",
            "role_suffix": _role_suffix(name),
            **_gate_meta(name, "pending" if pending else "completed", "REVIEW"),
        },
    )
    if pending:
        _write_json(artifact / "running.json", {"pid": 0})
        _write_json(artifact / "pending_question.json", {})
        _write_workflow_state(artifact, name, pid=0, status="waiting")
    else:
        _write_json(
            artifact / "done.json",
            {
                "outcome": "completed",
                "name": name,
                "finished_at": finished_at or 1.0,
            },
        )


def _write_proc(artifact: Path, name: str, *, family: str) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    _write_json(
        artifact / "agent_meta.json",
        {
            "name": name,
            "agent_family": family,
            "agent_family_role": "proc",
            "role_suffix": _role_suffix(name),
            "proc_id": "proc-1",
        },
    )
    _write_json(
        artifact / "done.json",
        {
            "outcome": "completed",
            "name": name,
            "finished_at": datetime.fromisoformat(
                _stamp_iso(artifact.name)
            ).timestamp(),
        },
    )


def _write_done(
    artifact: Path,
    name: str,
    *,
    family: str,
    finished_at: float,
    parent: str | None = None,
) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {"name": name, "agent_family": family}
    if parent:
        meta["parent_timestamp"] = parent
    _write_json(artifact / "agent_meta.json", meta)
    _write_json(
        artifact / "done.json",
        {
            "outcome": "completed",
            "name": name,
            "finished_at": finished_at,
        },
    )


FACT_FAMILY_OBSERVATIONS = {
    "tale-fam": "dead",
    "tale-fam--plan": "dead",
    "tale-fam--code": "dead",
    "epic-fam": "dead",
    "epic-fam--plan": "dead",
    "epic-fam--epic": "dead",
    "active-fam": "alive",
    "active-fam--plan": "dead",
    "active-fam--code": "alive",
    "wait-fam": "alive",
    "review-plan": "alive",
    "answering": "alive",
    "asker": "dead",
    "asker--ask": "dead",
    "asker--code": "dead",
    "chain--plan": "dead",
    "chain--mon": "dead",
    "chain--1": "dead",
}


def _stamp_iso(stamp: str) -> str:
    """Directory stamp as an aware ISO time (the catalog reads stamps as UTC)."""
    return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC).isoformat()


def _role_suffix(name: str) -> str:
    return "--" + name.rsplit("--", 1)[1]


def _sync_stopped_at(artifacts: Path) -> None:
    """Persist ``stopped_at`` beside every ``done.json`` like a real runner."""
    for done_path in artifacts.glob("*/done.json"):
        meta_path = done_path.parent / "agent_meta.json"
        if not meta_path.exists():
            continue
        finished_at = json.loads(done_path.read_text(encoding="utf-8"))["finished_at"]
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["stopped_at"] = datetime.fromtimestamp(finished_at, tz=UTC).isoformat()
        _write_json(meta_path, meta)


def _gate_meta(gate_id: str, state: str, label: str) -> dict[str, object]:
    """Persisted flat ``gate_*`` keys; the scanner folds them into ``family_shell``."""
    return {
        "gate_id": gate_id,
        "gate_kind": "approval",
        "gate_state": state,
        "gate_label": label,
        "gate_accent": "blue",
        "gate_start_status": label if state == "pending" else None,
        "gate_stop_status": None if state == "pending" else "DONE",
    }


def _iso(now: datetime, minutes: int) -> str:
    return (now - timedelta(minutes=minutes)).astimezone().isoformat()


def _write_fact_families(
    artifacts: Path,
    root: Path,
    *,
    now: datetime,
    pid: int,
    ts: Callable[[int], str],
) -> None:
    """Plan-chain, active, waiting, pending-review, and answered families."""
    stamp = ts

    def member(
        ts_value: str,
        name: str,
        *,
        family: str,
        role: str,
        parent: str | None,
        done: bool = True,
        alive: bool = False,
        extra: dict[str, object] | None = None,
    ) -> None:
        artifact = artifacts / ts_value
        artifact.mkdir(parents=True, exist_ok=True)
        meta: dict[str, object] = {
            "name": name,
            "agent_family": family,
            "agent_family_role": role,
            "role_suffix": "--" + name.rsplit("--", 1)[1],
            "run_started_at": _stamp_iso(ts_value),
        }
        if parent:
            meta["parent_timestamp"] = parent
            meta["plan_chain_parent_timestamp"] = parent
        meta.update(extra or {})
        _write_json(artifact / "agent_meta.json", meta)
        if done:
            _write_json(
                artifact / "done.json",
                {
                    "outcome": "completed",
                    "name": name,
                    "finished_at": (now - timedelta(minutes=30)).timestamp(),
                },
            )
        if alive:
            _write_json(artifact / "running.json", {"pid": pid})
            _write_workflow_state(artifact, name, pid=pid, status="running")

    def family_root(
        ts_value: str,
        name: str,
        *,
        action: str,
        done: bool,
        alive: bool = False,
    ) -> None:
        artifact = artifacts / ts_value
        artifact.mkdir(parents=True, exist_ok=True)
        _write_json(
            artifact / "agent_meta.json",
            {
                "name": name,
                "agent_family": name,
                "agent_family_role": "root",
                "plan": True,
                "plan_chain_root": True,
                "plan_approved": True,
                "plan_action": action,
                "plan_submitted_at": [_iso(now, 60)],
                "tribe": "plans",
            },
        )
        if done:
            _write_json(
                artifact / "done.json",
                {
                    "outcome": "completed",
                    "name": name,
                    "finished_at": (now - timedelta(minutes=31)).timestamp(),
                },
            )
        if alive:
            _write_json(artifact / "running.json", {"pid": pid})
            _write_workflow_state(artifact, name, pid=pid, status="running")

    def plan_shell(ts_value: str, name: str, *, family: str, parent: str) -> None:
        member(
            ts_value,
            name,
            family=family,
            role="gate",
            parent=parent,
            extra=_gate_meta(f"{family}-gate", "completed", "PLAN"),
        )

    # 0n: tale plan chain, settled.
    t_root, t_plan, t_code = stamp(90), stamp(89), stamp(88)
    family_root(t_root, "tale-fam", action="tale", done=True)
    plan_shell(t_plan, "tale-fam--plan", family="tale-fam", parent=t_root)
    member(t_code, "tale-fam--code", family="tale-fam", role="code", parent=t_root)
    # 0k: epic plan chain, settled.
    e_root, e_plan, e_epic = stamp(87), stamp(86), stamp(85)
    family_root(e_root, "epic-fam", action="epic", done=True)
    plan_shell(e_plan, "epic-fam--plan", family="epic-fam", parent=e_root)
    member(e_epic, "epic-fam--epic", family="epic-fam", role="epic", parent=e_root)
    # Active family whose coder is still running.
    a_root, a_plan, a_code = stamp(84), stamp(83), stamp(82)
    family_root(a_root, "active-fam", action="tale", done=False, alive=True)
    plan_shell(a_plan, "active-fam--plan", family="active-fam", parent=a_root)
    member(
        a_code,
        "active-fam--code",
        family="active-fam",
        role="code",
        parent=a_root,
        done=False,
        alive=True,
    )
    # Waiting family root.
    w_root = artifacts / stamp(81)
    _write_alive(w_root, "wait-fam", family="wait-fam", role="root", pid=pid)
    _write_json(w_root / "waiting.json", {"waiting_for": ["tale-fam"]})
    # Pending review: submitted, unapproved plan with a tier file.
    review = artifacts / stamp(80)
    plan_file = root / "review_plan.md"
    plan_file.write_text("---\ntier: tale\n---\n# Review\n", encoding="utf-8")
    _write_alive(review, "review-plan", pid=pid)
    _write_json(
        review / "agent_meta.json",
        {
            "name": "review-plan",
            "plan": True,
            "plan_path": str(plan_file),
            "plan_submitted_at": [_iso(now, 5)],
        },
    )
    # Answered question: marker plus sibling response file.
    answering = artifacts / stamp(79)
    _write_alive(answering, "answering", pid=pid)
    session = answering / "question_session"
    session.mkdir()
    _write_json(session / "question_request.json", {})
    _write_json(session / "question_response.json", {})
    _write_json(
        answering / "pending_question.json",
        {"request_path": str(session / "question_request.json")},
    )
    # Answered continuation: the asker child handed off to a later child.
    s_root, s_ask, s_code = stamp(78), stamp(77), stamp(76)
    family_root(s_root, "asker", action="tale", done=True)
    ask_session = artifacts / s_ask / "question_session"
    member(
        s_ask,
        "asker--ask",
        family="asker",
        role="plan",
        parent=s_root,
        extra={
            "questions_submitted_at": [_iso(now, 50)],
            "question_request_path": str(ask_session / "question_request.json"),
            "question_response_path": str(ask_session / "question_response.json"),
        },
    )
    ask_session.mkdir(parents=True, exist_ok=True)
    _write_json(ask_session / "question_request.json", {})
    _write_json(ask_session / "question_response.json", {})
    member(s_code, "asker--code", family="asker", role="code", parent=s_root)
    # Production shape of a completed plan-chain family: no separate root
    # record exists. The plan shell is its own family root (role "root", no
    # parent) and every later shell points back at it.
    c_plan, c_mon, c_one = stamp(75), stamp(74), stamp(73)
    member(c_plan, "chain--plan", family="chain", role="root", parent=None)
    member(
        c_mon,
        "chain--mon",
        family="chain",
        role="monitor",
        parent=c_plan,
        extra={
            "monitor_id": "chain-mon",
            "proc_id": "chain-mon",
            "monitor_state": "completed",
            "monitor_label": "just check",
            "monitor_command": "just check",
        },
    )
    member(c_one, "chain--1", family="chain", role="root", parent=c_plan)
    # A directory that only holds a side file is not an agent on either side.
    bare = artifacts / stamp(72)
    bare.mkdir(parents=True, exist_ok=True)
    (bare / "continuation_stage_diagnostics.jsonl").write_text("{}\n", encoding="utf-8")
