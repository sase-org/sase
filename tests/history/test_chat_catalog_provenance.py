"""Headless tests for transcript sync-provenance classification and caching."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest
from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
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


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_sidecar(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q")
    _git(
        path,
        "-c",
        "user.name=SASE Tests",
        "-c",
        "user.email=sase@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "initial",
    )
    return path


def _commit_sidecar(path: Path, message: str = "publish") -> None:
    _git(path, "add", "-A")
    _git(
        path,
        "-c",
        "user.name=SASE Tests",
        "-c",
        "user.email=sase@example.invalid",
        "commit",
        "-qm",
        message,
    )


def _publication_row(
    *,
    revision: str = "a" * 40,
    local_agent: str = "alpha",
    global_agent: str = "bryan.athena.alpha",
    attempts: int = 0,
    last_error: str | None = None,
    quarantined: bool = False,
    created_at: float = 1.0,
    updated_at: float = 1.0,
) -> dict[str, object]:
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent=local_agent,
        global_agent=global_agent,
        primary_revision=revision,
        local_hood=local_agent.split(".", 1)[0],
        attempts=attempts,
        last_error=last_error,
        quarantined=quarantined,
        quarantined_at=updated_at if quarantined else None,
        created_at=created_at,
        updated_at=updated_at,
    ).to_json_dict()


def _write_outbox(
    home: Path,
    rows: list[dict[str, object]],
    *,
    schema_version: int = 2,
) -> Path:
    path = home / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": schema_version, "items": rows}),
        encoding="utf-8",
    )
    return path


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


def test_git_sidecar_reads_only_committed_tree_and_reuses_warm_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    sidecar_path = _git_sidecar(tmp_path / "sidecar")
    monkeypatch.setattr(
        sidecars, "resolve_sync_targets", lambda: _selection(sidecar_path)
    )
    chat = _chat(home, "committed-260724_100300")
    _artifact(home, "20260724100300", chat)
    published = sidecar_path / "agents" / "bryan.athena.alpha" / "chat.md"
    published.parent.mkdir(parents=True)
    published.write_text("prepared but uncommitted", encoding="utf-8")

    assert load_chat_catalog(force=True).entries[0].provenance == "local"

    _commit_sidecar(sidecar_path)
    assert load_chat_catalog().entries[0].provenance == "shared"

    real_run_git = sidecars.run_git
    tree_calls = 0

    def counting_run_git(*args, **kwargs):
        nonlocal tree_calls
        if kwargs.get("op") == "chat_catalog.sidecar_tree":
            tree_calls += 1
        return real_run_git(*args, **kwargs)

    monkeypatch.setattr(sidecars, "run_git", counting_run_git)
    assert load_chat_catalog().entries[0].provenance == "shared"
    assert tree_calls == 0


def test_committed_index_supports_v1_v2_coexisting_and_historical_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    sidecar_path = _git_sidecar(tmp_path / "sidecar")
    monkeypatch.setattr(
        sidecars, "resolve_sync_targets", lambda: _selection(sidecar_path)
    )
    local_names = (
        "v1-only",
        "v2-only",
        "coexisting",
        "4x--epic.f-0",
        "fi--code.f0",
        "fi--code.f0--plan",
        "fi--code.f0--code",
    )
    for index, local_name in enumerate(local_names):
        chat = _chat(home, f"names-{index}-260724_1004{index:02d}")
        _artifact(
            home,
            f"202607241004{index:02d}",
            chat,
            name=local_name,
        )
    published_names = {
        "athena.v1-only",
        "bryan.athena.v2-only",
        "athena.coexisting",
        "bryan.athena.coexisting",
        *(
            f"bryan.athena.{name}"
            for name in local_names
            if name not in {"v1-only", "v2-only", "coexisting"}
        ),
    }
    for name in published_names:
        path = sidecar_path / "agents" / name / "chat.md"
        path.parent.mkdir(parents=True)
        path.write_text(name, encoding="utf-8")
    _commit_sidecar(sidecar_path)

    snapshot = load_chat_catalog(force=True)

    assert {entry.provenance for entry in snapshot.entries} == {"shared"}
    by_local_name = {entry.agent_local_name: entry for entry in snapshot.entries}
    assert by_local_name["v1-only"].sidecar_relpath == ("agents/athena.v1-only/chat.md")
    assert by_local_name["v2-only"].sidecar_relpath == (
        "agents/bryan.athena.v2-only/chat.md"
    )
    assert by_local_name["coexisting"].sidecar_relpath == (
        "agents/bryan.athena.coexisting/chat.md"
    )
    for historical_name in local_names[3:]:
        assert by_local_name[historical_name].sidecar_relpath == (
            f"agents/bryan.athena.{historical_name}/chat.md"
        )


def test_git_tree_failure_never_falls_back_to_dirty_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    sidecar_path = _git_sidecar(tmp_path / "sidecar")
    monkeypatch.setattr(
        sidecars, "resolve_sync_targets", lambda: _selection(sidecar_path)
    )
    chat = _chat(home, "tree-failure-260724_100500")
    _artifact(home, "20260724100500", chat)
    dirty = sidecar_path / "agents" / "bryan.athena.alpha" / "chat.md"
    dirty.parent.mkdir(parents=True)
    dirty.write_text("dirty", encoding="utf-8")
    real_run_git = sidecars.run_git

    def failing_tree(cwd, args, **kwargs):
        if kwargs.get("op") == "chat_catalog.sidecar_tree":
            return subprocess.CompletedProcess(args, 1, "", "tree unavailable")
        return real_run_git(cwd, args, **kwargs)

    monkeypatch.setattr(sidecars, "run_git", failing_tree)

    snapshot = load_chat_catalog(force=True)

    assert snapshot.entries[0].provenance == "unknown"
    assert any("tree unavailable" in item for item in snapshot.diagnostics)


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
    row = _publication_row(attempts=28, last_error="network down")
    row.pop("quarantined")
    row.pop("quarantined_at")
    outbox = _write_outbox(
        home,
        [row],
        schema_version=1,
    )

    entry = load_chat_catalog(force=True).entries[0]

    assert entry.publication_pending is True
    assert entry.publication_quarantined is False
    assert entry.publication_disposition == "queued"
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
    outbox = _write_outbox(
        home,
        [
            _publication_row(
                attempts=3,
                last_error="remote rejected update",
                quarantined=True,
            )
        ],
    )

    entry = load_chat_catalog(force=True).entries[0]

    assert entry.publication_pending is False
    assert entry.publication_quarantined is True
    assert entry.publication_disposition == "quarantined"
    assert entry.publication_attempts == 3
    assert entry.publication_last_error == "remote rejected update"
    assert not outbox.with_suffix(".json.lock").exists()


def test_malformed_publication_state_becomes_catalog_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "malformed-260724_160200")
    _artifact(home, "20260724160200", chat)
    row = _publication_row()
    row["quarantined"] = 1
    _write_outbox(home, [row])

    snapshot = load_chat_catalog(force=True)

    assert snapshot.entries[0].provenance == "local"
    assert snapshot.entries[0].publication_disposition is None
    assert any("quarantined must be a boolean" in item for item in snapshot.diagnostics)


def test_multiple_publication_revisions_aggregate_deterministically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "aggregate-260724_160300")
    _artifact(home, "20260724160300", chat)

    cases = (
        (
            [
                _publication_row(
                    revision="a" * 40,
                    attempts=7,
                    last_error="older active",
                    updated_at=10.0,
                ),
                _publication_row(
                    revision="b" * 40,
                    attempts=2,
                    last_error="newer active",
                    updated_at=20.0,
                ),
            ],
            ("queued", True, False, 7, "newer active"),
        ),
        (
            [
                _publication_row(
                    revision="a" * 40,
                    attempts=3,
                    last_error="older quarantine",
                    quarantined=True,
                    updated_at=10.0,
                ),
                _publication_row(
                    revision="b" * 40,
                    attempts=5,
                    last_error="newer quarantine",
                    quarantined=True,
                    updated_at=20.0,
                ),
            ],
            ("quarantined", False, True, 5, "newer quarantine"),
        ),
        (
            [
                _publication_row(
                    revision="a" * 40,
                    attempts=8,
                    last_error="active max attempts",
                    updated_at=10.0,
                ),
                _publication_row(
                    revision="b" * 40,
                    attempts=4,
                    last_error="newest quarantined",
                    quarantined=True,
                    updated_at=20.0,
                ),
            ],
            ("mixed", True, False, 8, "newest quarantined"),
        ),
    )
    for rows, expected in cases:
        _write_outbox(home, rows)
        entry = load_chat_catalog().entries[0]
        assert (
            entry.publication_disposition,
            entry.publication_pending,
            entry.publication_quarantined,
            entry.publication_attempts,
            entry.publication_last_error,
        ) == expected


def test_remote_provenance_suppresses_colliding_local_publication_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "remote-collision-260724_160400")
    _artifact(
        home,
        "20260724160400",
        chat,
        name="alpha",
        meta_extra={
            "canonical_global_name": "bryan.athena.alpha",
            "imported_source_owner": {
                "username": "alice",
                "machine_name": "zeus",
            },
        },
    )
    _write_outbox(
        home,
        [
            _publication_row(
                attempts=2,
                last_error="local collision",
            )
        ],
    )

    entry = load_chat_catalog(force=True).entries[0]

    assert entry.provenance == "remote"
    assert entry.publication_pending is False
    assert entry.publication_quarantined is False
    assert entry.publication_attempts is None
    assert entry.publication_last_error is None
    assert entry.publication_disposition is None


def test_publication_transition_preserves_provenance_and_catalog_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    sidecar_path = _git_sidecar(tmp_path / "sidecar")
    monkeypatch.setattr(
        sidecars, "resolve_sync_targets", lambda: _selection(sidecar_path)
    )
    chat = _chat(home, "transition-260724_160500")
    _artifact(home, "20260724160500", chat)
    active = _publication_row(
        revision="a" * 40,
        attempts=1,
        last_error="push pending",
        updated_at=10.0,
    )
    quarantined = _publication_row(
        revision="a" * 40,
        attempts=3,
        last_error="prepare failed",
        quarantined=True,
        updated_at=20.0,
    )

    _write_outbox(home, [active])
    entry = load_chat_catalog(force=True).entries[0]
    assert (entry.provenance, entry.publication_disposition) == (
        "local",
        "queued",
    )

    _write_outbox(home, [quarantined])
    entry = load_chat_catalog().entries[0]
    assert (entry.provenance, entry.publication_disposition) == (
        "local",
        "quarantined",
    )

    published = sidecar_path / "agents" / "bryan.athena.alpha" / "chat.md"
    published.parent.mkdir(parents=True)
    published.write_text("prepared", encoding="utf-8")
    assert load_chat_catalog(force=True).entries[0].provenance == "local"

    _write_outbox(home, [active])
    _commit_sidecar(sidecar_path)
    entry = load_chat_catalog().entries[0]
    assert (entry.provenance, entry.publication_disposition) == (
        "shared",
        "queued",
    )

    _write_outbox(home, [quarantined])
    entry = load_chat_catalog().entries[0]
    assert (entry.provenance, entry.publication_disposition) == (
        "shared",
        "quarantined",
    )

    later_quarantined = _publication_row(
        revision="b" * 40,
        attempts=4,
        last_error="later revision failed",
        quarantined=True,
        updated_at=30.0,
    )
    _write_outbox(home, [active, later_quarantined])
    entry = load_chat_catalog().entries[0]
    assert (entry.provenance, entry.publication_disposition) == (
        "shared",
        "mixed",
    )

    _write_outbox(home, [])
    entry = load_chat_catalog().entries[0]
    assert entry.provenance == "shared"
    assert entry.publication_disposition is None


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
