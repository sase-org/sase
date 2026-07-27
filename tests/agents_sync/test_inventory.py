from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import inventory, inventory_io, inventory_models
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.agents_sync.publication import reconcile_agent_hoods
from sase.agents_sync.v2_io import read_hood_snapshot
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_scan_wire import AgentArtifactRecordWire, WaitingMarkerWire


def _target(tmp_path: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir()
    return ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        tmp_path / "sidecar",
        "unused",
    )


def _record(artifact: Path, timestamp: str) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(artifact.parents[1]),
        project_file=str(artifact.parents[1] / "proj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact),
        timestamp=timestamp,
        has_done_marker=(artifact / "done.json").is_file(),
    )


def test_inventory_keeps_active_and_dismissed_states_but_rejects_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    artifacts = home / "projects" / "proj" / "artifacts" / "ace-run"
    local = artifacts / "20260723120000"
    imported = artifacts / "20260723120100"
    local.mkdir(parents=True)
    imported.mkdir()
    (local / "raw_xprompt.md").write_text("active prompt\n")
    (local / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "athena.foo",
                "artifact_agent_id": "stable-foo",
                "model": "gpt",
                "pid": 1,
                "workspace_dir": "/private",
            }
        )
    )
    (imported / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "zeus.foreign",
                "imported_from_machine": "zeus",
                "imported_digest": "a" * 64,
            }
        )
    )
    monkeypatch.setattr(
        inventory,
        "_indexed_records",
        lambda _target: (
            (
                _record(local, "20260723120000"),
                _record(imported, "20260723120100"),
            ),
            [],
        ),
    )
    monkeypatch.setattr(
        inventory,
        "_dismissed_records",
        lambda _target: (
            (
                {
                    "agent_name": "260723.foo.old",
                    "raw_suffix": "20260723110000",
                    "status": "DONE",
                    "start_time": "2026-07-23T11:00:00+00:00",
                    "stop_time": "2026-07-23T11:01:00+00:00",
                    "model": "gpt",
                },
                "dismissed.json",
            ),
        ),
    )
    sha = "b" * 40
    log = (
        f"{sha}\x001\x00subject\x00subject\n\n"
        "SASE_AGENT=alice.athena.foo\nSASE_MACHINE=athena\x00"
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
    result = inventory.build_project_hood_inventory(
        _target(tmp_path),
        AgentIdentitySnapshot(owner),
        git_runner=runner,
    )

    assert [run.local_name for run in result.runs] == ["foo", "foo.old"]
    active = next(run for run in result.runs if run.local_name == "foo")
    assert active.state == "active"
    assert active.prompt_bytes == b"active prompt\n"
    assert active.commits[0].sha == sha
    assert dict(active.metadata) == {"model": "gpt"}
    assert result.eligible_hoods() == ("foo",)


def test_portable_metadata_sanitizes_output_variables() -> None:
    metadata = dict(
        inventory_io.portable_metadata(
            {
                "model": "gpt",
                "output_variables": {
                    "z_path": "reports/z.md",
                    "bad-key": "drop",
                    "wrong_type": 7,
                    "a_status": "ready",
                    "too_large": "x" * 8_193,
                },
            }
        )
    )

    assert metadata == {
        "model": "gpt",
        "output_variables": {
            "a_status": "ready",
            "z_path": "reports/z.md",
        },
    }
    assert "output_variables" not in dict(
        inventory_io.portable_metadata({"output_variables": ["malformed"]})
    )


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    (
        (0, "git@github.com:acme/project.git\n", "git@github.com:acme/project.git"),
        (0, "\n", None),
        (1, "git@github.com:acme/project.git\n", None),
    ),
)
def test_primary_remote_resolution_is_optional(
    tmp_path: Path,
    returncode: int,
    stdout: str,
    expected: str | None,
) -> None:
    target = _target(tmp_path)

    def runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network
        assert cwd == target.primary_checkout
        assert args == ["config", "--get", "remote.origin.url"]
        assert op == "agents_sync.v2_primary_remote"
        return subprocess.CompletedProcess(args, returncode, stdout, "")

    assert inventory._primary_remote_url(target, runner) == expected


