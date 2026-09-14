"""Clan wait dependency tests for the wait_checks chop script."""

import json
from pathlib import Path

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks
from tests._dismissed_completion_helpers import (
    add_archive_identity,
    rebuild_completion_archive,
    write_dismissed_completion,
)


def test_clan_wait_does_not_resolve_while_members_are_queued(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "research")
    generation = "20260720080000"

    for index in range(6):
        member_dir = make_agent(
            tmp_path,
            "proj",
            f"20260720080{index + 1}00",
            f"research.{index + 1}",
            done=True,
            outcome="completed",
        )
        meta_path = member_dir / "agent_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.update(
            {
                "agent_clan": "research",
                "agent_clan_generation": generation,
            }
        )
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    for index, name in enumerate(("7", "8", "land"), start=1):
        member_dir = make_agent(
            tmp_path,
            "proj",
            f"20260720081{index}00",
            f"research.{name}",
        )
        meta_path = member_dir / "agent_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.update(
            {
                "agent_clan": "research",
                "agent_clan_generation": generation,
            }
        )
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        (member_dir / "waiting.json").write_text(
            json.dumps({"waiting_for": ["research.predecessor"]}),
            encoding="utf-8",
        )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_clan_wait_writes_ready_after_successful_member_is_dismissed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "research")
    generation = "20260720110000"
    archived = make_agent(
        tmp_path,
        "proj",
        "20260720110100",
        "research.archived",
        done=True,
        outcome="completed",
    )
    archived_meta = add_archive_identity(archived)
    archived_meta.update(
        {
            "agent_clan": "research",
            "agent_clan_generation": generation,
        }
    )
    (archived / "agent_meta.json").write_text(
        json.dumps(archived_meta),
        encoding="utf-8",
    )
    write_dismissed_completion(tmp_path, archived, "research.archived")
    (archived / "done.json").unlink()

    live = make_agent(
        tmp_path,
        "proj",
        "20260720110200",
        "research.live",
        done=True,
        outcome="completed",
    )
    live_meta = json.loads((live / "agent_meta.json").read_text(encoding="utf-8"))
    live_meta.update(
        {
            "agent_clan": "research",
            "agent_clan_generation": generation,
        }
    )
    (live / "agent_meta.json").write_text(json.dumps(live_meta), encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    rebuild_completion_archive()

    run_wait_checks(tmp_path, monkeypatch)

    assert json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8")) == {
        "resolved_deps": ["research"]
    }
