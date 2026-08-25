"""Coverage for finalizer declaration-channel provider validation."""

from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path

import pytest

from sase.finalizers import declaration as declaration_module
from sase.finalizers.declaration import (
    FinalizerDeclarationError,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.xprompt.directives import PromptDirectives

from .finalizer_declaration_channel_test_helpers import clean_state, prepare_agent_env

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
