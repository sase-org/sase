"""Dry-run-first coverage for the legacy v1 forget-import escape hatch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.incoming_cache_metadata import cache_id_for
from sase.agents_sync.incoming_cache_receipts import (
    read_project_receipts,
    write_import_receipt,
)
from sase.agents_sync.models import AgentHoodImportReceipt
from sase.agents_sync.v1_forget_import import forget_v1_import
from sase.core.agent_types import AgentType
from sase.core.dismissed_agents_facade import (
    load_dismissed_agents,
    persist_dismissed_agents,
)


def _seed_v1_artifact(
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
                "imported_owner_kind": "username_unknown_v1",
                "imported_digest": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    return artifact_dir, chat_path


def _seed_bundle(
    state: Path,
    timestamp: str,
    *,
    agent_name: str,
    artifacts_dir: Path,
) -> Path:
    path = state / "dismissed_bundles" / timestamp[:6] / f"{timestamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "agent_type": "run",
                "patch_name": "proj",
                "cl_name": "proj",
                "raw_suffix": timestamp,
                "agent_name": agent_name,
                "artifacts_dir": str(artifacts_dir),
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


def _seed_closure(
    state: Path,
    projects: Path,
) -> tuple[Path, Path, Path, Path]:
    v1_dir, v1_chat = _seed_v1_artifact(
        projects,
        "proj",
        "20260601120000",
        machine="zeus",
        name="zeus.worker",
        chats_root=state / "chats",
    )
    v1_bundle = _seed_bundle(
        state,
        "20260601120000",
        agent_name="zeus.worker",
        artifacts_dir=v1_dir,
    )
    local_dir = projects / "proj" / "artifacts" / "ace-run" / "20260601130000"
    local_dir.mkdir(parents=True)
    (local_dir / "agent_meta.json").write_text(
        json.dumps({"name": "local-run"}), encoding="utf-8"
    )
    persist_dismissed_agents(
        {
            (AgentType.RUNNING, "proj", "20260601120000"),
            (AgentType.RUNNING, "proj", "20260601130000"),
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
    return v1_dir, v1_chat, v1_bundle, local_dir


def test_dry_run_reports_closure_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    projects = state / "projects"
    monkeypatch.setenv("SASE_HOME", str(state))
    v1_dir, v1_chat, v1_bundle, local_dir = _seed_closure(state, projects)

    outcome = forget_v1_import("zeus")

    assert outcome.dry_run is True
    assert outcome.artifact_dirs == (v1_dir,)
    assert outcome.chat_files == (v1_chat,)
    assert outcome.bundle_files == (v1_bundle,)
    assert outcome.dismissed_identities == (
        (AgentType.RUNNING, "proj", "20260601120000"),
    )
    assert outcome.receipts == (
        ("proj", ("username_unknown_v1", None, "zeus", "crew")),
    )
    assert outcome.surviving_import_v1_names == ()
    assert outcome.errors == ()

    # Nothing was mutated.
    assert v1_dir.is_dir()
    assert v1_chat.is_file()
    assert v1_bundle.is_file()
    assert local_dir.is_dir()
    assert len(read_project_receipts("proj")) == 2
    assert (AgentType.RUNNING, "proj", "20260601120000") in load_dismissed_agents()


def test_apply_removes_closure_and_leaves_others_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    projects = state / "projects"
    monkeypatch.setenv("SASE_HOME", str(state))
    v1_dir, v1_chat, v1_bundle, local_dir = _seed_closure(state, projects)

    outcome = forget_v1_import("zeus", apply=True)

    assert outcome.dry_run is False
    assert outcome.ok
    assert outcome.surviving_import_v1_names == ()
    assert not v1_dir.exists()
    assert not v1_chat.exists()
    assert not v1_bundle.exists()
    assert local_dir.is_dir()

    remaining_receipts = read_project_receipts("proj")
    assert len(remaining_receipts) == 1
    assert remaining_receipts[0].source_machine == "mars"

    dismissed = load_dismissed_agents()
    assert (AgentType.RUNNING, "proj", "20260601130000") in dismissed
    assert (AgentType.RUNNING, "proj", "20260601120000") not in dismissed


def test_unwritable_artifact_reported_without_aborting_sweep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    projects = state / "projects"
    monkeypatch.setenv("SASE_HOME", str(state))
    v1_dir_a, _chat_a = _seed_v1_artifact(
        projects,
        "proj",
        "20260601120000",
        machine="zeus",
        name="zeus.worker-a",
        chats_root=state / "chats",
    )
    v1_dir_b, _chat_b = _seed_v1_artifact(
        projects,
        "proj",
        "20260601120001",
        machine="zeus",
        name="zeus.worker-b",
        chats_root=state / "chats",
    )

    import sase.agents_sync.v1_forget_import as module

    real_rmtree = module.shutil.rmtree

    def fail_for_a(path: object, *args: object, **kwargs: object) -> None:
        if Path(str(path)) == v1_dir_a:
            raise OSError("permission denied")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(module.shutil, "rmtree", fail_for_a)

    outcome = forget_v1_import("zeus", apply=True)

    assert v1_dir_a.exists()
    assert not v1_dir_b.exists()
    assert outcome.errors
    assert any(str(v1_dir_a) in error for error in outcome.errors)
