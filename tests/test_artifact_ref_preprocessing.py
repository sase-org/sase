from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest
import sase_core_rs

from sase import artifact_ref_prompt
from sase.artifact_refs import (
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefProject,
    ArtifactRefRepository,
    process_artifact_references,
    validate_artifact_references,
)
from sase.llm_provider.preprocessing import preprocess_prompt_late
from sase.file_references import process_file_references


@pytest.fixture(autouse=True)
def _disable_consumption_ledger_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda _events: None,
    )


def _context(tmp_path: Path) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(
            ArtifactRefDocumentRoot("plans", tmp_path / "plans"),
            ArtifactRefDocumentRoot("designs", tmp_path / "designs"),
        ),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(
            ArtifactRefRepository(
                "sase",
                aliases=("sase-org/sase",),
                checkout_path=tmp_path / "workspace",
            ),
        ),
        projects=(
            ArtifactRefProject(
                name="sase",
                key="gh_sase-org__sase",
            ),
        ),
        bead_stores=(
            ArtifactRefBeadStore(
                project="sase",
                prefix="sase",
                root=tmp_path / "beads",
            ),
        ),
        agent_roots=(
            ArtifactRefAgentRoot(
                project="sase",
                root=tmp_path / "agents-sidecar",
            ),
        ),
        agent_owner=ArtifactRefAgentOwner(
            username="alice",
            machine_name="athena",
        ),
    )


def test_expands_document_chat_file_and_fragments(tmp_path: Path) -> None:
    context = _context(tmp_path)
    plan = tmp_path / "plans" / "202607" / "plan.md"
    chat = tmp_path / "chats" / "202607" / "agent.md"
    artifact = tmp_path / "figure.png"
    plan.parent.mkdir(parents=True)
    chat.parent.mkdir(parents=True)
    context.artifact_index_path.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")
    chat.write_text("# Chat\n", encoding="utf-8")
    artifact.write_bytes(b"png")
    artifact_id = "default:52895d68931185056fd0e49f"
    context.artifact_index_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact": {"id": artifact_id, "path": str(artifact)},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    prompt = (
        "Read @plans:202607/plan.md#L2-L4, "
        "@chat:202607/agent.md#t=30, and "
        f"@file:{artifact_id}#page=2."
    )

    assert process_artifact_references(prompt, context=context) == (
        f"Read @{plan} (lines 2-4), @{chat} (time 30s), and @{artifact} (page 2)."
    )


