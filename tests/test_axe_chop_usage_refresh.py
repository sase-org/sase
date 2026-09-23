"""Builtin usage_refresh chop coverage: inline runs, summaries, cadence."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from sase.axe.chop_script_context import ChopScriptContext, write_chop_context
from sase.chops.builtin import run_builtin_chop
from sase.llm_provider.usage.refresh import (
    _UsageRefreshProviderResult,
    UsageRefreshReceipt,
)


@pytest.fixture(autouse=True)
def _isolate_chop_result_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep an outer chop runner from overriding each test context."""

    monkeypatch.delenv("SASE_CHOP_RESULT_FILE", raising=False)


def _receipt(*, started: bool) -> UsageRefreshReceipt:
    providers = [
        _UsageRefreshProviderResult(
            provider="claude",
            status="reserved",
            reason="cadence",
            operation_id="usage-job:abc123" if started else None,
        ),
        _UsageRefreshProviderResult(
            provider="grok",
            status="deferred",
            reason="backoff",
            operation_id=None,
            due_at=1_800_000_600.0,
        ),
    ]
    if not started:
        providers[0] = _UsageRefreshProviderResult(
            provider="claude",
            status="deferred",
            reason="floor",
            operation_id=None,
            due_at=1_800_000_300.0,
        )
    return UsageRefreshReceipt(
        schema_version=1,
        origin="axe",
        operation_ids=("usage-job:abc123",) if started else (),
        providers=tuple(providers),
        inline_results=(
            (
                {
                    "provider": "claude",
                    "outcome": "ok",
                    "reason_code": None,
                    "skipped": None,
                },
            )
            if started
            else ()
        ),
    )


def _run_usage_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source: str,
    started: bool,
) -> tuple[dict[str, object], dict[str, object]]:
    importlib.import_module("sase.scripts.sase_chop_usage_refresh")
    calls: dict[str, object] = {}

    def fake_submit(
        providers: tuple[str, ...] | None,
        *,
        explicit: bool,
        origin: str,
        execution: str = "proc",
    ) -> UsageRefreshReceipt:
        calls["explicit"] = explicit
        calls["origin"] = origin
        calls["execution"] = execution
        calls["providers"] = providers
        return _receipt(started=started)

    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh.submit_usage_refresh", fake_submit
    )
    result_path = tmp_path / "result.json"
    context_path = tmp_path / "context.json"
    write_chop_context(
        ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="usage",
            state_dir=str(tmp_path),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
            result_file=str(result_path),
            source=source,
        ),
        str(context_path),
    )
    run_builtin_chop("usage_refresh", ["--context", str(context_path)])
    return json.loads(result_path.read_text(encoding="utf-8")), calls


def test_scheduled_usage_refresh_is_due_only_inline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, calls = _run_usage_refresh(
        tmp_path, monkeypatch, source="scheduled", started=True
    )
    assert calls["explicit"] is False
    assert calls["execution"] == "inline"
    assert result["status"] == "ok"
    assert result["counters"] == {
        "providers": 2,
        "succeeded": 1,
        "failed": 0,
        "deferred": 1,
    }
    summary = str(result["summary"])
    assert "claude=ok" in summary
    assert "grok=backoff" in summary


def test_manual_usage_refresh_is_explicit_inline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, calls = _run_usage_refresh(
        tmp_path, monkeypatch, source="manual", started=True
    )
    assert calls["explicit"] is True
    assert calls["execution"] == "inline"
    assert result["status"] == "ok"


def test_idle_usage_refresh_reports_nothing_due(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _ = _run_usage_refresh(
        tmp_path, monkeypatch, source="scheduled", started=False
    )
    assert result["status"] == "no_op"
    assert result["reason"] == "nothing_due"
    summary = str(result["summary"])
    assert "claude=floor" in summary
    assert "grok=backoff" in summary


def test_provider_summary_counts_probe_outcomes() -> None:
    from sase.scripts.sase_chop_usage_refresh import _summary_fields

    fields = _summary_fields(_receipt(started=True))
    assert fields["providers"] == 2
    assert fields["succeeded"] == 1
    assert fields["failed"] == 0
    assert fields["deferred"] == 1
    assert fields["claude"] == "ok"
    assert fields["grok"] == "backoff"
