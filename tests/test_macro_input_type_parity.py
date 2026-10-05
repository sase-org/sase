"""Shared scalar corpus for Rust frontmatter validation and Python convert."""

from __future__ import annotations

import json

import pytest

from sase.macro.frontmatter_schema import validate_frontmatter
from sase.macro.models import InputArg, InputType, MacroValidationError


_CORPUS: tuple[tuple[InputType, str, bool], ...] = (
    (InputType.WORD, "ok", True),
    (InputType.WORD, "a b", False),
    (InputType.WORD, "", False),
    (InputType.LINE, "a b", True),
    (InputType.LINE, "a\nb", False),
    (InputType.TEXT, "a\nb", True),
    (InputType.PATH, "src/foo.rs", True),
    (InputType.PATH, "src/my file.rs", True),
    (InputType.PATH, "src/my\nfile.rs", False),
    (InputType.INT, "3", True),
    (InputType.INT, "3.5", False),
    (InputType.INT, "x", False),
    (InputType.FLOAT, "3.5", True),
    (InputType.FLOAT, "x", False),
    (InputType.BOOL, "true", True),
    (InputType.BOOL, "yes", True),
    (InputType.BOOL, "maybe", False),
    (InputType.AGENT, "worker", True),
    (InputType.AGENT, "a b", False),
)


def _python_accepts(input_type: InputType, value: str) -> bool:
    try:
        InputArg(name="sample", type=input_type).validate_and_convert(value)
    except MacroValidationError:
        return False
    return True


def _rust_accepts(input_type: InputType, value: str) -> bool:
    dumped = json.dumps(value)
    text = (
        "---\n"
        "input:\n"
        "  - name: sample\n"
        f"    type: {input_type.value}\n"
        f"    default: {dumped}\n"
        "---\n"
    )
    return not any(diagnostic.is_error for diagnostic in validate_frontmatter(text))


@pytest.mark.parametrize(("input_type", "value", "expected"), _CORPUS)
def test_rust_and_python_scalar_value_rules_agree(
    input_type: InputType, value: str, expected: bool
) -> None:
    python_ok = _python_accepts(input_type, value)
    rust_ok = _rust_accepts(input_type, value)
    assert python_ok is expected
    assert rust_ok is expected
    assert python_ok is rust_ok
