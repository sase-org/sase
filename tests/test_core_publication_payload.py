"""Tests for the Rust-backed publication payload batch facade."""

from __future__ import annotations

import pytest

from sase.core.publication_payload_facade import (
    PublicationPayloadFile,
    plan_publication_payload_batches,
)

from ._rust_extension_module_helpers import install_fake_rust_extension


def test_publication_payload_facade_calls_rust_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[dict[str, object]], int]] = []

    def fake_binding(files: list[dict[str, object]], byte_budget: int) -> dict:
        calls.append((files, byte_budget))
        return {
            "schema_version": 1,
            "byte_budget": byte_budget,
            "total_byte_count": 5,
            "batches": [
                {"paths": ["a.txt", "b.txt"], "byte_count": 5},
            ],
        }

    install_fake_rust_extension(
        monkeypatch,
        plan_publication_payload_batches=fake_binding,
    )

    plan = plan_publication_payload_batches(
        (
            PublicationPayloadFile("b.txt", 3),
            PublicationPayloadFile("a.txt", 2),
        ),
        5,
    )

    assert plan.schema_version == 1
    assert plan.byte_budget == 5
    assert plan.total_byte_count == 5
    assert len(plan.batches) == 1
    assert plan.batches[0].paths == ("a.txt", "b.txt")
    assert plan.batches[0].byte_count == 5
    assert calls == [
        (
            [
                {"path": "b.txt", "byte_length": 3},
                {"path": "a.txt", "byte_length": 2},
            ],
            5,
        )
    ]


def test_publication_payload_facade_rejects_stale_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_rust_extension(
        monkeypatch,
        plan_publication_payload_batches=lambda *_args: {
            "schema_version": 0,
            "byte_budget": 5,
            "total_byte_count": 0,
            "batches": [],
        },
    )

    with pytest.raises(RuntimeError, match="wire is stale"):
        plan_publication_payload_batches((), 5)


def test_publication_payload_facade_rejects_invalid_budget() -> None:
    with pytest.raises(ValueError, match="positive"):
        plan_publication_payload_batches((), 0)
