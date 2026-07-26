from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess

import pytest

from sase.ace import dismissed_agents
from sase.ace import dismissed_agents_bundles
from sase.ace.tui.models._loaders import _done_loaders
from sase.ace.tui.models.agent_types import AgentType
from sase.agents_sync import inventory
from sase.agents_sync import v2_importer
from sase.agents_sync import v2_import_storage
from sase.agents_sync import v2_import_transactions
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication import reconcile_agent_hoods
from sase.agents_sync.v2_import_package import discover_agent_imports
from sase.core.agent_group_archive_wire import saved_agent_group_from_dict
from sase.core.agent_identity_facade import AgentIdentitySnapshot

from tests.agents_sync.v2_importer_fixtures import (
    LOCAL_OWNER,
    PROJECT,
    SOURCE_OWNER,
    isolate_local_state,
    published_package,
)


def test_family_import_recovers_as_one_visible_idempotent_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = published_package(tmp_path)
    artifact_root, groups, claims = isolate_local_state(
        tmp_path,
        target,
        monkeypatch,
    )
    identity = AgentIdentitySnapshot(LOCAL_OWNER)
    real_finalize = v2_import_transactions._finalize_transaction
    failures = 0

    def fail_first_finalize(
        target_arg: ProjectTarget,
        journal: dict[str, object],
    ) -> None:
        nonlocal failures
        failures += 1
        if failures == 1:
            raise OSError("injected finalize failure")
        real_finalize(target_arg, journal)

    monkeypatch.setattr(
        v2_import_transactions,
        "_finalize_transaction",
        fail_first_finalize,
    )
    interrupted = v2_importer.integrate_v2_hoods(
        target,
        (package,),
        identity=identity,
    )
    assert interrupted.hoods_quarantined == 1
    artifacts = sorted(artifact_root.glob("*"))
    assert len(artifacts) == 2
    assert all(
        _done_loaders._load_done_agent_for_dir(path, "ace-run", {}, {}) is None
        for path in artifacts
    )
    bundle_paths = sorted((tmp_path / "state" / "dismissed_bundles").rglob("*.json"))
    assert len(bundle_paths) == 2
    assert all(
        dismissed_agents_bundles.load_bundle_file(path) is None for path in bundle_paths
    )

    monkeypatch.setattr(v2_import_transactions, "_finalize_transaction", real_finalize)
    assert (
        v2_import_transactions.recover_v2_import_transactions(
            target,
            identity=identity,
        )
        == ()
    )
    _done_loaders._completed_import_transaction.cache_clear()
    loaded = [
        _done_loaders._load_done_agent_for_dir(path, "ace-run", {}, {})
        for path in artifacts
    ]
    assert all(agent is not None for agent in loaded)
    dismissed_agents_bundles._completed_import_transaction.cache_clear()
    assert all(
        dismissed_agents_bundles.load_bundle_file(path) is not None
        for path in bundle_paths
    )
    assert dismissed_agents.load_dismissed_agents() == {
        (AgentType.RUNNING, PROJECT.key, path.name) for path in artifacts
    }

    metas = [
        json.loads((artifact / "agent_meta.json").read_text()) for artifact in artifacts
    ]
    assert {meta["name"] for meta in metas} == {
        "bob.zeus.crew--plan",
        "bob.zeus.crew--code",
    }
    assert all("pid" not in meta and "workspace_dir" not in meta for meta in metas)
    active_done = next(
        json.loads((artifact / "done.json").read_text())
        for artifact in artifacts
        if json.loads((artifact / "agent_meta.json").read_text())[
            "historical_source_state"
        ]
        == "active"
    )
    assert active_done["outcome"] == "stopped"
    assert "pid" not in active_done and "workspace_num" not in active_done

    group_path = next(groups.glob("agents-sidecar-*.json"))
    group_data = json.loads(group_path.read_text())
    group = saved_agent_group_from_dict(group_data)
    assert group.source == "agents_sidecar"
    assert [ref.source_run_id for ref in group.agent_refs] == [
        "source-1",
        "source-2",
    ]
    assert all(ref.reasoning_effort == "high" for ref in group.agent_refs)
    assert [ref.agent_name for ref in group.agent_refs] == [
        "bob.zeus.crew--plan",
        "bob.zeus.crew--code",
    ]
    assert group.top_level_agent_count == 2
    assert group.canonical_global_family == "bob.zeus.crew"
    assert group.source_snapshot_digest == package.entry.digest
    assert any(row[0] == "claim" for row in claims)

    unchanged = v2_importer.integrate_v2_hoods(
        target,
        (package,),
        identity=identity,
    )
    assert unchanged.hoods_unchanged == 1
    assert len(list(artifact_root.glob("*"))) == 2
    assert len(list(groups.glob("agents-sidecar-*.json"))) == 1

    group_data["revived_at"] = "2026-07-24T13:00:00Z"
    group_data["times_revived"] = 2
    group_path.write_text(json.dumps(group_data), encoding="utf-8")
    refreshed_package = replace(
        package,
        entry=replace(package.entry, digest="f" * 64),
    )
    refreshed = v2_importer.integrate_v2_hoods(
        target,
        (refreshed_package,),
        identity=identity,
    )
    assert refreshed.hoods_refreshed == 1
    refreshed_group = saved_agent_group_from_dict(json.loads(group_path.read_text()))
    assert refreshed_group.revived_at == "2026-07-24T13:00:00Z"
    assert refreshed_group.times_revived == 2
    assert len(list(artifact_root.glob("*"))) == 2
    assert len(list(groups.glob("agents-sidecar-*.json"))) == 1


