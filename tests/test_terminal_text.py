"""Terminal output cleanup shared by prompts and continuation capture."""

from __future__ import annotations

from sase.core.continuation_facade import validate_agent_delta
from sase.terminal_text import continuation_wire_text, strip_terminal_controls


def test_strips_the_reported_ansi_and_screen_control_bytes() -> None:
    text = "\x1b[31m-    assert!(empty_rows\n\x1b[m\x0f"

    assert strip_terminal_controls(text) == "-    assert!(empty_rows\n"


def test_strips_mypy_charset_designation_and_sgr_sequences() -> None:
    text = "x.py:1: \x1b[1m\x1b[31merror:\x1b(B\x1b[m Argument"

    assert strip_terminal_controls(text) == "x.py:1: error: Argument"


def test_strips_osc_hyperlinks_and_dcs_strings() -> None:
    text = (
        "before \x1b]8;;https://example.invalid\x07linked"
        "\x1b]8;;\x07 after \x1bPprivate payload\x1b\\ done"
    )

    assert strip_terminal_controls(text) == "before linked after  done"


def test_normalizes_crlf_and_terminal_overwrite_semantics() -> None:
    assert strip_terminal_controls("one\r\ntwo\r\n") == "one\ntwo\n"
    assert strip_terminal_controls("a\rb\n") == "b\n"
    assert continuation_wire_text("a\rb\n") == "a\nb\n"
    assert continuation_wire_text("one\r\ntwo\r\n") == "one\ntwo\n"


def test_preserves_tabs_newlines_and_non_ascii_text() -> None:
    text = "tab\tline\né ✅ ─ 😀"

    assert strip_terminal_controls(text) == text
    assert continuation_wire_text(text) == text


def test_clean_input_uses_the_identity_fast_path() -> None:
    text = "clean\ttext\nwith Unicode: é ✅ ─ 😀"

    assert strip_terminal_controls(text) is text
    assert continuation_wire_text(text) is text


def test_terminal_wire_text_matches_rust_control_character_validation() -> None:
    def delta(text: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "node_id": "agent-delta:terminal-text:test",
            "authored_local_request": text,
            "materialized_local_prompt_segments": [],
            "status": "completed",
            "source_refs": [],
        }

    controls = (*range(0x00, 0x20), *range(0x7F, 0xA0))
    for codepoint in controls:
        raw = f"x{chr(codepoint)}y"
        validate_agent_delta(delta(continuation_wire_text(raw)))
        if codepoint in (0x09, 0x0A):
            validate_agent_delta(delta(raw))
        else:
            try:
                validate_agent_delta(delta(raw))
            except Exception:
                pass
            else:
                raise AssertionError(f"Rust accepted control U+{codepoint:04X}")
