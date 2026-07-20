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
    """Remove the installed handler after each test (global logger state)."""
    logger = logging.getLogger("sase")
    before = list(logger.handlers)
    yield
    for handler in list(logger.handlers):
        if handler not in before:
            logger.removeHandler(handler)
            handler.close()


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
