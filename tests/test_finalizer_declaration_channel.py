"""Coverage for the finalizer declaration channel."""

from __future__ import annotations

import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import threading
from unittest.mock import MagicMock

import pytest

from sase.finalizers import declaration as declaration_module
from sase.finalizers.controller_context import declaration_recovery_spent
from sase.finalizers.declaration import (
    FINAL_CONTEXT_FILENAME,
    FINAL_CONTEXT_HOST_FILENAME,
    FINAL_DECLARATION_RECOVERY_EVIDENCE_FILENAME,
    FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    FINAL_SUBMISSION_ATTEMPTS_FILENAME,
    FINAL_SUBMISSION_FILENAME,
    FINAL_SUBMISSION_HOST_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    FinalContextPublication,
    FinalizerDeclarationError,
    ensure_final_declaration_or_recover,
    final_submission_is_current,
    load_accepted_host_repositories,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult
from sase.main.parser import create_parser
from sase.xprompt.directives import PromptDirectives

_INCIDENT_PATHS = (
    "Justfile",
    "src/sase/ace/query_profile/__init__.py",
    "src/sase/ace/query_profile/pane_registry.py",
    "src/sase/ace/query_profile/profiles.py",
    "src/sase/ace/tui/_proc_query.py",
    "tests/ace/tui/test_proc_query.py",
    "tests/test_query_profile.py",
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


def _prepare_agent_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")


def _dirty_state(repo: Path) -> DirtyState:
    return DirtyState(
        project_dir=str(repo),
        repos=(
            DirtyRepo(
                name="main",
                path=str(repo),
                changed_files=("src/app.py",),
                kind="main",
            ),
        ),
        details="dirty",
    )


def _clean_state(repo: Path) -> DirtyState:
    return DirtyState(project_dir=str(repo), repos=(), details="")


def _persist_default_plan(tmp_path: Path) -> None:
    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(tmp_path),
    )


def _valid_manifest(publication: FinalContextPublication) -> dict[str, object]:
    manifest = deepcopy(publication.payload["manifest_template"])
    repositories = manifest["payloads"][0]["payload"]["repositories"]
    repositories[0]["message"] = "fix(final): submit declaration"
    return manifest


def _refuse_manifest(publication: FinalContextPublication) -> dict[str, object]:
    manifest = deepcopy(publication.payload["manifest_template"])
    repositories = manifest["payloads"][0]["payload"]["repositories"]
    repositories[0]["action"] = "refuse"
    repositories[0].pop("message", None)
    repositories[0]["reason"] = "I have no context"
    return manifest


def _incident_dirty_state(repo: Path) -> DirtyState:
    return DirtyState(
        project_dir=str(repo),
        repos=(
            DirtyRepo(
                name="main",
                path=str(repo),
                changed_files=_INCIDENT_PATHS,
                kind="main",
            ),
        ),
        details="dirty",
    )


def _attempt_records(root: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (root / FINAL_SUBMISSION_ATTEMPTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]


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
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )

    _persist_default_plan(tmp_path)
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
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )

    _persist_default_plan(tmp_path)
    publication = publish_final_context()
    manifest = _valid_manifest(publication)
    accepted = submit_final_manifest(manifest)

    stale = deepcopy(manifest)
    stale["context_digest"] = "0" * 64
    with pytest.raises(FinalizerDeclarationError, match="context"):
        submit_final_manifest(stale)

    assert accepted["validation"]["accepted_instances"] == ["commit"]
    assert (tmp_path / FINAL_SUBMISSION_FILENAME).is_file()
    attempts = [
        json.loads(line)
        for line in (tmp_path / FINAL_SUBMISSION_ATTEMPTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert attempts[-2]["accepted"] is True
    assert attempts[-1]["accepted"] is False
    assert attempts[-1]["content_digest"]


def test_submit_rejects_dirty_fingerprint_changed_since_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprints = {"src/app.py": ("M", "abc123")}
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: dict(fingerprints),
    )

    _persist_default_plan(tmp_path)
    publication = publish_final_context()
    manifest = _valid_manifest(publication)
    fingerprints["src/app.py"] = ("M", "def456")

    with pytest.raises(FinalizerDeclarationError, match="rerun `sase final context`"):
        submit_final_manifest(manifest)

    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()
    assert not (tmp_path / FINAL_SUBMISSION_HOST_FILENAME).exists()
    attempts = _attempt_records(tmp_path)
    assert attempts[-1]["accepted"] is False
    assert attempts[-1]["code"] == "stale_final_context"
    assert "rerun `sase final context`" in str(attempts[-1]["message"])
    assert attempts[-1]["content_digest"]


def test_submit_rejects_dirty_context_that_became_clean_before_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dirty = {"value": True}
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: (
            _dirty_state(tmp_path) if dirty["value"] else _clean_state(tmp_path)
        ),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )

    _persist_default_plan(tmp_path)
    publication = publish_final_context()
    manifest = _valid_manifest(publication)
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
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )

    _persist_default_plan(tmp_path)
    publication = publish_final_context()
    manifest = _valid_manifest(publication)
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


