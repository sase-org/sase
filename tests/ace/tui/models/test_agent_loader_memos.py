from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.models import agent_workspace_retention, artifact_files
from sase.ace.tui.models._loader_memos import agent_loader_memos
from sase.macro.project_identity import (
    load_project_alias_map,
    project_identity_load_scope,
)


def test_workspace_retention_and_ttl_are_memoized_per_loader_batch(monkeypatch) -> None:
    read_calls: list[str | None] = []
    ttl_calls: list[None] = []
    record = SimpleNamespace(terminal=True, unresolved=True)
    monkeypatch.setattr(
        agent_workspace_retention,
        "read_workspace_retention_record",
        lambda artifacts_dir: read_calls.append(artifacts_dir) or record,
    )
    monkeypatch.setattr(
        "sase.workspace_provider.retention_record.configured_held_claim_ttl_days",
        lambda: ttl_calls.append(None) or 14,
    )

    with agent_loader_memos():
        first = agent_workspace_retention.load_agent_workspace_retention("/artifacts/a")
        repeated = agent_workspace_retention.load_agent_workspace_retention(
            "/artifacts/a"
        )
        agent_workspace_retention.load_agent_workspace_retention("/artifacts/b")

    assert first is repeated
    assert read_calls == ["/artifacts/a", "/artifacts/b"]
    assert ttl_calls == [None]

    with agent_loader_memos():
        agent_workspace_retention.load_agent_workspace_retention("/artifacts/a")

    assert read_calls == ["/artifacts/a", "/artifacts/b", "/artifacts/a"]
    assert ttl_calls == [None, None]


def test_artifacts_dir_is_memoized_per_agent_and_batch(monkeypatch) -> None:
    calls: list[object] = []
    agent = object()
    monkeypatch.setattr(
        artifact_files,
        "_get_artifacts_dir_uncached",
        lambda value: calls.append(value) or "/artifacts/a",
    )

    with agent_loader_memos():
        assert artifact_files.get_artifacts_dir(agent) == "/artifacts/a"
        assert artifact_files.get_artifacts_dir(agent) == "/artifacts/a"
    with agent_loader_memos():
        assert artifact_files.get_artifacts_dir(agent) == "/artifacts/a"

    assert calls == [agent, agent]


def test_project_alias_map_is_shared_inside_one_loader_scope(monkeypatch) -> None:
    calls: list[None] = []
    aliases = {"alias": "project"}
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda: calls.append(None) or aliases,
    )

    with project_identity_load_scope():
        first = load_project_alias_map()
        repeated = load_project_alias_map()
    assert first is aliases
    assert repeated is aliases
    assert calls == [None]

    with project_identity_load_scope():
        assert load_project_alias_map() is aliases
    assert calls == [None, None]
