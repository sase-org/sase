"""Headless tests for transcript sync-provenance classification and caching."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.history import chat_catalog
from sase.history.chat_catalog_provenance import load_chat_catalog
from sase.history.chat_catalog_provenance import (
    artifacts,
    cache as provenance_cache,
    catalog,
    sidecars,
)

from tests.conftest import redirect_sase_home


def _setup_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / ".sase"
    home.mkdir()
    redirect_sase_home(monkeypatch, home)
    owner = AgentOwnerIdentity("bryan", "athena")
    monkeypatch.setattr(catalog, "get_agent_owner_identity", lambda: owner)
    monkeypatch.setattr(artifacts, "get_agent_owner_identity", lambda: owner)
    return home


def _chat(home: Path, name: str, *, prompt: str = "hello") -> Path:
    path = home / "chats" / "202607" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "# Chat History - ace-run (alpha)\n\n"
            f"## Prompt\n\n{prompt}\n\n"
            "## Response\n\ndone\n"
        ),
        encoding="utf-8",
    )
    return path


def _artifact(
    home: Path,
    timestamp: str,
    chat_path: Path,
    *,
    name: str = "alpha",
    meta_extra: dict[str, object] | None = None,
    done_extra: dict[str, object] | None = None,
) -> Path:
    path = home / "projects" / "proj" / "artifacts" / "ace-run" / timestamp
    path.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {"name": name, "chat_path": str(chat_path)}
    meta.update(meta_extra or {})
    done: dict[str, object] = {
        "name": name,
        "response_path": str(chat_path),
        "finished_at": 1.0,
    }
    done.update(done_extra or {})
    (path / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (path / "done.json").write_text(json.dumps(done), encoding="utf-8")
    return path


def _selection(sidecar_path: Path) -> TargetSelection:
    target = ProjectTarget(
        project_key="proj",
        project="Project",
        primary_checkout=sidecar_path.parent / "primary",
        primary_roots=(),
        sidecar_path=sidecar_path,
        remote_url="git@example.invalid:agents.git",
    )
    return TargetSelection((target,), ())


def _readable_sidecar(path: Path) -> Path:
    agents = path / "agents"
    agents.mkdir(parents=True)
    return agents


def test_classifies_local_shared_and_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    sidecar_path = tmp_path / "sidecar"
    agents = _readable_sidecar(sidecar_path)
    monkeypatch.setattr(
        sidecars, "resolve_sync_targets", lambda: _selection(sidecar_path)
    )

    local_chat = _chat(home, "local-260724_100000")
    shared_chat = _chat(home, "shared-260724_100100")
    remote_chat = _chat(home, "remote-260724_100200")
    _artifact(home, "20260724100000", local_chat, name="local-agent")
    _artifact(home, "20260724100100", shared_chat, name="shared-agent")
    _artifact(
        home,
        "20260724100200",
        remote_chat,
        name="zeus.remote-agent",
        meta_extra={
            "canonical_global_name": "alice.zeus.remote-agent",
            "imported_source_owner": {
                "username": "alice",
                "machine_name": "zeus",
            },
        },
    )
    published = agents / "bryan.athena.shared-agent"
    published.mkdir()
    (published / "chat.md").write_text("published", encoding="utf-8")

    snapshot = load_chat_catalog(force=True)
    by_name = {entry.basename: entry for entry in snapshot.entries}

    assert by_name[local_chat.stem].provenance == "local"
    assert by_name[shared_chat.stem].provenance == "shared"
    assert by_name[shared_chat.stem].sidecar_relpath == (
        "agents/bryan.athena.shared-agent/chat.md"
    )
    remote = by_name[remote_chat.stem]
    assert remote.provenance == "remote"
    assert remote.source_username == "alice"
    assert remote.source_machine == "zeus"
    assert snapshot.provenance_counts == {
        "local": 1,
        "shared": 1,
        "remote": 1,
        "unknown": 0,
    }
    assert snapshot.remote_machines == frozenset({"zeus"})


def test_missing_sidecar_is_unknown_with_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    missing = tmp_path / "missing-sidecar"
    monkeypatch.setattr(sidecars, "resolve_sync_targets", lambda: _selection(missing))
    chat = _chat(home, "unknown-260724_110000")
    _artifact(home, "20260724110000", chat)

    snapshot = load_chat_catalog(force=True)

    assert snapshot.entries[0].provenance == "unknown"
    assert any("Project" in diagnostic for diagnostic in snapshot.diagnostics)


def test_no_configured_sidecar_and_unlinked_chat_are_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    linked = _chat(home, "linked-260724_120000")
    unlinked = _chat(home, "mentor-260724_120100")
    _artifact(home, "20260724120000", linked)

    snapshot = load_chat_catalog(force=True)

    assert {entry.basename: entry.provenance for entry in snapshot.entries} == {
        linked.stem: "local",
        unlinked.stem: "local",
    }
    assert snapshot.diagnostics == ()


def test_imported_shard_fallback_is_remote_without_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = home / "chats" / "v2-abc" / "imported-v2-alpha-v2-abcdef.md"
    chat.parent.mkdir(parents=True)
    chat.write_text("# Chat History - ace-run\n", encoding="utf-8")

    snapshot = load_chat_catalog(force=True)

    assert snapshot.entries[0].provenance == "remote"
    assert snapshot.entries[0].agent_artifact_dir is None


def test_newest_artifact_is_primary_and_others_are_retained_in_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "shared-link-260724_130000")
    older = _artifact(
        home,
        "20260724130000",
        chat,
        done_extra={"finished_at": 10.0},
    )
    newer = _artifact(
        home,
        "20260724130100",
        chat,
        done_extra={"finished_at": 20.0},
    )

    snapshot = load_chat_catalog(force=True)
    assert snapshot.entries[0].agent_artifact_dir == str(newer)

    with provenance_cache.open_catalog_cache() as cache:
        links = artifacts.load_agent_links(cache, force=False)
    link = links[str(chat.resolve())]
    assert link.artifact_dirs == (str(newer), str(older))


def test_warm_cache_skips_head_reads_and_mtime_invalidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "cache-260724_140000", prompt="cold")
    calls = 0
    real_read_head = chat_catalog._read_head

    def counting_read_head(path: Path) -> str:
        nonlocal calls
        calls += 1
        return real_read_head(path)

    monkeypatch.setattr(chat_catalog, "_read_head", counting_read_head)
    cold = load_chat_catalog(force=True)
    assert calls == 1
    warm = load_chat_catalog()
    assert calls == 1
    assert warm == cold

    chat.write_text(
        "# Chat History - ace-run\n\n## Prompt\n\nchanged\n",
        encoding="utf-8",
    )
    stat = chat.stat()
    os.utime(chat, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    changed = load_chat_catalog()

    assert calls == 2
    assert changed.entries[0].prompt_snippet == "changed"


def test_filters_counts_and_limit_use_full_filtered_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    for index in range(3):
        _chat(home, f"query-{index}-260724_15000{index}", prompt="needle")

    snapshot = load_chat_catalog(limit=1, query="needle", provenance="local")

    assert len(snapshot.entries) == 1
    assert snapshot.truncated is True
    assert snapshot.provenance_counts["local"] == 3


def test_schema_v1_publication_backlog_is_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "pending-260724_160000")
    _artifact(home, "20260724160000", chat)
    outbox = home / "projects" / "proj" / "agents-publication-outbox.json"
    outbox.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": [
                    {
                        "global_agent": "bryan.athena.alpha",
                        "local_agent": "alpha",
                        "attempts": 28,
                        "last_error": "network down",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    entry = load_chat_catalog(force=True).entries[0]

    assert entry.publication_pending is True
    assert entry.publication_quarantined is False
    assert entry.publication_attempts == 28
    assert entry.publication_last_error == "network down"
    assert not outbox.with_suffix(".json.lock").exists()


def test_schema_v2_quarantined_publication_is_not_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "quarantined-260724_160100")
    _artifact(home, "20260724160100", chat)
    outbox = home / "projects" / "proj" / "agents-publication-outbox.json"
    outbox.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "items": [
                    {
                        "global_agent": "bryan.athena.alpha",
                        "local_agent": "alpha",
                        "attempts": 3,
                        "last_error": "remote rejected update",
                        "quarantined": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    entry = load_chat_catalog(force=True).entries[0]

    assert entry.publication_pending is False
    assert entry.publication_quarantined is True
    assert entry.publication_attempts == 3
    assert entry.publication_last_error == "remote rejected update"
    assert not outbox.with_suffix(".json.lock").exists()


def test_publication_quarantine_requires_a_json_boolean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    project_dir = home / "projects" / "proj"
    project_dir.mkdir(parents=True)
    (project_dir / "agents-publication-outbox.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "items": [
                    {
                        "global_agent": "bryan.athena.alpha",
                        "local_agent": "alpha",
                        "quarantined": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    backlog = sidecars.load_publication_backlog()

    assert backlog[("proj", "alpha")].quarantined is False


def test_corrupt_catalog_cache_is_rebuilt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "rebuild-260724_170000")
    (home / "chats_catalog.sqlite").write_bytes(b"not sqlite")

    snapshot = load_chat_catalog()

    assert snapshot.entries[0].absolute_path == str(chat)
