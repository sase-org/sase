"""Tests for stored chat prompt limits."""

import json
from pathlib import Path
from unittest.mock import patch

import yaml

from sase.config import (
    DEFAULT_CHAT_RENDERED_PROMPT_MAX_BYTES,
    get_chat_rendered_prompt_max_bytes,
)


def test_chat_rendered_prompt_limit_accessor_validates_values() -> None:
    with patch(
        "sase.config.core.load_merged_config",
        return_value={"chat_history": {"rendered_prompt_max_bytes": 123}},
    ):
        assert get_chat_rendered_prompt_max_bytes() == 123

    for invalid in (0, -1, True, "123", None):
        with patch(
            "sase.config.core.load_merged_config",
            return_value={"chat_history": {"rendered_prompt_max_bytes": invalid}},
        ):
            assert (
                get_chat_rendered_prompt_max_bytes()
                == DEFAULT_CHAT_RENDERED_PROMPT_MAX_BYTES
            )


def test_chat_rendered_prompt_limit_default_matches_schema() -> None:
    root = Path(__file__).resolve().parents[1]
    default_config = yaml.safe_load(
        (root / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (root / "src/sase/config/sase.schema.json").read_text(encoding="utf-8")
    )

    assert default_config["chat_history"]["rendered_prompt_max_bytes"] == (
        DEFAULT_CHAT_RENDERED_PROMPT_MAX_BYTES
    )
    assert (
        schema["properties"]["chat_history"]["properties"]["rendered_prompt_max_bytes"][
            "default"
        ]
        == DEFAULT_CHAT_RENDERED_PROMPT_MAX_BYTES
    )
