"""Coverage for the finalizer declaration channel."""

from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

from sase.finalizers import declaration as declaration_module
from sase.finalizers.declaration import (
    FINAL_CONTEXT_FILENAME,
    FINAL_CONTEXT_HOST_FILENAME,
    FINAL_SUBMISSION_FILENAME,
    FINAL_SUBMISSION_HOST_FILENAME,
    FinalizerDeclarationError,
    final_submission_is_current,
    load_accepted_host_repositories,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.main.parser import create_parser
from sase.xprompt.directives import PromptDirectives

from .finalizer_declaration_channel_test_helpers import (
    attempt_records,
    clean_state,
    dirty_state,
    prepare_agent_env,
    prepare_dirty_declaration,
    valid_manifest,
)

_COMMIT_DECLARATION_HELPERS = (
    "accepted_context_from_submission",
    "hold_finalizer_declaration_lock",
    "load_accepted_host_repositories",
    "load_finalizer_plan",
    "load_latest_finalizer_context",
    "load_latest_finalizer_submission",
    "normalize_submission_envelope",
    "repository_obligation_id",
    "repository_state_digest",
    "require_artifacts_dir",
    "validate_provider_payloads",
)


def test_final_parser_registers_context_and_submit() -> None:
    parser = create_parser(only="final")

    context_args = parser.parse_args(["final", "context", "-f", "json"])
    submit_args = parser.parse_args(["final", "submit", "-"])

    assert context_args.command == "final"
    assert context_args.final_subcommand == "context"
    assert context_args.format == "json"
    assert submit_args.final_subcommand == "submit"
    assert submit_args.manifest == "-"


def test_context_publishes_opaque_dirty_repository_obligation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)

    publication = publish_final_context()

    context = publication.payload["context"]
    obligations = context["obligations"]
    assert publication.payload["submission_required"] is True
    assert context["run_id"] == "run-1"
    assert context["agent_id"] == "agent-1"
    assert context["turn_nonce"] == "nonce-1"
    assert context["requirements"][0]["trigger"] == "dirty_repository"
    assert context["requirements"][0]["submission_required"] is True
    assert obligations[0]["obligation_id"].startswith("repo-")
    assert obligations[0]["kind"] == "repository"
    assert obligations[0]["paths"] == ["src/app.py"]
    assert str(tmp_path) not in json.dumps(publication.payload)
    assert (tmp_path / FINAL_CONTEXT_FILENAME).is_file()


def test_submit_accepts_manifest_and_retains_invalid_attempt_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    accepted = submit_final_manifest(manifest)

    stale = deepcopy(manifest)
    stale["context_digest"] = "0" * 64
    with pytest.raises(FinalizerDeclarationError, match="context"):
        submit_final_manifest(stale)

    assert accepted["validation"]["accepted_instances"] == ["commit"]
    assert (tmp_path / FINAL_SUBMISSION_FILENAME).is_file()
    attempts = attempt_records(tmp_path)
    assert attempts[-2]["accepted"] is True
    assert attempts[-1]["accepted"] is False
    assert attempts[-1]["content_digest"]


def test_submit_rejects_dirty_fingerprint_changed_since_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprints = {"src/app.py": ("M", "abc123")}
    prepare_dirty_declaration(monkeypatch, tmp_path, fingerprints=fingerprints)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    fingerprints["src/app.py"] = ("M", "def456")

    with pytest.raises(FinalizerDeclarationError, match="rerun `sase final context`"):
        submit_final_manifest(manifest)

    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()
    assert not (tmp_path / FINAL_SUBMISSION_HOST_FILENAME).exists()
    attempts = attempt_records(tmp_path)
    assert attempts[-1]["accepted"] is False
    assert attempts[-1]["code"] == "stale_final_context"
    assert "rerun `sase final context`" in str(attempts[-1]["message"])
    assert attempts[-1]["content_digest"]


def test_submit_rejects_dirty_context_that_became_clean_before_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dirty = {"value": True}
    prepare_dirty_declaration(
        monkeypatch,
        tmp_path,
        collect=lambda _root: (
            dirty_state(tmp_path) if dirty["value"] else clean_state(tmp_path)
        ),
    )
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    dirty["value"] = False

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "stale_final_context"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()
    refreshed = publish_final_context()
    assert refreshed.submission_required is False
    assert refreshed.payload["manifest_template"]["payloads"] == []
    assert final_submission_is_current(artifacts_dir=str(tmp_path)) is True


