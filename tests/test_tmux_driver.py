"""Unit tests for the tmux modifyOtherKeys driver hook."""

from __future__ import annotations

import os

from sase.tmux_driver import (
    MODIFY_OTHER_KEYS_OFF,
    MODIFY_OTHER_KEYS_ON,
    TmuxModifyOtherKeysDriver,
    _tmux_modify_other_keys_active,
    maybe_tmux_driver_class,
)


def _driver_with_capture(monkeypatch) -> tuple[TmuxModifyOtherKeysDriver, list[str]]:
    writes: list[str] = []
    monkeypatch.setattr(
        TmuxModifyOtherKeysDriver, "write", lambda self, data: writes.append(data)
    )
    monkeypatch.setattr(TmuxModifyOtherKeysDriver, "flush", lambda self: None)
    import sase.tmux_driver as mod

    monkeypatch.setattr(mod.LinuxDriver, "start_application_mode", lambda self: None)
    monkeypatch.setattr(mod.LinuxDriver, "stop_application_mode", lambda self: None)
    driver = TmuxModifyOtherKeysDriver.__new__(TmuxModifyOtherKeysDriver)
    return driver, writes


def test_sequences_written_only_when_tmux_set(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1,2,3")
    assert _tmux_modify_other_keys_active() is True
    driver, writes = _driver_with_capture(monkeypatch)
    driver.start_application_mode()
    assert writes == [MODIFY_OTHER_KEYS_ON]
    writes.clear()
    driver.stop_application_mode()
    assert writes == [MODIFY_OTHER_KEYS_OFF]


def test_no_sequences_without_tmux(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    assert _tmux_modify_other_keys_active() is False
    driver, writes = _driver_with_capture(monkeypatch)
    driver.start_application_mode()
    driver.stop_application_mode()
    assert writes == []


def test_headless_base_class_is_untouched() -> None:
    class Headless:
        pass

    assert maybe_tmux_driver_class(Headless) is Headless


def test_linux_base_selects_tmux_driver() -> None:
    import sase.tmux_driver as mod

    assert maybe_tmux_driver_class(mod.LinuxDriver) is TmuxModifyOtherKeysDriver


def test_stop_writes_reset_for_suspend_path(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-9,9,9")
    driver, writes = _driver_with_capture(monkeypatch)
    driver.stop_application_mode()
    assert writes == [MODIFY_OTHER_KEYS_OFF]
    assert os.environ.get("TMUX")
