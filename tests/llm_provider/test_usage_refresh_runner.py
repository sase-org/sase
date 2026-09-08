"""Usage-refresh runner: synthetic probes, batch bounds, and secret hygiene."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from sase.axe.chop_script_context import ChopScriptContext, write_chop_context
from sase.chops.builtin import run_builtin_chop
from sase.feature_flags import override_flags
from sase.llm_provider.usage.refresh import UsageRefreshReceipt
from sase.llm_provider.usage.refresh_runner import _run_admitted_refresh
from sase.testing.usage_synthetic import (
    SECRET_CANARY,
    SYNTHETIC_MODE_ENV,
    SYNTHETIC_PLUGIN_SPEC,
)


@pytest.fixture
def runner_home(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Path:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    return tmp_path


def test_runner_collects_synthetic_provider(
    runner_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(SYNTHETIC_MODE_ENV, raising=False)
    with override_flags(provider_usage_metrics=True):
        results = _run_admitted_refresh(
            {
                "batch_deadline_seconds": 8,
                "provider_deadline_seconds": 6,
                "max_concurrent": 3,
                "plugin_specs": {"synth": SYNTHETIC_PLUGIN_SPEC},
                "providers": [
                    {
                        "provider": "synth",
                        "context_id": "default",
                        "account_generation": 1,
                        "lease_id": "lease-synth",
                    }
                ],
            }
        )
    assert results[0]["provider"] == "synth"
    assert results[0]["outcome"] == "ok"
    stored = (runner_home / "llm_provider_usage.json").read_text(encoding="utf-8")
    assert SECRET_CANARY not in stored
    assert "synth" in stored


def test_runner_reports_providers_that_miss_the_batch_deadline(
    runner_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SYNTHETIC_MODE_ENV, "hang")
    jobs = [
        {
            "provider": f"p{index}",
            "context_id": "default",
            "account_generation": 1,
            "lease_id": f"lease-{index}",
            "plugin_spec": SYNTHETIC_PLUGIN_SPEC,
        }
        for index in range(4)
    ]
    with override_flags(provider_usage_metrics=True):
        results = _run_admitted_refresh(
            {
                "batch_deadline_seconds": 1.2,
                "provider_deadline_seconds": 0.4,
                "max_concurrent": 3,
                "plugin_specs": {
                    f"p{index}": SYNTHETIC_PLUGIN_SPEC for index in range(4)
                },
                "providers": jobs,
            }
        )
    assert len(results) == 4
    assert {item["outcome"] for item in results} == {"error"}
    assert any(
        item["reason_code"] in {"deadline_exceeded", "timeout"} for item in results
    )


def test_chop_emits_nothing_due_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    importlib.import_module("sase.scripts.sase_chop_usage_refresh")

    result_path = tmp_path / "result.json"
    context_path = tmp_path / "context.json"
    write_chop_context(
        ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="checks",
            state_dir=str(tmp_path),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
            result_file=str(result_path),
        ),
        str(context_path),
    )
    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh.request_due_usage_refresh",
        lambda origin="axe": UsageRefreshReceipt(
            schema_version=1, origin=origin, operation_ids=(), providers=()
        ),
    )
    run_builtin_chop("usage_refresh", ["--context", str(context_path)])
    out = capsys.readouterr().out
    assert "usage_refresh:" in out
    assert "reason=nothing_due" in out
    payload = Path(result_path).read_text(encoding="utf-8")
    assert '"status": "no_op"' in payload