def test_submit_rejects_host_repository_snapshot_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    host_payload = json.loads(
        (tmp_path / FINAL_CONTEXT_HOST_FILENAME).read_text(encoding="utf-8")
    )
    host_payload["repositories"] = []
    (tmp_path / FINAL_CONTEXT_HOST_FILENAME).write_text(
        json.dumps(host_payload),
        encoding="utf-8",
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "stale_final_context"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


def test_submit_rejects_stale_nonce_and_plan_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    stale_nonce = deepcopy(valid_manifest(publication))
    stale_nonce["turn_nonce"] = "other-nonce"
    with pytest.raises(FinalizerDeclarationError):
        submit_final_manifest(stale_nonce)

    stale_plan = deepcopy(valid_manifest(publication))
    stale_plan["plan_digest"] = "0" * 64
    with pytest.raises(FinalizerDeclarationError):
        submit_final_manifest(stale_plan)


def test_commit_consumes_exported_declaration_helpers() -> None:
    exported = set(declaration_module.__all__)
    missing_exports = [
        name for name in _COMMIT_DECLARATION_HELPERS if name not in exported
    ]
    assert missing_exports == []

    declaration_consumer_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sase"
        / "finalizers"
        / "commit_declaration.py"
    )
    tree = ast.parse(
        declaration_consumer_path.read_text(encoding="utf-8"),
        filename=str(declaration_consumer_path),
    )
    private_imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").endswith("finalizers.declaration")
        for alias in node.names
        if alias.name.startswith("_")
    ]
    assert private_imports == []

    consumed = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "finalizer_declaration"
    }
    missing_consumers = [
        name for name in _COMMIT_DECLARATION_HELPERS if name not in consumed
    ]
    assert missing_consumers == []


def test_submit_invokes_external_provider_validate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.finalizers.config import (
        ConfiguredFinalizerInstance,
        FinalizerConfig,
        FinalizerFieldProvenance,
    )
    from sase.finalizers.executor import FinalizerExecutionError

    instance = ConfiguredFinalizerInstance(
        instance_id="audit",
        provider_ref="example-finalizers@audit",
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    config = FinalizerConfig(
        defaults=("audit",),
        required=(),
        instances={"audit": instance},
        provenance={},
    )
    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", lambda: config)
    monkeypatch.setattr(
        "sase.finalizers.plan.diagnose_finalizer_providers",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: clean_state(tmp_path),
    )
    seen: list[object] = []

    def accept(
        instance_id: str,
        provider_ref: str,
        _context: object,
        payload: object,
        **_kwargs: object,
    ) -> None:
        seen.append((instance_id, provider_ref, payload))

    monkeypatch.setattr(
        "sase.finalizers.executor.validate_external_declaration_payload",
        accept,
    )
    prepare_agent_env(monkeypatch, tmp_path)
    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(tmp_path),
    )
    publication = publish_final_context()
    manifest = deepcopy(publication.payload["manifest_template"])
    manifest["payloads"][0]["payload"] = {"note": "ok"}
    submit_final_manifest(manifest)

    assert seen == [("audit", "example-finalizers@audit", {"note": "ok"})]

    def reject(*_args: object, **_kwargs: object) -> None:
        raise FinalizerExecutionError("audit payload rejected")

    monkeypatch.setattr(
        "sase.finalizers.executor.validate_external_declaration_payload",
        reject,
    )
    with pytest.raises(FinalizerDeclarationError, match="audit payload rejected"):
        submit_final_manifest(manifest)


def test_context_host_snapshot_is_not_model_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    submit_final_manifest(valid_manifest(publication))

    assert str(tmp_path) not in json.dumps(publication.payload)
    assert (tmp_path / FINAL_CONTEXT_HOST_FILENAME).is_file()
    assert (tmp_path / FINAL_SUBMISSION_HOST_FILENAME).is_file()
    records = load_accepted_host_repositories(tmp_path)
    assert records[0].path == str(tmp_path)
    assert records[0].obligation_id == publication.context.obligations[0].obligation_id
