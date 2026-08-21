"""Adversarial coverage for sealed finalizer plan authentication."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.config.core import ConfigLayer
from sase.core.finalizer_facade import finalizer_plan_digest
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.controller import FinalizerControllerError, run_finalizers
from sase.finalizers.declaration import (
    SASE_FINAL_TURN_NONCE_ENV,
    FinalizerDeclarationError,
    mint_finalizer_turn_nonce,
    publish_final_context,
)
from sase.finalizers.executor import (
    FinalizerExecutionContext,
    execute_non_commit_finalizer,
)
from sase.finalizers.plan import (
    FINALIZER_PLAN_AUTHORITY_FILENAME,
    FINALIZER_PLAN_FILENAME,
    SASE_FINALIZER_PLAN_DIGEST_ENV,
    resolve_and_persist_finalizer_plan,
)
from sase.finalizers.providers import FinalizerProviderRecord
from sase.llm_provider.commit_finalizer_types import DirtyState
from sase.llm_provider.types import InvokeResult
from sase.xprompt.directives import PromptDirectives, extract_prompt_directives


def _prepare_agent_env(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(artifacts))


def _command_config(
    *,
    command: list[str] | None = None,
    required: list[str] | None = None,
) -> ConfigLayer:
    return ConfigLayer(
        name="default",
        path=None,
        exists=True,
        list_strategy="concatenate",
        data={
            "finalizers": {
                "defaults": ["local-check"],
                "required": required if required is not None else ["local-check"],
                "instances": {
                    "local-check": {
                        "use": "builtin@command",
                        "after": [],
                        "max_attempts": 1,
                        "refusal": "fail",
                        "config": {
                            "command": command or ["true"],
                            "cwd": "primary",
                            "timeout": "5s",
                            "submission": "none",
                        },
                    }
                },
            }
        },
    )


def _patch_command_config(
    monkeypatch: pytest.MonkeyPatch,
    layer: ConfigLayer | None = None,
) -> None:
    config_layer = layer or _command_config()
    monkeypatch.setattr(
        "sase.finalizers.config.load_config_layers",
        lambda: [config_layer],
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: DirtyState(project_dir=".", repos=(), details=""),
    )


def _persist_command_plan(artifacts: Path) -> dict[str, Any]:
    artifacts.mkdir(parents=True, exist_ok=True)
    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    return json.loads((artifacts / FINALIZER_PLAN_FILENAME).read_text(encoding="utf-8"))


def _write_visible_plan(artifacts: Path, payload: MappingOrDict) -> None:
    (artifacts / FINALIZER_PLAN_FILENAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


MappingOrDict = dict[str, Any]


def _run(artifacts: Path) -> InvokeResult:
    return run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="small",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )


def _assert_integrity_failed(artifacts: Path, exc: BaseException) -> dict[str, Any]:
    assert getattr(exc, "code", None) == "plan_integrity_failed"
    payload = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "failed"
    assert payload["instances"] == []
    assert payload["diagnostics"][0]["code"] == "plan_integrity_failed"
    assert not (artifacts / "finalizers" / "local-check").exists()
    return payload


def test_forged_empty_plan_with_invalid_digest_fails_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts)
    _patch_command_config(monkeypatch)
    payload = _persist_command_plan(artifacts)
    payload["plan"] = {
        "schema_version": 1,
        "entries": [],
        "required": [],
        "selectors": [],
        "plan_digest": "not-a-digest",
    }
    _write_visible_plan(artifacts, payload)

    with pytest.raises(FinalizerControllerError) as excinfo:
        _run(artifacts)

    _assert_integrity_failed(artifacts, excinfo.value)


@pytest.mark.parametrize(
    "mutator",
    [
        "truncate",
        "reorder",
        "add_entry",
        "remove_entry",
        "provider_ref",
        "max_attempts",
        "provenance",
        "dependency_order",
        "forge_digest",
        "omit_digest",
        "remove_required",
    ],
)
def test_plan_artifact_mutations_fail_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutator: str,
) -> None:
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts)
    _patch_command_config(monkeypatch)
    payload = _persist_command_plan(artifacts)
    plan = payload["plan"]
    entry = plan["entries"][0]

    if mutator == "truncate":
        (artifacts / FINALIZER_PLAN_FILENAME).write_text("{", encoding="utf-8")
    elif mutator == "reorder":
        clone = deepcopy(entry)
        clone["instance_id"] = "extra-check"
        clone["selector_index"] = 1
        clone["resolved_index"] = 0
        entry["resolved_index"] = 1
        plan["entries"] = [clone, entry]
        plan["plan_digest"] = finalizer_plan_digest(plan)
    elif mutator == "add_entry":
        clone = deepcopy(entry)
        clone["instance_id"] = "extra-check"
        clone["selector_index"] = 1
        clone["resolved_index"] = 1
        plan["entries"].append(clone)
        plan["plan_digest"] = finalizer_plan_digest(plan)
    elif mutator == "remove_entry":
        plan["entries"] = []
        plan["required"] = []
        plan["plan_digest"] = finalizer_plan_digest(plan)
    elif mutator == "provider_ref":
        entry["provider_ref"] = "builtin@commit"
        plan["plan_digest"] = finalizer_plan_digest(plan)
    elif mutator == "max_attempts":
        entry["policy"]["max_attempts"] = 4
        plan["plan_digest"] = finalizer_plan_digest(plan)
    elif mutator == "provenance":
        entry["provenance_id"] = "tampered"
        plan["plan_digest"] = finalizer_plan_digest(plan)
    elif mutator == "dependency_order":
        entry["after"] = ["local-check"]
        plan["plan_digest"] = finalizer_plan_digest(plan)
    elif mutator == "forge_digest":
        plan["plan_digest"] = "0" * 64
    elif mutator == "omit_digest":
        del plan["plan_digest"]
    elif mutator == "remove_required":
        plan["required"] = []
        plan["plan_digest"] = finalizer_plan_digest(plan)
    if mutator != "truncate":
        _write_visible_plan(artifacts, payload)

    with pytest.raises(FinalizerControllerError) as excinfo:
        _run(artifacts)

    _assert_integrity_failed(artifacts, excinfo.value)


def test_live_configuration_drift_fails_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts)
    _patch_command_config(monkeypatch)
    _persist_command_plan(artifacts)
    _patch_command_config(
        monkeypatch,
        _command_config(command=["false"]),
    )

    with pytest.raises(FinalizerControllerError) as excinfo:
        _run(artifacts)

    payload = _assert_integrity_failed(artifacts, excinfo.value)
    assert "configuration" in payload["diagnostics"][0]["message"]


def test_independent_env_digest_rejects_matching_forged_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts)
    _patch_command_config(monkeypatch)
    payload = _persist_command_plan(artifacts)
    original_digest = payload["plan"]["plan_digest"]
    payload["plan"]["entries"] = []
    payload["plan"]["required"] = []
    payload["plan"]["plan_digest"] = finalizer_plan_digest(payload["plan"])
    _write_visible_plan(artifacts, payload)
    (artifacts / FINALIZER_PLAN_AUTHORITY_FILENAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(SASE_FINALIZER_PLAN_DIGEST_ENV, original_digest)

    with pytest.raises(FinalizerControllerError) as excinfo:
        _run(artifacts)

    _assert_integrity_failed(artifacts, excinfo.value)


def test_final_none_empty_plan_still_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _prepare_agent_env(monkeypatch, artifacts)
    _patch_command_config(monkeypatch, _command_config(required=[]))
    _, directives = extract_prompt_directives("%final:none\nDo work")
    resolve_and_persist_finalizer_plan(directives, artifacts_dir=str(artifacts))

    result = _run(artifacts)

    assert result.content == "done"
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    assert payload["instances"] == []


def test_resume_turn_keeps_host_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts)
    _patch_command_config(monkeypatch)
    payload = _persist_command_plan(artifacts)
    first_digest = payload["plan"]["plan_digest"]
    mint_finalizer_turn_nonce()
    payload["plan"]["entries"] = []
    payload["plan"]["required"] = []
    payload["plan"]["plan_digest"] = finalizer_plan_digest(payload["plan"])
    _write_visible_plan(artifacts, payload)

    with pytest.raises(FinalizerControllerError) as excinfo:
        _run(artifacts)

    _assert_integrity_failed(artifacts, excinfo.value)
    authority = json.loads(
        (artifacts / FINALIZER_PLAN_AUTHORITY_FILENAME).read_text(encoding="utf-8")
    )
    assert authority["plan"]["plan_digest"] == first_digest
    assert os.environ[SASE_FINALIZER_PLAN_DIGEST_ENV] == first_digest


def test_worker_request_uses_sealed_selection_and_turn_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    instance = ConfiguredFinalizerInstance(
        instance_id="audit",
        provider_ref="example-finalizers@audit",
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    commit = ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    config = FinalizerConfig(
        defaults=("commit",),
        required=(),
        instances={"audit": instance, "commit": commit},
        provenance={},
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
    seen: list[dict[str, Any]] = []

    def run_operation(
        _instance: ConfiguredFinalizerInstance,
        _provider: FinalizerProviderRecord,
        operation: str,
        request: Any,
        _context: FinalizerExecutionContext,
    ) -> dict[str, Any]:
        seen.append(dict(request))
        return {
            "schema_version": 1,
            "operation": operation,
            "provider_ref": "example-finalizers@audit",
            "instance_id": "audit",
            "status": "success" if operation == "execute" else "ok",
        }

    result = execute_non_commit_finalizer(
        instance,
        config,
        FinalizerExecutionContext(
            artifacts_dir=str(tmp_path),
            plan_digest="a" * 64,
            run_id="run-1",
            agent_id="agent-1",
            turn_nonce="nonce-2",
            context_digest="b" * 64,
            selected=("audit",),
            accepted_payloads={"audit": {"note": "sealed"}},
            obligations=({"obligation_id": "repo-1", "kind": "repository"},),
        ),
        operation_runner=run_operation,
    )

    assert result.status == "success"
    for request in seen:
        assert request["selected"] == ["audit"]
        assert request["run_id"] == "run-1"
        assert request["agent_id"] == "agent-1"
        assert request["turn_nonce"] == "nonce-2"
        assert request["context_digest"] == "b" * 64
        assert request["payload"] == {"note": "sealed"}
        assert request["obligations"][0]["obligation_id"] == "repo-1"


def test_context_publication_authenticates_the_sealed_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts)
    _patch_command_config(monkeypatch)
    payload = _persist_command_plan(artifacts)
    payload["plan"]["entries"][0]["provider_ref"] = "builtin@commit"
    _write_visible_plan(artifacts, payload)

    with pytest.raises(FinalizerDeclarationError) as excinfo:
        publish_final_context(artifacts_dir=str(artifacts))
    assert excinfo.value.code == "plan_integrity_failed"

    result = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert result["diagnostics"][0]["code"] == "plan_integrity_failed"
