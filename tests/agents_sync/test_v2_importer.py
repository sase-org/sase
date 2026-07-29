"""Local-history and preflight behavior for the v2 importer."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import v2_import_history
from sase.agents_sync import v2_import_planning
from sase.agents_sync import v2_importer
from sase.agents_sync.models import ProjectTarget
from sase.core.agent_identity_facade import AgentIdentitySnapshot

from tests.agents_sync.v2_importer_fixtures import (
    LOCAL_OWNER,
    isolate_local_state,
    make_target,
    published_package,
)


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
        v2_import_history.reserve_timestamp(make_target(tmp_path), future, set())


def test_reserve_timestamp_probes_backward_at_current_time_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: object | None = None) -> datetime:
            assert tz is UTC
            return now

    monkeypatch.setattr(v2_import_history, "datetime", _FrozenDatetime)
    monkeypatch.setattr(
        v2_import_history,
        "canonical_agent_artifact_path",
        lambda _project, _workflow, timestamp: tmp_path / timestamp,
    )
    preferred = now.strftime("%Y%m%d%H%M%S")

    reserved = v2_import_history.reserve_timestamp(
        make_target(tmp_path),
        preferred,
        {preferred},
    )

    assert reserved == (now - timedelta(seconds=1)).strftime("%Y%m%d%H%M%S")


def test_exact_current_owner_commit_evidence_observes_without_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = published_package(tmp_path, owner=LOCAL_OWNER)
    artifact_root, groups, claims = isolate_local_state(
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
    target, package = published_package(tmp_path, owner=LOCAL_OWNER)
    artifact_root, groups, claims = isolate_local_state(
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
    target, package = published_package(tmp_path, owner=LOCAL_OWNER)
    artifact_root, groups, claims = isolate_local_state(
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


def test_preflight_context_scans_artifacts_once_for_multi_run_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = published_package(tmp_path)
    artifact_root, _groups, _claims = isolate_local_state(
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


def test_shared_preflight_context_recovers_transactions_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = published_package(tmp_path)
    isolate_local_state(tmp_path, target, monkeypatch)
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


def test_imported_artifact_restores_output_variables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = published_package(tmp_path)
    artifact_root, _groups, _claims = isolate_local_state(
        tmp_path,
        target,
        monkeypatch,
    )

    imported = v2_importer.integrate_v2_hoods(
        target,
        (package,),
        identity=AgentIdentitySnapshot(LOCAL_OWNER),
    )
    metadata = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(artifact_root.glob("*/agent_meta.json"))
    ]

    assert imported.runs_imported == 2
    assert [
        row["output_variables"] for row in metadata if "output_variables" in row
    ] == [{"plan_file": "plans/crew.md"}]