def test_expands_vcs_backed_file_to_materialized_cache_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "-C", str(workspace), "init"], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(workspace), "config", "user.name", "Test"],
        check=True,
    )
    source = workspace / "docs" / "report.md"
    source.parent.mkdir()
    content = b"# exact report\n"
    source.write_bytes(content)
    subprocess.run(
        ["git", "-C", str(workspace), "add", "docs/report.md"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-m", "add report"],
        check=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    artifact_id = "default:52895d68931185056fd0e49f"
    context.artifact_index_path.parent.mkdir(parents=True)
    context.artifact_index_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artifact": {
                    "id": artifact_id,
                    "label": "report.md",
                    "kind": "markdown",
                    "path": None,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                    "mime_type": "text/markdown",
                    "vcs_repo": "sase",
                    "vcs_sha": sha,
                    "vcs_relpath": "docs/report.md",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cache_root = tmp_path / "artifact-cache"
    monkeypatch.setattr(
        "sase.core.artifact_file_vcs.default_artifact_files_root",
        lambda: cache_root,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_query_facade.ARTIFACT_FILE_QUERY_WIRE_SCHEMA_VERSION",
        3,
    )
    recorded = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: recorded.extend(events),
    )

    expanded = process_artifact_references(
        f"Read @file:{artifact_id}.",
        context=context,
    )

    materialized = Path(expanded.removeprefix("Read @").removesuffix("."))
    assert materialized.read_bytes() == content
    assert materialized.is_relative_to(cache_root / "vcs-cache")
    assert len(recorded) == 1
    assert recorded[0].ref == f"file:{artifact_id}"
    assert recorded[0].artifact_id == artifact_id
    assert recorded[0].resolved_path == str(materialized)
    assert recorded[0].role == "report"


def test_expands_bead_and_agent_pages(tmp_path: Path) -> None:
    context = _context(tmp_path)
    bead_page = context.bead_stores[0].root / "pages" / "sase-9z" / "README.md"
    agent_page = (
        context.agent_roots[0].root / "agents" / "alice.athena.9w" / "README.md"
    )
    bead_page.parent.mkdir(parents=True)
    agent_page.parent.mkdir(parents=True)
    bead_page.write_text("# Bead\n", encoding="utf-8")
    agent_page.write_text("# Agent\n", encoding="utf-8")

    assert (
        process_artifact_references(
            "Read @bead:sase-9z and @agent:9w.",
            context=context,
        )
        == f"Read @{bead_page} and @{agent_page}."
    )


def test_unknown_bare_and_literal_references_survive_byte_identically(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    prompt = (
        "@user:handle and @plans stay\n"
        "`@plans:missing.md`\n"
        "```\n@plans:also-missing.md\n```\n"
    )

    assert process_artifact_references(prompt, context=context) == prompt


def test_unicode_before_reference_preserves_replacement_boundaries(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    plan = tmp_path / "plans" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")

    assert (
        process_artifact_references(
            "é @plans:plan.md done",
            context=context,
        )
        == f"é @{plan} done"
    )


@pytest.mark.parametrize(
    ("reference", "status"),
    (
        ("@plans:missing.md", "missing"),
        ("@commit:unknown@abcdef0", "unknown_repo"),
        ("@plans:../escape.md", "malformed"),
    ),
)
def test_known_reference_failure_exits_clearly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    reference: str,
    status: str,
) -> None:
    with pytest.raises(SystemExit, match="1"):
        validate_artifact_references(reference, context=_context(tmp_path))

    output = capsys.readouterr().out
    assert reference in output
    assert status in output


def test_unpublished_entity_reference_failure_includes_publication_hint(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="1"):
        validate_artifact_references("@bead:sase-missing", context=_context(tmp_path))

    output = capsys.readouterr().out
    assert "@bead:sase-missing" in output
    assert "hint: no published page for sase-missing" in output
    assert "sase bead page refresh" in output


def test_ambiguous_document_drift_fails_with_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = _context(tmp_path)
    for month in ("202606", "202607"):
        path = tmp_path / "plans" / month / "plan.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Plan\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="1"):
        process_artifact_references(
            "@plans:202605/plan.md",
            context=context,
        )

    assert "ambiguous" in capsys.readouterr().out


def test_commit_expands_to_full_locator_and_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    full_sha = "a" * 40
    monkeypatch.setattr(
        artifact_ref_prompt,
        "_resolve_checkout_commit",
        lambda _path, _sha: full_sha,
    )

    assert (
        process_artifact_references(
            "@commit:sase@aaaaaaa",
            context=context,
        )
        == f"sase@{full_sha} (checkout: {tmp_path / 'workspace'})"
    )


def test_bug_expands_to_number_and_resolved_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        artifact_ref_prompt,
        "_resolved_bug_url",
        lambda project, number: f"https://bugs.test/{project}/{number}",
    )

    assert (
        process_artifact_references(
            "@bug:gh_sase-org__sase#42",
            context=_context(tmp_path),
        )
        == "#42 https://bugs.test/sase/42"
    )


def test_rewrite_records_one_edge_per_expanded_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    chat = tmp_path / "chats" / "agent.md"
    plan.parent.mkdir(parents=True)
    chat.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    chat.write_text("# Chat\n", encoding="utf-8")
    recorded = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: recorded.extend(events),
    )

    process_artifact_references(
        "Read @plans:report.md and @chat:agent.md.",
        context=context,
    )

    assert [event.ref for event in recorded] == [
        "plans:report.md",
        "chat:agent.md",
    ]
    assert [event.ref_kind for event in recorded] == ["plans", "chat"]
    assert [event.role for event in recorded] == ["report", "report"]
    assert [event.resolved_path for event in recorded] == [
        str(plan),
        str(chat),
    ]


