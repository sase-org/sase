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
    record = {
        "schema_version": 1,
        "recorded_at": "2026-08-01T12:00:00Z",
        "agent_artifacts_dir": str(run),
        "raw_ref": "@file.txt",
        "expanded_ref": "@file.txt",
        "ref_kind": "file",
        "label": "file.txt",
        "source_path": None,
        "sha256": "c" * 64,
        "size_bytes": 1,
        "mime_type": "text/plain",
        "pool_relpath": None,
        "vcs_repo": "primary",
        "vcs_relpath": "file.txt",
        "locator": None,
        "skipped_reason": None,
    }
    manifest.write_text(
        sase_core_rs.prompt_artifact_manifest_render_record(record) + "\n",
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


def test_missing_plans_checkout_is_a_nonfailing_warning(tmp_path: Path) -> None:
    repo = tmp_path / "agents"
    _write_prompt(
        repo,
        _prompt_document(plan_label="202608/example.md"),
    )

    validation = validate_prompt_archive(repo)

    assert validation.ok
    assert _codes(validation) == ["plan-unresolved"]
