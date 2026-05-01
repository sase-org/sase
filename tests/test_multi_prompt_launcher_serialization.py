"""Tests for multi-prompt local xprompt serialization."""

import os

from sase.agent.multi_prompt_launcher import (
    _serialize_local_xprompts,
    deserialize_local_xprompts,
)
from sase.xprompt.models import InputArg, InputType, XPrompt


def test_serialize_deserialize_roundtrip_simple() -> None:
    """Simple xprompt survives serialization round-trip."""
    xprompts = {
        "_review": XPrompt(
            name="_review",
            content="Focus on correctness",
            source_path="user-prompt",
        ),
    }
    path = _serialize_local_xprompts(xprompts)
    try:
        result = deserialize_local_xprompts(path)
        assert "_review" in result
        xp = result["_review"]
        assert xp.name == "_review"
        assert xp.content == "Focus on correctness"
        assert xp.source_path == "user-prompt"
        assert xp.inputs == []
    finally:
        os.unlink(path)


def test_serialize_deserialize_roundtrip_with_inputs() -> None:
    """Xprompt with typed inputs survives round-trip."""
    xprompts = {
        "_greet": XPrompt(
            name="_greet",
            content="Hello {{ name }}",
            inputs=[
                InputArg(name="name", type=InputType.WORD),
                InputArg(name="count", type=InputType.INT, default=3),
            ],
            source_path="/some/path.yml",
        ),
    }
    path = _serialize_local_xprompts(xprompts)
    try:
        result = deserialize_local_xprompts(path)
        xp = result["_greet"]
        assert xp.name == "_greet"
        assert len(xp.inputs) == 2
        assert xp.inputs[0].name == "name"
        assert xp.inputs[0].type == InputType.WORD
        assert xp.inputs[1].name == "count"
        assert xp.inputs[1].type == InputType.INT
        assert xp.inputs[1].default == 3
    finally:
        os.unlink(path)


def test_serialize_deserialize_multiple_xprompts() -> None:
    """Multiple xprompts in a single file."""
    xprompts = {
        "_a": XPrompt(name="_a", content="A"),
        "_b": XPrompt(name="_b", content="B"),
    }
    path = _serialize_local_xprompts(xprompts)
    try:
        result = deserialize_local_xprompts(path)
        assert set(result.keys()) == {"_a", "_b"}
    finally:
        os.unlink(path)
