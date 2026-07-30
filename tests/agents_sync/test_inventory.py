from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import inventory, inventory_io, inventory_models
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_scan_wire import AgentArtifactRecordWire, WaitingMarkerWire
from tests.agents_sync.inventory_fixtures import make_record, make_target


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
                make_record(local, "20260723120000"),
                make_record(imported, "20260723120100"),
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
        make_target(tmp_path),
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
    assert result.primary_repo_name == "primary"


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
                    "config": {
                        "z_enabled": True,
                        "a_limits": [1, 2.5, None],
                    },
                    "invalid_nested": {"": "drop"},
                    "too_large": "x" * 8_193,
                },
            }
        )
    )

    assert metadata == {
        "model": "gpt",
        "output_variables": {
            "a_status": "ready",
            "config": {
                "a_limits": [1, 2.5, None],
                "z_enabled": True,
            },
            "wrong_type": 7,
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
    target = make_target(tmp_path)

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
    target = make_target(tmp_path)

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
