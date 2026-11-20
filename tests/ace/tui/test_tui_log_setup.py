"""Tests for the TUI diagnostics file-logging install."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from sase.ace.tui import log_setup
from sase.ace.tui.log_setup import _HANDLER_NAME, install_tui_file_logging
from sase.logs import launch_log, tui_log_path


@pytest.fixture(autouse=True)
def _cleanup_sase_handler() -> Iterator[None]:
    """Restore handlers and level after each test (global logger state)."""
    logger = logging.getLogger("sase")
    before = list(logger.handlers)
    before_level = logger.level
    yield
    for handler in list(logger.handlers):
        if handler not in before:
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(before_level)


def _sase_handlers() -> list[logging.Handler]:
    return [
        h
        for h in logging.getLogger("sase").handlers
        if getattr(h, "name", None) == _HANDLER_NAME
    ]


def test_install_attaches_handler() -> None:
    install_tui_file_logging()
    assert len(_sase_handlers()) == 1


def test_install_is_idempotent() -> None:
    install_tui_file_logging()
    install_tui_file_logging()
    install_tui_file_logging()
    assert len(_sase_handlers()) == 1


def test_warning_lands_in_tui_log() -> None:
    install_tui_file_logging()
    logging.getLogger("sase.somewhere").warning("a wild warning")
    for handler in _sase_handlers():
        handler.flush()
    text = tui_log_path().read_text()
    assert "a wild warning" in text
    assert "WARNING" in text


def test_exception_traceback_lands_in_tui_log() -> None:
    install_tui_file_logging()
    logger = logging.getLogger("sase.launch")
    try:
        raise RuntimeError("kaboom in tui")
    except RuntimeError:
        logger.exception("launch failed")
    for handler in _sase_handlers():
        handler.flush()
    text = tui_log_path().read_text()
    assert "launch failed" in text
    assert "RuntimeError: kaboom in tui" in text


def test_info_below_threshold_is_filtered() -> None:
    install_tui_file_logging()
    logging.getLogger("sase.quiet").info("just info")
    for handler in _sase_handlers():
        handler.flush()
    path = tui_log_path()
    text = path.read_text() if path.exists() else ""
    assert "just info" not in text


def test_tui_log_keeps_only_configured_rotating_generations(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui.log"
    monkeypatch.setattr(launch_log, "TUI_LOG", str(path))
    monkeypatch.setattr(log_setup, "_MAX_BYTES", 100)
    monkeypatch.setattr(log_setup, "_BACKUP_COUNT", 1)

    install_tui_file_logging()
    logger = logging.getLogger("sase.rotation")
    for index in range(4):
        logger.warning("record %s %s", index, "x" * 150)
    for handler in _sase_handlers():
        handler.flush()

    assert path.exists()
    assert path.with_name("tui.log.1").exists()
    assert not path.with_name("tui.log.2").exists()


def _stamp(ts: float, message: str) -> str:
    from datetime import datetime

    rendered = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    return f"{rendered} WARNING sase: {message}\n"


def test_tui_log_rotates_by_age_and_prunes_old_segments(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui.log"
    now = 1_700_000_000.0
    monkeypatch.setattr(launch_log, "TUI_LOG", str(path))
    monkeypatch.setattr(log_setup, "_MAX_AGE_SECONDS", 14 * 86400)
    monkeypatch.setattr(log_setup, "_now", lambda: now)
    path.write_text(_stamp(now - 20 * 86400, "ancient"), encoding="utf-8")
    stale_backup = path.with_name("tui.log.1")
    stale_backup.write_text(_stamp(now - 40 * 86400, "rotated"), encoding="utf-8")

    install_tui_file_logging()
    logging.getLogger("sase.rotation").warning("fresh")
    for handler in _sase_handlers():
        handler.flush()

    text = path.read_text(encoding="utf-8")
    assert "fresh" in text
    assert "ancient" not in text
    assert not stale_backup.exists()


def test_tui_log_keeps_rotated_segment_with_recent_entries(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui.log"
    now = 1_700_000_000.0
    monkeypatch.setattr(launch_log, "TUI_LOG", str(path))
    monkeypatch.setattr(log_setup, "_MAX_AGE_SECONDS", 14 * 86400)
    monkeypatch.setattr(log_setup, "_now", lambda: now)
    path.write_text(
        _stamp(now - 20 * 86400, "old") + _stamp(now - 3600, "recent"),
        encoding="utf-8",
    )

    install_tui_file_logging()
    logging.getLogger("sase.rotation").warning("fresh")
    for handler in _sase_handlers():
        handler.flush()

    backup = path.with_name("tui.log.1")
    assert backup.exists()
    backup_text = backup.read_text(encoding="utf-8")
    assert "old" in backup_text
    assert "recent" in backup_text
    assert "fresh" in path.read_text(encoding="utf-8")