def test_clean_commit_context_does_not_spend_recovery_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _clean_state(tmp_path),
    )
    provider = MagicMock()
    original = InvokeResult(content="done")

    _persist_default_plan(tmp_path)
    result = ensure_final_declaration_or_recover(
        provider=provider,
        invoke_result=original,
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path),
    )

    assert result is original
    provider.invoke.assert_not_called()


def test_missing_required_declaration_gets_one_fresh_recovery_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )

    provider = MagicMock()

    def recover(prompt: str, **_kwargs: object) -> InvokeResult:
        assert "single declaration-recovery turn" in prompt
        assert "/sase_final" in prompt
        assert "src/app.py" in prompt
        assert "not a valid refusal reason" in prompt
        assert os.environ[SASE_FINAL_TURN_NONCE_ENV] != "nonce-1"
        publication = publish_final_context()
        submit_final_manifest(_valid_manifest(publication))
        return InvokeResult(content="recovered", usage={"input_tokens": 1})

    provider.invoke.side_effect = recover

    _persist_default_plan(tmp_path)
    result = ensure_final_declaration_or_recover(
        provider=provider,
        invoke_result=InvokeResult(content="initial", usage={"input_tokens": 2}),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path),
    )

    assert provider.invoke.call_count == 1
    assert "initial" in result.content
    assert "recovered" in result.content
    assert result.usage == {"input_tokens": 3}
    assert os.environ[SASE_FINAL_TURN_NONCE_ENV] == "nonce-1"


@pytest.mark.parametrize("include_prompt", [True, False])
def test_recovery_prompt_includes_original_prompt_excerpt_when_supplied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    include_prompt: bool,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )
    original = "Implement the query profile pane registry"
    captured: dict[str, str] = {}
    provider = MagicMock()

    def recover(prompt: str, **_kwargs: object) -> InvokeResult:
        captured["prompt"] = prompt
        publication = publish_final_context()
        submit_final_manifest(_valid_manifest(publication))
        return InvokeResult(content="recovered")

    provider.invoke.side_effect = recover
    _persist_default_plan(tmp_path)
    ensure_final_declaration_or_recover(
        provider=provider,
        invoke_result=InvokeResult(content="initial"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path),
        original_prompt=original if include_prompt else None,
    )

    prompt = captured["prompt"]
    if include_prompt:
        assert "## What this run was asked to do" in prompt
        assert original in prompt
    else:
        assert "## What this run was asked to do" not in prompt
        assert original not in prompt


def test_recovery_writes_evidence_artifact_and_spent_keys_off_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )
    provider = MagicMock()

    def recover(prompt: str, **_kwargs: object) -> InvokeResult:
        publication = publish_final_context()
        submit_final_manifest(_valid_manifest(publication))
        return InvokeResult(content="recovered")

    provider.invoke.side_effect = recover
    _persist_default_plan(tmp_path)
    ensure_final_declaration_or_recover(
        provider=provider,
        invoke_result=InvokeResult(content="initial"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path),
        original_prompt="do the work",
    )

    evidence = tmp_path / FINAL_DECLARATION_RECOVERY_EVIDENCE_FILENAME
    prompt_file = tmp_path / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME
    assert evidence.is_file()
    assert "do the work" in evidence.read_text(encoding="utf-8")
    assert prompt_file.is_file()
    assert declaration_recovery_spent(str(tmp_path)) is True
    evidence.unlink()
    assert declaration_recovery_spent(str(tmp_path)) is True
    prompt_file.unlink()
    assert declaration_recovery_spent(str(tmp_path)) is False


def test_incident_shaped_recovery_prompt_attributes_paths_to_this_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _incident_dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: dict.fromkeys(_INCIDENT_PATHS, ("M", "abc123")),
    )
    (tmp_path / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repositories": [
                    {
                        "repo_id": "linked:beads",
                        "path": normalize_path(str(tmp_path / "beads")),
                        "kind": "linked",
                        "name": "beads",
                        "scope": "run_start",
                        "fingerprints": {"issue.jsonl": ["M", "def"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, str] = {}
    provider = MagicMock()

    def recover(prompt: str, **_kwargs: object) -> InvokeResult:
        captured["prompt"] = prompt
        publication = publish_final_context()
        submit_final_manifest(_refuse_manifest(publication))
        return InvokeResult(content="refused")

    provider.invoke.side_effect = recover
    _persist_default_plan(tmp_path)
    ensure_final_declaration_or_recover(
        provider=provider,
        invoke_result=InvokeResult(content="implemented the pane registry"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path),
        original_prompt="implement the query profile pane",
    )

    prompt = captured["prompt"]
    assert "this run's own work" in prompt
    for path in _INCIDENT_PATHS:
        assert path in prompt
        assert f"- `{path}` — new since run start" in prompt


def test_submit_rejects_stale_nonce_and_plan_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )

    _persist_default_plan(tmp_path)
    publication = publish_final_context()
    stale_nonce = deepcopy(_valid_manifest(publication))
    stale_nonce["turn_nonce"] = "other-nonce"
    with pytest.raises(FinalizerDeclarationError):
        submit_final_manifest(stale_nonce)

    stale_plan = deepcopy(_valid_manifest(publication))
    stale_plan["plan_digest"] = "0" * 64
    with pytest.raises(FinalizerDeclarationError):
        submit_final_manifest(stale_plan)


def test_handoff_skips_declaration_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )
    (tmp_path / ".sase_plan_pending").write_text("1\n", encoding="utf-8")
    provider = MagicMock()
    original = InvokeResult(content="planning")

    _persist_default_plan(tmp_path)
    result = ensure_final_declaration_or_recover(
        provider=provider,
        invoke_result=original,
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path),
    )

    assert result is original
    provider.invoke.assert_not_called()


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
        lambda _root: _clean_state(tmp_path),
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
    _prepare_agent_env(monkeypatch, tmp_path)
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


