from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.artifact_file_explicit import write_artifact_file_index_unlocked
from sase.core.artifact_file_retention import (
    RetentionPolicy,
    plan_artifact_file_retention,
)
from sase.core.artifact_file_types import ArtifactFile


def _artifact(
    artifact_id: str,
    *,
    label: str,
    created_at: str,
    path: str | None,
    explicit: bool = False,
) -> ArtifactFile:
    return ArtifactFile(
        id=artifact_id,
        label=label,
        kind="file",
        path=path,
        created_at=created_at,
        project="proj",
        agent_name="agent",
        explicit=explicit,
        sha256=artifact_id[-24:],
        size_bytes=10,
        vcs_repo=None if path else "repo",
        vcs_sha=None if path else "commit",
        vcs_relpath=None if path else f"{label}.txt",
    )


def test_retention_constructs_policy_and_projects_plan(tmp_path: Path) -> None:
    index_path = tmp_path / "index.jsonl"
    oldest = _artifact(
        "default:111111111111111111111111",
        label="report",
        created_at="2026-07-01T00:00:00Z",
        path=str(tmp_path / "old.txt"),
    )
    middle = _artifact(
        "default:222222222222222222222222",
        label="report",
        created_at="2026-07-02T00:00:00Z",
        path=None,
    )
    newest = _artifact(
        "default:333333333333333333333333",
        label="report",
        created_at="2026-07-03T00:00:00Z",
        path=str(tmp_path / "new.txt"),
    )
    explicit = _artifact(
        "explicit:444444444444444444444444",
        label="declared",
        created_at="2026-07-01T00:00:00Z",
        path=str(tmp_path / "explicit.txt"),
        explicit=True,
    )
    write_artifact_file_index_unlocked(
        index_path,
        [oldest, middle, newest, explicit],
    )

    result = plan_artifact_file_retention(
        RetentionPolicy(
            now="2026-07-30T00:00:00Z",
            keep_per_label=1,
            before="2026-07-30",
            kinds=("file",),
            project="proj",
            min_size_bytes=1,
            protected_ids=frozenset({middle.id}),
            limit=5,
        ),
        index_path=index_path,
    )

    assert [item.id for item in result.selected] == [oldest.id]
    assert result.selected[0].reason
    assert {(item.id, item.reason) for item in result.protected} == {
        (middle.id, "referenced"),
        (explicit.id, "explicit"),
    }
    assert result.counts.candidates == 2
    assert result.counts.selected == 1
    assert result.counts.protected == 2
    assert result.counts.byte_backed_selected == 1
    assert result.counts.byte_free_selected == 0
    assert result.reclaimable_bytes == 10
    assert result.truncated == 0
    assert len(result.summary_lines) == 4
    assert result.to_json_dict()["selected"][0]["id"] == oldest.id  # type: ignore[index]


def test_retention_policy_wire_is_built_only_in_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def binding(name: str):  # type: ignore[no-untyped-def]
        if name == "artifact_file_lifecycle_wire_schema_version":
            return lambda: 1

        def plan(_path: str, policy: dict[str, object]) -> dict[str, object]:
            calls.append(policy)
            return {
                "schema_version": 1,
                "selected": [],
                "protected": [],
                "counts": {
                    "candidates": 0,
                    "selected": 0,
                    "protected": 0,
                    "byte_backed_selected": 0,
                    "byte_free_selected": 0,
                },
                "reclaimable_bytes": 0,
                "truncated": 0,
                "summary_lines": [],
            }

        return plan

    monkeypatch.setattr(
        "sase.core.artifact_file_retention.require_rust_binding",
        binding,
    )
    plan_artifact_file_retention(
        RetentionPolicy(
            now="2026-07-30T00:00:00Z",
            protected_ids=frozenset(
                {
                    "default:222222222222222222222222",
                    "default:111111111111111111111111",
                }
            ),
        ),
        index_path="/missing",
    )

    assert calls == [
        {
            "schema_version": 1,
            "now": "2026-07-30T00:00:00Z",
            "keep_per_label": 3,
            "before": None,
            "kinds": None,
            "project": None,
            "min_size_bytes": None,
            "protected_ids": [
                "default:111111111111111111111111",
                "default:222222222222222222222222",
            ],
            "limit": None,
        }
    ]


def test_retention_names_an_incompatible_binding_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def binding(name: str):  # type: ignore[no-untyped-def]
        if name == "artifact_file_lifecycle_wire_schema_version":
            return lambda: 1
        return lambda *_args: {"schema_version": 1, "selected": "wrong"}

    monkeypatch.setattr(
        "sase.core.artifact_file_retention.require_rust_binding",
        binding,
    )

    with pytest.raises(RuntimeError, match="selected"):
        plan_artifact_file_retention(
            RetentionPolicy(now="2026-07-30T00:00:00Z"),
            index_path="/missing",
        )
