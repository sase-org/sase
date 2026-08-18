"""Cross-command presentation coverage for structured task ``+1`` evidence."""

from __future__ import annotations

import json

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, PhaseSize, Resolution, Status
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


def test_plus_one_badge_evidence_search_stats_and_json_agree(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        task = project.create(
            "Cache remains stale",
            IssueType.TASK,
            task_type="bug",
            description="Invalidate the cache deterministically.",
            size=PhaseSize.MEDIUM,
        )
        task, changed = project.plus_one(
            task.id,
            "Reproduced after a cold restart.",
            reporter="agent.beta",
            refs=("research:202608/cache.md",),
        )
    assert changed
    assert task.plus_one_count == 1

    bead_cli.handle_bead_show(create_parser().parse_args(["bead", "show", task.id]))
    detail = capsys.readouterr().out
    assert "[+1]" in detail
    assert "+1 EVIDENCE" in detail
    assert "+1 agent.beta" in detail
    assert "Reproduced after a cold restart." in detail
    assert "research:202608/cache.md" in detail

    bead_cli.handle_bead_list(create_parser().parse_args(["bead", "list"]))
    assert "[+1]" in capsys.readouterr().out

    bead_cli.handle_bead_search(
        create_parser().parse_args(["bead", "search", "cold restart"])
    )
    search = capsys.readouterr().out
    assert "[+1]" in search
    assert 'plus_one_evidence: "Reproduced after a cold restart."' in search

    bead_cli.handle_bead_stats(create_parser().parse_args(["bead", "stats"]))
    assert "+1 Reports:  1" in capsys.readouterr().out

    bead_cli.handle_bead_show(
        create_parser().parse_args(["bead", "show", task.id, "--format", "json"])
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["issue"]["plus_one_count"] == 1
    assert payload["issue"]["plus_one_evidence"][0]["reporter"] == "agent.beta"


def test_post_close_plus_one_badge_marker_search_and_json_agree(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        task = project.create(
            "Cache remains stale",
            IssueType.TASK,
            task_type="bug",
            description="Invalidate the cache deterministically.",
            size=PhaseSize.MEDIUM,
        )
        project.close([task.id], reason="fixed", resolution=Resolution.DONE)
        task = project.show(task.id)
        assert task.closed_at is not None
        task, changed = project.plus_one(
            task.id,
            "Saw this before the close landed.",
            reporter="agent.beta",
            observed_since="2026-01-01T00:00:00Z",
        )
    assert changed
    assert task.status is Status.CLOSED

    bead_cli.handle_bead_show(create_parser().parse_args(["bead", "show", task.id]))
    detail = capsys.readouterr().out
    assert "[+1 after close]" in detail
    assert "post-close evidence" in detail
    assert "Observed since: 2026-01-01T00:00:00Z" in detail

    bead_cli.handle_bead_list(
        create_parser().parse_args(["bead", "list", "--status", "closed"])
    )
    assert "[+1 after close]" in capsys.readouterr().out

    bead_cli.handle_bead_search(
        create_parser().parse_args(["bead", "search", "2026-01-01T00:00:00Z"])
    )
    search = capsys.readouterr().out
    assert "[+1 after close]" in search

    bead_cli.handle_bead_show(
        create_parser().parse_args(["bead", "show", task.id, "--format", "json"])
    )
    evidence = json.loads(capsys.readouterr().out)["issue"]["plus_one_evidence"][0]
    assert evidence["observed_since"] == "2026-01-01T00:00:00Z"
    assert evidence["recorded_after_current_close"] is True
