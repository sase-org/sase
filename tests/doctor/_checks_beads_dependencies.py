"""Tests for dependency checks in doctor bead checks."""

from __future__ import annotations

from sase.bead.model import Dependency, Issue, Status
from sase.doctor import checks_beads
from tests.doctor._checks_beads_support import context, stub_agent_scan, stub_issues


def test_project_beads_warns_about_dangling_dependency_edges(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "sdd" / "beads").mkdir(parents=True)
    dependent = Issue(
        id="sase-1.2",
        title="Dependent phase",
        status=Status.OPEN,
        parent_id="sase-1",
        dependencies=[
            Dependency(
                issue_id="sase-1.2",
                depends_on_id="sase-1.9",
                created_at="20260725120000",
            ),
            Dependency(
                issue_id="sase-1.2",
                depends_on_id="sase-1.1",
                created_at="20260725120000",
            ),
        ],
    )
    present = Issue(
        id="sase-1.1",
        title="Present phase",
        status=Status.CLOSED,
        parent_id="sase-1",
    )
    stub_issues(monkeypatch, [dependent, present])
    stub_agent_scan(
        monkeypatch,
        tmp_path,
        agent_name="other-agent",
        bead_id="sase-9.9",
        agent_meta={},
        pid=None,
    )

    check = checks_beads._check_project_beads(context(tmp_path))

    assert check.status == "WARN"
    assert check.details == (
        "WARNING: dependency edges point at beads that no longer exist: "
        "sase-1.2 -> sase-1.9; recreate the missing bead or recreate the "
        "dependent without the edge",
    )


def test_project_beads_ignores_satisfied_dependency_edges(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "sdd" / "beads").mkdir(parents=True)
    stub_issues(
        monkeypatch,
        [
            Issue(
                id="sase-1.2",
                title="Dependent phase",
                status=Status.OPEN,
                parent_id="sase-1",
                dependencies=[
                    Dependency(
                        issue_id="sase-1.2",
                        depends_on_id="sase-1.1",
                        created_at="20260725120000",
                    )
                ],
            ),
            Issue(
                id="sase-1.1",
                title="Present phase",
                status=Status.CLOSED,
                parent_id="sase-1",
            ),
        ],
    )
    stub_agent_scan(
        monkeypatch,
        tmp_path,
        agent_name="other-agent",
        bead_id="sase-9.9",
        agent_meta={},
        pid=None,
    )

    assert checks_beads._check_project_beads(context(tmp_path)).status == "OK"
