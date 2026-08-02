"""Tests for warm prompt commit inventory snapshots."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from textual.worker import Worker, WorkerState

from sase.ace.tui.widgets.prompt_commit_inventory import (
    ArtifactRefCommitRow,
    PROMPT_COMMIT_INVENTORY_TTL,
    PromptCommitSnapshot,
    load_prompt_commit_snapshot,
    prompt_commit_snapshot_expired,
    revalidate_prompt_commit_snapshot,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


def _context() -> SimpleNamespace:
    return SimpleNamespace(to_wire=lambda: {"repositories": []})


def test_snapshot_maps_shared_core_rows_without_rederiving_fields() -> None:
    inventory = {
        "payloads": [
            {
                "payload": "sase@5143cb981f0a",
                "label": "fix(stats): expose payload inventory",
                "detail": "",
                "age": "3h",
                "scope": "sase",
                "rank": 7,
                "body": "Longer explanation\nwith a second line.",
            },
            {"label": "missing payload is ignored"},
        ],
        "truncated_payloads": 4,
    }
    binding = Mock(return_value=inventory)
    with patch(
        "sase.ace.tui.widgets.prompt_commit_inventory.require_rust_binding",
        return_value=binding,
    ) as loader:
        snapshot = load_prompt_commit_snapshot(
            "sase",
            _context(),  # type: ignore[arg-type]
            loaded_at=12.0,
        )

    loader.assert_called_once_with("artifact_ref_payload_inventory")
    binding.assert_called_once_with("commit", {"repositories": []})
    assert snapshot == PromptCommitSnapshot(
        "sase",
        (
            ArtifactRefCommitRow(
                payload="sase@5143cb981f0a",
                label="fix(stats): expose payload inventory",
                detail="",
                age="3h",
                scope="sase",
                rank=7,
                body="Longer explanation\nwith a second line.",
            ),
        ),
        12.0,
        4,
    )


def test_revalidation_preserves_identity_inside_ttl_and_reloads_when_expired() -> None:
    previous = PromptCommitSnapshot("sase", (), 10.0)
    replacement = PromptCommitSnapshot("sase", (), 20.0)

    with patch(
        "sase.ace.tui.widgets.prompt_commit_inventory.load_prompt_commit_snapshot",
        return_value=replacement,
    ) as loader:
        inside = revalidate_prompt_commit_snapshot(
            previous,
            "sase",
            _context(),  # type: ignore[arg-type]
            now=10.0 + PROMPT_COMMIT_INVENTORY_TTL - 0.01,
        )
        expired = revalidate_prompt_commit_snapshot(
            previous,
            "sase",
            _context(),  # type: ignore[arg-type]
            now=10.0 + PROMPT_COMMIT_INVENTORY_TTL,
        )

    assert inside is previous
    assert expired is replacement
    loader.assert_called_once()
    assert prompt_commit_snapshot_expired(
        previous,
        now=10.0 + PROMPT_COMMIT_INVENTORY_TTL,
    )


def test_cold_commit_snapshot_schedules_one_threaded_worker() -> None:
    text_area = PromptTextArea()
    context = _context()

    with patch.object(type(text_area), "run_worker") as run_worker:
        text_area._schedule_prompt_commit_inventory_load(
            "sase",
            context,  # type: ignore[arg-type]
        )
        text_area._schedule_prompt_commit_inventory_load(
            "sase",
            context,  # type: ignore[arg-type]
        )

    assert text_area._prompt_commit_inflight == {"sase"}
    run_worker.assert_called_once()
    assert run_worker.call_args.kwargs["group"] == "prompt-commit-inventory"
    assert run_worker.call_args.kwargs["thread"] is True


def test_running_worker_keeps_its_project_marked_inflight() -> None:
    text_area = PromptTextArea()
    context = _context()

    with patch.object(type(text_area), "run_worker") as run_worker:
        text_area._schedule_prompt_commit_inventory_load(
            "sase",
            context,  # type: ignore[arg-type]
        )
    worker_name = run_worker.call_args.kwargs["name"]

    for state in (WorkerState.PENDING, WorkerState.RUNNING):
        text_area.on_worker_state_changed(
            _worker_event(worker_name, state),
        )
        assert text_area._prompt_commit_inflight == {"sase"}

    with patch.object(type(text_area), "run_worker") as rerun_worker:
        text_area._schedule_prompt_commit_inventory_load(
            "sase",
            context,  # type: ignore[arg-type]
        )
    rerun_worker.assert_not_called()

    text_area.on_worker_state_changed(
        _worker_event(worker_name, WorkerState.ERROR),
    )
    assert text_area._prompt_commit_inflight == set()


def _worker_event(name: str, state: WorkerState) -> Worker.StateChanged:
    worker = SimpleNamespace(
        name=name,
        group="prompt-commit-inventory",
        result=None,
    )
    return cast(Worker.StateChanged, SimpleNamespace(worker=worker, state=state))


def test_fresh_snapshot_does_not_schedule_revalidation() -> None:
    text_area = PromptTextArea()
    snapshot = PromptCommitSnapshot("sase", (), 10.0)

    with (
        patch(
            "sase.ace.tui.widgets._file_completion_workers."
            "prompt_commit_snapshot_expired",
            return_value=False,
        ),
        patch.object(type(text_area), "run_worker") as run_worker,
    ):
        text_area._schedule_prompt_commit_inventory_load(
            "sase",
            _context(),  # type: ignore[arg-type]
            snapshot,
        )

    run_worker.assert_not_called()
    assert text_area._prompt_commit_inflight == set()
