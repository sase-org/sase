"""Environment matrix for the shared stdout/stderr color contract."""

from __future__ import annotations

import pytest

from sase.core.term_color import should_colorize


class _Stream:
    """Minimal ``isatty()``-carrying stream for contract tests."""

    def __init__(self, *, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture
def clean_color_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scrub the color environment so each case declares its own inputs."""
    for name in ("NO_COLOR", "FORCE_COLOR", "CLICOLOR_FORCE", "TERM"):
        monkeypatch.delenv(name, raising=False)


def test_explicit_modes_win_over_environment(
    clean_color_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert should_colorize(_Stream(tty=False), mode="always") is True
    assert should_colorize(_Stream(tty=True), mode="never") is False


def test_no_color_wins_over_force_color(
    clean_color_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    assert should_colorize(_Stream(tty=True)) is False


def test_no_color_wins_even_when_empty(
    clean_color_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NO_COLOR", "")
    assert should_colorize(_Stream(tty=True)) is False


@pytest.mark.parametrize("var", ["FORCE_COLOR", "CLICOLOR_FORCE"])
@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_force_variables_enable_color_off_tty(
    clean_color_env: None,
    monkeypatch: pytest.MonkeyPatch,
    var: str,
    value: str,
) -> None:
    monkeypatch.setenv(var, value)
    assert should_colorize(_Stream(tty=False)) is True


@pytest.mark.parametrize("var", ["FORCE_COLOR", "CLICOLOR_FORCE"])
@pytest.mark.parametrize("value", ["", "0"])
def test_empty_or_zero_force_is_not_force(
    clean_color_env: None,
    monkeypatch: pytest.MonkeyPatch,
    var: str,
    value: str,
) -> None:
    monkeypatch.setenv(var, value)
    assert should_colorize(_Stream(tty=False)) is False


def test_tty_defaults_to_color(
    clean_color_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    assert should_colorize(_Stream(tty=True)) is True
    assert should_colorize(_Stream(tty=False)) is False


def test_dumb_terminal_is_off_unless_forced(
    clean_color_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERM", "dumb")
    assert should_colorize(_Stream(tty=True)) is False
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert should_colorize(_Stream(tty=False)) is True


def test_missing_or_broken_stream_is_off(clean_color_env: None) -> None:
    assert should_colorize(None) is False

    class _Broken:
        def isatty(self) -> bool:
            raise OSError("no tty here")

    assert should_colorize(_Broken()) is False  # type: ignore[arg-type]


def test_unknown_mode_behaves_like_auto(clean_color_env: None) -> None:
    assert should_colorize(_Stream(tty=True), mode="bogus") is True
    assert should_colorize(_Stream(tty=False), mode="bogus") is False
