from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.chop_subprocess_diagnostics import (
    SUBPROCESS_DIAGNOSTIC_LOG_READ_BYTES,
    capture_chop_subprocess_diagnostic,
)
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.lumberjack import Lumberjack
from sase.axe.state import (
    MAX_CHOP_RUN_HISTORY,
    chop_run_log_path,
    read_chop_run,
    read_errors,
)
from sase.notifications import senders
from sase.notifications.models import Notification

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]

_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"


def test_capture_subprocess_diagnostic_bounds_and_sanitizes_output(
    temp_state_dir: Path,
) -> None:
    run_id = "20260906T211142_996558"
    log_path = chop_run_log_path("telegram", "tg_inbound", run_id)
    log_path.parent.mkdir(parents=True)
    giant_line = "x" * (20 * 1024)
    log_path.write_bytes(
        (
            ("old line\n" * 7000)
            + "fatal: non-python stderr\n"
            + giant_line
            + f"\n\x1b[31mhttps://api.telegram.org/bot{_TOKEN}/getUpdates\x1b[0m"
            + "\n"
        ).encode("utf-8")
        + b"\xff"
        + b"\ntelegram.error.TimedOut: Timed out"
    )

    diagnostic = capture_chop_subprocess_diagnostic(
        lumberjack_name="telegram",
        chop_name="tg_inbound",
        run_id=run_id,
        exit_code=-7,
    )
    excerpt = diagnostic["output_excerpt"]

    assert diagnostic["exit_code"] == -7
    assert diagnostic["output_status"] == "captured"
    assert diagnostic["had_decode_errors"] is True
    assert diagnostic["truncated"] is True
    assert diagnostic["omitted_bytes"] > 0
    assert len(excerpt.encode("utf-8")) <= 16 * 1024
    assert "telegram.error.TimedOut: Timed out" in excerpt
    assert "bot<redacted>/getUpdates" in excerpt
    assert _TOKEN not in excerpt
    assert "\x1b" not in excerpt


def test_capture_subprocess_diagnostic_classifies_absent_and_missing_logs(
    temp_state_dir: Path,
) -> None:
    silent_run_id = "silent"
    silent_log = chop_run_log_path("hooks", "silent_chop", silent_run_id)
    silent_log.parent.mkdir(parents=True)
    silent_log.write_bytes(b"")

    absent = capture_chop_subprocess_diagnostic(
        lumberjack_name="hooks",
        chop_name="silent_chop",
        run_id=silent_run_id,
        exit_code=1,
    )
    missing = capture_chop_subprocess_diagnostic(
        lumberjack_name="hooks",
        chop_name="missing_chop",
        run_id="missing",
        exit_code=1,
    )

    assert absent["output_status"] == "absent"
    assert absent["output_excerpt"] == ""
    assert absent["truncated"] is False
    assert missing["output_status"] == "unavailable"
    assert missing["unavailable_reason"] == "missing_log"


def test_capture_subprocess_diagnostic_reads_only_bounded_log_tail(
    temp_state_dir: Path,
) -> None:
    run_id = "bounded"
    log_path = chop_run_log_path("hooks", "bounded_chop", run_id)
    log_path.parent.mkdir(parents=True)
    old_prefix = b"old" * SUBPROCESS_DIAGNOSTIC_LOG_READ_BYTES
    log_path.write_bytes(
        old_prefix
        + b"\nrecent non-python stderr"
        + b"\ntelegram.error.TimedOut: Timed out"
    )

    diagnostic = capture_chop_subprocess_diagnostic(
        lumberjack_name="hooks",
        chop_name="bounded_chop",
        run_id=run_id,
        exit_code=2,
    )

    assert "recent non-python stderr" in diagnostic["output_excerpt"]
    assert "telegram.error.TimedOut: Timed out" in diagnostic["output_excerpt"]
    assert diagnostic["omitted_bytes"] >= SUBPROCESS_DIAGNOSTIC_LOG_READ_BYTES


