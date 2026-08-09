"""Repeat and bulk launch fan-out tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.repeat_launcher import RepeatAgentSpec
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from tests.ace.tui._launch_fan_out_helpers import _BulkApp, _ctx, _RepeatApp


def _skip_without_prompt_stash_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "append_prompt_stash"):
        pytest.skip("sase_core_rs is too old (no append_prompt_stash binding).")


def test_repeat_launch_runs_off_main_thread_and_batches_delta() -> None:
    app = _RepeatApp()
    ctx = _ctx()

    def _fake_batch(
        prompt: str,
        *,
        base_spawn_fn: Callable[[RepeatAgentSpec], None],
        sleep_between: float = 0.0,
        timestamps: list[str] | None = None,
    ) -> list[RepeatAgentSpec]:
        del prompt, sleep_between
        assert timestamps == ["260501_120000", "260501_120001", "260501_120002"]
        specs = [
            RepeatAgentSpec(
                prompt="p",
                name=f"n{i}",
                iteration=i,
                total=3,
                timestamp=timestamps[i],
            )
            for i in range(3)
        ]
        for spec in specs:
            base_spawn_fn(spec)
        return specs

    with patch("sase.running_field.claim_next_axe_workspace", return_value=2):
        with patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/tmp/ws", None),
        ):
            with patch(
                "sase.running_field.get_workspace_directory", return_value="/tmp/ws"
            ):
                with patch(
                    "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
                    return_value=[
                        "260501_120000",
                        "260501_120001",
                        "260501_120002",
                    ],
                ):
                    with patch(
                        "sase.agent.repeat_launcher.spawn_repeat_batch",
                        side_effect=_fake_batch,
                    ):
                        outcome = app._run_repeat_launch(
                            "p %r:3", ctx, None, has_wait=False
                        )

    assert len(app.launched) == 3
    app._apply_launch_outcome(outcome)
    assert app.refresh_requests == []
    assert len(app.launch_delta_batches) == 1
    assert [result.timestamp for result in app.launch_delta_batches[0]] == [
        "260501_120000",
        "260501_120001",
        "260501_120002",
    ]


def test_repeat_launch_failure_records_failed_history() -> None:
    app = _RepeatApp()
    ctx = _ctx()

    with (
        patch(
            "sase.agent.repeat_launcher.extract_repeat_and_name",
            return_value=(3, None, "repeat prompt"),
        ),
        patch(
            "sase.agent.repeat_launcher.spawn_repeat_batch",
            side_effect=RuntimeError("repeat failed"),
        ),
        patch("sase.history.prompt.record_failed_launch_prompt") as record_failed,
    ):
        outcome = app._run_repeat_launch("repeat prompt %r:3", ctx, None, False)

    record_failed.assert_called_once_with("repeat prompt %r:3")
    assert outcome.message == "Repeat launch failed - see Logs in SASE Admin Center (#)"
    assert outcome.severity == "error"


def test_bulk_launch_takes_patch_snapshot() -> None:
    """Mutating ``_bulk_patches`` after dispatch must not affect the worker."""

    class _CS:
        def __init__(self, name: str) -> None:
            self.name = name
            self.project_basename = "proj"

    app = _BulkApp()
    app._bulk_patches = [_CS("a"), _CS("b")]  # type: ignore[list-item]
    app._prompt_context = _ctx()

    with patch("os.path.isfile", return_value=False):
        app._launch_bulk_agents("the prompt")

    # The bulk-launch entry zeros out the live ref before dispatch so a
    # subsequent mutation is impossible. The worker received its own local copy.
    assert app._bulk_patches is None
    # A tracked launch task was submitted to drive the worker.
    assert len(app.launch_tasks) == 1
    assert app.launch_tasks[0]["display_name"] == "launch bulk 2 Patches"
    # The shared prompt rides along as payloadless-failure recovery metadata.
    assert app.launch_tasks[0]["submitted_prompt"] == "the prompt"


def test_bulk_partial_failure_leaves_stash_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bulk launch with any failed slot stashes the shared prompt once."""
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    monkeypatch.setattr(
        "sase.core.paths.prompt_stash_path", lambda: stash_path, raising=True
    )

    class _CS:
        def __init__(self, name: str) -> None:
            self.name = name
            self.project_basename = "proj"

    app = _BulkApp()
    # A single patch whose project file is missing fails the whole launch.
    with patch("os.path.isfile", return_value=False):
        outcome = app._run_bulk_launch("the bulk prompt", [_CS("a")])  # type: ignore[list-item]

    assert outcome.severity == "warning"

    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    entries = read_prompt_stash_snapshot(stash_path).entries
    assert [e.text for e in entries] == ["the bulk prompt"]
    assert entries[0].source == "failed_launch"
