from __future__ import annotations

from sase.ace.tui.graphics import GraphicsCapability, detect_graphics_capability


def _env(**values: str) -> dict[str, str]:
    base = {"TERM": "xterm-kitty", "COLORTERM": "truecolor"}
    base.update(values)
    return base


def _unexpected_probe(passthrough: str, timeout: float) -> bool:
    raise AssertionError("probe should not have been called")


def test_disabled_env_wins() -> None:
    cap = detect_graphics_capability(
        _env(SASE_TUI_GRAPHICS="off"),
        probe_func=_unexpected_probe,
    )

    assert not cap.supported
    assert "disabled" in cap.reason


def test_unknown_terminal_is_unsupported_without_override() -> None:
    cap = detect_graphics_capability(
        {"TERM": "xterm-256color", "COLORTERM": "truecolor"},
        probe_func=_unexpected_probe,
    )

    assert not cap.supported
    assert cap.probed is False
    assert "not attempted" in cap.reason


def test_truecolor_required_for_placeholders() -> None:
    cap = detect_graphics_capability(
        {"TERM": "xterm-kitty"},
        probe_func=_unexpected_probe,
    )

    assert not cap.supported
    assert "truecolor" in cap.reason


def test_probe_success_enables_kitty() -> None:
    cap = detect_graphics_capability(
        _env(KITTY_WINDOW_ID="1"),
        probe_func=lambda passthrough, timeout: True,
    )

    assert cap == GraphicsCapability(
        supported=True,
        protocol="kitty",
        passthrough="none",
        reason="Kitty graphics probe succeeded",
        terminal="kitty",
        truecolor=True,
        probed=True,
    )


def test_tmux_passthrough_is_recorded() -> None:
    seen: list[str] = []

    cap = detect_graphics_capability(
        _env(KITTY_WINDOW_ID="1", TMUX="/tmp/tmux"),
        probe_func=lambda passthrough, timeout: (
            seen.append(passthrough) is None or True
        ),
    )

    assert cap.supported
    assert cap.passthrough == "tmux"
    assert seen == ["tmux"]


def test_unknown_tmux_terminal_probe_success_enables_kitty() -> None:
    seen: list[str] = []

    cap = detect_graphics_capability(
        {"TERM": "tmux-256color", "TERM_PROGRAM": "tmux", "TMUX": "/tmp/tmux"},
        probe_func=lambda passthrough, timeout: (
            seen.append(passthrough) is None or True
        ),
    )

    assert cap.supported
    assert cap.protocol == "kitty"
    assert cap.passthrough == "tmux"
    assert cap.terminal == "kitty"
    assert cap.truecolor is False
    assert cap.probed
    assert seen == ["tmux"]


def test_unknown_tmux_terminal_reports_probe_failure() -> None:
    cap = detect_graphics_capability(
        {"TERM": "tmux-256color", "TERM_PROGRAM": "tmux", "TMUX": "/tmp/tmux"},
        probe_func=lambda passthrough, timeout: False,
    )

    assert not cap.supported
    assert cap.passthrough == "tmux"
    assert cap.terminal is None
    assert cap.truecolor is False
    assert cap.probed
    assert "probe did not receive" in cap.reason


def test_missing_colorterm_does_not_block_successful_tmux_probe() -> None:
    cap = detect_graphics_capability(
        {"TERM": "xterm-256color", "TMUX": "/tmp/tmux"},
        probe_func=lambda passthrough, timeout: True,
    )

    assert cap.supported
    assert cap.passthrough == "tmux"
    assert cap.truecolor is False


def test_force_kitty_probes_unknown_terminal_without_truecolor() -> None:
    seen: list[str] = []

    cap = detect_graphics_capability(
        {"TERM": "xterm-256color", "SASE_TUI_GRAPHICS": "kitty"},
        probe_func=lambda passthrough, timeout: (
            seen.append(passthrough) is None or True
        ),
    )

    assert cap.supported
    assert cap.passthrough == "none"
    assert cap.terminal == "kitty"
    assert cap.truecolor is False
    assert seen == ["none"]


def test_probe_failure_disables_kitty() -> None:
    cap = detect_graphics_capability(
        _env(TERM="xterm-256color", TERM_PROGRAM="ghostty"),
        probe_func=lambda passthrough, timeout: False,
    )

    assert not cap.supported
    assert cap.probed
    assert cap.terminal == "ghostty"


def test_probe_can_be_skipped_for_noninteractive_tests() -> None:
    cap = detect_graphics_capability(_env(KITTY_WINDOW_ID="1"), probe=False)

    assert cap.supported
    assert not cap.probed
