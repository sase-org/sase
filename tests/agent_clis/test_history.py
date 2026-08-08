from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sase.agent_clis import history
from sase.agent_clis.history import (
    MAX_OUTPUT_TAIL_CHARS,
    MAX_REASON_CHARS,
    read_agent_cli_update_runs,
    record_agent_cli_update_run,
    should_record_run,
)
from sase.agent_clis.models import (
    AgentCliOperation,
    AgentCliUpdateResult,
    UpdateResultStatus,
    UpdateTrigger,
)

_NOW = datetime(2026, 8, 3, 6, 41, 14, tzinfo=ZoneInfo("America/New_York"))


def _result(
    status: UpdateResultStatus,
    *,
    name: str = "claude",
    command: tuple[str, ...] | None = ("claude", "update"),
    reason: str | None = None,
    output_tail: str | None = None,
) -> AgentCliUpdateResult:
    return AgentCliUpdateResult(
        name=name,
        display_name=name.title(),
        status=status,
        old_version="1.0.0",
        new_version="2.0.0",
        command=command,
        docs_url=f"https://example.test/{name}",
        elapsed=2.5,
        reason=reason,
        output_tail=output_tail,
    )


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ((_result(UpdateResultStatus.UPDATED),), True),
        ((_result(UpdateResultStatus.FAILED),), True),
        (
            (
                _result(
                    UpdateResultStatus.ALREADY_CURRENT,
                    command=None,
                ),
            ),
            False,
        ),
        ((_result(UpdateResultStatus.SKIPPED, command=None),), False),
        ((), False),
    ],
)
def test_should_record_run(
    results: tuple[AgentCliUpdateResult, ...], expected: bool
) -> None:
    assert should_record_run(results) is expected


