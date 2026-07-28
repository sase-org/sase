"""Tests for the derived bead association index."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.bead.model import Issue, IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.bead_pages.associations import build_bead_association_index
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
)
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


def _store(plans: Path, beads: Path) -> SddStore:
    plans.mkdir(parents=True, exist_ok=True)
    return SddStore(
        "sidecar_repos",
        plans,
        plans,
        beads_dir=beads,
    )


def _record(
    tmp_path: Path,
    name: str,
    *,
    hidden: bool = False,
    done_hidden: bool = False,
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="sase",
        project_dir=str(tmp_path),
        project_file=str(tmp_path / "sase.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / name),
        timestamp="20260728120000",
        agent_meta=AgentMetaWire(name=name, hidden=hidden),
        done=DoneMarkerWire(name=name, hidden=done_hidden),
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


def test_builds_associations_with_one_store_read_and_history_walk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads = tmp_path / "beads-sidecar"
    beads.mkdir()
    with BeadProject.init(beads, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        root = project.create("Epic", IssueType.PLAN)
        phase = project.create("Phase", IssueType.PHASE, parent_id=root.id)
        grandchild = project.create(
            "Grandchild",
            IssueType.PHASE,
            parent_id=phase.id,
        )

    store_reads = 0
    original_list = BeadProject.list_issues

    def counted_list(self: BeadProject, *args: object, **kwargs: object) -> list[Issue]:
        nonlocal store_reads
        store_reads += 1
        return original_list(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(BeadProject, "list_issues", counted_list)
    tagged_sha = "b" * 40
    legacy_sha = "a" * 40
    git = _FakeGit(
        _history_entry(
            tagged_sha,
            20,
            "tagged subject",
            "tagged subject\n\n"
            f"SASE_BEAD=[{phase.id}][bead]\n"
            f"SASE_AGENT={phase.id}--code\n\n"
            f"[bead]: https://beads.example/{phase.id}",
        )
        + _history_entry(
            legacy_sha,
            10,
            f"legacy subject ({grandchild.id})",
            f"legacy subject ({grandchild.id})",
        )
        + _history_entry(
            "c" * 40,
            30,
            "ordinary parenthetical (not-a-bead)",
            "ordinary parenthetical (not-a-bead)",
        )
    )

    index = build_bead_association_index(
        _store(tmp_path / "plans", beads),
        primary_root=tmp_path,
        git_runner=git,
        link_resolver=_FakeLinks(),
        artifact_records=(
            _record(tmp_path, f"{phase.id}--review"),
            _record(tmp_path, f"{root.id}.land"),
            _record(tmp_path, f"{grandchild.id}--hidden", hidden=True),
            _record(tmp_path, f"{grandchild.id}--done-hidden", done_hidden=True),
        ),
        identity=_identity(),
    )

    assert store_reads == 1
    assert git.calls == 1
    assert set(index.by_bead) == {root.id, phase.id, grandchild.id}

    root_associations = index.for_bead(root.id)
    assert [(row.bead_id, row.label) for row in root_associations.agents] == [
        (phase.id, f"alice.athena.{phase.id}--code"),
        (phase.id, f"alice.athena.{phase.id}--review"),
        (root.id, f"alice.athena.{root.id}.land"),
    ]
    assert [
        (row.bead_id, row.label, row.subject) for row in root_associations.commits
    ] == [
        (grandchild.id, "aaaaaaa", f"legacy subject ({grandchild.id})"),
        (phase.id, "bbbbbbb", "tagged subject"),
    ]
    tagged_agent = next(
        row
        for row in root_associations.agents
        if row.label.endswith(f"{phase.id}--code")
    )
    assert tagged_agent.commit_count == 1
    assert tagged_agent.target == f"https://agents.example/{tagged_agent.label}"
    assert root_associations.commits[0].target == (
        f"https://commits.example/{legacy_sha}"
    )

    phase_associations = index.for_bead(phase.id)
    assert {row.bead_id for row in phase_associations.agents} == {phase.id}
    assert [row.sha for row in phase_associations.commits] == [tagged_sha]
    assert index.for_bead(grandchild.id).agents == ()
    assert [row.sha for row in index.for_bead(grandchild.id).commits] == [legacy_sha]
    with pytest.raises(TypeError):
        index.by_bead[root.id] = phase_associations  # type: ignore[index]


def test_tagged_unknown_bead_does_not_fall_back_to_legacy_subject(
    tmp_path: Path,
) -> None:
    issue = Issue("sase-known", "Known", issue_type=IssueType.PLAN)
    git = _FakeGit(
        _history_entry(
            "d" * 40,
            10,
            "subject (sase-known)",
            "subject (sase-known)\n\nSASE_BEAD=sase-missing",
        )
    )

    index = build_bead_association_index(
        _store(tmp_path / "plans", tmp_path / "missing"),
        primary_root=tmp_path,
        git_runner=git,
        link_resolver=_FakeLinks(),
        artifact_records=(),
        bead_issues=(issue,),
        identity=_identity(),
    )

    assert index.for_bead(issue.id).commits == ()


def test_parent_cycle_terminates_and_keeps_each_bead_direct_only(
    tmp_path: Path,
) -> None:
    left = Issue(
        "sase-cycle.1",
        "Left",
        issue_type=IssueType.PHASE,
        parent_id="sase-cycle.2",
    )
    right = Issue(
        "sase-cycle.2",
        "Right",
        issue_type=IssueType.PHASE,
        parent_id="sase-cycle.1",
    )

    index = build_bead_association_index(
        _store(tmp_path / "plans", tmp_path / "missing"),
        primary_root=tmp_path,
        git_runner=_FakeGit(""),
        link_resolver=_FakeLinks(),
        artifact_records=(
            _record(tmp_path, left.id),
            _record(tmp_path, right.id),
        ),
        bead_issues=(left, right),
        identity=_identity(),
    )

    assert [row.bead_id for row in index.for_bead(left.id).agents] == [left.id]
    assert [row.bead_id for row in index.for_bead(right.id).agents] == [right.id]


def test_source_failures_are_diagnostics_instead_of_exceptions(
    tmp_path: Path,
) -> None:
    index = build_bead_association_index(
        _store(tmp_path / "plans", tmp_path / "missing"),
        primary_root=tmp_path,
        git_runner=_FakeGit("", returncode=1),
        link_resolver=_FakeLinks(),
        artifact_records=(),
        identity=_identity(),
    )

    assert index.by_bead == {}
    assert index.diagnostics == (
        "could not read bead store: "
        f"No missing/ directory found at {tmp_path}. "
        "Run 'sase bead init' first.",
        "could not read git history: bad",
    )
