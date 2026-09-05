"""Full-sweep coverage for the generalized local-import-state purge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.purge_local_state import purge_local_import_state
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


def _imports_root(projects: Path, project_key: str) -> Path:
    return projects / project_key / "agents_sync_imports"


def _cache_objects_dir(state: Path) -> Path:
    return state / "agents_sync" / "cache" / "objects"


def _cache_staging_dir(state: Path) -> Path:
    return state / "agents_sync" / "cache" / "staging"


def _receipts_dir(state: Path) -> Path:
    return state / "agents_sync" / "receipts"


def _seed_receipts(state: Path) -> Path:
    path = _receipts_dir(state) / "proj.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_key": "proj",
                "project": "Project",
                "receipts": [
                    {"source_owner_kind": "username_unknown_v1"},
                    {"source_owner_kind": "exact"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


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
    receipts = _seed_receipts(state)

    import_root = _imports_root(projects, "proj")
    journal_dir = import_root / "journals"
    journal_dir.mkdir(parents=True)
    (journal_dir / "txn.json").write_text("{}", encoding="utf-8")
    staging_dir = import_root / "stage" / "txn"
    staging_dir.mkdir(parents=True)
    (staging_dir / "file.txt").write_text("staged", encoding="utf-8")

    _cache_objects_dir(state).mkdir(parents=True, exist_ok=True)
    (_cache_objects_dir(state) / "somecache").mkdir()
    (_cache_objects_dir(state) / "somecache" / "metadata.json").write_text(
        "{}", encoding="utf-8"
    )
    _cache_staging_dir(state).mkdir(parents=True, exist_ok=True)

    return {
        "v1_dir": v1_dir,
        "v1_chat": v1_chat,
        "v2_dir": v2_dir,
        "v2_chat": v2_chat,
        "bundle": bundle,
        "local_dir": local_dir,
        "import_root": import_root,
        "receipts": receipts,
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
    assert outcome.import_dirs == (seeded["import_root"],)
    assert set(outcome.cache_dirs) == {
        _cache_objects_dir(state),
        _cache_staging_dir(state),
    }
    assert len(outcome.receipt_files) == 1
    assert outcome.errors == ()
    assert not outcome.is_empty

    # Nothing was mutated.
    assert seeded["v1_dir"].is_dir()
    assert seeded["v2_dir"].is_dir()
    assert seeded["bundle"].is_file()
    assert seeded["local_dir"].is_dir()
    assert seeded["import_root"].is_dir()
    assert _cache_objects_dir(state).is_dir()
    assert seeded["receipts"].is_file()


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
    assert not seeded["import_root"].exists()
    assert not _cache_objects_dir(state).exists()
    assert not _cache_staging_dir(state).exists()

    assert not seeded["receipts"].exists()

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