def test_run_configured_chop_once_preserves_subprocess_diagnostic(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(
        tmp_path,
        "tg_inbound",
        _fake_timeout_traceback_script_body(exit_code=1),
    )
    axe_config = AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")])
    chop = ChopConfig(name="tg_inbound", description="")

    with patch("sase.axe.chop_runner.find_all_patches", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="telegram",
            chop=chop,
            axe_config=axe_config,
            source="manual",
        )

    assert outcome.status == "failure"
    assert outcome.subprocess_diagnostic is not None
    assert (
        "telegram.error.TimedOut: Timed out"
        in (outcome.subprocess_diagnostic["output_excerpt"])
    )
    assert outcome.run_id is not None
    entry = read_chop_run("telegram", "tg_inbound", outcome.run_id)
    assert entry is not None
    assert entry.subprocess_diagnostic == outcome.subprocess_diagnostic


def test_timeout_preserves_partial_subprocess_output(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(
        tmp_path,
        "slow_chop",
        (
            f"\"{sys.executable}\" - <<'PY'\n"
            "import sys, time\n"
            "sys.stderr.write('partial timeout output\\n')\n"
            "sys.stderr.flush()\n"
            "time.sleep(5)\n"
            "PY\n"
        ),
    )
    axe_config = AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")])

    with patch("sase.axe.chop_runner.find_all_patches", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="hooks",
            chop=ChopConfig(name="slow_chop", description="", timeout=1),
            axe_config=axe_config,
            source="manual",
        )

    assert outcome.status == "timeout"
    assert outcome.subprocess_diagnostic is not None
    assert "partial timeout output" in outcome.subprocess_diagnostic["output_excerpt"]


def test_scheduled_error_digest_keeps_diagnostic_after_run_log_pruned(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(
        tmp_path,
        "tg_inbound",
        _fake_timeout_traceback_script_body(exit_code=1),
    )
    axe_config = AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")])
    config = LumberjackConfig(
        name="telegram",
        description="Poll Telegram inbound messages",
        interval=60,
        chops=[ChopConfig(name="tg_inbound", description="")],
    )

    with patch("sase.axe.check_cycles.find_all_patches", return_value=[]):
        lumberjack = Lumberjack("telegram", config, axe_config)
        lumberjack._run_tick()

        errors = read_errors()
        assert len(errors) == 1
        diagnostic = errors[0]["subprocess_diagnostic"]
        failed_run_id = diagnostic["run_id"]
        entry = read_chop_run("telegram", "tg_inbound", failed_run_id)
        assert entry is not None
        assert entry.subprocess_diagnostic == diagnostic

        make_script(tmp_path, "tg_inbound", "echo recovered\n")
        for _ in range(MAX_CHOP_RUN_HISTORY + 1):
            lumberjack._run_tick()

    assert read_chop_run("telegram", "tg_inbound", failed_run_id) is None
    assert not chop_run_log_path("telegram", "tg_inbound", failed_run_id).exists()

    notifications: list[Notification] = []
    with (
        patch("sase.notifications.senders.sase_subdir", return_value=temp_state_dir),
        patch("sase.notifications.senders.append_notification", notifications.append),
    ):
        senders.notify_axe_error_digest(errors)

    report_path = Path(notifications[0].files[0])
    report = report_path.read_text(encoding="utf-8")
    assert failed_run_id in report
    assert "Subprocess Output:" in report
    assert "telegram.error.TimedOut: Timed out" in report
    assert "bot<redacted>/getUpdates" in report
    assert _TOKEN not in report
    assert "<no python traceback: subprocess error>" not in report
    assert "\n  Traceback:\n" not in report


def test_digest_keeps_legacy_host_tracebacks(
    temp_state_dir: Path,
) -> None:
    errors = [
        {
            "timestamp": "2026-09-06T21:31:16-04:00",
            "lumberjack": "hooks",
            "job": "host_job",
            "error": "host failed",
            "traceback": "Traceback (most recent call last):\nRuntimeError: host",
        }
    ]
    notifications: list[Notification] = []
    with (
        patch("sase.notifications.senders.sase_subdir", return_value=temp_state_dir),
        patch("sase.notifications.senders.append_notification", notifications.append),
    ):
        senders.notify_axe_error_digest(errors)

    report = Path(notifications[0].files[0]).read_text(encoding="utf-8")
    assert "  Traceback:" in report
    assert "RuntimeError: host" in report


def _fake_timeout_traceback_script_body(*, exit_code: int) -> str:
    return (
        f"\"{sys.executable}\" - <<'PY'\n"
        "import sys\n"
        "sys.stderr.write('Traceback (most recent call last):\\n')\n"
        "sys.stderr.write('  File \"poll.py\", line 10, in poll\\n')\n"
        "sys.stderr.write('httpx.ReadTimeout: timed out\\n')\n"
        "sys.stderr.write('The URL was https://api.telegram.org/"
        f"bot{_TOKEN}/getUpdates\\n')\n"
        "sys.stderr.write('telegram.error.TimedOut: Timed out\\n')\n"
        "PY\n"
        f"exit {exit_code}\n"
    )
