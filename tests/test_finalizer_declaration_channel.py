"""Coverage for the finalizer declaration channel."""

from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

from sase.core.finalizer_wire import FINALIZER_DEFERRAL_REASONS
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
from sase.finalizers.declaration_context_evidence import COMMIT_DECLARATION_RULE
from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
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
    declaration = publication.payload["commit_declaration"]
    assert declaration["rule"] == COMMIT_DECLARATION_RULE
    assert declaration["default_action"] == "commit"
    assert declaration["deferral"]["reasons"] == list(FINALIZER_DEFERRAL_REASONS)
    assert (
        publication.payload["manifest_template"]["payloads"][0]["payload"]["deferrals"]
        == []
    )
    assert str(tmp_path) not in json.dumps(publication.payload)
    assert (tmp_path / FINAL_CONTEXT_FILENAME).is_file()


def test_context_publishes_bounded_repository_commit_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprints = {
        "src/app.py": ("M", "abc123"),
        "src/run.py": ("M", "run456"),
        "src/protected.py": ("M", "protected789"),
    }
    dirty = DirtyState(
        project_dir=str(tmp_path),
        repos=(
            DirtyRepo(
                name="main",
                path=str(tmp_path),
                changed_files=("src/app.py", "src/run.py", "src/protected.py"),
                kind="main",
            ),
        ),
        details="dirty",
    )
    prepare_dirty_declaration(
        monkeypatch,
        tmp_path,
        fingerprints=fingerprints,
        collect=lambda _root: dirty,
    )
    _write_run_start_baseline(
        tmp_path,
        tmp_path,
        fingerprints={
            "src/app.py": ("M", "abc123"),
            "src/protected.py": ("M", "protected789"),
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_git_status.dirty_path_fingerprints",
        lambda _path: {
            "src/app.py": ("M", "abc123"),
            "src/protected.py": ("M", "protected789"),
        },
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_context_evidence.protected_baseline_paths",
        lambda _root, _repo_path, *, get_changed_files: ("src/protected.py",),
    )
    (tmp_path / "tool_calls.jsonl").write_text(
        json.dumps(
            {
                "event": "ToolUse",
                "tool_name": "Edit",
                "tool_input_summary": {"file_path": "src/run.py"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    publication = publish_final_context()

    evidence = publication.payload["commit_declaration"]["repository_evidence"][0]
    assert evidence["repo_id"] == publication.context.obligations[0].obligation_id
    assert evidence["display_name"] == "main"
    assert evidence["run_written_paths"] == ["src/run.py"]
    assert evidence["already_dirty_at_run_start_paths"] == [
        "src/app.py",
        "src/protected.py",
    ]
    assert evidence["protected_paths"] == ["src/protected.py"]
    paths = {item["path"]: item for item in evidence["paths"]}
    assert paths["src/app.py"]["provenance"] == "already_dirty_at_run_start"
    assert paths["src/run.py"]["provenance"] == "new_since_run_start"
    assert paths["src/run.py"]["written_by_this_run"] is True
    assert paths["src/protected.py"]["protected"] is True
    assert str(tmp_path) not in json.dumps(publication.payload)


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


@pytest.mark.parametrize(
    "legacy_reason",
    [
        "no commit was requested for this turn",
        "The user did not ask to commit",
        "I lack context to authorize a commit",
        "Declaration-recovery turn: do not mutate repositories",
        "not mine",
    ],
)
def test_submit_rejects_legacy_refuse_action_as_unrepresentable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_reason: str,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    decision = manifest["payloads"][0]["payload"]["repositories"][0]
    decision["action"] = "refuse"
    decision.pop("message")
    decision["reason"] = legacy_reason

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_action_invalid"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()
    attempts = attempt_records(tmp_path)
    assert attempts[-1]["accepted"] is False
    assert attempts[-1]["code"] == "commit_action_invalid"


def test_submit_rejects_unknown_typed_deferral_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    _add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="not_asked_to_commit",
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_deferral_reason_invalid"
    assert "not_asked_to_commit" in str(exc_info.value)


@pytest.mark.parametrize("reason", ["foreign_work", "belongs_to_another_turn"])
def test_submit_rejects_run_owned_deferral_from_baseline_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _write_run_start_baseline(tmp_path, tmp_path, fingerprints={})
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    _add_deferral(
        manifest, publication.context.obligations[0].obligation_id, reason=reason
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_deferral_rejected"
    message = str(exc_info.value)
    assert "src/app.py" in message
    assert "new or changed after this run began" in message
    assert "commit message" in message


def test_submit_rejects_run_owned_deferral_from_direct_write_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    (tmp_path / "tool_calls.jsonl").write_text(
        json.dumps(
            {
                "event": "ToolUse",
                "tool_name": "Edit",
                "tool_input_summary": {"file_path": "src/app.py"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    _add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="belongs_to_another_turn",
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_deferral_rejected"
    assert "write/edit tool calls" in str(exc_info.value)


def test_submit_upholds_foreign_work_when_baseline_proves_pre_existing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _write_run_start_baseline(
        tmp_path,
        tmp_path,
        fingerprints={"src/app.py": ("M", "content")},
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_git_status.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "content")},
    )
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    _add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="foreign_work",
    )

    accepted = submit_final_manifest(manifest)

    assert accepted["accepted_deferrals"] == [
        {
            "instance_id": "commit",
            "repo_id": publication.context.obligations[0].obligation_id,
            "repo_display_name": "main",
            "reason": "foreign_work",
            "paths": ["src/app.py"],
        }
    ]


def test_submit_upholds_protected_path_deferral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration_deferrals.protected_baseline_paths",
        lambda _root, _repo_path, *, get_changed_files: ("src/app.py",),
    )
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    _add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="protected_paths",
    )

    accepted = submit_final_manifest(manifest)

    assert accepted["accepted_deferrals"][0]["reason"] == "protected_paths"


def test_submit_upholds_unsafe_content_deferral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    _add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="unsafe_content",
    )

    accepted = submit_final_manifest(manifest)

    assert accepted["accepted_deferrals"][0]["reason"] == "unsafe_content"


def test_submit_rejects_deferral_paths_outside_obligation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    _add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        paths=["other.py"],
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_deferral_path_unknown"
    assert "other.py" in str(exc_info.value)


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


def test_submit_validates_against_sealed_config_after_live_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sase final submit`` is the other process the old check killed.

    Seal the plan while "audit" is configured, then drift live config so
    "audit" is no longer configured at all before submit validates the
    payload. Submission must still validate against the sealed instance
    instead of raising ``plan_integrity_failed`` or "unknown finalizer
    instance".
    """
    from sase.finalizers.config import (
        ConfiguredFinalizerInstance,
        FinalizerConfig,
        FinalizerFieldProvenance,
    )
    from sase.finalizers.providers import FinalizerProviderRecord

    instance = ConfiguredFinalizerInstance(
        instance_id="audit",
        provider_ref="example-finalizers@audit",
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    sealed_config = FinalizerConfig(
        defaults=("audit",),
        required=(),
        instances={"audit": instance},
        provenance={},
    )
    monkeypatch.setattr(
        "sase.finalizers.plan.load_finalizer_config", lambda: sealed_config
    )
    monkeypatch.setattr(
        "sase.finalizers.plan.diagnose_finalizer_providers",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: clean_state(tmp_path),
    )
    prepare_agent_env(monkeypatch, tmp_path)
    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(tmp_path),
    )
    publication = publish_final_context()
    manifest = deepcopy(publication.payload["manifest_template"])
    manifest["payloads"][0]["payload"] = {"note": "ok"}

    # Live config drifts after the plan was sealed: "audit" is gone entirely.
    drifted_config = FinalizerConfig(
        defaults=(), required=(), instances={}, provenance={}
    )
    monkeypatch.setattr(
        "sase.finalizers.plan.load_finalizer_config", lambda: drifted_config
    )
    provider = FinalizerProviderRecord(
        provider_ref="example-finalizers@audit",
        provider_id="audit",
        package="example-finalizers",
        version="1.0.0",
        entry_point="example_finalizers:provider",
        builtin=False,
    )
    monkeypatch.setattr(
        "sase.finalizers.executor.collect_finalizer_providers",
        lambda: (provider,),
    )
    seen: list[str] = []

    def run_operation(
        _instance: object,
        _provider: object,
        operation: str,
        _request: object,
        _context: object,
    ) -> dict[str, object]:
        seen.append(operation)
        return {
            "schema_version": 1,
            "operation": operation,
            "provider_ref": "example-finalizers@audit",
            "instance_id": "audit",
            "status": "ok",
        }

    monkeypatch.setattr(
        "sase.finalizers.executor.run_provider_operation", run_operation
    )

    submit_final_manifest(manifest)

    assert seen == ["validate"]


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


def _add_deferral(
    manifest: dict[str, object],
    repo_id: str,
    *,
    reason: str = "foreign_work",
    paths: list[str] | None = None,
) -> None:
    payload = manifest["payloads"][0]["payload"]
    payload["deferrals"].append(
        {
            "repo_id": repo_id,
            "reason": reason,
            "paths": paths if paths is not None else ["src/app.py"],
        }
    )


def _write_run_start_baseline(
    artifacts: Path,
    repo: Path,
    *,
    fingerprints: dict[str, tuple[str, str]],
) -> None:
    payload = {
        "schema_version": 1,
        "repositories": [
            {
                "repo_id": "main",
                "path": normalize_path(str(repo)),
                "kind": "main",
                "name": "main",
                "scope": "run_start",
                "fingerprints": {
                    path: list(fingerprint)
                    for path, fingerprint in fingerprints.items()
                },
            }
        ],
    }
    (artifacts / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
