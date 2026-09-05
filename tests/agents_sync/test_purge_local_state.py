"""Full-sweep coverage for the generalized local-import-state purge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.incoming_cache_metadata import cache_id_for
from sase.agents_sync.incoming_cache_paths import (
    cache_objects_dir,
    cache_staging_dir,
)
from sase.agents_sync.incoming_cache_receipts import (
    read_project_receipts,
    write_import_receipt,
)
from sase.agents_sync.models import AgentHoodImportReceipt
from sase.agents_sync.purge_local_state import purge_local_import_state
from sase.agents_sync.v2_import_storage import imports_root
from sase.core.agent_types import AgentType
from sase.core.dismissed_agents_facade import (
    load_dismissed_agents,
    persist_dismissed_agents,
)


def _seed_imported_artifact(
    projects: Path,
    project_key: str,
    timestamp: str,
    *,
    machine: str,
    name: str,
    chats_root: Path,
) -> tuple[Path, Path]:
    artifact_dir = projects / project_key / "artifacts" / "ace-run" / timestamp
    artifact_dir.mkdir(parents=True)
    chat_path = chats_root / f"imported-{name}-{timestamp}.md"
    chat_path.parent.mkdir(parents=True, exist_ok=True)
    chat_path.write_text("chat body\n", encoding="utf-8")
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": name,
                "chat_path": str(chat_path),
                "imported_from_machine": machine,
                "imported_digest": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    return artifact_dir, chat_path


def _seed_bundle(state: Path, timestamp: str, *, artifacts_dir: Path) -> Path:
    path = state / "dismissed_bundles" / timestamp[:6] / f"{timestamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "agent_type": "run",
                "patch_name": "proj",
                "cl_name": "proj",
                "raw_suffix": timestamp,
                "artifacts_dir": str(artifacts_dir),
                "imported_from_machine": "zeus",
            }
        ),
        encoding="utf-8",
    )
    return path


def _receipt(
    *,
    source_owner_kind: str,
    source_username: str | None,
    source_machine: str,
) -> AgentHoodImportReceipt:
    hood_digest = "a" * 64
    cache_id = cache_id_for(
        project_key="proj",
        project="Project",
        format_version=1 if source_owner_kind == "username_unknown_v1" else 2,
        source_owner_kind=source_owner_kind,  # type: ignore[arg-type]
        source_username=source_username,
        source_machine=source_machine,
        top_hood="crew",
        hood_digest=hood_digest,
    )
    return AgentHoodImportReceipt(
        project_key="proj",
        project="Project",
        source_owner_kind=source_owner_kind,  # type: ignore[arg-type]
        source_username=source_username,
        source_machine=source_machine,
        top_hood="crew",
        hood_digest=hood_digest,
        cache_id=cache_id,
        fetched_ref="refs/remotes/origin/main",
        fetched_sha="b" * 40,
        cache_created_at=1.0,
        applied_at=2.0,
    )


def _seed_full_closure(state: Path, projects: Path) -> dict[str, Path]:
    v1_dir, v1_chat = _seed_imported_artifact(
        projects,
        "proj",
        "20260601120000",
        machine="zeus",
        name="zeus.worker",
        chats_root=state / "chats",
    )
    v2_dir, v2_chat = _seed_imported_artifact(
        projects,
        "proj",
        "20260601130000",
        machine="mars",
        name="bob.worker",
        chats_root=state / "chats",
    )
    bundle = _seed_bundle(state, "20260601120000", artifacts_dir=v1_dir)
    local_dir = projects / "proj" / "artifacts" / "ace-run" / "20260601140000"
    local_dir.mkdir(parents=True)
    (local_dir / "agent_meta.json").write_text(
        json.dumps({"name": "local-run"}), encoding="utf-8"
    )
    persist_dismissed_agents(
        {
            (AgentType.RUNNING, "proj", "20260601120000"),
            (AgentType.RUNNING, "proj", "20260601140000"),
        }
    )
    write_import_receipt(
        _receipt(
            source_owner_kind="username_unknown_v1",
            source_username=None,
            source_machine="zeus",
        )
    )
    write_import_receipt(
        _receipt(
            source_owner_kind="exact",
            source_username="bob",
            source_machine="mars",
        )
    )

    journal_dir = imports_root("proj") / "journals"
    journal_dir.mkdir(parents=True)
    (journal_dir / "txn.json").write_text("{}", encoding="utf-8")
    staging_dir = imports_root("proj") / "stage" / "txn"
    staging_dir.mkdir(parents=True)
    (staging_dir / "file.txt").write_text("staged", encoding="utf-8")

    cache_objects_dir().mkdir(parents=True, exist_ok=True)
    (cache_objects_dir() / "somecache").mkdir()
    (cache_objects_dir() / "somecache" / "metadata.json").write_text(
        "{}", encoding="utf-8"
    )
    cache_staging_dir().mkdir(parents=True, exist_ok=True)

    return {
        "v1_dir": v1_dir,
        "v1_chat": v1_chat,
        "v2_dir": v2_dir,
        "v2_chat": v2_chat,
        "bundle": bundle,
        "local_dir": local_dir,
    }


def test_dry_run_reports_full_closure_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    projects = state / "projects"
    monkeypatch.setenv("SASE_HOME", str(state))
    seeded = _seed_full_closure(state, projects)

    outcome = purge_local_import_state()

    assert outcome.dry_run is True
    assert set(outcome.artifact_dirs) == {seeded["v1_dir"], seeded["v2_dir"]}
    assert set(outcome.chat_files) == {seeded["v1_chat"], seeded["v2_chat"]}
    assert outcome.bundle_files == (seeded["bundle"],)
    assert outcome.dismissed_identities == (
        (AgentType.RUNNING, "proj", "20260601120000"),
    )
    assert outcome.import_dirs == (imports_root("proj"),)
    assert set(outcome.cache_dirs) == {cache_objects_dir(), cache_staging_dir()}
    assert len(outcome.receipt_files) == 1
    assert outcome.errors == ()
    assert not outcome.is_empty

    # Nothing was mutated.
    assert seeded["v1_dir"].is_dir()
    assert seeded["v2_dir"].is_dir()
    assert seeded["bundle"].is_file()
    assert seeded["local_dir"].is_dir()
    assert imports_root("proj").is_dir()
    assert cache_objects_dir().is_dir()
    assert len(read_project_receipts("proj")) == 2


def test_apply_removes_full_closure_and_leaves_local_state_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    projects = state / "projects"
    monkeypatch.setenv("SASE_HOME", str(state))
    seeded = _seed_full_closure(state, projects)

    outcome = purge_local_import_state(apply=True)

    assert outcome.dry_run is False
    assert outcome.ok
    assert outcome.surviving_import_names == ()
    assert not seeded["v1_dir"].exists()
    assert not seeded["v2_dir"].exists()
    assert not seeded["v1_chat"].exists()
    assert not seeded["v2_chat"].exists()
    assert not seeded["bundle"].exists()
    assert seeded["local_dir"].is_dir()
    assert not imports_root("proj").exists()
    assert not cache_objects_dir().exists()
    assert not cache_staging_dir().exists()

    assert read_project_receipts("proj") == ()

    dismissed = load_dismissed_agents()
    assert (AgentType.RUNNING, "proj", "20260601140000") in dismissed
    assert (AgentType.RUNNING, "proj", "20260601120000") not in dismissed


def test_no_imported_state_reports_empty_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("SASE_HOME", str(state))

    outcome = purge_local_import_state()

    assert outcome.is_empty
    assert outcome.ok


def test_unwritable_artifact_reported_without_aborting_sweep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    projects = state / "projects"
    monkeypatch.setenv("SASE_HOME", str(state))
    dir_a, _chat_a = _seed_imported_artifact(
        projects,
        "proj",
        "20260601120000",
        machine="zeus",
        name="zeus.worker-a",
        chats_root=state / "chats",
    )
    dir_b, _chat_b = _seed_imported_artifact(
        projects,
        "proj",
        "20260601120001",
        machine="zeus",
        name="zeus.worker-b",
        chats_root=state / "chats",
    )

    import sase.agents_sync.purge_local_state as module

    real_rmtree = module.shutil.rmtree

    def fail_for_a(path: object, *args: object, **kwargs: object) -> None:
        if Path(str(path)) == dir_a:
            raise OSError("permission denied")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(module.shutil, "rmtree", fail_for_a)

    outcome = purge_local_import_state(apply=True)

    assert dir_a.exists()
    assert not dir_b.exists()
    assert outcome.errors
    assert any(str(dir_a) in error for error in outcome.errors)
