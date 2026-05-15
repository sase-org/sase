"""Tests for system clipboard helpers."""

import subprocess
from subprocess import CalledProcessError
from unittest.mock import call, patch

from sase.core.clipboard import _clipboard_commands, copy_to_system_clipboard


def test_copy_to_system_clipboard_tries_linux_fallbacks() -> None:
    with (
        patch("sase.core.clipboard.sys.platform", "linux"),
        patch.dict(
            "sase.core.clipboard.os.environ",
            {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"},
            clear=True,
        ),
        patch("sase.core.clipboard.subprocess.run") as run,
    ):
        run.side_effect = [
            FileNotFoundError(),
            CalledProcessError(1, "xclip"),
            None,
        ]

        assert copy_to_system_clipboard("hello") is True

    assert run.call_args_list == [
        call(
            ["wl-copy"],
            input="hello",
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ),
        call(
            ["xclip", "-selection", "clipboard"],
            input="hello",
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ),
        call(
            ["xsel", "--clipboard", "--input"],
            input="hello",
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ),
    ]


def test_clipboard_commands_wayland_only() -> None:
    with (
        patch("sase.core.clipboard.sys.platform", "linux"),
        patch.dict(
            "sase.core.clipboard.os.environ",
            {"WAYLAND_DISPLAY": "wayland-0"},
            clear=True,
        ),
    ):
        assert _clipboard_commands() == [["wl-copy"]]


def test_clipboard_commands_x11_only() -> None:
    with (
        patch("sase.core.clipboard.sys.platform", "linux"),
        patch.dict(
            "sase.core.clipboard.os.environ",
            {"DISPLAY": ":0"},
            clear=True,
        ),
    ):
        assert _clipboard_commands() == [
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]


def test_clipboard_commands_both_set() -> None:
    with (
        patch("sase.core.clipboard.sys.platform", "linux"),
        patch.dict(
            "sase.core.clipboard.os.environ",
            {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"},
            clear=True,
        ),
    ):
        assert _clipboard_commands() == [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]


def test_clipboard_commands_neither_set() -> None:
    with (
        patch("sase.core.clipboard.sys.platform", "linux"),
        patch.dict(
            "sase.core.clipboard.os.environ",
            {},
            clear=True,
        ),
    ):
        assert _clipboard_commands() == [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]