def test_submit_rereads_context_and_rejects_in_lock_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )
    _persist_default_plan(tmp_path)
    publication = publish_final_context()
    manifest = _valid_manifest(publication)

    def hook(point: str) -> None:
        if point != "submit_after_validate":
            return
        payload = json.loads(
            (tmp_path / FINAL_CONTEXT_FILENAME).read_text(encoding="utf-8")
        )
        payload["context"]["context_digest"] = "0" * 64
        (tmp_path / FINAL_CONTEXT_FILENAME).write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    monkeypatch.setattr(declaration_module, "_declaration_sync_hook", hook)
    with pytest.raises(FinalizerDeclarationError, match="changed|stale"):
        submit_final_manifest(manifest)
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).is_file()


def test_publish_and_submit_serialize_on_declaration_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )
    _persist_default_plan(tmp_path)
    publication = publish_final_context()
    manifest = _valid_manifest(publication)
    publisher_holding = threading.Event()
    submitter_before = threading.Event()
    submitter_holding = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def hook(point: str) -> None:
        name = threading.current_thread().name
        if point == "before_declaration_lock" and name == "submitter":
            submitter_before.set()
        if point != "holding_declaration_lock":
            return
        if name == "publisher":
            publisher_holding.set()
            assert release.wait(timeout=5)
            return
        submitter_holding.set()

    monkeypatch.setattr(declaration_module, "_declaration_sync_hook", hook)

    def publish() -> None:
        try:
            publish_final_context()
        except BaseException as exc:  # noqa: BLE001 - collected by parent
            errors.append(exc)

    def submit() -> None:
        try:
            submit_final_manifest(manifest)
        except BaseException as exc:  # noqa: BLE001 - collected by parent
            errors.append(exc)

    publisher = threading.Thread(target=publish, name="publisher")
    submitter = threading.Thread(target=submit, name="submitter")
    publisher.start()
    assert publisher_holding.wait(timeout=5)
    submitter.start()
    assert submitter_before.wait(timeout=5)
    assert not submitter_holding.is_set()
    release.set()
    publisher.join(timeout=5)
    submitter.join(timeout=5)
    assert not publisher.is_alive()
    assert not submitter.is_alive()
    assert errors == []
    assert submitter_holding.is_set()


def test_context_host_snapshot_is_not_model_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )
    _persist_default_plan(tmp_path)
    publication = publish_final_context()
    submit_final_manifest(_valid_manifest(publication))

    assert str(tmp_path) not in json.dumps(publication.payload)
    assert (tmp_path / FINAL_CONTEXT_HOST_FILENAME).is_file()
    assert (tmp_path / FINAL_SUBMISSION_HOST_FILENAME).is_file()
    records = load_accepted_host_repositories(tmp_path)
    assert records[0].path == str(tmp_path)
    assert records[0].obligation_id == publication.context.obligations[0].obligation_id


def test_simultaneous_republish_and_submit_keep_acceptance_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprints = {"value": {"src/app.py": ("M", "abc123")}}
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: dict(fingerprints["value"]),
    )
    _persist_default_plan(tmp_path)
    publication = publish_final_context()
    manifest = _valid_manifest(publication)
    start = threading.Barrier(2)
    accepted: list[dict[str, object]] = []
    errors: list[BaseException] = []

    def hook(point: str) -> None:
        if point == "before_declaration_lock":
            start.wait(timeout=5)

    monkeypatch.setattr(declaration_module, "_declaration_sync_hook", hook)

    def do_submit() -> None:
        try:
            accepted.append(submit_final_manifest(manifest))
        except FinalizerDeclarationError as exc:
            errors.append(exc)

    def do_publish() -> None:
        fingerprints["value"] = {"src/app.py": ("M", "changed")}
        try:
            publish_final_context()
        except BaseException as exc:  # noqa: BLE001 - collected by parent
            errors.append(exc)

    threads = [
        threading.Thread(target=do_submit, name="submitter"),
        threading.Thread(target=do_publish, name="publisher"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    latest = json.loads((tmp_path / FINAL_CONTEXT_FILENAME).read_text(encoding="utf-8"))
    assert accepted == []
    assert len(errors) == 1
    assert isinstance(errors[0], FinalizerDeclarationError)
    assert errors[0].code == "stale_final_context"
    assert latest["context"]["context_digest"] != publication.context.context_digest
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()
