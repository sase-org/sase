from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace import dismissed_agents
from sase.ace import dismissed_bundle_index
from sase.ace.tui.models.agent_types import AgentType
from sase.agents_sync import v2_import_storage
from sase.agents_sync import v2_import_transactions
from sase.core.agent_identity_facade import AgentIdentitySnapshot

from tests.agents_sync.v2_importer_fixtures import (
    LOCAL_OWNER,
    PROJECT,
    SOURCE_OWNER,
    isolate_local_state,
    make_target,
)


def test_import_finalization_upserts_bundle_index_without_full_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
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


def test_import_finalize_dismissed_state_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    dismissed_file = tmp_path / "state" / "dismissed_agents.json"
    existing = (AgentType.RUNNING, PROJECT.key, "20260724115959")
    imported = (AgentType.RUNNING, PROJECT.key, "20260724120000")
    sync_calls: list[tuple[set[object], set[object]]] = []

    def sync_index(
        dismissed: object = None,
        *,
        added: object = None,
        **_kwargs: object,
    ) -> bool:
        sync_calls.append((set(dismissed or ()), set(added or ())))
        return True

    monkeypatch.setattr(dismissed_agents, "_DISMISSED_AGENTS_FILE", dismissed_file)
    assert dismissed_agents.save_dismissed_agents({existing})
    monkeypatch.setattr(
        v2_import_transactions,
        "update_agent_artifact_index_for_marker_mutation",
        lambda _path: None,
    )
    monkeypatch.setattr(
        v2_import_transactions,
        "_apply_staged_files",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        v2_import_transactions,
        "_update_dismissed_bundle_index",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        v2_import_transactions,
        "sync_dismissed_agent_artifact_index",
        sync_index,
    )
    journal = {
        "artifact_relatives": [],
        "groups": [],
        "files": [],
        "dismissed_identities": [
            {
                "agent_type": "run",
                "cl_name": PROJECT.key,
                "raw_suffix": imported[2],
            },
            {
                "agent_type": "run",
                "cl_name": PROJECT.key,
                "raw_suffix": imported[2],
            },
        ],
    }

    v2_import_transactions._finalize_transaction(target, journal)
    first_payload = dismissed_file.read_text()
    v2_import_transactions._finalize_transaction(target, journal)

    assert dismissed_agents.load_dismissed_agents() == {existing, imported}
    assert dismissed_file.read_text() == first_payload
    assert sync_calls == [
        ({existing, imported}, {imported}),
        ({existing, imported}, set()),
    ]


def test_recover_v2_import_transaction_accepts_legacy_journal_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    isolate_local_state(tmp_path, target, monkeypatch)
    transaction_key = "legacy-journal-0001"
    path = v2_import_storage.journal_path(target.project_key, transaction_key)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transaction_key": transaction_key,
                "project_key": target.project_key,
                "source_owner": {
                    "username": SOURCE_OWNER.username,
                    "machine_name": SOURCE_OWNER.machine_name,
                },
                "hood": "crew",
                "snapshot_digest": "1" * 64,
                "state": "applied",
                "stage_relative": f"staging/{transaction_key}",
                "files": [],
                "groups": [],
                "claims": [],
                "artifact_relatives": [],
            }
        ),
        encoding="utf-8",
    )

    assert (
        v2_import_transactions.recover_v2_import_transactions(
            target,
            identity=AgentIdentitySnapshot(LOCAL_OWNER),
        )
        == ()
    )
    recovered = v2_import_storage.read_journal(path)
    assert recovered["state"] == "complete"
    assert recovered["schema_version"] == v2_import_storage.JOURNAL_SCHEMA_VERSION
    assert recovered["dismissed_identities"] == []
