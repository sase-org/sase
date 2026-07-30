from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import inventory, inventory_models
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.publication import reconcile_agent_hoods
from sase.agents_sync.v2_io import read_hood_snapshot
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from tests.agents_sync.inventory_fixtures import (
    git_log,
    make_inventory_run,
    make_record,
    make_target,
    write_artifact,
)


def test_inventory_discovers_real_legacy_names_and_reconciles_unrelated_hood(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    artifacts = home / "projects" / "proj" / "artifacts" / "ace-run"
    names = (
        "4x--epic.f-0",
        "fi--code.f0",
        "fi--code.f0--plan",
        "fi--code.f0--code",
        "work.committer",
    )
    artifact_dirs = tuple(
        write_artifact(artifacts, f"20260723120{index:02d}", name)
        for index, name in enumerate(names, start=1)
    )
    monkeypatch.setattr(
        inventory,
        "_indexed_records",
        lambda _target: (
            tuple(
                make_record(artifact, f"20260723120{index:02d}")
                for index, artifact in enumerate(artifact_dirs, start=1)
            ),
            [],
        ),
    )
    monkeypatch.setattr(inventory, "_dismissed_records", lambda _target: ())

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        if args[0] == "log":
            return subprocess.CompletedProcess(args, 0, git_log(names), "")
        return subprocess.CompletedProcess(args, 1, "", "unused")

    owner = AgentOwnerIdentity("alice", "athena")
    identity = AgentIdentitySnapshot(owner)
    target = make_target(tmp_path)
    result = inventory.build_project_hood_inventory(
        target,
        identity,
        git_runner=runner,
    )

    assert {run.local_name for run in result.runs} == set(names)
    assert result.eligible_hoods() == ("4x", "fi", "work")
    assert result.diagnostics == ()

    repo = target.sidecar_path
    repo.mkdir()
    counts = reconcile_agent_hoods(target, repo, identity=identity, inventory=result)

    assert counts.hoods_published == 3
    assert counts.diagnostics == ()
    machine = repo / "users" / "alice" / "machines" / "athena"
    assert (machine / "hoods" / "4x" / "snapshot.json").is_file()
    assert (machine / "hoods" / "fi" / "snapshot.json").is_file()
    work = read_hood_snapshot(machine / "hoods" / "work" / "snapshot.json")
    assert {run.local_name for run in work.runs} == {"work.committer"}


def test_inventory_synthesizes_run_for_linked_commit_without_local_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(inventory, "_indexed_records", lambda _target: ((), []))
    monkeypatch.setattr(inventory, "_dismissed_records", lambda _target: ())

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        if args[0] == "log":
            return subprocess.CompletedProcess(
                args,
                0,
                git_log(("missing.agent", "missing.agent")),
                "",
            )
        return subprocess.CompletedProcess(args, 1, "", "unused")

    owner = AgentOwnerIdentity("alice", "athena")
    identity = AgentIdentitySnapshot(owner)
    target = make_target(tmp_path)
    result = inventory.build_project_hood_inventory(
        target,
        identity,
        git_runner=runner,
    )

    assert [run.local_name for run in result.runs] == ["missing.agent"]
    assert len(result.runs[0].commits) == 2
    assert result.runs[0].started_at == "1970-01-01T00:00:01+00:00"
    assert result.runs[0].finished_at == "1970-01-01T00:00:02+00:00"
    assert result.eligible_hoods() == ("missing",)
    assert result.diagnostics == (
        "primary commit history for alice.athena.missing.agent: synthesized "
        "publication record because no local artifact remains",
    )

    repo = target.sidecar_path
    repo.mkdir()
    counts = reconcile_agent_hoods(target, repo, identity=identity, inventory=result)

    assert counts.hoods_published == 1
    assert (repo / "agents" / "alice.athena.missing.agent" / "README.md").is_file()


def test_inventory_diagnoses_unrepresentable_family_history_without_phantom_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(inventory, "_indexed_records", lambda _target: ((), []))
    monkeypatch.setattr(inventory, "_dismissed_records", lambda _target: ())
    sha = "c" * 40
    log = (
        f"{sha}\x001\x00family lane\x00family lane\n\n"
        "SASE_AGENT=[alice.athena.crew][2]\n\n"
        "[2]: https://github.com/acme/project--agents/blob/main/"
        "families/alice.athena.crew.md\x00"
    )

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        if args[0] == "log":
            return subprocess.CompletedProcess(args, 0, log, "")
        return subprocess.CompletedProcess(args, 1, "", "unused")

    owner = AgentOwnerIdentity("alice", "athena")
    identity = AgentIdentitySnapshot(owner)
    target = make_target(tmp_path)
    result = inventory.build_project_hood_inventory(
        target,
        identity,
        git_runner=runner,
    )

    assert result.runs == ()
    assert result.eligible_hoods() == ()
    assert result.lane_commits == (
        inventory_models.InventoryLaneCommitHistory(
            "crew",
            True,
            (CommitRecord(sha, "family lane", 1),),
        ),
    )
    assert result.diagnostics == (
        "primary commit history for family lane alice.athena.crew: retained "
        "1 commit(s), but no family member run remains and v2 family containers "
        "require at least one member",
    )


def test_inventory_preserves_legacy_member_attribution_beside_family_lane_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    artifacts = home / "projects" / "proj" / "artifacts" / "ace-run"
    artifact = write_artifact(artifacts, "20260723120000", "crew--code")
    monkeypatch.setattr(
        inventory,
        "_indexed_records",
        lambda _target: ((make_record(artifact, "20260723120000"),), []),
    )
    monkeypatch.setattr(inventory, "_dismissed_records", lambda _target: ())
    legacy_sha = "d" * 40
    lane_sha = "e" * 40
    log = "".join(
        (
            f"{legacy_sha}\x001\x00legacy member\x00legacy member\n\n"
            "SASE_AGENT=alice.athena.crew--code\x00",
            f"{lane_sha}\x002\x00family lane\x00family lane\n\n"
            "SASE_AGENT=[alice.athena.crew][2]\n\n"
            "[2]: https://github.com/acme/project--agents/blob/main/"
            "families/alice.athena.crew.md\x00",
        )
    )

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        if args[0] == "log":
            return subprocess.CompletedProcess(args, 0, log, "")
        return subprocess.CompletedProcess(args, 1, "", "unused")

    owner = AgentOwnerIdentity("alice", "athena")
    identity = AgentIdentitySnapshot(owner)
    target = make_target(tmp_path)
    result = inventory.build_project_hood_inventory(
        target,
        identity,
        git_runner=runner,
    )

    assert [run.local_name for run in result.runs] == ["crew--code"]
    assert result.runs[0].commits == (CommitRecord(legacy_sha, "legacy member", 1),)

    repo = target.sidecar_path
    repo.mkdir()
    reconcile_agent_hoods(target, repo, identity=identity, inventory=result)
    snapshot = read_hood_snapshot(
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "crew"
        / "snapshot.json"
    )

    assert snapshot.runs[0].commits == (CommitRecord(legacy_sha, "legacy member", 1),)
    assert snapshot.containers[0].commits == (CommitRecord(lane_sha, "family lane", 2),)
    assert {run.local_name for run in snapshot.runs} == {"crew--code"}


def test_inventory_disambiguates_historical_runs_that_share_a_timestamp_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    artifacts = home / "projects" / "proj" / "artifacts" / "ace-run"
    timestamp = "20260723120000"
    artifact = write_artifact(artifacts, timestamp, "foo.live")
    monkeypatch.setattr(
        inventory,
        "_indexed_records",
        lambda _target: ((make_record(artifact, timestamp),), []),
    )
    monkeypatch.setattr(
        inventory,
        "_dismissed_records",
        lambda _target: (
            (
                {
                    "agent_name": "foo.dismissed",
                    "raw_suffix": timestamp,
                    "status": "DONE",
                },
                "dismissed.json",
            ),
        ),
    )

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        if args[0] == "log":
            return subprocess.CompletedProcess(
                args,
                0,
                git_log(("foo.live",)),
                "",
            )
        return subprocess.CompletedProcess(args, 1, "", "unused")

    owner = AgentOwnerIdentity("alice", "athena")
    identity = AgentIdentitySnapshot(owner)
    target = make_target(tmp_path)
    result = inventory.build_project_hood_inventory(
        target,
        identity,
        git_runner=runner,
    )

    assert {run.local_name for run in result.runs} == {
        "foo.dismissed",
        "foo.live",
    }
    assert len({run.source_run_id for run in result.runs}) == 2
    assert any(
        "was shared by 2 records and was deterministically disambiguated" in diagnostic
        for diagnostic in result.diagnostics
    )

    repo = target.sidecar_path
    repo.mkdir()
    counts = reconcile_agent_hoods(target, repo, identity=identity, inventory=result)

    assert counts.hoods_published == 1
    snapshot = read_hood_snapshot(
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "foo"
        / "snapshot.json"
    )
    assert len({run.source_run_id for run in snapshot.runs}) == 2


def test_inventory_diagnoses_and_drops_stale_solo_family_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    artifacts = home / "projects" / "proj" / "artifacts" / "ace-run"
    artifact = write_artifact(artifacts, "20260723120000", "research.g.image")
    (artifact / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "research.g.image",
                "artifact_agent_id": "20260723120000",
                "agent_family": "research.g.final",
                "model": "gpt",
            }
        )
    )
    monkeypatch.setattr(
        inventory,
        "_indexed_records",
        lambda _target: ((make_record(artifact, "20260723120000"),), []),
    )
    monkeypatch.setattr(inventory, "_dismissed_records", lambda _target: ())

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        if args[0] == "log":
            return subprocess.CompletedProcess(
                args,
                0,
                git_log(("research.g.image",)),
                "",
            )
        return subprocess.CompletedProcess(args, 1, "", "unused")

    owner = AgentOwnerIdentity("alice", "athena")
    identity = AgentIdentitySnapshot(owner)
    target = make_target(tmp_path)
    result = inventory.build_project_hood_inventory(
        target,
        identity,
        git_runner=runner,
    )

    run = result.runs[0]
    assert run.family_name is None
    assert "agent_family" not in dict(run.metadata)
    assert any(
        "historical agent_family 'research.g.final' disagrees with canonical name "
        "'research.g.image'" in diagnostic
        for diagnostic in result.diagnostics
    )

    repo = target.sidecar_path
    repo.mkdir()
    counts = reconcile_agent_hoods(target, repo, identity=identity, inventory=result)

    assert counts.hoods_published == 1
    snapshot = read_hood_snapshot(
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "research"
        / "snapshot.json"
    )
    assert snapshot.containers == ()


def test_inventory_selection_excludes_and_diagnoses_classifier_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    good = make_inventory_run("good.agent", "1", source_label="/artifacts/good")
    bad = make_inventory_run("bad.agent", "2", source_label="/artifacts/bad")
    hoods = inventory_models.ProjectHoodInventory(owner, "proj", (good, bad))

    def local_hood(name: str) -> str:
        if name == "bad.agent":
            raise RuntimeError("bad local hood")
        return "good"

    monkeypatch.setattr(inventory_models, "agent_local_hood", local_hood)

    assert hoods.eligible_hoods() == ("good",)
    assert hoods.diagnostics == (
        "/artifacts/bad: excluded from agent hood inventory: bad local hood",
    )

    runs = inventory_models.ProjectHoodInventory(owner, "proj", (good, bad))

    def name_in_hood(name: str, hood: str) -> bool:
        if name == "bad.agent":
            raise RuntimeError("bad hood membership")
        return hood == "good"

    monkeypatch.setattr(inventory_models, "agent_name_in_hood", name_in_hood)

    assert runs.hood_runs("good") == (good,)
    assert runs.diagnostics == (
        "/artifacts/bad: excluded from agent hood inventory: bad hood membership",
    )