def test_recorded_run_round_trips_every_field_in_plan_order(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    results = (
        _result(UpdateResultStatus.UPDATED),
        _result(
            UpdateResultStatus.SKIPPED,
            name="codex",
            command=None,
            reason="not installed",
        ),
    )

    recorded = record_agent_cli_update_run(
        results,
        trigger=UpdateTrigger.COMPREHENSIVE,
        elapsed=12.41,
        path=path,
        now=_NOW,
        run_id="9f2c1ab40e77",
    )

    assert recorded is not None
    assert read_agent_cli_update_runs(path=path) == (recorded,)
    assert recorded.run_id == "9f2c1ab40e77"
    assert recorded.timestamp == "2026-08-03T06:41:14-04:00"
    assert recorded.epoch == _NOW.timestamp()
    assert recorded.trigger is UpdateTrigger.COMPREHENSIVE
    assert recorded.all_clis is True
    assert recorded.elapsed_seconds == 12.41
    assert recorded.counts == {
        "updated": 1,
        "already_current": 0,
        "failed": 0,
        "skipped": 1,
    }
    assert [entry.name for entry in recorded.entries] == ["claude", "codex"]
    assert recorded.executed_entries == (recorded.entries[0],)
    assert recorded.executed_count == 1


def test_read_returns_newest_first_and_honors_limit(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    for run_id in ("first", "second", "third"):
        assert record_agent_cli_update_run(
            (_result(UpdateResultStatus.UPDATED),),
            trigger=UpdateTrigger.CLI,
            elapsed=1.0,
            path=path,
            now=_NOW,
            run_id=run_id,
        )

    assert [run.run_id for run in read_agent_cli_update_runs(path=path)] == [
        "third",
        "second",
        "first",
    ]
    assert [run.run_id for run in read_agent_cli_update_runs(path=path, limit=2)] == [
        "third",
        "second",
    ]


def test_read_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_agent_cli_update_runs(path=tmp_path / "missing.jsonl") == ()


def test_read_skips_malformed_and_unsupported_records(tmp_path: Path) -> None:
    valid_path = tmp_path / "valid.jsonl"
    assert record_agent_cli_update_run(
        (_result(UpdateResultStatus.UPDATED),),
        trigger=UpdateTrigger.CLI,
        elapsed=1.0,
        path=valid_path,
        now=_NOW,
        run_id="valid",
    )
    valid_line = valid_path.read_text(encoding="utf-8").strip()
    path = tmp_path / "mixed.jsonl"
    path.write_text(
        '\nnot json\n[]\n{"schema_version": 99}\n' + valid_line + "\n",
        encoding="utf-8",
    )

    runs = read_agent_cli_update_runs(path=path)

    assert len(runs) == 1
    assert runs[0].run_id == "valid"


def test_unknown_trigger_decodes_as_unknown(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    assert record_agent_cli_update_run(
        (_result(UpdateResultStatus.UPDATED),),
        trigger=UpdateTrigger.CLI,
        elapsed=1.0,
        path=path,
        now=_NOW,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["trigger"] = "future-trigger"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert read_agent_cli_update_runs(path=path)[0].trigger is UpdateTrigger.UNKNOWN


def test_record_truncates_reason_and_keeps_only_failed_output(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    long_reason = "r" * (MAX_REASON_CHARS + 10)
    long_output = "prefix" + "o" * MAX_OUTPUT_TAIL_CHARS
    results = (
        _result(
            UpdateResultStatus.FAILED,
            reason=long_reason,
            output_tail=long_output,
        ),
        _result(
            UpdateResultStatus.UPDATED,
            name="codex",
            reason=long_reason,
            output_tail="successful noise",
        ),
    )

    run = record_agent_cli_update_run(
        results,
        trigger=UpdateTrigger.ADMIN_CENTER,
        elapsed=1.0,
        path=path,
        now=_NOW,
    )

    assert run is not None
    assert run.entries[0].reason == "r" * MAX_REASON_CHARS
    assert run.entries[0].output_tail == "o" * MAX_OUTPUT_TAIL_CHARS
    assert run.entries[1].output_tail is None


def test_append_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        history,
        "append_jsonl_record",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("read only")),
    )

    assert (
        record_agent_cli_update_run(
            (_result(UpdateResultStatus.FAILED),),
            trigger=UpdateTrigger.CLI,
            elapsed=1.0,
            now=_NOW,
        )
        is None
    )


def test_rotation_keeps_complete_readable_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "history.jsonl"
    assert record_agent_cli_update_run(
        (_result(UpdateResultStatus.UPDATED),),
        trigger=UpdateTrigger.CLI,
        elapsed=1.0,
        path=path,
        now=_NOW,
        run_id="first",
    )
    max_bytes = path.stat().st_size + 10
    monkeypatch.setenv(history.ENV_MAX_BYTES, str(max_bytes))

    second = record_agent_cli_update_run(
        (_result(UpdateResultStatus.UPDATED),),
        trigger=UpdateTrigger.CLI,
        elapsed=1.0,
        path=path,
        now=_NOW,
        run_id="second",
    )

    assert second is not None
    assert path.stat().st_size <= max_bytes
    assert read_agent_cli_update_runs(path=path) == (second,)
    assert path.with_name("history.jsonl.1").read_text(encoding="utf-8").endswith("\n")


def test_successful_noop_does_not_append(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    current = replace(
        _result(UpdateResultStatus.UPDATED),
        status=UpdateResultStatus.ALREADY_CURRENT,
    )

    assert (
        record_agent_cli_update_run(
            (current,),
            trigger=UpdateTrigger.CLI,
            elapsed=1.0,
            path=path,
            now=_NOW,
        )
        is None
    )
    assert not path.exists()


def test_install_runs_journal_their_operation_and_script_digest(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.jsonl"
    install = replace(
        _result(UpdateResultStatus.UPDATED, name="muse"),
        operation=AgentCliOperation.INSTALL,
        script_digest="d" * 64,
    )

    run = record_agent_cli_update_run(
        (install,),
        trigger=UpdateTrigger.CLI,
        elapsed=1.0,
        path=path,
        now=_NOW,
    )

    assert run is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["entries"][0]["operation"] == "install"
    assert payload["entries"][0]["script_digest"] == "d" * 64
    assert read_agent_cli_update_runs(path=path) == (run,)


def test_records_written_before_installs_shipped_still_decode(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    assert record_agent_cli_update_run(
        (_result(UpdateResultStatus.UPDATED),),
        trigger=UpdateTrigger.CLI,
        elapsed=1.0,
        path=path,
        now=_NOW,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["entries"][0].pop("operation")
    payload["entries"][0].pop("script_digest")
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    entry = read_agent_cli_update_runs(path=path)[0].entries[0]

    assert entry.operation is AgentCliOperation.UPDATE
    assert entry.script_digest is None