def test_v2_import_records_dismissed_agent_identities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = published_package(tmp_path)
    artifact_root, _groups, _claims = isolate_local_state(
        tmp_path,
        target,
        monkeypatch,
    )
    sync_calls: list[tuple[set[object], set[object]]] = []

    def sync_index(
        dismissed: object = None,
        *,
        added: object = None,
        **_kwargs: object,
    ) -> bool:
        sync_calls.append((set(dismissed or ()), set(added or ())))
        return True

    monkeypatch.setattr(
        v2_import_transactions,
        "sync_dismissed_agent_artifact_index",
        sync_index,
    )

    imported = v2_importer.integrate_v2_hoods(
        target,
        (package,),
        identity=AgentIdentitySnapshot(LOCAL_OWNER),
    )

    assert imported.hoods_imported == 1
    expected = {
        (AgentType.RUNNING, PROJECT.key, path.name)
        for path in sorted(artifact_root.glob("*"))
    }
    assert dismissed_agents.load_dismissed_agents() == expected
    assert sync_calls == [(expected, expected)]
    journal_paths = list(
        v2_import_storage.journals_dir(target.project_key).glob("*.json")
    )
    assert len(journal_paths) == 1
    journal = v2_import_storage.read_journal(journal_paths[0])
    assert {
        (row["agent_type"], row["cl_name"], row["raw_suffix"])
        for row in journal["dismissed_identities"]
    } == {("run", cl_name, raw_suffix) for _, cl_name, raw_suffix in expected}


def test_imported_bundles_are_not_republished(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = published_package(tmp_path)
    _artifact_root, _groups, _claims = isolate_local_state(
        tmp_path,
        target,
        monkeypatch,
    )
    identity = AgentIdentitySnapshot(LOCAL_OWNER)

    imported = v2_importer.integrate_v2_hoods(
        target,
        (package,),
        identity=identity,
    )
    bundle_rows = tuple(
        (
            json.loads(path.read_text()),
            str(path),
        )
        for path in sorted((tmp_path / "state" / "dismissed_bundles").rglob("*.json"))
    )

    assert imported.runs_imported == 2
    assert len(bundle_rows) == 2
    assert all(
        row["imported_source_owner"]
        == {
            "username": SOURCE_OWNER.username,
            "machine_name": SOURCE_OWNER.machine_name,
        }
        for row, _path in bundle_rows
    )
    assert all(
        row["imported_snapshot_digest"] == package.entry.digest
        for row, _path in bundle_rows
    )

    monkeypatch.setattr(inventory, "_indexed_records", lambda _target: ((), []))
    monkeypatch.setattr(
        inventory,
        "_dismissed_records",
        lambda _target: bundle_rows,
    )

    def empty_history(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        return subprocess.CompletedProcess(args, 0, "", "")

    republished = inventory.build_project_hood_inventory(
        target,
        identity,
        git_runner=empty_history,
    )

    assert republished.runs == ()

    republish_counts = reconcile_agent_hoods(
        target,
        target.sidecar_path,
        identity=identity,
        inventory=republished,
    )
    assert republish_counts.runs_published == 0
    rediscovery = discover_agent_imports(target.sidecar_path, PROJECT)
    second_import = v2_importer.integrate_v2_hoods(
        target,
        rediscovery.v2_packages,
        identity=identity,
    )
    assert second_import.runs_imported == 0
    assert second_import.hoods_unchanged == 1
    assert all(
        datetime.strptime(path.name, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        <= datetime.now(UTC)
        for path in (
            tmp_path / "state" / "projects" / "proj" / "artifacts" / "ace-run"
        ).glob("*")
    )
