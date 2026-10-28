"""Tool-run store busy-timeout delegation tests."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import Mock

import pytest


pytestmark = pytest.mark.skipif(
    not hasattr(importlib.import_module("sase_core_rs"), "tool_run_begin"),
    reason="tool_run bindings are not in this wheel",
)


@pytest.mark.parametrize(
    "name",
    [
        "tool_run_append_event",
        "tool_run_begin",
        "tool_run_briefs",
        "tool_run_claim",
        "tool_run_detail",
        "tool_run_failures",
        "tool_run_finish",
        "tool_run_join",
        "tool_run_list",
        "tool_run_live_glance",
        "tool_run_node_summaries",
        "tool_run_observe",
        "tool_run_receipt_lookup",
        "tool_run_receipt_settle",
        "tool_run_receipts_report",
        "tool_run_reconcile",
        "tool_run_record_demand",
        "tool_run_release_join",
        "tool_run_request_stop",
        "tool_run_retention_apply",
        "tool_run_retention_preview",
        "tool_run_show",
        "tool_run_stats_report",
        "tool_run_store_stats",
        "tool_run_summary",
        "tool_run_triage_record",
        "tool_run_triage_settle",
        "tool_run_triage_show",
        "tool_run_triage_stage",
    ],
)
@pytest.mark.parametrize(
    "budget", [None, 0, 37], ids=["omitted", "core-default", "explicit"]
)
def test_store_adapters_delegate_busy_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, budget: int | None
) -> None:
    """The Python boundary delegates defaults and preserves caller deadlines."""
    from sase.core import tool_run

    binding = Mock(return_value={})
    resolver = Mock(return_value=binding)
    monkeypatch.setattr(tool_run, "require_rust_binding", resolver)
    kwargs = {} if budget is None else {"busy_timeout_ms": budget}
    store = str(tmp_path / "ledger.sqlite")
    if name == "tool_run_store_stats":
        args = ()
    elif name in ("tool_run_show", "tool_run_detail"):
        args = ("run-1",)
    else:
        args = ({"schema_version": 1},)
    getattr(tool_run, name)(*args, store_path=store, **kwargs)

    resolver.assert_called_once_with(name)
    binding.assert_called_once()
    assert binding.call_args.args[0] == store
    assert binding.call_args.args[-1] == (0 if budget is None else budget)
