"""Guard tests for the Rust artifact-link conflict facade."""

from __future__ import annotations

from typing import Any

import pytest

from sase.core import artifact_link_conflict_facade


def test_merge_artifact_link_indexes_calls_static_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_require(name: str) -> object:
        calls.append(name)

        def merge(
            base: dict[str, Any],
            ours: dict[str, Any],
            theirs: dict[str, Any],
        ) -> dict[str, Any]:
            assert base == {"base": True}
            assert ours == {"ours": True}
            assert theirs == {"theirs": True}
            return {"merged": True}

        return merge

    monkeypatch.setattr(
        artifact_link_conflict_facade,
        "require_rust_binding",
        fake_require,
    )

    assert artifact_link_conflict_facade.merge_artifact_link_indexes(
        {"base": True},
        {"ours": True},
        {"theirs": True},
    ) == {"merged": True}
    assert calls == ["artifact_link_merge_indexes"]
