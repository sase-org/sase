from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from sase import artifact_ref_prompt
from sase.artifact_refs import (
    process_artifact_references,
    validate_artifact_references,
)

from .preprocessing_helpers import (
    context as make_context,
    disable_consumption_ledger_writes,  # noqa: F401 (registers autouse fixture)
    sidecar_sentence,
)


def test_expands_document_chat_file_and_fragments(tmp_path: Path) -> None:
    context = make_context(tmp_path)
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
        "Read "
        f"{sidecar_sentence('plans', '202607/plan.md')}, "
        f"@{chat} (time 30s), and "
        f"@{artifact} (page 2)."
    )


def test_expands_vcs_backed_file_to_materialized_cache_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = make_context(tmp_path)
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
    context = make_context(tmp_path)
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
    context = make_context(tmp_path)
    prompt = (
        "@user:handle and @plans stay\n"
        "`@plans:missing.md`\n"
        "```\n@plans:also-missing.md\n```\n"
    )

    assert process_artifact_references(prompt, context=context) == prompt


def test_unicode_before_reference_preserves_replacement_boundaries(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    plan = tmp_path / "plans" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")

    assert (
        process_artifact_references(
            "é @plans:plan.md done",
            context=context,
        )
        == f"é {sidecar_sentence('plans', 'plan.md')} done"
    )


@pytest.mark.parametrize(
    ("reference", "status"),
    (
        ("@plans:missing.md", "missing"),
        ("#ref/plans:missing.md", "missing"),
        ("@commit:unknown@abcdef0", "unknown_repo"),
        ("@plans:../escape.md", "malformed"),
        ("#ref/plans:../escape.md", "malformed"),
        ("#ref/unknown:thing.md", "unknown_kind"),
    ),
)
def test_known_reference_failure_exits_clearly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    reference: str,
    status: str,
) -> None:
    with pytest.raises(SystemExit, match="1"):
        validate_artifact_references(reference, context=make_context(tmp_path))

    output = capsys.readouterr().out
    assert reference in output
    assert status in output


def test_unpublished_entity_reference_failure_includes_publication_hint(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="1"):
        validate_artifact_references(
            "@bead:sase-missing", context=make_context(tmp_path)
        )

    output = capsys.readouterr().out
    assert "@bead:sase-missing" in output
    assert "hint: no published page for sase-missing" in output
    assert "sase bead page refresh" in output


def test_ambiguous_document_drift_fails_with_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = make_context(tmp_path)
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
    context = make_context(tmp_path)
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
            context=make_context(tmp_path),
        )
        == "#42 https://bugs.test/sase/42"
    )
