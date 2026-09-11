"""Baseline fixtures for legacy continuation prompt growth."""

from __future__ import annotations

import json
from pathlib import Path

from sase.continuation_baseline import (
    MEASUREMENT_LOG_NAME,
    measure_fork_render,
    node_counts_for_sources,
)
from sase.history.chat import build_fork_injected_history


def _write_chat(path: Path, prompt: str, response: str) -> None:
    path.write_text(
        f"## Prompt\n\n{prompt}\n\n## Response\n\n{response}\n",
        encoding="utf-8",
    )


def test_recursive_multi_parent_fixture_exposes_shared_ancestor_growth(
    tmp_path: Path,
) -> None:
    ancestor = tmp_path / "ancestor.md"
    left = tmp_path / "left.md"
    right = tmp_path / "right.md"
    _write_chat(ancestor, "Establish base constraints.", "COMMON_ANCESTOR_REPLY")
    _write_chat(left, f"#fork_by_chat:`{ancestor}`\nDo left work.", "LEFT_REPLY")
    _write_chat(right, f"#fork_by_chat:`{ancestor}`\nDo right work.", "RIGHT_REPLY")
    sources = [
        {"kind": "agent", "name": "left", "path": str(left)},
        {"kind": "agent", "name": "right", "path": str(right)},
    ]

    rendered = build_fork_injected_history(sources)
    measurement = measure_fork_render(sources, rendered, capacity_tokens=10)

    assert rendered.count("COMMON_ANCESTOR_REPLY") == 2
    assert measurement.prompt_sizes.history_bytes > measurement.prompt_sizes.local_bytes
    assert measurement.prompt_sizes.total_expanded_bytes == len(rendered.encode())
    assert measurement.node_counts.known_node_count == 2
    assert measurement.budget.threshold_exceeded is True


def test_split_only_clan_fixture_keeps_prompts_but_loses_member_reply_text(
    tmp_path: Path,
) -> None:
    member_chat = tmp_path / "reviewer.md"
    member_dir = tmp_path / "artifacts" / "20260911010101"
    member_dir.mkdir(parents=True)
    _write_chat(member_chat, "Review the split branch.", "REVIEWER_DECISION_REPLY")
    (member_dir / "agent_meta.json").write_text(
        json.dumps({"model": "gpt-5", "llm_provider": "openai"}),
        encoding="utf-8",
    )
    (member_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}),
        encoding="utf-8",
    )
    source = {
        "kind": "clan",
        "name": "review",
        "generation": "20260911010000",
        "tribe": None,
        "members": [
            {
                "name": "review.alpha",
                "path": str(member_chat),
                "artifact_dir": str(member_dir),
            }
        ],
    }

    rendered = build_fork_injected_history([source])
    measurement = measure_fork_render([source], rendered)

    assert "Review the split branch." in rendered
    assert "REVIEWER_DECISION_REPLY" not in rendered
    assert measurement.node_counts.source_kind_counts == {"clan": 1}
    assert measurement.node_counts.unique_node_count == 1


def test_fork_render_shadow_measurement_appends_to_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    chat = tmp_path / "chat.md"
    _write_chat(chat, "Continue from here.", "Done.")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    build_fork_injected_history([{"kind": "agent", "name": "alpha", "path": str(chat)}])

    [record] = [
        json.loads(line)
        for line in (artifacts / MEASUREMENT_LOG_NAME).read_text().splitlines()
    ]
    assert record["component"] == "fork_render"
    assert record["schema_version"] == 1
    assert record["node_counts"]["unique_node_count"] == 1


def test_node_counts_surface_duplicate_known_family_members(tmp_path: Path) -> None:
    chat = tmp_path / "same.md"
    _write_chat(chat, "Same parent.", "Same reply.")
    sources = [
        {
            "kind": "family",
            "name": "repeat",
            "members": [
                {
                    "name": "repeat--a",
                    "path": str(chat),
                    "artifact_dir": str(tmp_path / "a"),
                },
                {
                    "name": "repeat--b",
                    "path": str(chat),
                    "artifact_dir": str(tmp_path / "b"),
                },
            ],
            "excluded": [],
        }
    ]

    counts = node_counts_for_sources(sources)

    assert counts.known_node_count == 2
    assert counts.unique_node_count == 1
    assert counts.duplicate_node_count == 1
