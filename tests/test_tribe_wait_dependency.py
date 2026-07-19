"""Next-entity tribe selection in the wait-dependency index."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)


def _agent(
    projects_root: Path,
    timestamp: str,
    name: str,
    *,
    outcome: str | None = "completed",
    tribe: str | None = None,
    cl_name: str | None = None,
    clan: str | None = None,
    generation: str | None = None,
    clan_tribe: str | None = None,
) -> Path:
    artifact_dir = projects_root / "proj/artifacts/ace-run" / timestamp
    artifact_dir.mkdir(parents=True)
    meta: dict[str, object] = {"name": name}
    if tribe is not None:
        meta["tribe"] = tribe
    if cl_name is not None:
        meta["cl_name"] = cl_name
    if clan is not None:
        meta["agent_clan"] = clan
        meta["agent_clan_generation"] = generation or timestamp
    if clan_tribe is not None:
        meta["clan_tribe"] = clan_tribe
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(meta),
        encoding="utf-8",
    )
    if outcome is not None:
        (artifact_dir / "done.json").write_text(
            json.dumps({"outcome": outcome}),
            encoding="utf-8",
        )
    return artifact_dir


def _index(
    projects_root: Path,
    *,
    tribes_path: Path | None = None,
    legacy_tags_path: Path | None = None,
):
    return build_wait_dependency_index(
        "proj",
        projects_root=projects_root,
        agent_tribes_path=tribes_path or projects_root / "missing-agent-tribes.json",
        legacy_agent_tags_path=legacy_tags_path,
    )


def test_tribe_wait_requires_waiter_launch_cutoff(tmp_path: Path) -> None:
    _agent(tmp_path, "20260718010000", "old", tribe="epic")
    _agent(tmp_path, "20260718030000", "next", tribe="epic")
    index = _index(tmp_path)

    assert not index.is_resolved("@epic")
    assert not dependency_resolution_status(index, ["@epic"]).resolved
    assert dependency_resolution_status(
        index,
        ["@epic"],
        self_artifact_dir=tmp_path / "20260718020000",
    ).resolved


def test_tribe_candidate_uses_earliest_complete_new_entity(tmp_path: Path) -> None:
    _agent(tmp_path, "20260718021000", "failed", outcome="failed", tribe="epic")
    _agent(tmp_path, "20260718024000", "later", tribe="epic")
    _agent(tmp_path, "20260718022000", "earliest", tribe="epic")
    index = _index(tmp_path)

    candidate = index.tribe_candidate("epic", newer_than="20260718020000")

    assert candidate is not None
    assert candidate.kind == "agent"
    assert candidate.name == "earliest"
    assert candidate.timestamp == "20260718022000"


def test_tribe_wait_ignores_older_and_self_entities(tmp_path: Path) -> None:
    self_dir = _agent(tmp_path, "20260718020000", "self", tribe="epic")
    _agent(tmp_path, "20260718010000", "old", tribe="epic")
    index = _index(tmp_path)

    assert (
        index.tribe_candidate(
            "epic",
            newer_than="20260718010000",
            exclude_artifact_dir=self_dir,
        )
        is None
    )


def test_tagged_clan_member_enrolls_complete_generation(tmp_path: Path) -> None:
    generation = "20260718020000"
    first = _agent(
        tmp_path,
        "20260718020100",
        "review.one",
        tribe="epic",
        clan="review",
        generation=generation,
    )
    second = _agent(
        tmp_path,
        "20260718020200",
        "review.two",
        outcome=None,
        clan="review",
        generation=generation,
    )
    index = _index(tmp_path)

    assert index.tribe_candidate("epic", newer_than="20260718010000") is None

    (second / "done.json").write_text(
        json.dumps({"outcome": "completed"}),
        encoding="utf-8",
    )
    index = _index(tmp_path)
    candidate = index.tribe_candidate("epic", newer_than="20260718010000")

    assert candidate is not None
    assert candidate.kind == "clan"
    assert candidate.name == "review"
    assert candidate.generation == generation
    assert [member.name for member in candidate.members] == [
        "review.one",
        "review.two",
    ]
    assert (
        index.tribe_candidate(
            "epic",
            newer_than="20260718010000",
            exclude_artifact_dir=first,
        )
        is None
    )


def test_effective_clan_tribe_uses_shared_precedence_facade(tmp_path: Path) -> None:
    generation = "20260718020000"
    _agent(
        tmp_path,
        "20260718020100",
        "review.one",
        clan="review",
        generation=generation,
        clan_tribe="old",
    )
    _agent(
        tmp_path,
        "20260718020200",
        "review.two",
        clan="review",
        generation=generation,
        clan_tribe="epic",
    )
    index = _index(tmp_path)

    assert index.tribe_candidate("old", newer_than="20260718010000") is None
    candidate = index.tribe_candidate("epic", newer_than="20260718010000")
    assert candidate is not None
    assert candidate.kind == "clan"


def test_legacy_posthoc_agent_tag_assignment_enrolls_entity(tmp_path: Path) -> None:
    timestamp = "20260718030000"
    _agent(tmp_path, timestamp, "builder", cl_name="change")
    tags_path = tmp_path / "agent_tags.json"
    tags_path.write_text(
        json.dumps(
            [
                {
                    "id": ["workflow", "change", timestamp],
                    "tag": "epic",
                }
            ]
        ),
        encoding="utf-8",
    )
    index = _index(tmp_path, legacy_tags_path=tags_path)

    candidate = index.tribe_candidate("epic", newer_than="20260718020000")
    assert candidate is not None
    assert candidate.name == "builder"
