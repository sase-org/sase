from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess

import pytest

from sase.ace import dismissed_agents
from sase.ace import dismissed_agents_bundles
from sase.ace import dismissed_bundle_index
from sase.ace.tui.models._loaders import _done_loaders
from sase.agents_sync import inventory
from sase.agents_sync import v2_importer
from sase.agents_sync import v2_import_history
from sase.agents_sync import v2_import_planning
from sase.agents_sync import v2_import_rendering
from sase.agents_sync import v2_import_storage
from sase.agents_sync import v2_import_transactions
from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.v2_import_package import discover_agent_imports
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.core.agent_group_archive_wire import saved_agent_group_from_dict
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity


SOURCE_OWNER = AgentOwnerIdentity("bob", "zeus")
LOCAL_OWNER = AgentOwnerIdentity("alice", "athena")
PROJECT = V2ProjectIdentity("proj", "Project")


def _target(tmp_path: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir()
    return ProjectTarget(
        PROJECT.key,
        PROJECT.name,
        primary,
        (primary.resolve(),),
        tmp_path / "sidecar",
        "unused",
    )


def _run(
    name: str,
    suffix: str,
    *,
    state: str,
    chat: bytes | None,
    owner: AgentOwnerIdentity = SOURCE_OWNER,
) -> InventoryRun:
    finished_at = None if state == "active" else "2026-07-24T12:01:00+00:00"
    return InventoryRun(
        f"source-{suffix}",
        name,
        f"{owner.username}.{owner.machine_name}.{name}",
        state,
        "2026-07-24T12:00:00+00:00",
        finished_at,
        None,
        (
            ("agent_family", "crew"),
            ("agent_family_role", name.rsplit("--", 1)[-1]),
            ("llm_provider", "codex"),
            ("model", "gpt-test"),
            ("reasoning_effort", "high"),
            ("tribe", "backend"),
        ),
        (CommitRecord(suffix * 40, name, 1),),
        f"prompt {name}\n".encode(),
        chat,
        "crew",
        None,
        (),
        f"2026072412000{suffix}",
        b'[{"args":{},"name":"propose","tags":["rollover"]}]\n',
        (
            b'[{"file_name":"prompt_step_0.json","marker":'
            b'{"status":"completed","step_index":0}}]\n'
        ),
    )


def _published_package(
    tmp_path: Path,
    *,
    owner: AgentOwnerIdentity = SOURCE_OWNER,
) -> tuple[ProjectTarget, v2_importer.ValidatedV2HoodPackage]:
    target = _target(tmp_path)
    target.sidecar_path.mkdir()
    inventory = ProjectHoodInventory(
        owner,
        PROJECT.key,
        (
            _run(
                "crew--plan",
                "1",
                state="completed",
                chat=b"plan chat\n",
                owner=owner,
            ),
            _run(
                "crew--code",
                "2",
                state="active",
                chat=None,
                owner=owner,
            ),
        ),
    )
    publish_agent_hood(
        target,
        target.sidecar_path,
        "crew--plan",
        identity=AgentIdentitySnapshot(owner),
        inventory=inventory,
    )
    discovery = discover_agent_imports(target.sidecar_path, PROJECT)
    assert discovery.diagnostics == ()
    return target, discovery.v2_packages[0]


def _isolate_local_state(
    tmp_path: Path,
    target: ProjectTarget,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, list[tuple[object, ...]]]:
    state = tmp_path / "state"
    projects = state / "projects"
    artifact_root = projects / target.project_key / "artifacts" / "ace-run"
    bundles = state / "dismissed_bundles"
    groups = state / "dismissed_agent_groups"
    claims: list[tuple[object, ...]] = []

    monkeypatch.setattr(v2_import_storage, "sase_home", lambda: state)
    monkeypatch.setattr(v2_import_storage, "sase_projects_dir", lambda: projects)
    monkeypatch.setattr(v2_import_transactions, "sase_home", lambda: state)
    monkeypatch.setattr(v2_import_transactions, "sase_projects_dir", lambda: projects)
    monkeypatch.setattr(v2_import_rendering, "sase_projects_dir", lambda: projects)
    monkeypatch.setattr(
        v2_import_history,
        "canonical_agent_artifact_path",
        lambda _project, _workflow, timestamp: artifact_root / timestamp,
    )
    monkeypatch.setattr(
        v2_import_planning,
        "canonical_agent_artifact_path",
        lambda _project, _workflow, timestamp: artifact_root / timestamp,
    )
    monkeypatch.setattr(
        v2_import_history,
        "iter_agent_artifact_dirs",
        lambda *_args, **_kwargs: iter(sorted(artifact_root.glob("*"))),
    )
    monkeypatch.setattr(
        v2_import_planning,
        "iter_agent_artifact_dirs",
        lambda *_args, **_kwargs: iter(sorted(artifact_root.glob("*"))),
    )
    monkeypatch.setattr(
        v2_import_planning,
        "preflight_imported_registered_names_v2",
        lambda rows, **_kwargs: claims.append(("preflight", *rows)),
    )
    monkeypatch.setattr(
        v2_import_transactions,
        "claim_imported_registered_names_v2",
        lambda rows, **_kwargs: claims.append(("claim", *rows)),
    )
    monkeypatch.setattr(
        v2_import_transactions,
        "update_agent_artifact_index_for_marker_mutation",
        lambda _path: None,
    )
    monkeypatch.setattr(
        v2_import_transactions,
        "sync_dismissed_agent_artifact_index",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(v2_import_storage, "dismissed_bundles_dir", lambda: bundles)
    monkeypatch.setattr(v2_import_storage, "dismissed_groups_dir", lambda: groups)
    monkeypatch.setattr(
        v2_import_transactions, "dismissed_bundles_dir", lambda: bundles
    )
    monkeypatch.setattr(v2_import_transactions, "dismissed_groups_dir", lambda: groups)
    monkeypatch.setattr(
        dismissed_agents,
        "rebuild_dismissed_bundle_index",
        lambda: None,
    )
    return artifact_root, groups, claims


def test_preferred_timestamp_never_returns_a_future_value() -> None:
    for index in range(10_000):
        value = v2_import_history.preferred_timestamp(f"source-{index}", None)
        parsed = datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        assert parsed <= datetime.now(UTC)

    future = datetime.now(UTC) + timedelta(days=365)
    embedded = v2_import_history.preferred_timestamp(
        f"source-{future.strftime('%Y%m%d%H%M%S')}",
        None,
    )
    started = v2_import_history.preferred_timestamp("source-future", future.isoformat())
    assert datetime.strptime(embedded, "%Y%m%d%H%M%S").replace(
        tzinfo=UTC
    ) <= datetime.now(UTC)
    assert datetime.strptime(started, "%Y%m%d%H%M%S").replace(
        tzinfo=UTC
    ) <= datetime.now(UTC)


def test_reserve_timestamp_rejects_a_future_preferred_value(tmp_path: Path) -> None:
    future = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y%m%d%H%M%S")

    with pytest.raises(ValueError, match="future imported artifact timestamp"):
        v2_import_history.reserve_timestamp(_target(tmp_path), future, set())


def test_family_import_recovers_as_one_visible_idempotent_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = _published_package(tmp_path)
    artifact_root, groups, claims = _isolate_local_state(
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


def test_exact_current_owner_commit_evidence_observes_without_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = _published_package(tmp_path, owner=LOCAL_OWNER)
    artifact_root, groups, claims = _isolate_local_state(
        tmp_path,
        target,
        monkeypatch,
    )
    for suffix, name in (("1", "crew--plan"), ("2", "crew--code")):
        artifact = artifact_root / f"2026072413000{suffix}"
        artifact.mkdir(parents=True)
        (artifact / "agent_meta.json").write_text(
            json.dumps({"name": name}),
            encoding="utf-8",
        )
        (artifact / "done.json").write_text(
            json.dumps({"name": name, "outcome": "completed"}),
            encoding="utf-8",
        )
        (artifact / "commit_results.json").write_text(
            json.dumps([{"result": suffix * 40}]),
            encoding="utf-8",
        )

    observed = v2_importer.integrate_v2_hoods(
        target,
        (package,),
        identity=AgentIdentitySnapshot(LOCAL_OWNER),
    )

    assert observed.hoods_unchanged == 1
    assert observed.runs_imported == 0
    assert len(list(artifact_root.glob("*"))) == 2
    assert not list(groups.glob("*.json"))
    assert not any(row[0] == "claim" for row in claims)
    assert all(
        "imported_source_owner"
        not in json.loads((artifact / "agent_meta.json").read_text())
        for artifact in artifact_root.glob("*")
    )


def test_exact_current_owner_primary_history_observes_cleaned_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = _published_package(tmp_path, owner=LOCAL_OWNER)
    artifact_root, groups, claims = _isolate_local_state(
        tmp_path,
        target,
        monkeypatch,
    )

    def primary_git(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "agents_sync.git",
    ) -> subprocess.CompletedProcess[str]:
        del cwd, network
        if op == "agents_sync.v2_primary_commit_index":
            return subprocess.CompletedProcess(args, 0, f"{'1' * 40}\n{'2' * 40}\n", "")
        if op == "agents_sync.v2_primary_commit_messages":
            stdout = "".join(
                (
                    f"{'1' * 40}\x00SASE_AGENT=alice.athena.crew--plan\n"
                    "SASE_MACHINE=athena\n\x00\n",
                    f"{'2' * 40}\x00SASE_AGENT=alice.athena.crew--code\n"
                    "SASE_MACHINE=athena\n\x00\n",
                )
            )
            return subprocess.CompletedProcess(args, 0, stdout, "")
        raise AssertionError(f"unexpected git operation: {op}")

    context = v2_import_planning.build_import_preflight_context(
        target,
        AgentIdentitySnapshot(LOCAL_OWNER),
        (package,),
        git_runner=primary_git,
    )
    observed = v2_importer.integrate_v2_hoods(
        target,
        (package,),
        identity=AgentIdentitySnapshot(LOCAL_OWNER),
        preflight_context=context,
    )

    assert observed.hoods_unchanged == 1
    assert observed.runs_imported == 0
    assert not list(artifact_root.glob("*"))
    assert not list(groups.glob("*.json"))
    assert not any(row[0] == "claim" for row in claims)


def test_exact_current_owner_without_local_observation_is_not_materialized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = _published_package(tmp_path, owner=LOCAL_OWNER)
    artifact_root, groups, claims = _isolate_local_state(
        tmp_path,
        target,
        monkeypatch,
    )

    result = v2_importer.integrate_v2_hoods(
        target,
        (package,),
        identity=AgentIdentitySnapshot(LOCAL_OWNER),
    )

    assert result.hoods_unchanged == 1
    assert result.runs_imported == 0
    assert not list(artifact_root.glob("*"))
    assert not list(groups.glob("*.json"))
    assert not any(row[0] == "claim" for row in claims)


def test_imported_bundles_are_not_republished(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = _published_package(tmp_path)
    _artifact_root, _groups, _claims = _isolate_local_state(
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


def test_preflight_context_scans_artifacts_once_for_multi_run_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = _published_package(tmp_path)
    artifact_root, _groups, _claims = _isolate_local_state(
        tmp_path,
        target,
        monkeypatch,
    )
    history_scans = 0
    planning_scans = 0

    def history_artifacts(
        *_args: object,
        **_kwargs: object,
    ) -> Iterator[Path]:
        nonlocal history_scans
        history_scans += 1
        return iter(sorted(artifact_root.glob("*")))

    def planning_artifacts(
        *_args: object,
        **_kwargs: object,
    ) -> Iterator[Path]:
        nonlocal planning_scans
        planning_scans += 1
        return iter(sorted(artifact_root.glob("*")))

    monkeypatch.setattr(
        v2_import_history,
        "iter_agent_artifact_dirs",
        history_artifacts,
    )
    monkeypatch.setattr(
        v2_import_planning,
        "iter_agent_artifact_dirs",
        planning_artifacts,
    )
    identity = AgentIdentitySnapshot(LOCAL_OWNER)
    context = v2_import_planning.build_import_preflight_context(target, identity)

    imported = v2_importer.integrate_v2_hoods(
        target,
        (package,),
        identity=identity,
        preflight_context=context,
    )

    assert imported.hoods_imported == 1
    assert imported.runs_imported == 2
    assert history_scans == 2
    assert planning_scans == 1


def test_import_finalization_upserts_bundle_index_without_full_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path)
    bundles = tmp_path / "bundles"
    bundle_path = bundles / "202607" / "20260724120000.json"
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text('{"agent_name":"crew--plan"}\n')
    upserts: list[tuple[Path, Path, dict[str, object]]] = []

    def upsert(
        root: Path,
        path: Path,
        bundle: dict[str, object],
    ) -> bool:
        upserts.append((root, path, bundle))
        return True

    monkeypatch.setattr(
        v2_import_transactions,
        "dismissed_bundles_dir",
        lambda: bundles,
    )
    monkeypatch.setattr(
        v2_import_transactions,
        "destination_path",
        lambda _target, _row: bundle_path,
    )
    monkeypatch.setattr(
        dismissed_bundle_index,
        "archive_index_exists",
        lambda root: root == bundles,
    )
    monkeypatch.setattr(
        dismissed_bundle_index,
        "upsert_bundle_summary",
        upsert,
    )
    monkeypatch.setattr(
        dismissed_agents,
        "rebuild_dismissed_bundle_index",
        lambda: pytest.fail("incremental finalization must not rebuild"),
    )

    v2_import_transactions._update_dismissed_bundle_index(
        target,
        {
            "files": [
                {
                    "destination_kind": "bundles",
                    "relative": "202607/20260724120000.json",
                },
                {
                    "destination_kind": "project",
                    "relative": "artifacts/ignored.json",
                },
            ]
        },
    )

    assert upserts == [
        (
            bundles,
            bundle_path,
            {"agent_name": "crew--plan"},
        )
    ]


def test_shared_preflight_context_recovers_transactions_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = _published_package(tmp_path)
    _isolate_local_state(tmp_path, target, monkeypatch)
    recoveries = 0

    def recover(
        _target: ProjectTarget,
        *,
        identity: AgentIdentitySnapshot,
    ) -> tuple[str, ...]:
        nonlocal recoveries
        del identity
        recoveries += 1
        return ()

    monkeypatch.setattr(
        v2_importer,
        "recover_v2_import_transactions",
        recover,
    )
    identity = AgentIdentitySnapshot(LOCAL_OWNER)
    context = v2_import_planning.build_import_preflight_context(target, identity)

    v2_importer.integrate_v2_hoods(
        target,
        (package,),
        identity=identity,
        preflight_context=context,
    )
    v2_importer.integrate_v2_hoods(
        target,
        (package,),
        identity=identity,
        preflight_context=context,
    )

    assert recoveries == 1
