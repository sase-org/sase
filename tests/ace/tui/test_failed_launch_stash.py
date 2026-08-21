"""Failed-launch stash coverage for the ACE TUI launch boundaries.

These pin that a failed agent launch which still holds the submitted prompt
preserves it in the per-user prompt stash so it stays recoverable through
``@`` / ``Ctrl+G p`` after the prompt bar has been unmounted:

- the single-agent launch task carries the submitted prompt as recovery
  metadata,
- a payloadless launch-task failure (worker died before returning an outcome,
  e.g. a project-alias canonicalization conflict) stashes that metadata and
  refreshes the badge, and
- a failed/partial launch outcome refreshes the badge from disk.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agent_workflow._launch_procs import LaunchProcMixin
from sase.ace.tui.actions.agent_workflow._prompt_bar_stash import PromptBarStashMixin
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.proc_observer import ObservedProc as ProcInfo
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.logs import clear_registered_errors

from ._agent_launch_helpers import _FakeApp


@pytest.fixture(autouse=True)
def _clear_registered_errors() -> Iterator[None]:
    clear_registered_errors()
    yield
    clear_registered_errors()


def _skip_without_prompt_stash_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "append_prompt_stash"):
        pytest.skip("sase_core_rs is too old (no append_prompt_stash binding).")


def _point_store_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("sase.core.paths.prompt_stash_path", lambda: path, raising=True)


def _entries(path: Path) -> list:
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    return list(read_prompt_stash_snapshot(path).entries)


class _CompletionApp(LaunchProcMixin, PromptBarStashMixin):
    """Real launch-completion + stash-badge glue without a live Textual DOM."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.applied_counts: list[int] = []
        self.applied_pinned_counts: list[int] = []
        self._prompt_context = None

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def _apply_prompt_stash_counts(self, count: int, pinned_count: int) -> None:
        self.applied_counts.append(count)
        self.applied_pinned_counts.append(pinned_count)

    # Payload-branch collaborators (unused by the error-only outcomes here).
    def _handle_launch_results_delta(self, results: Any) -> None:
        del results

    def request_agents_refresh(self, source: str) -> None:
        del source

    def _schedule_agents_async_refresh(self, *, source: str = "launch") -> None:
        del source


async def _drain_async_tasks(app: object) -> None:
    for attr in ("_prompt_stash_async_tasks", "_launch_failure_log_tasks"):
        tasks: list[Any] = list(getattr(app, attr, None) or [])
        for task in tasks:
            await task


def _completion(
    *,
    success: bool,
    payload: dict[str, object] | None,
    proc_id: str = "task-1",
    message: str = "m",
) -> TrackedProcCompletion[object]:
    return TrackedProcCompletion(
        proc_info=ProcInfo(
            proc_id=proc_id,
            proc_type="launch",
            cl_name="cl",
            project_file="/tmp/proj.sase",
            status="error" if not success else "success",
            message=message,
            started_at=datetime.now(),
            display_name="launch cl",
        ),
        success=success,
        message=message,
        output="",
        payload=payload,
        error=None if success else "worker died",
    )


# --- single-agent launch threads the submitted prompt as recovery metadata --


def test_launch_resolved_prompt_threads_submitted_prompt() -> None:
    app = _FakeApp()

    app._finish_agent_launch("a long prompt to keep recoverable")

    assert len(app.launch_tasks) == 1
    assert (
        app.launch_tasks[0]["submitted_prompt"] == "a long prompt to keep recoverable"
    )


# --- payloadless launch-task failure (the project-alias conflict regression) -


async def test_payloadless_failure_with_metadata_stashes_and_refreshes_badge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)

    app = _CompletionApp()
    lost = "#al:thing build the entire feature, this is a long prompt"
    app._launch_submitted_prompts = {"task-1": lost}
    logged: list[dict[str, Any]] = []

    with patch(
        "sase.logs.log_launch_failure",
        side_effect=lambda **kwargs: logged.append(kwargs),
    ):
        app._on_launch_proc_complete(_completion(success=False, payload=None))
        await _drain_async_tasks(app)

    entries = _entries(stash_path)
    assert [e.text for e in entries] == [lost]
    assert entries[0].source == "failed_launch"
    # The badge reflects the freshly stashed row.
    assert app.applied_counts and app.applied_counts[-1] == 1
    # Recovery metadata is consumed exactly once.
    assert app._launch_submitted_prompts == {}
    assert [item["prompt_preview"] for item in logged] == [lost]


async def test_payloadless_failure_without_metadata_does_not_stash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)

    app = _CompletionApp()
    app._on_launch_proc_complete(_completion(success=False, payload=None))
    await _drain_async_tasks(app)

    assert not stash_path.exists()
    assert app.applied_counts == []


# --- failed/partial outcome refreshes the badge from disk -------------------


async def test_error_outcome_refreshes_badge_for_worker_stashed_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)

    # Simulate the worker having already stashed its prompt synchronously.
    from sase.agent.failed_launch_prompt_stash import stash_failed_launch_prompt

    stash_failed_launch_prompt("already stashed by the worker thread")

    app = _CompletionApp()
    app._on_launch_proc_complete(
        _completion(
            success=False,
            payload={},
            message="Launch failed",
        )
    )
    await _drain_async_tasks(app)

    assert app.applied_counts and app.applied_counts[-1] == 1
    assert app.notifications[-1] == ("Launch failed", "error")
