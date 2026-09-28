"""Coverage for tab lineage inheritance and the dispatch preflight."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sase.dispatch.launch as launch
from sase.agent.launch_request import create_launch_approval_request
from sase.axe.run_agent_directive_metadata import export_agent_tab_env
from sase.axe.run_agent_exec import _export_exec_agent_tab
from sase.dispatch.models import DispatchConfig, MachineRecord, ProviderSettings
from sase.gate_turn.member import _GATE_INHERITED_METADATA_FIELDS
from sase.monitor.member import _MONITOR_INHERITED_METADATA_FIELDS
from sase.monitor.supervise import _reexport_member_agent_tab
from sase.xprompt.directive_edit import (
    apply_inherited_agent_tab,
    inherited_agent_tab,
    scan_tab_directive,
    set_agent_tab_directive,
)
from tests.conftest import redirect_sase_home


def test_inherited_tab_absent_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_AGENT_TAB", raising=False)
    assert inherited_agent_tab() is None


def test_inherited_tab_validates_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_AGENT_TAB", "Sase")
    assert inherited_agent_tab() == "sase"
    monkeypatch.setenv("SASE_AGENT_TAB", "local")
    assert inherited_agent_tab() is None
    monkeypatch.setenv("SASE_AGENT_TAB", "")
    assert inherited_agent_tab() is None


def test_apply_inserts_plain_prompt() -> None:
    assert apply_inherited_agent_tab("do work", "sase") == "%tab:sase\ndo work"


def test_apply_is_idempotent() -> None:
    once = apply_inherited_agent_tab("do work", "sase")
    assert apply_inherited_agent_tab(once, "sase") == once


def test_apply_skips_existing_tab_and_explicit_default() -> None:
    assert apply_inherited_agent_tab("%tab:blog do work", "sase") == "%tab:blog do work"
    assert apply_inherited_agent_tab("%tab:main do work", "sase") == "%tab:main do work"
    assert (
        apply_inherited_agent_tab("%tab(blog) do work", "sase") == "%tab(blog) do work"
    )


def test_apply_skips_session_attach() -> None:
    prompt = "%id(@, session=mysess) do work"
    assert apply_inherited_agent_tab(prompt, "sase") == prompt


def test_apply_handles_swarm_segments_per_segment() -> None:
    prompt = "a work\n---\n%tab:b b work\n---\n%id(@, session=s) c"
    assert apply_inherited_agent_tab(prompt, "sase") == (
        "%tab:sase\na work\n---\n%tab:b b work\n---\n%id(@, session=s) c"
    )


def test_apply_ignores_fenced_tab() -> None:
    prompt = "```\n%tab:x\n```\ndo work"
    assert apply_inherited_agent_tab(prompt, "sase") == f"%tab:sase\n{prompt}"


def test_apply_without_tab_is_noop() -> None:
    assert apply_inherited_agent_tab("do work", None) == "do work"


def test_set_agent_tab_directive_replaces_and_strips() -> None:
    replaced = set_agent_tab_directive("%tab:old do work", "new")
    assert replaced.startswith("%tab:new")
    assert "%tab:old" not in replaced
    assert "%tab" not in set_agent_tab_directive("%tab:old do work", None)


def test_export_agent_tab_sets_and_pops(monkeypatch: pytest.MonkeyPatch) -> None:
    export_agent_tab_env("sase")
    assert os.environ["SASE_AGENT_TAB"] == "sase"
    export_agent_tab_env(None)
    assert "SASE_AGENT_TAB" not in os.environ


def test_exec_export_reads_root_meta_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_AGENT_TAB", raising=False)
    ctx = SimpleNamespace(agent_meta={"agent_tab": "blog"})
    _export_exec_agent_tab(ctx, export_agent_tab_env)
    assert os.environ["SASE_AGENT_TAB"] == "blog"
    _export_exec_agent_tab(SimpleNamespace(agent_meta={}), export_agent_tab_env)
    assert "SASE_AGENT_TAB" not in os.environ


def test_turn_members_record_creator_tab() -> None:
    assert "agent_tab" in _GATE_INHERITED_METADATA_FIELDS
    assert "agent_tab" in _MONITOR_INHERITED_METADATA_FIELDS


def test_monitor_reexport_restores_tab_after_scrub() -> None:
    env: dict[str, str] = {}
    _reexport_member_agent_tab(env, {"agent_tab": "sase"})
    assert env["SASE_AGENT_TAB"] == "sase"
    _reexport_member_agent_tab(env, {})
    assert env["SASE_AGENT_TAB"] == "sase"


def test_launch_approval_prompt_carries_inherited_tab(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TAB", "sase")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)

    result = create_launch_approval_request(
        {
            "schema_version": 1,
            "prompt": "do delegated work",
            "reason": "lineage check",
            "approval": "required",
            "max_slots": 1,
        },
        source_surface="agent_skill",
    )
    envelope = json.loads(result.request_path.read_text(encoding="utf-8"))
    assert envelope["payload"]["dispatch"]["prompt"].startswith("%tab:sase\n")


def _pin(hex_char: str = "a") -> str:
    return "sase_inst_v1_" + hex_char * 64


def _machine() -> MachineRecord:
    return MachineRecord(
        alias="apollo",
        provider_ref="builtin@https",
        endpoint="https://fleet.example.test",
        credential_ref="fleet:apollo",
        pinned_installation_id=_pin(),
    )


def _rust_binding(name: str) -> Any:
    if name == "fleet_installation_identity_ensure":
        return lambda _home: {"record": {"installation_id": "source-install"}}
    if name == "fleet_launch_payload_fingerprint":
        return lambda _intent: {"schema_version": 1, "sha256": "a" * 64}
    if name == "fleet_validate_launch_request":
        return lambda request: request
    if name == "fleet_validate_launch_intent":
        return lambda intent: intent
    raise AssertionError(f"unexpected binding: {name}")


def _preview_config() -> DispatchConfig:
    return DispatchConfig(
        providers={
            "builtin@https": ProviderSettings(ref="builtin@https", enabled=True)
        },
        machines=((_machine(),)),
        request_timeout_seconds=5.0,
    )


def _preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    query: str,
    version: int | None,
) -> Any:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(launch, "load_dispatch_config", _preview_config)
    monkeypatch.setattr(launch, "require_rust_binding", _rust_binding)
    monkeypatch.setattr(
        launch, "_read_cached_target_contract_version", lambda alias: version
    )
    return launch.preview_dispatch_launch(
        query,
        payload={"project": "sase", "patch_ref": "patch-123", "follow": True},
    )


def test_tab_preflight_current_target_proceeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preview = _preview(
        monkeypatch, tmp_path, "%tab:sase %dispatch:apollo do work", version=7
    )
    assert preview is not None
    assert preview.target_detail == ""


def test_tab_preflight_unknown_target_warns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preview = _preview(
        monkeypatch, tmp_path, "%tab:sase %dispatch:apollo do work", version=None
    )
    assert preview is not None
    assert "no cached contract version" in preview.target_detail


def test_tab_preflight_older_target_refuses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with pytest.raises(launch.RemoteDispatchLaunchError, match="upgrade sase"):
        _preview(monkeypatch, tmp_path, "%tab:sase %dispatch:apollo do work", version=6)


def test_tab_preflight_skipped_without_tab(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(launch, "load_dispatch_config", _preview_config)
    monkeypatch.setattr(launch, "require_rust_binding", _rust_binding)

    def _unexpected(alias: str) -> int | None:
        raise AssertionError("version lookup must not run without %tab")

    monkeypatch.setattr(launch, "_read_cached_target_contract_version", _unexpected)
    preview = launch.preview_dispatch_launch(
        "%dispatch:apollo do remote work",
        payload={"project": "sase", "patch_ref": "patch-123", "follow": True},
    )
    assert preview is not None
    assert preview.target_detail == ""


def test_contract_version_parsing() -> None:
    assert (
        launch._contract_version_for_alias(
            {"hosts": [{"alias": "apollo", "fleet_contract_schema_version": 7}]},
            "apollo",
        )
        == 7
    )
    assert (
        launch._contract_version_for_alias(
            {
                "hosts": [
                    {
                        "alias": "apollo",
                        "status": {"fleet_contract_schema_version": 6},
                    }
                ]
            },
            "apollo",
        )
        == 6
    )
    assert (
        launch._contract_version_for_alias(
            {"hosts": [{"alias": "mac", "fleet_contract_schema_version": 7}]},
            "apollo",
        )
        is None
    )
    assert launch._contract_version_for_alias({"hosts": []}, "apollo") is None
    assert launch._contract_version_for_alias({}, "apollo") is None


def test_scan_tab_directive_absent() -> None:
    assert scan_tab_directive("do work") is None
    assert scan_tab_directive("```\n%tab:blog\n```\ndo work") is None


def test_scan_tab_directive_named_forms() -> None:
    assert scan_tab_directive("%tab:blog\ndo work").tab == "blog"  # type: ignore[union-attr]
    assert scan_tab_directive("%tab(Blog)\ndo work").tab == "blog"  # type: ignore[union-attr]


def test_scan_tab_directive_explicit_default() -> None:
    scan = scan_tab_directive("%tab:main\ndo work")
    assert scan is not None
    assert scan.tab is None
    assert scan.explicit_default is True
    assert scan.error is None


def test_scan_tab_directive_reserved_names_error() -> None:
    assert scan_tab_directive("%tab:local\ndo work").error is not None  # type: ignore[union-attr]
    assert scan_tab_directive("%tab:all\ndo work").error is not None  # type: ignore[union-attr]


def test_scan_tab_directive_duplicate_errors() -> None:
    scan = scan_tab_directive("%tab:a\n%tab:b\ndo work")
    assert scan is not None
    assert "Only one %tab" in (scan.error or "")


def test_scan_tab_directive_fan_out_shows_first() -> None:
    scan = scan_tab_directive("%{%tab:a | %tab:b}\ndo work")
    assert scan is not None
    assert scan.tab == "a"
    assert scan.error is None


def test_scan_tab_directive_bare_form_errors() -> None:
    scan = scan_tab_directive("%tab\ndo work")
    assert scan is not None
    assert scan.error is not None
