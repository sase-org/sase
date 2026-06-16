from __future__ import annotations

import pytest

from sase.axe.runner_args import parse_runner_bool_arg


@pytest.mark.parametrize("value", ["", "0", "false", "False", " no ", "OFF"])
def test_parse_runner_bool_arg_accepts_common_falsy_values(value: str) -> None:
    assert parse_runner_bool_arg(value) is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "home", "anything"])
def test_parse_runner_bool_arg_preserves_legacy_truthy_values(value: str) -> None:
    assert parse_runner_bool_arg(value) is True
