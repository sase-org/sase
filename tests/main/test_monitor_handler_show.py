"""Behavior tests for the ``sase monitor show`` handler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.main.monitor_handler_helpers import (
    dispatch,
    make_monitor,
    monitor_home,
    patch_project_records,
)

__all__ = ["monitor_home"]


def test_show_renders_detail_panel_and_output_tail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The detail panel names the command/reason/lane, followed by output."""
    artifacts_dir = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="aaabbbcccddd",
        command="just check-full",
        reason="verify the fix",
    )
    (Path(artifacts_dir) / "live_reply.md").write_text(
        "running the suite...\n", encoding="utf-8"
    )
    patch_project_records(monkeypatch, [artifacts_dir])

    assert dispatch(["monitor", "show", "aaabbbcccddd"]) == 0

    out = capsys.readouterr().out
    assert "just check-full" in out
    assert "verify the fix" in out
    assert "acme" in out
    assert "running the suite..." in out


def test_show_resolves_by_lane_and_member_agent_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lane name or the exact member agent name both resolve to the record."""
    artifacts_dir = make_monitor(
        "proj", "20260812120000", "acme--mon", lane="acme", monitor_id="aaabbbcccddd"
    )
    patch_project_records(monkeypatch, [artifacts_dir])

    assert dispatch(["monitor", "show", "acme", "--output-only"]) == 0
    assert dispatch(["monitor", "show", "acme--mon", "--output-only"]) == 0


def test_show_unknown_ref_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unresolvable reference reports a usage error, not a crash."""
    patch_project_records(monkeypatch, [])

    assert dispatch(["monitor", "show", "ghost"]) == 2
    assert "no monitor matches" in capsys.readouterr().err


def test_show_output_only_suppresses_the_detail_panel(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``-o/--output-only`` prints just the captured output."""
    artifacts_dir = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="aaabbbcccddd",
        command="just check-full",
    )
    (Path(artifacts_dir) / "live_reply.md").write_text("hello\n", encoding="utf-8")
    patch_project_records(monkeypatch, [artifacts_dir])

    assert dispatch(["monitor", "show", "aaabbbcccddd", "--output-only"]) == 0

    out = capsys.readouterr().out
    assert out == "hello\n"


def test_show_output_reads_rotated_and_active_logs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    artifacts_dir = make_monitor(
        "proj", "20260812120000", "acme--mon", lane="acme", monitor_id="aaabbbcccddd"
    )
    path = Path(artifacts_dir) / "live_reply.md"
    path.with_name("live_reply.md.1").write_text("old\n", encoding="utf-8")
    path.write_text("new\n", encoding="utf-8")
    patch_project_records(monkeypatch, [artifacts_dir])

    assert dispatch(["monitor", "show", "aaabbbcccddd", "--output-only"]) == 0

    assert capsys.readouterr().out == "old\nnew\n"


def test_show_json_envelope_is_stable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The JSON envelope carries the monitor projection and captured output."""
    artifacts_dir = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="aaabbbcccddd",
        monitor_state="failed",
        exit_code=3,
    )
    (Path(artifacts_dir) / "live_reply.md").write_text("boom\n", encoding="utf-8")
    patch_project_records(monkeypatch, [artifacts_dir])

    assert dispatch(["monitor", "show", "aaabbbcccddd", "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["monitor"]["monitor_id"] == "aaabbbcccddd"
    assert payload["monitor"]["exit_code"] == 3
    assert payload["monitor"]["status_bucket"] == "Failed"
    assert payload["output"] == "boom\n"


def test_show_follow_streams_new_output_until_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--follow`` prints retained output, then streams until a terminal state."""
    artifacts_dir = make_monitor(
        "proj", "20260812120000", "acme--mon", lane="acme", monitor_id="aaabbbcccddd"
    )
    output_path = Path(artifacts_dir) / "live_reply.md"
    output_path.write_text("first line\n", encoding="utf-8")
    patch_project_records(monkeypatch, [artifacts_dir])

    from sase.main import monitor_handler as handler_module
    from sase.monitor.store import read_monitor_marker as real_read_monitor_marker

    calls = {"count": 0}

    def fake_read_monitor_marker(project_name: str, dir_: str):
        calls["count"] += 1
        if calls["count"] == 2:
            output_path.write_text(
                output_path.read_text(encoding="utf-8") + "and this\n",
                encoding="utf-8",
            )
            _set_monitor_state(artifacts_dir, "completed")
        return real_read_monitor_marker(project_name, dir_)

    monkeypatch.setattr(handler_module, "read_monitor_marker", fake_read_monitor_marker)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    assert dispatch(["monitor", "show", "aaabbbcccddd", "--follow"]) == 0

    out = capsys.readouterr().out
    assert "first line" in out
    assert "and this" in out


def test_read_new_text_resets_after_active_log_rotation(tmp_path: Path) -> None:
    from sase.main.monitor_handler import _read_new_text

    path = tmp_path / "live_reply.md"
    path.write_text("old current with more bytes\n", encoding="utf-8")

    os_offset = path.stat().st_size
    path.with_name("live_reply.md.1").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    path.write_text("new current\n", encoding="utf-8")

    text, offset = _read_new_text(path, os_offset)

    assert text == "new current\n"
    assert offset == len("new current\n")


def _set_monitor_state(artifacts_dir: str, state: str) -> None:
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["monitor_state"] = state
    meta["monitor_settled"] = state != "running"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
