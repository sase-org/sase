"""Tests for multi-prompt local macro serialization."""

import os
from pathlib import Path

import pytest

from sase.agent.multi_prompt_launcher import (
    _serialize_local_macros,
    deserialize_local_macros,
)
from sase.core.paths import PYTEST_SANDBOX_MANAGED_TMPDIR_NAME
from sase.macro.models import InputArg, InputType, Macro


def test_serialize_deserialize_roundtrip_simple() -> None:
    """Simple macro survives serialization round-trip."""
    macros = {
        "_review": Macro(
            name="_review",
            content="Focus on correctness",
            source_path="user-prompt",
        ),
    }
    path = _serialize_local_macros(macros)
    try:
        result = deserialize_local_macros(path)
        assert "_review" in result
        xp = result["_review"]
        assert xp.name == "_review"
        assert xp.content == "Focus on correctness"
        assert xp.source_path == "user-prompt"
        assert xp.inputs == []
    finally:
        os.unlink(path)


def test_serialize_local_macros_uses_managed_tmpdir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    macros = {
        "_review": Macro(
            name="_review",
            content="Focus on correctness",
            source_path="user-prompt",
        ),
    }

    # Under pytest the managed root is the published sandbox, not the
    # developer's $SASE_TMPDIR — the handoff subdirectory is what this asserts.
    developer_root = tmp_path / "developer-root"
    monkeypatch.setenv("SASE_TMPDIR", str(developer_root))
    path = _serialize_local_macros(macros)
    try:
        parent = Path(path).parent
        assert parent.name == "handoff"
        assert parent.parent.name == PYTEST_SANDBOX_MANAGED_TMPDIR_NAME
        assert not developer_root.exists()
        assert deserialize_local_macros(path)["_review"].content == (
            "Focus on correctness"
        )
    finally:
        os.unlink(path)


def test_serialize_deserialize_roundtrip_with_inputs() -> None:
    """Macro with typed inputs survives round-trip."""
    macros = {
        "_greet": Macro(
            name="_greet",
            content="Hello {{ name }}",
            inputs=[
                InputArg(name="name", type=InputType.WORD),
                InputArg(name="count", type=InputType.INT, default=3),
            ],
            source_path="/some/path.yml",
        ),
    }
    path = _serialize_local_macros(macros)
    try:
        result = deserialize_local_macros(path)
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


def test_serialize_deserialize_multiple_macros() -> None:
    """Multiple macros in a single file."""
    macros = {
        "_a": Macro(name="_a", content="A"),
        "_b": Macro(name="_b", content="B"),
    }
    path = _serialize_local_macros(macros)
    try:
        result = deserialize_local_macros(path)
        assert set(result.keys()) == {"_a", "_b"}
    finally:
        os.unlink(path)


def test_serialize_deserialize_nested_local_macros() -> None:
    """A macro carrying markdown-local helpers survives round-trip."""
    macros = {
        "_outer": Macro(
            name="_outer",
            content="Use #_inner",
            local_macros={"_inner": Macro(name="_inner", content="Nested helper")},
        )
    }
    path = _serialize_local_macros(macros)
    try:
        result = deserialize_local_macros(path)
        assert result["_outer"].content == "Use #_inner"
        assert set(result["_outer"].local_macros) == {"_inner"}
        assert result["_outer"].local_macros["_inner"].content == "Nested helper"
    finally:
        os.unlink(path)
