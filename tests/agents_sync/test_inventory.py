from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import inventory
from sase.agents_sync.models import ProjectTarget
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
