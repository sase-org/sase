"""Coverage for pluggable finalizer extension runtime and CLI inspection."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.feature_flags import override_flags
from sase.finalizers.cli import build_finalizer_inventory
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.controller import run_finalizers
from sase.finalizers.executor import (
    FinalizerExecutionContext,
    execute_non_commit_finalizer,
)
from sase.finalizers.plan import FinalizerPlanError, resolve_and_persist_finalizer_plan
from sase.finalizers.providers import (
    FinalizerProviderRecord,
    parse_command_finalizer_config,
)
from sase.llm_provider.types import InvokeResult
from sase.main.parser import create_parser, default_list_delegation_notice
from sase.xprompt.directives import PromptDirectives


def _config(
    instances: dict[str, ConfiguredFinalizerInstance],
    *,
    defaults: tuple[str, ...],
    required: tuple[str, ...] = (),
) -> FinalizerConfig:
    return FinalizerConfig(
        defaults=defaults,
        required=required,
        instances=instances,
        provenance={},
    )


def _instance(
    instance_id: str,
    provider_ref: str,
    *,
    config: dict[str, Any] | None = None,
    after: tuple[str, ...] = (),
) -> ConfiguredFinalizerInstance:
    return ConfiguredFinalizerInstance(
        instance_id=instance_id,
        provider_ref=provider_ref,
        after=after,
        config=config or {},
        provenance={
            "use": FinalizerFieldProvenance("test", None),
        },
    )


def test_bare_final_defaults_to_list_with_notice() -> None:
    args = create_parser().parse_args(["final"])

    assert args.command == "final"
    assert args.final_subcommand == "list"
    assert args.format == "pretty"
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase final'; delegating to 'sase final list'."
    )


def test_final_list_json_includes_unconfigured_plugin_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        {
            "commit": _instance("commit", "builtin@commit"),
        },
        defaults=("commit",),
    )
    monkeypatch.setattr(
        "sase.finalizers.cli.collect_finalizer_providers",
        lambda: (
            FinalizerProviderRecord(
                provider_ref="builtin@commit",
                provider_id="commit",
                package="builtin",
                version="builtin",
                entry_point=None,
                builtin=True,
            ),
            FinalizerProviderRecord(
                provider_ref="example-finalizers@audit",
                provider_id="audit",
                package="example-finalizers",
                version="1.0.0",
                entry_point="example_finalizers:provider",
                builtin=False,
            ),
        ),
    )
    monkeypatch.setattr(
        "sase.finalizers.cli.diagnose_finalizer_providers",
        lambda _config, plan=None: (),
    )

    view = build_finalizer_inventory(config_fn=lambda: config)

    assert view["selected"] == ["commit"]
    providers = {provider["provider_ref"]: provider for provider in view["providers"]}
    assert providers["example-finalizers@audit"]["configured"] is False
    assert [instance["instance_id"] for instance in view["instances"]] == ["commit"]


def test_selected_missing_external_provider_fails_before_plan_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        {
            "audit": _instance("audit", "missing-finalizers@audit"),
        },
        defaults=("audit",),
    )
    monkeypatch.setattr(
        "sase.finalizers.plan.load_finalizer_config",
        lambda: config,
    )

    with override_flags(pluggable_finalizers=True):
        with pytest.raises(FinalizerPlanError, match="not installed"):
            resolve_and_persist_finalizer_plan(
                PromptDirectives(),
                artifacts_dir=str(tmp_path),
            )

    assert not (tmp_path / "finalizer_plan.json").exists()


def test_builtin_command_shell_string_is_rejected() -> None:
    instance = _instance(
        "local-check",
        "builtin@command",
        config={"command": "just check"},
    )

    parsed, diagnostics = parse_command_finalizer_config(instance)

    assert parsed is None
    assert diagnostics[0].code == "invalid_command_argv"


def test_builtin_command_finalizer_runs_and_records_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(
        "local-check",
        "builtin@command",
        config={
            "command": [sys.executable, "-c", "print('checked')"],
            "cwd": "primary",
            "timeout": "5s",
            "submission": "none",
        },
    )
    config = _config({"local-check": instance}, defaults=("local-check",))
    monkeypatch.setattr(
        "sase.finalizers.plan.load_finalizer_config",
        lambda: config,
    )
    monkeypatch.setattr(
        "sase.finalizers.controller.load_finalizer_config",
        lambda: config,
    )

    with override_flags(pluggable_finalizers=True):
        resolve_and_persist_finalizer_plan(
            PromptDirectives(),
            artifacts_dir=str(tmp_path),
        )

    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="small",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path),
    )

    assert result.content == "done"
    payload = json.loads((tmp_path / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    assert payload["instances"][0]["instance_id"] == "local-check"
    stdout = tmp_path / "finalizers" / "local-check" / "attempt-1.stdout"
    assert stdout.read_text().strip() == "checked"


def test_external_provider_runs_describe_validate_execute_verify(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    instance = _instance("audit", "example-finalizers@audit")
    config = _config({"audit": instance}, defaults=("audit",))
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
        _instance: ConfiguredFinalizerInstance,
        _provider: FinalizerProviderRecord,
        operation: str,
        _request: Mapping[str, Any],
        _context: FinalizerExecutionContext,
    ) -> dict[str, Any]:
        seen.append(operation)
        return {
            "schema_version": 1,
            "operation": operation,
            "provider_ref": "example-finalizers@audit",
            "instance_id": "audit",
            "status": "success" if operation == "execute" else "ok",
            "evidence": [{"kind": "audit", "value": "ok"}]
            if operation == "execute"
            else [],
        }

    result = execute_non_commit_finalizer(
        instance,
        config,
        FinalizerExecutionContext(
            artifacts_dir=str(tmp_path),
            plan_digest="sha256:test",
        ),
        operation_runner=run_operation,
    )

    assert result.status == "success"
    assert seen == ["describe", "validate", "execute", "verify"]
    assert result.evidence[0].kind == "audit"