def test_primary_remote_resolution_swallows_git_failure(tmp_path: Path) -> None:
    target = _target(tmp_path)

    def runner(
        _cwd: Path,
        _args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        raise OSError("git unavailable")

    assert inventory._primary_remote_url(target, runner) is None


@pytest.mark.parametrize(
    "marker",
    (
        {"imported_source_owner": {"username": "alice", "machine_name": "athena"}},
        {"imported_snapshot_digest": "a" * 64},
        {"imported_transaction_key": "v2-" + "b" * 40},
    ),
)
def test_is_imported_accepts_current_bundle_provenance_markers(
    marker: dict[str, object],
) -> None:
    assert inventory_io.is_imported(marker, None)


def test_dismissed_inventory_rejects_legacy_step_output_import_marker(
    tmp_path: Path,
) -> None:
    run = inventory._run_from_dismissed(
        {
            "agent_name": "foo",
            "step_output": {"imported_source_run_id": "source-1"},
        },
        "dismissed.json",
        "proj",
        AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena")),
        {},
    )

    assert run is None


def test_inventory_relationships_skip_tribe_wait_targets(tmp_path: Path) -> None:
    identity = AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"))
    expected = (inventory_models.InventoryRelationship("wait", "foo.peer", "name"),)
    record = AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(tmp_path),
        project_file=str(tmp_path / "proj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / "artifact"),
        timestamp="20260723120000",
        waiting=WaitingMarkerWire(waiting_for=["@epic", "foo.peer"]),
    )

    assert inventory._artifact_relationships({}, record, identity) == expected
    assert (
        inventory._dismissed_relationships(
            {"waiting_for": ["@epic", "foo.peer"]},
            identity,
        )
        == expected
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
        _write_artifact(artifacts, f"20260723120{index:02d}", name)
        for index, name in enumerate(names, start=1)
    )
    monkeypatch.setattr(
        inventory,
        "_indexed_records",
        lambda _target: (
            tuple(
                _record(artifact, f"20260723120{index:02d}")
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
            return subprocess.CompletedProcess(args, 0, _git_log(names), "")
        return subprocess.CompletedProcess(args, 1, "", "unused")

    owner = AgentOwnerIdentity("alice", "athena")
    identity = AgentIdentitySnapshot(owner)
    target = _target(tmp_path)
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
                _git_log(("missing.agent", "missing.agent")),
                "",
            )
        return subprocess.CompletedProcess(args, 1, "", "unused")

    owner = AgentOwnerIdentity("alice", "athena")
    identity = AgentIdentitySnapshot(owner)
    target = _target(tmp_path)
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


def test_inventory_disambiguates_historical_runs_that_share_a_timestamp_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    artifacts = home / "projects" / "proj" / "artifacts" / "ace-run"
    timestamp = "20260723120000"
    artifact = _write_artifact(artifacts, timestamp, "foo.live")
    monkeypatch.setattr(
        inventory,
        "_indexed_records",
        lambda _target: ((_record(artifact, timestamp),), []),
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
                _git_log(("foo.live",)),
                "",
            )
        return subprocess.CompletedProcess(args, 1, "", "unused")

    owner = AgentOwnerIdentity("alice", "athena")
    identity = AgentIdentitySnapshot(owner)
    target = _target(tmp_path)
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
    artifact = _write_artifact(artifacts, "20260723120000", "research.g.image")
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
        lambda _target: ((_record(artifact, "20260723120000"),), []),
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
                _git_log(("research.g.image",)),
                "",
            )
        return subprocess.CompletedProcess(args, 1, "", "unused")

    owner = AgentOwnerIdentity("alice", "athena")
    identity = AgentIdentitySnapshot(owner)
    target = _target(tmp_path)
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
    good = _inventory_run("good.agent", "1", source_label="/artifacts/good")
    bad = _inventory_run("bad.agent", "2", source_label="/artifacts/bad")
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


def _write_artifact(artifacts: Path, timestamp: str, name: str) -> Path:
    artifact = artifacts / timestamp
    artifact.mkdir(parents=True)
    (artifact / "raw_xprompt.md").write_text(f"prompt for {name}\n")
    (artifact / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": name,
                "artifact_agent_id": timestamp,
                "model": "gpt",
            }
        )
    )
    (artifact / "done.json").write_text(
        json.dumps(
            {
                "name": name,
                "outcome": "completed",
                "finished_at": "2026-07-23T12:01:00+00:00",
            }
        )
    )
    return artifact


def _git_log(names: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for index, name in enumerate(names, start=1):
        sha = f"{index:040x}"
        chunks.append(
            f"{sha}\x00{index}\x00subject {index}\x00"
            f"subject {index}\n\nSASE_AGENT=alice.athena.{name}\x00"
        )
    return "".join(chunks)


def _inventory_run(
    name: str,
    suffix: str,
    *,
    source_label: str,
) -> inventory_models.InventoryRun:
    return inventory_models.InventoryRun(
        f"run-{suffix}",
        name,
        f"alice.athena.{name}",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:01:00+00:00",
        None,
        (),
        (CommitRecord("c" * 39 + suffix, name, 1),),
        None,
        None,
        None,
        None,
        (),
        f"2026072312000{suffix}",
        source_label=source_label,
    )
