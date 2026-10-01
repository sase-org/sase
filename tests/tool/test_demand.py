"""Per-run demand recording: context, fail-open writes, and grant files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.tool import demand as demand_module
from sase.tool.demand import (
    demand_context,
    demand_file_path,
    read_demand_grants,
    record_run_demand,
)
from sase.tool.executor_process import DEMAND_FILE_NAME


def test_demand_context_from_env_provider_and_ceilings() -> None:
    env = {
        "SASE_AGENT_LLM_PROVIDER": "claude",
        "SASE_PROVIDER_SYNC_CEILING_SECONDS": "600",
        "SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS": "300",
    }
    assert demand_context(env) == {
        "provider": "claude",
        "sync_ceiling_seconds": 600,
        "sync_soft_ceiling_seconds": 300,
    }


def test_demand_context_falls_back_to_provider_overlay() -> None:
    env = {"SASE_TOOL_RUN_PROVIDER": "muse"}
    assert demand_context(env) == {"provider": "muse"}


def test_demand_context_without_starter_records_provider_only() -> None:
    env = {
        "SASE_AGENT_LLM_PROVIDER": "claude",
        "SASE_PROVIDER_SYNC_CEILING_SECONDS": "600",
    }
    assert demand_context(env, include_ceilings=False) == {"provider": "claude"}


def test_demand_context_with_none_at_all_is_none() -> None:
    assert demand_context({}) is None
    assert demand_context({"SASE_PROVIDER_SYNC_CEILING_SECONDS": "0"}) is None
    assert demand_context({"SASE_PROVIDER_SYNC_CEILING_SECONDS": "bogus"}) is None


def test_demand_context_invalid_ceilings_are_absent() -> None:
    env = {
        "SASE_AGENT_LLM_PROVIDER": "claude",
        "SASE_PROVIDER_SYNC_CEILING_SECONDS": "-5",
        "SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS": "  ",
    }
    assert demand_context(env) == {"provider": "claude"}


def test_record_run_demand_failure_warns_once_and_returns_false(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(demand_module, "_warned_no_demand", False)

    def _boom(_request: object) -> object:
        raise RuntimeError("store gone")

    monkeypatch.setattr(demand_module, "tool_run_record_demand", _boom)
    assert record_run_demand("run-1", usage={"cpu_user_ms": 5}) is False
    assert record_run_demand("run-1", usage={"cpu_user_ms": 5}) is False
    captured = capsys.readouterr()
    assert captured.err.count("sase: run demand not recorded") == 1


def test_record_run_demand_skips_empty_fragments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        demand_module, "tool_run_record_demand", lambda request: calls.append(request)
    )
    assert record_run_demand("run-1") is True
    assert calls == []


def _grant_line(run_id: str, **grant: object) -> str:
    base: dict[str, object] = {
        "grant_id": "g1",
        "source": "pytest",
        "observed_ts_ms": 1700000000000,
        "path": "lease",
        "requested_floor": 2,
        "requested_ceiling": 8,
        "granted": 3,
        "wait_ms": 0,
    }
    base.update(grant)
    return json.dumps(
        {"schema_version": 1, "kind": "worker_grant", "run_id": run_id, "grant": base}
    )


def test_read_demand_grants_valid_malformed_and_cross_run(tmp_path: Path) -> None:
    path = tmp_path / "demand.jsonl"
    path.write_text(
        "\n".join(
            [
                _grant_line("run-1"),
                "not json at all",
                json.dumps({"schema_version": 1, "kind": "sample"}),
                _grant_line("run-2", grant_id="other"),
                _grant_line("run-1", grant_id="g2", granted="three"),
                json.dumps(
                    {
                        "schema_version": 2,
                        "kind": "worker_grant",
                        "run_id": "run-1",
                        "grant": {"grant_id": "new"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    grants, diagnostics = read_demand_grants(path, "run-1")
    assert [grant["grant_id"] for grant in grants] == ["g1"]
    assert diagnostics == ["ignored cross-run demand record"]


def test_read_demand_grants_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_demand_grants(tmp_path / "absent.jsonl", "run-1") == ([], [])
    assert read_demand_grants(None, "run-1") == ([], [])


def test_read_demand_grants_skips_oversized_lines_and_caps_count(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demand.jsonl"
    lines = ["x" * 5000]
    lines.extend(_grant_line("run-1", grant_id=f"g{i}") for i in range(70))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    grants, _ = read_demand_grants(path, "run-1")
    assert len(grants) == 64
    assert grants[0]["grant_id"] == "g0"


def test_read_demand_grants_drops_out_of_range_with_diagnostic(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demand.jsonl"
    path.write_text(
        "\n".join(
            [
                _grant_line("run-1"),
                _grant_line("run-1", grant_id="negative", granted=-1),
                _grant_line("run-1", grant_id="huge", requested_ceiling=2**40),
                _grant_line("run-1", grant_id="negative", granted=-1),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    grants, diagnostics = read_demand_grants(path, "run-1")
    assert [grant["grant_id"] for grant in grants] == ["g1"]
    assert diagnostics == [
        "ignored out-of-range demand grant negative",
        "ignored out-of-range demand grant huge",
    ]


def test_read_demand_grants_ignores_grants_past_the_read_cap(
    tmp_path: Path,
) -> None:
    # The reader caps the file at 64 KiB; a grant past the cap is unread.
    read_cap = 64 * 1024
    path = tmp_path / "demand.jsonl"
    filler = json.dumps({"schema_version": 1, "kind": "sample", "padding": "x" * 4000})
    lines = [filler] * ((read_cap // (len(filler) + 1)) + 2)
    lines.append(_grant_line("run-1"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert path.stat().st_size > read_cap
    grants, _ = read_demand_grants(path, "run-1")
    assert grants == []


def test_demand_file_path_beside_events(tmp_path: Path) -> None:
    events = tmp_path / "run-1" / "events.jsonl"
    assert demand_file_path(events) == tmp_path / "run-1" / DEMAND_FILE_NAME
    assert demand_file_path(None) is None


def _writer_kwargs(**overrides: object) -> dict:
    kwargs: dict[str, object] = {
        "path": "lease",
        "requested_floor": 2,
        "requested_ceiling": 8,
        "granted": 7,
    }
    kwargs.update(overrides)
    return kwargs


def test_record_worker_grant_noop_without_channel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests._suite_gate_demand import record_worker_grant

    monkeypatch.delenv("SASE_TOOL_RUN_DEMAND", raising=False)
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "run-1")
    assert record_worker_grant(**_writer_kwargs()) is None
    monkeypatch.setenv("SASE_TOOL_RUN_DEMAND", str(tmp_path / "demand.jsonl"))
    monkeypatch.delenv("SASE_TOOL_RUN_ID", raising=False)
    assert record_worker_grant(**_writer_kwargs()) is None


def test_record_worker_grant_appends_one_json_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import stat

    from tests._suite_gate_demand import record_worker_grant

    demand_path = tmp_path / "demand.jsonl"
    monkeypatch.setenv("SASE_TOOL_RUN_DEMAND", str(demand_path))
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "run-1")
    grant_id = record_worker_grant(**_writer_kwargs(lane="fast", budget=12, wait_ms=50))
    assert grant_id
    assert stat.S_IMODE(demand_path.stat().st_mode) == 0o600
    record = json.loads(demand_path.read_text(encoding="utf-8"))
    assert record["schema_version"] == 1
    assert record["kind"] == "worker_grant"
    assert record["run_id"] == "run-1"
    grant = record["grant"]
    assert grant["grant_id"] == grant_id
    assert grant["source"] == "pytest"
    assert grant["lane"] == "fast"
    assert grant["budget"] == 12
    assert grant["wait_ms"] == 50


def test_record_worker_grant_never_raises_and_caps_line_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests._suite_gate_demand import record_worker_grant

    monkeypatch.setenv("SASE_TOOL_RUN_DEMAND", str(tmp_path / "missing" / "d.jsonl"))
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "run-1")
    assert record_worker_grant(**_writer_kwargs()) is None
    demand_path = tmp_path / "demand.jsonl"
    monkeypatch.setenv("SASE_TOOL_RUN_DEMAND", str(demand_path))
    assert record_worker_grant(**_writer_kwargs(lane="x" * 5000)) is None
    assert not demand_path.exists()
