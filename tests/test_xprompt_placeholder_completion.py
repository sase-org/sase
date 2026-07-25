"""Tests for the typed Rust placeholder facade."""

from __future__ import annotations

from typing import Any

import sase.xprompt.placeholder_completion as facade


def test_completion_rehydrates_binding_payload(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake_require(name: str) -> Any:
        calls.append(name)
        return lambda text, line, character: {
            "prefix": text[-1],
            "replacement_range": {
                "start": {"line": line, "character": character - 1},
                "end": {"line": line, "character": character},
            },
            "append_closing_bracket": True,
            "candidates": [
                {"text": "Alpha", "source": "prompt"},
                {"text": "Alpine", "source": "common"},
            ],
        }

    monkeypatch.setattr(facade, "require_rust_binding", fake_require)

    result = facade.placeholder_completion("<a", 0, 2)

    assert calls == ["placeholder_completion"]
    assert result is not None
    assert result.prefix == "a"
    assert result.replacement_range.start == facade.PlaceholderPosition(0, 1)
    assert result.append_closing_bracket is True
    assert result.candidates == ("Alpha", "Alpine")


def test_completion_preserves_null_binding_result(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        facade,
        "require_rust_binding",
        lambda name: lambda text, line, character: None,
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
