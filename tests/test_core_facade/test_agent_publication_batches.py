from __future__ import annotations

import pytest

from sase.core.agent_publication_batches import (
    AGENT_PUBLICATION_BATCH_WIRE_SCHEMA_VERSION,
    AgentPublicationPathRecord,
    plan_agent_publication_batches,
)
from tests._rust_extension_module_helpers import install_fake_rust_extension


def test_agent_publication_batch_facade_calls_rust_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[dict[str, object]], int]] = []

    def fake_plan(
        records: list[dict[str, object]], budget_bytes: int
    ) -> dict[str, object]:
        calls.append((records, budget_bytes))
        return {
            "schema_version": AGENT_PUBLICATION_BATCH_WIRE_SCHEMA_VERSION,
            "budget_bytes": budget_bytes,
            "total_size_bytes": 5,
            "batches": [
                {"paths": ["a.txt"], "size_bytes": 2},
                {"paths": ["b.txt"], "size_bytes": 3},
            ],
        }

    install_fake_rust_extension(
        monkeypatch,
        plan_agent_publication_batches=fake_plan,
    )

    plan = plan_agent_publication_batches(
        (
            AgentPublicationPathRecord("a.txt", 2),
            AgentPublicationPathRecord("b.txt", 3),
        ),
        budget_bytes=3,
    )

    assert calls == [
        (
            [
                {"path": "a.txt", "size_bytes": 2},
                {"path": "b.txt", "size_bytes": 3},
            ],
            3,
        )
    ]
    assert [batch.paths for batch in plan.batches] == [
        ("a.txt",),
        ("b.txt",),
    ]
    assert plan.total_size_bytes == 5


def test_agent_publication_batch_facade_rejects_stale_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_rust_extension(
        monkeypatch,
        plan_agent_publication_batches=lambda _records, _budget: {
            "schema_version": 0,
            "budget_bytes": 1,
            "total_size_bytes": 0,
            "batches": [],
        },
    )

    with pytest.raises(RuntimeError, match="wire is stale"):
        plan_agent_publication_batches((), budget_bytes=1)


def test_agent_publication_batch_facade_validates_inputs() -> None:
    with pytest.raises(ValueError, match="positive"):
        plan_agent_publication_batches((), budget_bytes=0)

    with pytest.raises(TypeError, match="AgentPublicationPathRecord"):
        plan_agent_publication_batches(("a.txt",), budget_bytes=1)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="non-negative"):
        plan_agent_publication_batches(
            (AgentPublicationPathRecord("a.txt", -1),),
            budget_bytes=1,
        )
