from __future__ import annotations

import json
from pathlib import Path

from sase.artifact_ref_models import (
    ArtifactRef,
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefContext,
    ArtifactRefPayload,
)
from sase.artifact_providers.builtin_entry_agent import resolve_agent_entry
from sase.artifact_ref_prompt_context import PromptRefContext


def _agent_ref(name: str) -> ArtifactRef:
    return ArtifactRef(
        schema_version=5,
        kind="agent",
        kind_type="agent",
        payload=ArtifactRefPayload(type="agent", name=name),
        fragment=None,
        rendered=f"agent:{name}",
    )


def _ref_context(context: ArtifactRefContext) -> PromptRefContext:
    return PromptRefContext(
        artifact_context=context,
        project=None,
        primary_repo=None,
        workspace_dir=None,
        workspace_num=None,
        origin="explicit",
        vcs_ref=None,
    )


def _write_page(
    tmp_path: Path,
    *,
    meta: dict | None = None,
    state: dict | None = None,
    chat: bool = False,
    prompt: bool = False,
) -> tuple[ArtifactRefContext, Path]:
    root = tmp_path / "agents-sidecar"
    page_dir = root / "agents" / "alice.athena.9w"
    page_dir.mkdir(parents=True)
    (page_dir / "README.md").write_text("# Agent\n")
    if meta is not None:
        (page_dir / "meta.json").write_text(json.dumps(meta))
    if state is not None:
        (page_dir / "state.json").write_text(json.dumps(state))
    if chat:
        (page_dir / "chat.md").write_text("chat transcript")
    if prompt:
        (page_dir / "prompt.md").write_text("prompt text")

    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(),
        agent_roots=(ArtifactRefAgentRoot(project="sase", root=root),),
        agent_owner=ArtifactRefAgentOwner(username="alice", machine_name="athena"),
    )
    return context, page_dir / "README.md"


_META = {
    "schema_version": 2,
    "owner": {"username": "alice", "machine_name": "athena"},
    "project": {"key": "gh_sase-org__sase", "name": "sase"},
    "source_run_id": "abc123",
    "local_name": "9w",
    "global_name": "alice.athena.9w",
    "metadata": {
        "model": "claude-sonnet-5",
        "llm_provider": "anthropic",
        "tribe": "sase-js",
    },
}
_STATE = {
    "schema_version": 2,
    "source_run_id": "abc123",
    "state": "completed",
    "started_at": "2026-08-11T10:00:00Z",
    "finished_at": "2026-08-11T11:00:00Z",
    "dismissed_at": None,
}


def test_properties_come_from_meta_and_state_json(tmp_path: Path) -> None:
    context, readme = _write_page(tmp_path, meta=_META, state=_STATE)

    outcome = resolve_agent_entry(
        _agent_ref("9w"), context=context, ref_context=_ref_context(context)
    )

    assert outcome.status == "exact"
    assert outcome.resolved_path == readme
    assert outcome.canonical_reference == "agent:alice.athena.9w"
    assert outcome.entry is not None
    props = outcome.entry.properties
    assert props["project"] == "sase"
    assert props["agent"] == "9w"
    assert props["model"] == "claude-sonnet-5"
    assert props["llm_provider"] == "anthropic"
    assert props["tribe"] == "sase-js"
    assert props["state"] == "completed"
    assert props["started_at"] == "2026-08-11T10:00:00Z"
    assert props["finished_at"] == "2026-08-11T11:00:00Z"
    assert props["lane"] == "9w"


def test_missing_meta_and_state_drop_properties_without_failing(tmp_path: Path) -> None:
    context, readme = _write_page(tmp_path)

    outcome = resolve_agent_entry(
        _agent_ref("9w"), context=context, ref_context=_ref_context(context)
    )

    assert outcome.status == "exact"
    assert outcome.entry is not None
    assert "model" not in outcome.entry.properties
    assert "state" not in outcome.entry.properties
    assert outcome.entry.properties["lane"] == "9w"


def test_malformed_meta_json_drops_properties_without_failing(tmp_path: Path) -> None:
    context, _readme = _write_page(tmp_path)
    (
        context.agent_roots[0].root / "agents" / "alice.athena.9w" / "meta.json"
    ).write_text("not json")

    outcome = resolve_agent_entry(
        _agent_ref("9w"), context=context, ref_context=_ref_context(context)
    )

    assert outcome.status == "exact"
    assert outcome.entry is not None
    assert "model" not in outcome.entry.properties


def test_prompt_expansion_uses_centralized_agent_wording(tmp_path: Path) -> None:
    from sase.artifact_refs import process_artifact_references

    context, page = _write_page(tmp_path, chat=True, prompt=True)

    result = process_artifact_references("Look at @agent:9w.", context=context)

    assert result == "Look at the alice.athena.9w agent in the sase project."
    assert f"@{page}" not in result
    assert "prompt.md" not in result
    assert "chat.md" not in result


def test_local_and_global_agent_names_expand_to_canonical_identity(
    tmp_path: Path,
) -> None:
    from sase.artifact_refs import process_artifact_references

    context, _page = _write_page(tmp_path)

    local = process_artifact_references("Look at @agent:9w.", context=context)
    global_name = process_artifact_references(
        "Look at @agent:alice.athena.9w.", context=context
    )

    assert local == global_name
    assert local == "Look at the alice.athena.9w agent in the sase project."


def test_unresolvable_agent_has_no_entry(tmp_path: Path) -> None:
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "idx.jsonl",
        repositories=(),
        projects=(),
        agent_roots=(),
    )

    outcome = resolve_agent_entry(
        _agent_ref("nope"), context=context, ref_context=_ref_context(context)
    )

    assert outcome.status == "missing"
    assert outcome.entry is None
