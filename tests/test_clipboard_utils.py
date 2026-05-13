"""Tests for system clipboard helpers."""

from subprocess import CalledProcessError
from unittest.mock import call, patch

from sase.core.clipboard import copy_to_system_clipboard


def test_copy_to_system_clipboard_tries_linux_fallbacks() -> None:
    with (
        patch("sase.core.clipboard.sys.platform", "linux"),
        patch("sase.core.clipboard.subprocess.run") as run,
    ):
        run.side_effect = [
            FileNotFoundError(),
            CalledProcessError(1, "xclip"),
            None,
        ]

        assert copy_to_system_clipboard("hello") is True

    assert run.call_args_list == [
        call(["wl-copy"], input="hello", text=True, check=True),
        call(
            ["xclip", "-selection", "clipboard"],
            input="hello",
            text=True,
            check=True,
        ),
        call(
            ["xsel", "--clipboard", "--input"],
            input="hello",
            text=True,
            check=True,
        ),
    ]
