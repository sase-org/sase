"""Tests for the typed Rust placeholder facade."""

from __future__ import annotations

from typing import Any

import sase.xprompt.placeholder_completion as facade


def test_completion_rehydrates_binding_payload(monkeypatch: Any) -> None:
    calls: list[str] = []

    common_args: list[list[str]] = []

    def fake_require(name: str) -> Any:
        calls.append(name)

        def binding(text: str, line: int, character: int, common: list[str]) -> Any:
            common_args.append(common)
            return {
                "prefix": text[-1],
                "replacement_range": {
                    "start": {"line": line, "character": character - 1},
                    "end": {"line": line, "character": character},
                },
                "append_closing_bracket": True,
                "candidates": [
                    {"text": "Alpha", "source": "prompt"},
                    {"text": "Alpine", "source": "common"},
                    {"text": "Aloe", "source": "from-the-future"},
                ],
            }

        return binding

    monkeypatch.setattr(facade, "require_rust_binding", fake_require)

    result = facade.placeholder_completion("<a", 0, 2, ("Alpine",))

    assert calls == ["placeholder_completion"]
    assert common_args == [["Alpine"]]
    assert result is not None
    assert result.prefix == "a"
    assert result.replacement_range.start == facade.PlaceholderPosition(0, 1)
    assert result.append_closing_bracket is True
    # An unrecognized source degrades to ``prompt`` rather than raising.
    assert result.candidates == (
        facade._PlaceholderCandidate(text="Alpha", source="prompt"),
        facade._PlaceholderCandidate(text="Alpine", source="common"),
        facade._PlaceholderCandidate(text="Aloe", source="prompt"),
    )


def test_completion_defaults_to_no_common_placeholders(monkeypatch: Any) -> None:
    common_args: list[list[str]] = []

    def fake_require(name: str) -> Any:
        def binding(text: str, line: int, character: int, common: list[str]) -> Any:
            common_args.append(common)
            return None

        return binding

    monkeypatch.setattr(facade, "require_rust_binding", fake_require)

    assert facade.placeholder_completion("<a", 0, 2) is None
    assert common_args == [[]]


def test_completion_preserves_null_binding_result(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        facade,
        "require_rust_binding",
        lambda name: lambda text, line, character, common: None,
    )

    assert facade.placeholder_completion("plain", 0, 5) is None


def test_spans_rehydrate_full_and_inner_ranges(monkeypatch: Any) -> None:
    def fake_require(name: str) -> Any:
        assert name == "placeholder_spans"
        return lambda text: [
            {
                "text": "alpha",
                "range": {
                    "start": {"line": 1, "character": 2},
                    "end": {"line": 1, "character": 9},
                },
                "inner_range": {
                    "start": {"line": 1, "character": 3},
                    "end": {"line": 1, "character": 8},
                },
            }
        ]

    monkeypatch.setattr(facade, "require_rust_binding", fake_require)

    spans = facade.placeholder_spans("\n  <alpha>")

    assert spans == (
        facade.PlaceholderSpan(
            text="alpha",
            range=facade.PlaceholderRange(
                facade.PlaceholderPosition(1, 2),
                facade.PlaceholderPosition(1, 9),
            ),
            inner_range=facade.PlaceholderRange(
                facade.PlaceholderPosition(1, 3),
                facade.PlaceholderPosition(1, 8),
            ),
        ),
    )
