"""Tests for ``sase image`` CLI handling."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.image_handler import handle_image_command


def _args(
    *,
    prompt: list[str] | None = None,
    model: str = "gemini-3-pro-image-preview",
    output_dir: str | None = None,
    no_notify: bool = False,
) -> Namespace:
    return Namespace(
        prompt=prompt or [],
        model=model,
        output_dir=output_dir,
        no_notify=no_notify,
    )


def test_handle_image_command_success_notifies(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_out = Path("/tmp/fake_image.png")
    with (
        patch(
            "sase.main.image_handler.generate_image",
            return_value=(fake_out, "image/png"),
        ) as mock_generate,
        patch("sase.main.image_handler.notify_image_generated") as mock_notify,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_image_command(_args(prompt=["draw", "a", "cat"]))

    assert exc_info.value.code == 0
    mock_generate.assert_called_once_with(
        "draw a cat",
        model="gemini-3-pro-image-preview",
        output_dir=None,
    )
    mock_notify.assert_called_once()
    out = capsys.readouterr().out.strip()
    assert out == str(fake_out)


def test_handle_image_command_no_notify(capsys: pytest.CaptureFixture[str]) -> None:
    fake_out = Path("/tmp/fake_image.png")
    with (
        patch(
            "sase.main.image_handler.generate_image",
            return_value=(fake_out, "image/png"),
        ),
        patch("sase.main.image_handler.notify_image_generated") as mock_notify,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_image_command(_args(prompt=["prompt"], no_notify=True))

    assert exc_info.value.code == 0
    mock_notify.assert_not_called()
    out = capsys.readouterr().out.strip()
    assert out == str(fake_out)


def test_handle_image_command_missing_prompt() -> None:
    with pytest.raises(SystemExit) as exc_info:
        handle_image_command(_args(prompt=[]))
    assert exc_info.value.code == 1


def test_handle_image_command_generation_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch(
            "sase.main.image_handler.generate_image",
            side_effect=RuntimeError("boom"),
        ) as _mock_generate,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_image_command(_args(prompt=["draw", "bird"]))

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Error generating image: boom" in err
