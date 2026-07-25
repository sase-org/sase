from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import inventory, inventory_models
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.agents_sync.publication import reconcile_agent_hoods
from sase.agents_sync.v2_io import read_hood_snapshot
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_scan_wire import AgentArtifactRecordWire


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
