"""Tests for the derived plan association index."""

from __future__ import annotations

from pathlib import Path
import subprocess

from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
    PlanPathMarkerWire,
)
from sase.sdd.associations import build_plan_association_index
from sase.sdd.store import SddStore


class _FakeGit:
    def __init__(self, output: str, *, returncode: int = 0) -> None:
        self.output = output
        self.returncode = returncode
        self.calls = 0

    def __call__(
        self,
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del cwd, network, op
        self.calls += 1
        assert args == ["log", "--format=%H%x00%ct%x00%s%x00%B%x00"]
        return subprocess.CompletedProcess(args, self.returncode, self.output, "bad")


class _FakeLinks:
    def agent_url(self, agent_name: str) -> str | None:
        return f"https://agents.example/{agent_name}"

    def commit_url(self, sha: str) -> str | None:
        return f"https://commits.example/{sha}"


def _store(root: Path) -> SddStore:
    root.mkdir(parents=True)
    return SddStore("sidecar_repos", root, root)


def _plan(
    root: Path,
    relative: str,
    *,
    tier: str,
    parent: str | None = None,
    legacy_parent: bool = False,
) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_field = f"parent: {parent}\n" if parent and legacy_parent else ""
    parent_bullet = (
        f"- **PARENT:**\n  [{parent}](https://example.test/{parent})\n"
        if parent and not legacy_parent
        else ""
    )
    path.write_text(
        f"---\ntier: {tier}\ntitle: Example\n{parent_field}---\n\n"
        f"{parent_bullet}\n# Plan\n",
        encoding="utf-8",
    )
    return path


def _record(
    tmp_path: Path,
    name: str,
    *,
    sdd_plan_path: str | None = None,
    plan_path: str | None = None,
    archived_plan_path: str | None = None,
    epic_plan_ref: str | None = None,
    hidden: bool = False,
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="sase",
        project_dir=str(tmp_path),
        project_file=str(tmp_path / "sase.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / name),
        timestamp="20260728120000",
        agent_meta=AgentMetaWire(
            name=name,
            sdd_plan_path=sdd_plan_path,
            plan_path=plan_path,
            epic_plan_ref=epic_plan_ref,
            hidden=hidden,
        ),
        done=DoneMarkerWire(name=name, plan_path=archived_plan_path),
        plan_path=PlanPathMarkerWire(plan_path=archived_plan_path),
    )


def _history_entry(
    sha: str,
    timestamp: int,
    subject: str,
    body: str,
) -> str:
    return f"{sha}\x00{timestamp}\x00{subject}\x00{body}\x00"


def _identity() -> AgentIdentitySnapshot:
    return AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"))


def test_builds_sorted_rendering_records_from_one_history_walk(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "plans"
    store = _store(plans)
    plan = _plan(plans, "202607/child.md", tier="tale")
    sha_late = "b" * 40
    sha_early = "a" * 40
    git = _FakeGit(
        _history_entry(
            sha_late,
            20,
            "later [subject]",
            "later\n\nSASE_PLAN=202607/child.md\nSASE_AGENT=worker.z",
        )
        + _history_entry(
            sha_early,
            10,
            "early subject",
            "early\n\nSASE_PLAN=[202607/child.md][plan]\n"
            "SASE_AGENT=worker.a\n\n[plan]: plans:202607/child.md",
        )
    )
    records = (
        _record(tmp_path, "reviewer", archived_plan_path=str(plan)),
        _record(tmp_path, "hidden", plan_path=str(plan), hidden=True),
    )

    index = build_plan_association_index(
        store,
        primary_root=tmp_path,
        git_runner=git,
        link_resolver=_FakeLinks(),
        artifact_records=records,
        identity=_identity(),
    )

    associations = index.for_plan("plans:202607/child.md")
    assert git.calls == 1
    assert [row.label for row in associations.agents] == [
        "alice.athena.reviewer",
        "alice.athena.worker.a",
        "alice.athena.worker.z",
    ]
    assert [row.label for row in associations.commits] == ["aaaaaaa", "bbbbbbb"]
    assert associations.commits[0].trailing_text == "— early subject"
    assert associations.commits[0].target == (f"https://commits.example/{sha_early}")
    assert associations.agents[0].target == (
        "https://agents.example/alice.athena.reviewer"
    )


def test_artifact_metadata_paths_collapse_to_one_plan_key(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    store = _store(plans)
    plan = _plan(plans, "202607/child.md", tier="tale")
    records = (
        _record(tmp_path, "sdd", sdd_plan_path="plans:202607/child.md"),
        _record(tmp_path, "legacy", plan_path="sdd/plans/202607/child.md"),
        _record(tmp_path, "archive", archived_plan_path=str(plan)),
        _record(
            tmp_path,
            "old-workspace",
            plan_path="/old/workspace/sdd/plans/202607/child.md",
        ),
        _record(tmp_path, "epic-ref", epic_plan_ref="202607/child.md"),
    )

    index = build_plan_association_index(
        store,
        primary_root=tmp_path,
        git_runner=_FakeGit(""),
        link_resolver=_FakeLinks(),
        artifact_records=records,
        identity=_identity(),
    )

    assert [row.label for row in index.for_plan("plans:202607/child.md").agents] == [
        "alice.athena.archive",
        "alice.athena.epic-ref",
        "alice.athena.legacy",
        "alice.athena.old-workspace",
        "alice.athena.sdd",
    ]


def test_epic_rollup_reads_bullets_and_legacy_parent_without_changing_tales(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "plans"
    store = _store(plans)
    epic = _plan(plans, "202607/epic.md", tier="epic")
    child = _plan(
        plans,
        "202607/child.md",
        tier="tale",
        parent="202607/epic.md",
    )
    grandchild = _plan(
        plans,
        "202607/grandchild.md",
        tier="tale",
        parent="plans:202607/child.md",
        legacy_parent=True,
    )
    records = (
        _record(tmp_path, "epic-agent", plan_path=str(epic)),
        _record(tmp_path, "child-agent", plan_path=str(child)),
        _record(tmp_path, "grandchild-agent", plan_path=str(grandchild)),
    )

    index = build_plan_association_index(
        store,
        primary_root=tmp_path,
        git_runner=_FakeGit(""),
        link_resolver=_FakeLinks(),
        artifact_records=records,
        identity=_identity(),
    )

    assert [row.label for row in index.for_plan("plans:202607/epic.md").agents] == [
        "alice.athena.child-agent",
        "alice.athena.epic-agent",
        "alice.athena.grandchild-agent",
    ]
    assert [row.label for row in index.for_plan("plans:202607/child.md").agents] == [
        "alice.athena.child-agent",
    ]


def test_epic_rollup_ignores_parent_cycles(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    store = _store(plans)
    epic = _plan(
        plans,
        "202607/epic.md",
        tier="epic",
        parent="202607/child.md",
    )
    child = _plan(
        plans,
        "202607/child.md",
        tier="tale",
        parent="202607/epic.md",
    )

    index = build_plan_association_index(
        store,
        primary_root=tmp_path,
        git_runner=_FakeGit(""),
        link_resolver=_FakeLinks(),
        artifact_records=(
            _record(tmp_path, "epic-agent", plan_path=str(epic)),
            _record(tmp_path, "child-agent", plan_path=str(child)),
        ),
        identity=_identity(),
    )

    assert [row.label for row in index.for_plan("plans:202607/epic.md").agents] == [
        "alice.athena.child-agent",
        "alice.athena.epic-agent",
    ]


def test_history_failure_keeps_artifact_results_and_reports_diagnostic(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "plans"
    store = _store(plans)
    plan = _plan(plans, "202607/child.md", tier="tale")

    index = build_plan_association_index(
        store,
        primary_root=tmp_path,
        git_runner=_FakeGit("", returncode=1),
        link_resolver=_FakeLinks(),
        artifact_records=(_record(tmp_path, "worker", plan_path=str(plan)),),
        identity=_identity(),
    )

    assert [row.label for row in index.for_plan("plans:202607/child.md").agents] == [
        "alice.athena.worker"
    ]
    assert index.diagnostics == ("could not read git history: bad",)
