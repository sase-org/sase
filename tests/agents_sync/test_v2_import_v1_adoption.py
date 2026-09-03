"""Evidence-backed v1-to-v2 adoption tests (uses the stubbed registry)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync import v2_import_transactions
from sase.agents_sync import v2_importer
from sase.agents_sync.inventory_io import source_run_id
from sase.core.agent_artifact_paths import ACE_RUN_WORKFLOW_DIR
from sase.core.agent_identity_facade import AgentIdentitySnapshot

from tests.agents_sync.v1_adoption_fixtures import (
    CHAT_BYTES,
    LOCAL_OWNER,
    V1_NAME,
    wedged_machine,
)
from tests.agents_sync.v2_importer_fixtures import PROJECT, SOURCE_OWNER


def _identity() -> AgentIdentitySnapshot:
    return AgentIdentitySnapshot(LOCAL_OWNER)


def test_unique_match_promotes_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wedged = wedged_machine(tmp_path, monkeypatch)

    result = v2_importer.integrate_v2_hoods(
        wedged.target,
        (wedged.package,),
        identity=_identity(),
    )

    assert result.hoods_refreshed == 1
    assert result.hoods_imported == 0
    assert [path.name for path in sorted(wedged.artifact_root.glob("*"))] == [
        wedged.durable
    ]
    meta = json.loads((wedged.v1_artifact_dir / "agent_meta.json").read_text())
    assert meta["imported_source_owner"] == {
        "username": SOURCE_OWNER.username,
        "machine_name": SOURCE_OWNER.machine_name,
    }
    assert meta["imported_source_run_id"] == source_run_id(
        PROJECT.key, ACE_RUN_WORKFLOW_DIR, wedged.durable
    )
    assert "imported_owner_kind" not in meta
    assert (wedged.v1_artifact_dir / "raw_xprompt.md").is_file()
    assert (wedged.v1_artifact_dir / "imported_commits.json").is_file()
    assert any(row[0] == "claim" for row in wedged.claims)
    assert any(
        "adopted 1 legacy v1 run(s) in place" in diagnostic
        for diagnostic in result.diagnostics
    )


def test_adoption_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wedged = wedged_machine(tmp_path, monkeypatch)
    identity = _identity()

    first = v2_importer.integrate_v2_hoods(
        wedged.target, (wedged.package,), identity=identity
    )
    assert first.hoods_refreshed == 1

    second = v2_importer.integrate_v2_hoods(
        wedged.target, (wedged.package,), identity=identity
    )
    assert second.hoods_unchanged == 1
    assert [path.name for path in sorted(wedged.artifact_root.glob("*"))] == [
        wedged.durable
    ]


def test_ambiguous_v1_candidates_quarantine_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wedged = wedged_machine(tmp_path, monkeypatch)
    second_dir = wedged.artifact_root / "20260601120099"
    second_dir.mkdir(parents=True)
    (second_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": V1_NAME,
                "artifact_agent_id": wedged.durable,
                "imported_from_machine": SOURCE_OWNER.machine_name,
                "imported_owner_kind": "username_unknown_v1",
                "imported_digest": "d" * 64,
            }
        ),
        encoding="utf-8",
    )
    before_first = (wedged.v1_artifact_dir / "agent_meta.json").read_bytes()
    before_second = (second_dir / "agent_meta.json").read_bytes()

    result = v2_importer.integrate_v2_hoods(
        wedged.target,
        (wedged.package,),
        identity=_identity(),
    )

    assert result.hoods_quarantined == 1
    assert any(
        str(wedged.v1_artifact_dir) in diagnostic and str(second_dir) in diagnostic
        for diagnostic in result.diagnostics
    )
    assert (wedged.v1_artifact_dir / "agent_meta.json").read_bytes() == before_first
    assert (second_dir / "agent_meta.json").read_bytes() == before_second


def test_contradicting_chat_digest_quarantines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wedged = wedged_machine(tmp_path, monkeypatch)
    wedged.v1_chat_path.write_bytes(b"tampered chat\n")
    before = (wedged.v1_artifact_dir / "agent_meta.json").read_bytes()

    result = v2_importer.integrate_v2_hoods(
        wedged.target,
        (wedged.package,),
        identity=_identity(),
    )

    assert result.hoods_quarantined == 1
    assert (wedged.v1_artifact_dir / "agent_meta.json").read_bytes() == before


def test_dismissed_state_preserved_and_forged_bundle_repaired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.core.agent_types import AgentType

    wedged = wedged_machine(tmp_path, monkeypatch)
    stale_root_bundle = wedged.bundles_dir / f"{wedged.durable}.json"
    stale_root_bundle.write_text(
        wedged.v1_bundle_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    pre_seeded = (AgentType.RUNNING, "unknown", wedged.durable)
    assert pre_seeded in load_dismissed_agents()

    v2_importer.integrate_v2_hoods(
        wedged.target,
        (wedged.package,),
        identity=_identity(),
    )

    assert not stale_root_bundle.exists()
    new_bundle = json.loads(wedged.v1_bundle_path.read_text(encoding="utf-8"))
    assert "imported_source_owner" in new_bundle

    dismissed = load_dismissed_agents()
    assert pre_seeded in dismissed
    assert any(identity[2] == wedged.durable for identity in dismissed)


def test_chat_preservation_when_v2_payload_has_no_chat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wedged = wedged_machine(tmp_path, monkeypatch, v2_chat_bytes=None)

    v2_importer.integrate_v2_hoods(
        wedged.target,
        (wedged.package,),
        identity=_identity(),
    )

    meta = json.loads((wedged.v1_artifact_dir / "agent_meta.json").read_text())
    assert meta["chat_path"] == str(wedged.v1_chat_path)
    assert wedged.v1_chat_path.is_file()
    assert wedged.v1_chat_path.read_bytes() == CHAT_BYTES


def test_crash_during_finalize_recovers_adopted_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wedged = wedged_machine(tmp_path, monkeypatch)
    identity = _identity()
    real_finalize = v2_import_transactions._finalize_transaction
    failures = 0

    def fail_first_finalize(target_arg: object, journal: dict[str, object]) -> None:
        nonlocal failures
        failures += 1
        if failures == 1:
            raise OSError("injected finalize failure")
        real_finalize(target_arg, journal)

    monkeypatch.setattr(
        v2_import_transactions, "_finalize_transaction", fail_first_finalize
    )
    interrupted = v2_importer.integrate_v2_hoods(
        wedged.target, (wedged.package,), identity=identity
    )
    assert interrupted.hoods_quarantined == 1

    monkeypatch.setattr(v2_import_transactions, "_finalize_transaction", real_finalize)
    diagnostics = v2_import_transactions.recover_v2_import_transactions(
        wedged.target, identity=identity
    )
    assert diagnostics == ()

    meta = json.loads((wedged.v1_artifact_dir / "agent_meta.json").read_text())
    assert meta["imported_source_owner"] == {
        "username": SOURCE_OWNER.username,
        "machine_name": SOURCE_OWNER.machine_name,
    }

    from sase.ace.dismissed_agents import load_dismissed_agents

    matches = [
        row
        for row in load_dismissed_agents()
        if row[2] == wedged.durable and row[1] == PROJECT.key
    ]
    assert len(matches) == 1


def test_crash_during_apply_staged_files_recovers_adopted_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wedged = wedged_machine(tmp_path, monkeypatch)
    identity = _identity()
    real_apply = v2_import_transactions._apply_staged_files
    failures = 0

    def fail_first_apply(
        target_arg: object,
        journal: dict[str, object],
        rows: list[dict[str, str]],
    ) -> None:
        nonlocal failures
        failures += 1
        if failures == 1:
            raise OSError("injected apply-staged-files failure")
        real_apply(target_arg, journal, rows)

    monkeypatch.setattr(v2_import_transactions, "_apply_staged_files", fail_first_apply)
    interrupted = v2_importer.integrate_v2_hoods(
        wedged.target, (wedged.package,), identity=identity
    )
    assert interrupted.hoods_quarantined == 1
    meta_before_recovery = json.loads(
        (wedged.v1_artifact_dir / "agent_meta.json").read_text()
    )
    assert meta_before_recovery["imported_owner_kind"] == "username_unknown_v1"

    monkeypatch.setattr(v2_import_transactions, "_apply_staged_files", real_apply)
    diagnostics = v2_import_transactions.recover_v2_import_transactions(
        wedged.target, identity=identity
    )
    assert diagnostics == ()

    meta = json.loads((wedged.v1_artifact_dir / "agent_meta.json").read_text())
    assert meta["imported_source_owner"] == {
        "username": SOURCE_OWNER.username,
        "machine_name": SOURCE_OWNER.machine_name,
    }
    assert "imported_owner_kind" not in meta

    from sase.ace.dismissed_agents import load_dismissed_agents

    matches = [
        row
        for row in load_dismissed_agents()
        if row[2] == wedged.durable and row[1] == PROJECT.key
    ]
    assert len(matches) == 1
