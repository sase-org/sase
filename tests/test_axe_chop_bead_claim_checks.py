"""Stale waiting-agent bead claim reconciliation tests."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

import sase.scripts.sase_chop_bead_claim_checks as claim_checks
from sase.axe.chop_script_context import ChopScriptContext
from sase.bead.model import Issue, Status
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger


def _runtime(tmp_path: Path) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="bead_claim_checks",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="waits",
            state_dir=str(tmp_path),
            all_changespecs_file=str(tmp_path / "all.json"),
            filtered_changespecs_file=str(tmp_path / "filtered.json"),
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )


def _artifact(
    tmp_path: Path,
    *,
    name: str = "sase-1.1",
    bead_id: str = "sase-1.1",
    promoted: bool | None = False,
    timestamp: str = "20260724120000",
) -> claim_checks._ClaimArtifact:
    return claim_checks._ClaimArtifact(
        project_name="sase",
        agent_name=name,
        artifact_dir=tmp_path / timestamp,
        timestamp=timestamp,
        pid=123,
        stopped_at=None,
        bead_id=bead_id,
        bead_claim_promoted=promoted,
    )


def _claimed_issue(
    *,
    bead_id: str = "sase-1.1",
    assignee: str = "sase-1.1",
) -> Issue:
    return Issue(
        id=bead_id,
        title="Claimed phase",
        status=Status.CLAIMED,
        parent_id="sase-1",
        assignee=assignee,
    )


def test_dead_unpromoted_owner_is_released_after_bead_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = _artifact(tmp_path)
    events: list[str] = []
    scans = iter(([record], [record]))

    def scan(_root: Path) -> list[claim_checks._ClaimArtifact]:
        events.append("scan")
        return next(scans)

    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", scan)
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda _project: events.append("beads") or [_claimed_issue()],
    )

    released: list[tuple[str, str, str]] = []

    def release(*, project_name: str, bead_id: str, agent_name: str) -> bool:
        released.append((project_name, bead_id, agent_name))
        return True

    monkeypatch.setattr(claim_checks, "release_bead_claim_for_agent", release)

    result = claim_checks._run(_runtime(tmp_path))

    assert events == ["scan", "beads", "scan"]
    assert released == [("sase", "sase-1.1", "sase-1.1")]
    assert result.counters == {
        "projects_scanned": 1,
        "claims_examined": 1,
        "claims_released": 1,
    }


@pytest.mark.parametrize(
    ("promoted", "alive"),
    [(False, True), (True, False), (True, True), (None, False)],
)
def test_live_promoted_or_unreadable_owner_is_untouched_in_prepass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    promoted: bool | None,
    alive: bool,
) -> None:
    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: [_artifact(tmp_path, promoted=promoted)],
    )
    monkeypatch.setattr(
        claim_checks,
        "_claim_owner_is_alive",
        lambda _record: alive,
    )

    def unexpected_read(_project: str) -> list[Issue]:
        raise AssertionError("steady-state prepass opened a bead store")

    monkeypatch.setattr(claim_checks, "_read_claimed_issues", unexpected_read)

    result = claim_checks._run(_runtime(tmp_path))

    assert result.reason == "no_dead_unpromoted_agents"
    assert result.counters["projects_scanned"] == 0


def test_unresolvable_assignee_is_not_released(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dead = _artifact(tmp_path)
    scans = iter(([dead], [dead]))
    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: next(scans),
    )
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda _project: [_claimed_issue(assignee="missing-agent")],
    )
    monkeypatch.setattr(
        claim_checks,
        "release_bead_claim_for_agent",
        lambda **_kwargs: pytest.fail("unowned claim must not be released"),
    )

    result = claim_checks._run(_runtime(tmp_path))

    assert result.counters["claims_examined"] == 1
    assert result.counters["claims_released"] == 0


def test_empty_steady_state_never_reads_a_bead_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", lambda _root: [])
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda _project: pytest.fail("empty steady state opened a bead store"),
    )

    result = claim_checks._run(_runtime(tmp_path))

    assert result.reason == "no_dead_unpromoted_agents"
