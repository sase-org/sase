"""End-to-end usage-limit coverage through the real executor and fakey.

Exercises the production path: fakey subprocess failure, invocation error
handling, first-writer disable, the automatic drain that owns the
notification, retry precedence, and the original provider error remaining
the raised exception.
"""

from __future__ import annotations

import threading
import time as real_time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe import run_agent_exec_retry
from sase.llm_provider.provider_disable import (
    disable_provider,
    get_active_provider_disables,
)
from sase.notifications.store import load_notifications
from sase.macro.workflow_models import WorkflowExecutionError

from tests.fakey.harness import FakeyRetryHarness, usage_limit_failure


def test_usage_limit_failure_disables_only_fakey_and_preserves_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = FakeyRetryHarness(
        tmp_path,
        monkeypatch,
        max_retries=2,
        wait_times=[5],
    )
    harness.use_scenario(monkeypatch, [usage_limit_failure()])
    # Freeze the sibling window. Reloaded timestamps can differ by one ULP, so
    # the later asserts compare identity fields rather than the whole object.
    sibling_now = 1_800_000_000.0
    sibling = disable_provider("claude", 900.0, source="ace", now=sibling_now)

    increments: list[str] = []
    retry_sleeps: list[float] = []
    lock = threading.Lock()

    class _Counter:
        def labels(self, **kwargs: object) -> object:
            provider = str(kwargs.get("provider"))

            class _Labeled:
                def inc(self) -> None:
                    with lock:
                        increments.append(provider)

            return _Labeled()

    monkeypatch.setattr(
        run_agent_exec_retry,
        "time",
        SimpleNamespace(time=real_time.time, sleep=retry_sleeps.append),
    )

    with (
        patch(
            "sase.llm_provider.usage_limit_disable.LLM_PROVIDER_AUTO_DISABLES",
            _Counter(),
        ),
        patch("sase.procs.submit_proc_request") as submit_drain,
    ):
        with pytest.raises(WorkflowExecutionError, match="FAKEY-USAGE-LIMIT") as caught:
            harness.run()

    assert "FAKEY-USAGE-LIMIT" in str(caught.value)
    assert retry_sleeps == []
    assert len(harness.invocation_records()) == 1
    assert increments == ["fakey"]

    disables = get_active_provider_disables()
    assert set(disables) == {"claude", "fakey"}
    stored_claude = disables["claude"]
    assert stored_claude.provider == sibling.provider == "claude"
    assert stored_claude.source == sibling.source == "ace"
    assert stored_claude.created_at == pytest.approx(sibling.created_at)
    assert stored_claude.expires_at == pytest.approx(sibling.expires_at)
    assert stored_claude.expires_at is not None
    assert stored_claude.expires_at - stored_claude.created_at == pytest.approx(900.0)
    assert disables["fakey"].source == "usage_limit"

    # A hard disable submits one durable drain that owns the (enriched)
    # notification, so this process sends no inline notification.
    submit_drain.assert_called_once()
    drain_request = submit_drain.call_args.args[0]
    assert drain_request.argv[:4] == ["sase", "agent", "drain", "fakey"]
    assert drain_request.operation_payload["notify"] is True
    assert "fakey" in drain_request.tags
    assert [
        note for note in load_notifications() if note.sender == "llm.usage_limit"
    ] == []

    attempt = harness.attempt_meta(1)
    assert attempt["status"] == "raised"
    assert attempt["reason"] is not None
    assert "usage limit" in attempt["reason"]
    assert "fakey" in attempt["reason"]
    assert "FAKEY-USAGE-LIMIT" in attempt["error_full"]
