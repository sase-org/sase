"""Tests for sase.logs.launch_log."""

from __future__ import annotations

import json
import re
from pathlib import Path

from sase.logs.error_registry import error_anchor
from sase.logs.launch_log import (
    launch_failures_jsonl_path,
    launch_failures_log_path,
    log_launch_failure,
)

_ERROR_ID_RE = r"^err_\d{6}_\d{6}_[0-9a-f]{6}$"


def _boom(message: str = "workspace claim failed") -> RuntimeError:
    """Return a RuntimeError carrying a real traceback."""
    try:
        raise RuntimeError(message)
    except RuntimeError as exc:
        return exc


class TestLogLaunchFailure:
    def test_writes_both_files(self) -> None:
        log_launch_failure(
            kind="single",
            display_name="my-cl",
            exc=_boom(),
            project="proj",
            workspace_num=3,
            prompt_preview="do the thing",
        )

        jsonl = launch_failures_jsonl_path()
        human = launch_failures_log_path()
        assert jsonl.exists()
        assert human.exists()

    def test_jsonl_record_fields_and_traceback(self) -> None:
        log_launch_failure(
            kind="fanout",
            display_name="my-cl",
            exc=_boom("kaboom"),
            project="proj",
            workspace_num=7,
            prompt_preview="hello",
            fanout_kind="model",
            slot_count=3,
        )

        line = launch_failures_jsonl_path().read_text().strip().splitlines()[-1]
        record = json.loads(line)
        assert record["kind"] == "fanout"
        assert record["display_name"] == "my-cl"
        assert record["exc_type"] == "RuntimeError"
        assert record["exc_message"] == "kaboom"
        assert record["project"] == "proj"
        assert record["workspace_num"] == 7
        assert record["prompt_preview"] == "hello"
        assert record["fanout_kind"] == "model"
        assert record["slot_count"] == 3
        assert "timestamp" in record
        # Full traceback captured from the exception.
        assert "RuntimeError: kaboom" in record["traceback"]
        assert "_boom" in record["traceback"]

    def test_human_block_contains_context_and_traceback(self) -> None:
        log_launch_failure(
            kind="repeat",
            display_name="rep-cl",
            exc=_boom("nope"),
            project="proj",
            workspace_num=2,
            prompt_preview="prompt text",
            name_collision=True,
        )

        text = launch_failures_log_path().read_text()
        assert "repeat launch failure: rep-cl" in text
        assert "error: RuntimeError: nope" in text
        assert "project: proj" in text
        assert "workspace: #2" in text
        assert "name_collision: True" in text
        assert "prompt: prompt text" in text
        assert "traceback:" in text
        assert "RuntimeError: nope" in text

    def test_omits_none_optionals(self) -> None:
        log_launch_failure(
            kind="bulk",
            display_name="bulk 4 Patches",
            exc=_boom(),
            slot_count=4,
        )

        record = json.loads(
            launch_failures_jsonl_path().read_text().strip().splitlines()[-1]
        )
        assert "project" not in record
        assert "workspace_num" not in record
        assert "prompt_preview" not in record
        assert record["slot_count"] == 4

    def test_prompt_preview_truncated(self) -> None:
        log_launch_failure(
            kind="single",
            display_name="cl",
            exc=_boom(),
            prompt_preview="x" * 500,
        )

        record = json.loads(
            launch_failures_jsonl_path().read_text().strip().splitlines()[-1]
        )
        assert len(record["prompt_preview"]) == 200

    def test_appends_multiple_records(self) -> None:
        for i in range(3):
            log_launch_failure(
                kind="single",
                display_name=f"cl-{i}",
                exc=_boom(f"err {i}"),
            )

        lines = launch_failures_jsonl_path().read_text().strip().splitlines()
        assert len(lines) == 3
        kinds = [json.loads(line)["display_name"] for line in lines]
        assert kinds == ["cl-0", "cl-1", "cl-2"]

    def test_never_raises_on_write_error(self, monkeypatch) -> None:
        # A failing writer must not propagate — logging can never break a launch.
        def _explode(*_a: object, **_k: object) -> Path:
            raise OSError("disk full")

        monkeypatch.setattr("sase.logs.launch_log.launch_failures_jsonl_path", _explode)
        # Should not raise, and still return a minted id.
        used_id = log_launch_failure(kind="single", display_name="cl", exc=_boom())
        assert re.fullmatch(_ERROR_ID_RE, used_id)

    def test_returns_minted_error_id_and_stamps_both_logs(self) -> None:
        used_id = log_launch_failure(
            kind="single",
            display_name="alpha",
            exc=_boom(),
        )

        assert re.fullmatch(_ERROR_ID_RE, used_id)
        record = json.loads(
            launch_failures_jsonl_path().read_text().strip().splitlines()[-1]
        )
        assert record["error_id"] == used_id
        header = launch_failures_log_path().read_text().splitlines()[1]
        assert header.endswith(f"  {error_anchor(used_id)}")
        assert "single launch failure: alpha" in header

    def test_explicit_error_id_is_used_verbatim(self) -> None:
        error_id = "err_260617_143000_7f3a9c"
        used_id = log_launch_failure(
            kind="single",
            display_name="alpha",
            exc=_boom(),
            error_id=error_id,
        )

        assert used_id == error_id
        record = json.loads(
            launch_failures_jsonl_path().read_text().strip().splitlines()[-1]
        )
        assert record["error_id"] == error_id
        text = launch_failures_log_path().read_text()
        assert error_anchor(error_id) in text