def test_rewrite_stages_the_same_resolved_reference_list(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    staged: list[dict[str, object]] = []
    monkeypatch.setattr(
        "sase.core.prompt_artifact_staging.stage_prompt_artifact",
        lambda **kwargs: staged.append(kwargs),
    )

    process_artifact_references("Read @plans:report.md.", context=context)

    assert staged == [
        {
            "raw_ref": "@plans:report.md",
            "expanded_ref": f"@{plan}",
            "resolved_path": plan,
            "ref_kind": "plans",
            "label": "report.md",
            "locator": None,
        }
    ]


def test_home_mode_does_not_stage_artifact_references(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    staged: list[dict[str, object]] = []
    monkeypatch.setattr(
        "sase.core.prompt_artifact_staging.stage_prompt_artifact",
        lambda **kwargs: staged.append(kwargs),
    )

    process_artifact_references(
        "Read @plans:report.md.",
        context=context,
        is_home_mode=True,
    )

    assert staged == []


def test_artifact_expansion_is_not_restaged_as_plain_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "run"))
    staged_paths: set[str] = set()

    expanded = process_artifact_references(
        "Read @plans:report.md.",
        context=context,
        staged_file_paths=staged_paths,
    )
    process_file_references(expanded, staged_file_paths=staged_paths)

    manifest = tmp_path / ".sase/artifacts/prompt-artifacts.jsonl"
    rows = sase_core_rs.prompt_artifact_manifest_parse(manifest.read_bytes())
    assert len(rows) == 1
    assert rows[0]["raw_ref"] == "@plans:report.md"


def test_fragment_is_recorded_separately_from_fragment_free_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    recorded = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: recorded.extend(events),
    )

    process_artifact_references(
        "@plans:report.md#L2-L4",
        context=context,
    )

    assert len(recorded) == 1
    assert recorded[0].ref == "plans:report.md"
    assert recorded[0].fragment == "L2-L4"


def test_bug_payload_hash_is_preserved_in_recorded_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recorded = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "_resolved_bug_url",
        lambda project, number: f"https://bugs.test/{project}/{number}",
    )
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: recorded.extend(events),
    )

    process_artifact_references(
        "@bug:gh_sase-org__sase#42",
        context=_context(tmp_path),
    )

    assert len(recorded) == 1
    assert recorded[0].ref == "bug:gh_sase-org__sase#42"
    assert recorded[0].fragment is None
    assert recorded[0].role == "source"


def test_duplicate_refs_in_one_prompt_record_one_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    recorded = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: recorded.extend(events),
    )

    process_artifact_references(
        "@plans:report.md and @plans:report.md#L2",
        context=context,
    )

    assert len(recorded) == 1
    assert recorded[0].ref == "plans:report.md"


def test_validation_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")
    append_calls = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: append_calls.append(tuple(events)),
    )

    validate_artifact_references("@plans:report.md", context=context)

    assert append_calls == []


def test_failed_expansion_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    append_calls = []
    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        lambda events: append_calls.append(tuple(events)),
    )

    with pytest.raises(SystemExit, match="1"):
        process_artifact_references(
            "@plans:missing.md",
            context=_context(tmp_path),
        )

    assert append_calls == []


def test_recorder_failure_does_not_change_expansion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    plan = tmp_path / "plans" / "report.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Report\n", encoding="utf-8")

    def fail(_events: object) -> None:
        raise OSError("ledger unavailable")

    monkeypatch.setattr(
        artifact_ref_prompt,
        "append_artifact_consumption_events",
        fail,
    )

    assert (
        process_artifact_references(
            "Read @plans:report.md.",
            context=context,
        )
        == f"Read @{plan}."
    )


def test_late_preprocessing_expands_artifacts_before_file_refs(
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, bool]] = []

    def expand(
        prompt: str,
        *,
        is_home_mode: bool,
        staged_file_paths: set[str],
    ) -> str:
        assert staged_file_paths == set()
        seen.append(("artifact", is_home_mode))
        return prompt.replace("@plans:x.md", "@/resolved/x.md")

    def process(
        prompt: str,
        *,
        is_home_mode: bool,
        staged_file_paths: set[str],
    ) -> str:
        assert staged_file_paths == set()
        seen.append(("file", is_home_mode))
        assert "@/resolved/x.md" in prompt
        return prompt

    with (
        patch(
            "sase.artifact_refs.process_artifact_references",
            side_effect=expand,
        ),
        patch(
            "sase.file_references.process_file_references",
            side_effect=process,
        ),
    ):
        preprocess_prompt_late(
            "@plans:x.md",
            is_home_mode=True,
        )

    assert seen == [("artifact", True), ("file", True)]
