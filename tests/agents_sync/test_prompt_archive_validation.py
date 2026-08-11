"""Validation tests for the canonical prompt and artifact archive."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import sase_core_rs

from sase.agents_sync.prompt_archive import validation as prompt_validation
from sase.agents_sync.prompt_archive.validation import validate_prompt_archive


def _prompt_document(
    *,
    artifact_target: str | None = None,
    plan_label: str | None = None,
) -> str:
    lines: list[str] = []
    if plan_label is not None:
        lines.append(
            f"- **PLAN:** [{plan_label}](https://example.test/plans/{plan_label})"
        )
    lines.extend(
        [
            "- **AGENTS:**",
            "  - [alice.athena.worker](https://example.test/agents/worker)",
        ]
    )
    if artifact_target is not None:
        lines.extend(
            [
                "- **ARTIFACTS:**",
                f"  - [diagram.png]({artifact_target})",
            ]
        )
    lines.extend(["", "# Test prompt", ""])
    return "\n".join(lines)


def _write_prompt(repo: Path, content: str, name: str = "example.md") -> Path:
    path = repo / "prompts/202608" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _codes(validation: object) -> list[str]:
    return [issue.code for issue in validation.issues]  # type: ignore[attr-defined]


def _manifest_record(run: Path) -> dict[str, object]:
    sha256 = "c" * 64
    return {
        "schema_version": sase_core_rs.prompt_artifact_wire_schema_version(),
        "recorded_at": "2026-08-01T12:00:00Z",
        "agent_artifacts_dir": str(run),
        "raw_ref": "@file.txt",
        "expanded_ref": "@file.txt",
        "ref_kind": "file",
        "label": "file.txt",
        "source_path": None,
        "sha256": sha256,
        "size_bytes": 1,
        "mime_type": "text/plain",
        "pool_relpath": None,
        "vcs_repo": "primary",
        "vcs_relpath": "file.txt",
        "locator": None,
        "skipped_reason": None,
        "logical_path": None,
        "root_name": None,
        "authored_path": None,
        "origin": None,
        "object_relpath": sase_core_rs.artifact_object_relpath(sha256),
        "sidecar_visibility": None,
    }


def test_clean_archive_validates_without_diagnostics(tmp_path: Path) -> None:
    repo = tmp_path / "agents"
    plans = tmp_path / "plans"
    (plans / "202608").mkdir(parents=True)
    (plans / "202608/example.md").write_text("# Plan\n", encoding="utf-8")
    content = b"diagram"
    digest = hashlib.sha256(content).hexdigest()
    artifact = repo / f"artifacts/202608/{digest[:12]}-diagram.png"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(content)
    _write_prompt(
        repo,
        _prompt_document(
            artifact_target=f"../../artifacts/202608/{artifact.name}",
            plan_label="202608/example.md",
        ),
    )

    validation = validate_prompt_archive(repo, plans_repo=plans)

    assert validation.ok
    assert validation.issues == ()


def test_xprompt_style_body_links_are_validated_as_ordinary_markdown(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "agents"
    _write_prompt(
        repo,
        _prompt_document() + "Use [#plan](../../xprompts/plan.md).\n",
    )

    validation = validate_prompt_archive(repo)

    assert validation.ok
    assert validation.issues == ()


def test_each_archive_diagnostic_has_a_single_purpose_built_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "agents"
    _write_prompt(repo, "---\ninvalid: [\n---\n# Broken\n", "parse.md")
    _write_prompt(
        repo,
        _prompt_document(
            artifact_target="../../artifacts/202608/aaaaaaaaaaaa-missing.png"
        ),
        "missing.md",
    )
    _write_prompt(
        repo,
        _prompt_document(artifact_target="../../artifacts/202608/bbbbbbbbbbbb-bad.png"),
        "digest.md",
    )
    bad = repo / "artifacts/202608/bbbbbbbbbbbb-bad.png"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"wrong digest")
    orphan_bytes = b"orphan"
    orphan_digest = hashlib.sha256(orphan_bytes).hexdigest()
    (repo / f"artifacts/202608/{orphan_digest[:12]}-orphan.bin").write_bytes(
        orphan_bytes
    )
    _write_prompt(
        repo,
        _prompt_document(plan_label="202608/missing-plan.md"),
        "plan.md",
    )

    workspace = tmp_path / "workspace"
    run = tmp_path / "runs/20260801120000"
    run.mkdir(parents=True)
    (run / "agent_meta.json").write_text(
        json.dumps({"name": "unpublished"}), encoding="utf-8"
    )
    manifest = workspace / ".sase/artifacts/prompt-artifacts.jsonl"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        sase_core_rs.prompt_artifact_manifest_render_record(_manifest_record(run))
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        prompt_validation, "_published_agent_name", lambda _run: "unpublished"
    )

    validation = validate_prompt_archive(
        repo,
        plans_repo=tmp_path / "missing-plans",
        workspace_roots=(workspace,),
    )

    assert _codes(validation).count("prompt-parse") == 1
    assert _codes(validation).count("artifact-missing") == 1
    assert _codes(validation).count("artifact-digest") == 1
    assert _codes(validation).count("plan-unresolved") == 1
    assert _codes(validation).count("artifact-orphan") == 1
    assert _codes(validation).count("prompt-unpublished") == 1


def test_inline_artifact_link_is_validated_outside_code_fences(tmp_path: Path) -> None:
    repo = tmp_path / "agents"
    _write_prompt(
        repo,
        _prompt_document()
        + "Use [@one](../../artifacts/202608/aaaaaaaaaaaa-one.txt).\n"
        + "```markdown\n"
        + "[@example](../../artifacts/202608/bbbbbbbbbbbb-example.txt)\n"
        + "```\n",
    )

    validation = validate_prompt_archive(repo)

    missing = [issue for issue in validation.issues if issue.code == "artifact-missing"]
    assert len(missing) == 1
    assert "aaaaaaaaaaaa-one.txt" in missing[0].message


_ERROR_CODES = (
    "artifact-missing",
    "artifact-digest",
    "prompt-parse",
)


def _write_pending_manifest_run(
    tmp_path: Path, *, agent_name: str = "unpublished"
) -> Path:
    workspace = tmp_path / "workspace"
    run = tmp_path / "runs/20260801120000"
    run.mkdir(parents=True)
    (run / "agent_meta.json").write_text(
        json.dumps({"name": agent_name}), encoding="utf-8"
    )
    manifest = workspace / ".sase/artifacts/prompt-artifacts.jsonl"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        sase_core_rs.prompt_artifact_manifest_render_record(_manifest_record(run))
        + "\n",
        encoding="utf-8",
    )
    return workspace


def test_pending_manifest_run_without_queue_entry_is_a_nonfailing_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "agents"
    workspace = _write_pending_manifest_run(tmp_path)
    monkeypatch.setattr(
        prompt_validation, "_published_agent_name", lambda _run: "unpublished"
    )

    validation = validate_prompt_archive(repo, workspace_roots=(workspace,))

    assert validation.ok
    assert _codes(validation) == ["prompt-unpublished"]
    issue = validation.issues[0]
    assert "no matching published prompt" in issue.message
    assert not any(code in _codes(validation) for code in _ERROR_CODES)


def test_pending_manifest_run_reports_unpublished_even_when_queued(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync.publication_outbox import (
        AGENT_PUBLICATION_OUTBOX_FILENAME,
        AgentPublicationOutboxItem,
    )

    repo = tmp_path / "agents"
    workspace = _write_pending_manifest_run(tmp_path, agent_name="queued-agent")
    monkeypatch.setattr(
        prompt_validation, "_published_agent_name", lambda _run: "queued-agent"
    )
    projects_root = tmp_path / "projects"
    project_dir = projects_root / "demo"
    project_dir.mkdir(parents=True)
    outbox = AgentPublicationOutboxItem(
        project_key="demo",
        project="Demo",
        local_agent="worker",
        global_agent="queued-agent",
        primary_revision="a" * 40,
        local_hood="worker",
        created_at=1.0,
        updated_at=1.0,
    )
    (project_dir / AGENT_PUBLICATION_OUTBOX_FILENAME).write_text(
        json.dumps(
            {"schema_version": 5, "items": [outbox.to_json_dict()]},
        ),
        encoding="utf-8",
    )

    validation = validate_prompt_archive(repo, workspace_roots=(workspace,))

    assert validation.ok
    assert _codes(validation) == ["prompt-unpublished"]
    issue = validation.issues[0]
    assert "no matching published prompt" in issue.message
    assert not any(code in _codes(validation) for code in _ERROR_CODES)


def test_full_validate_check_set_passes_with_pending_queue_and_unpublished_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both the plan-links check and the prompt-archive check must stay green
    while a plan's prompt has a queued but not-yet-published publication."""

    from sase.agents_sync.publication_outbox import (
        AGENT_PUBLICATION_OUTBOX_FILENAME,
        AgentPublicationOutboxItem,
    )
    from sase.sdd.links import validate_sdd_tree

    plans_root = tmp_path / "sdd"
    plan = plans_root / "plans" / "202608" / "pending.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [prompts/202608/pending.md]"
        "(https://github.com/example/project--agents/blob/main/"
        "prompts/202608/pending.md)\n\n"
        "# Plan\n",
        encoding="utf-8",
    )

    repo = tmp_path / "agents"
    workspace = _write_pending_manifest_run(tmp_path, agent_name="queued-agent")
    monkeypatch.setattr(
        prompt_validation, "_published_agent_name", lambda _run: "queued-agent"
    )
    projects_root = tmp_path / "projects"
    project_dir = projects_root / "demo"
    project_dir.mkdir(parents=True)
    outbox = AgentPublicationOutboxItem(
        project_key="demo",
        project="Demo",
        local_agent="worker",
        global_agent="queued-agent",
        primary_revision="a" * 40,
        local_hood="worker",
        created_at=1.0,
        updated_at=1.0,
    )
    (project_dir / AGENT_PUBLICATION_OUTBOX_FILENAME).write_text(
        json.dumps({"schema_version": 5, "items": [outbox.to_json_dict()]}),
        encoding="utf-8",
    )

    plan_validation = validate_sdd_tree(str(plans_root))
    prompt_validation_result = validate_prompt_archive(
        repo, workspace_roots=(workspace,)
    )

    assert plan_validation.ok
    assert prompt_validation_result.ok
    assert not any(code in _codes(prompt_validation_result) for code in _ERROR_CODES)


def test_missing_plans_checkout_is_a_nonfailing_warning(tmp_path: Path) -> None:
    repo = tmp_path / "agents"
    _write_prompt(
        repo,
        _prompt_document(plan_label="202608/example.md"),
    )

    validation = validate_prompt_archive(repo)

    assert validation.ok
    assert _codes(validation) == ["plan-unresolved"]
