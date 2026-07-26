"""Coverage for future-dated imported-state repair."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from unittest.mock import patch

from sase.agents.index_repair import (
    apply_imported_state_repair,
    plan_imported_state_repair,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _artifact(
    projects: Path,
    timestamp: str,
    *,
    imported: bool,
    transaction_key: str = "future-import-0001",
) -> Path:
    path = projects / "proj" / "artifacts" / "ace-run" / timestamp
    meta: dict[str, object] = {"name": f"agent-{timestamp}"}
    done: dict[str, object] = {"cl_name": "proj", "outcome": "completed"}
    if imported:
        meta.update(
            {
                "imported_source_owner": {
                    "username": "alice",
                    "machine_name": "zeus",
                },
                "imported_transaction_key": transaction_key,
            }
        )
        done["imported_transaction_key"] = transaction_key
    _write_json(path / "agent_meta.json", meta)
    _write_json(path / "done.json", done)
    return path


def _bundle(
    state: Path,
    timestamp: str,
    *,
    imported: bool,
    transaction_key: str = "future-import-0001",
) -> Path:
    path = state / "dismissed_bundles" / timestamp[:6] / f"{timestamp}.json"
    payload: dict[str, object] = {
        "agent_type": "run",
        "agent_name": f"agent-{timestamp}",
        "cl_name": "proj",
        "raw_suffix": timestamp,
    }
    if imported:
        payload.update(
            {
                "imported_source_owner": {
                    "username": "alice",
                    "machine_name": "zeus",
                },
                "imported_transaction_key": transaction_key,
            }
        )
    _write_json(path, payload)
    return path


def test_repair_is_dry_run_safe_and_apply_is_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = tmp_path / "state"
    projects = state / "projects"
    monkeypatch.setenv("SASE_HOME", str(state))
    future = "20990102030405"
    past = "20200102030405"

    imported_artifact = _artifact(projects, future, imported=True)
    local_artifact = _artifact(projects, "20990202030405", imported=False)
    old_imported_artifact = _artifact(projects, past, imported=True)
    imported_bundle = _bundle(state, future, imported=True)
    local_bundle = _bundle(state, "20990202030405", imported=False)
    old_imported_bundle = _bundle(state, past, imported=True)

    journal = (
        projects
        / "proj"
        / "agents_sync_imports"
        / "journals"
        / "future-import-0001.json"
    )
    _write_json(
        journal,
        {
            "transaction_key": "future-import-0001",
            "stage_relative": "staging/future-import-0001",
            "artifact_relatives": [f"artifacts/ace-run/{future}"],
            "files": [
                {
                    "destination_kind": "bundles",
                    "relative": f"{future[:6]}/{future}.json",
                }
            ],
        },
    )
    stage = journal.parent.parent / "staging" / "future-import-0001"
    stage.mkdir(parents=True)
    registry = state / "agent_name_registry.json"
    _write_json(
        registry,
        {
            "schema_version": 2,
            "entries": {
                "artifact-name": {"artifacts_dir": str(imported_artifact)},
                "bundle-name": {"bundle_path": str(imported_bundle)},
                "local-name": {"artifacts_dir": str(local_artifact)},
            },
        },
    )

    plan = plan_imported_state_repair(
        projects,
        now=datetime(2026, 7, 26, tzinfo=UTC),
    )

    assert plan.counts() == {
        "artifacts": 1,
        "bundles": 1,
        "index_rows": 2,
        "journals": 1,
        "registry_entries": 2,
    }
    assert imported_artifact.is_dir()
    assert imported_bundle.is_file()
    assert journal.is_file()

    with (
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "delete_agent_artifact_index_artifacts"
        ) as delete_index,
        patch(
            "sase.agents.index_repair._rebuild_dismissed_bundle_index"
        ) as rebuild_bundle_index,
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "sync_dismissed_agent_artifact_index"
        ) as sync_projection,
        patch("sase.agents.index_repair._rebuild_name_registry") as rebuild_registry,
    ):
        result = apply_imported_state_repair(
            plan,
            index_path=state / "agent_artifact_index.sqlite",
        )

    assert result["artifacts_removed"] == 1
    assert result["bundles_removed"] == 1
    assert result["journals_removed"] == 1
    delete_index.assert_called_once_with(
        {imported_artifact.resolve()},
        index_path=state / "agent_artifact_index.sqlite",
    )
    rebuild_bundle_index.assert_called_once()
    sync_projection.assert_called_once_with(
        index_path=state / "agent_artifact_index.sqlite",
        force=True,
    )
    rebuild_registry.assert_called_once()
    assert not imported_artifact.exists()
    assert not imported_bundle.exists()
    assert not journal.exists()
    assert not stage.exists()
    assert local_artifact.is_dir()
    assert local_bundle.is_file()
    assert old_imported_artifact.is_dir()
    assert old_imported_bundle.is_file()

    second = plan_imported_state_repair(
        projects,
        now=datetime(2026, 7, 26, tzinfo=UTC),
    )
    assert second.counts() == {
        "artifacts": 0,
        "bundles": 0,
        "index_rows": 0,
        "journals": 0,
        "registry_entries": 0,
    }


def test_future_local_records_are_never_selected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = tmp_path / "state"
    projects = state / "projects"
    monkeypatch.setenv("SASE_HOME", str(state))
    _artifact(projects, "20990102030405", imported=False)
    _bundle(state, "20990102030405", imported=False)

    plan = plan_imported_state_repair(
        projects,
        now=datetime(2026, 7, 26, tzinfo=UTC),
    )

    assert plan.artifacts == ()
    assert plan.bundles == ()
