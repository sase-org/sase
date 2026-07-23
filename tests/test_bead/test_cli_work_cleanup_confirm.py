"""Cleanup preview, confirmation, and stale-reservation regressions."""

from __future__ import annotations

import builtins
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.names import AgentNameWipeResult
from sase.bead import cli as bead_cli
from sase.bead.cli_work_cleanup import preview_bead_work_force_reuse
from sase.bead.cli_work_plan import confirm_launch, render_cleanup_preview
from sase.bead.project import BeadProject
from sase.main.parser import create_parser

from .cli_work_helpers import (
    FakeLaunchResult,
    make_args,
    seed_diamond,
    write_orphan_meta,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def _seed_live_collision(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, list[str], list[str], list[str]]:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    write_orphan_meta(fake_home, phase_ids[0])
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    wiped: list[str] = []

    def fake_wipe(name: str, **_kwargs: object) -> AgentNameWipeResult:
        wiped.append(name)
        return AgentNameWipeResult(
            target_name=name,
            found=True,
            registry_names_removed=(name,),
        )

    launched: list[str] = []
    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )
    return epic_id, phase_ids, wiped, launched


def test_cleanup_decline_aborts_before_wipe_or_launch(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, _phase_ids, wiped, launched = _seed_live_collision(
        project_dir, tmp_path, monkeypatch
    )
    prompts: list[str] = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt: prompts.append(prompt) or "n",
    )

    bead_cli.handle_bead_work(make_args(epic_id))

    assert prompts == ["Proceed with dismissing/killing these agents? [y/N] "]
    assert wiped == []
    assert launched == []
    with BeadProject(project_dir) as project:
        assert project.show(epic_id).is_ready_to_work is False


def test_yes_still_prompts_for_cleanup_but_skips_launch_prompt(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, phase_ids, wiped, launched = _seed_live_collision(
        project_dir, tmp_path, monkeypatch
    )
    prompts: list[str] = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt: prompts.append(prompt) or "y",
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert prompts == ["Proceed with dismissing/killing these agents? [y/N] "]
    assert phase_ids[0] in wiped
    assert len(launched) == 1


def test_no_flags_confirm_cleanup_then_launch(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, _phase_ids, _wiped, launched = _seed_live_collision(
        project_dir, tmp_path, monkeypatch
    )
    prompts: list[str] = []
    answers = iter(("y", "y"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt: prompts.append(prompt) or next(answers),
    )

    bead_cli.handle_bead_work(make_args(epic_id))

    assert prompts == [
        "Proceed with dismissing/killing these agents? [y/N] ",
        "Launch these agents? [y/N] ",
    ]
    assert len(launched) == 1


def test_yes_to_all_skips_both_prompts(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, phase_ids, wiped, launched = _seed_live_collision(
        project_dir, tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt: pytest.fail(f"unexpected prompt: {prompt}"),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))

    assert phase_ids[0] in wiped
    assert len(launched) == 1


def test_noninteractive_cleanup_refuses_with_yes_to_all_remedy(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _phase_ids, wiped, launched = _seed_live_collision(
        project_dir, tmp_path, monkeypatch
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt: pytest.fail(f"unexpected prompt: {prompt}"),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id))

    assert excinfo.value.code == 1
    assert "--yes-to-all" in capsys.readouterr().err
    assert wiped == []
    assert launched == []


def test_fresh_epic_has_no_cleanup_prompt_and_yes_skips_launch_prompt(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, _phase_ids = seed_diamond(project_dir)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt: pytest.fail(f"unexpected prompt: {prompt}"),
    )
    launched: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert len(launched) == 1


def test_json_implies_yes_to_all_noninteractively(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _phase_ids, _wiped, launched = _seed_live_collision(
        project_dir, tmp_path, monkeypatch
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt: pytest.fail(f"unexpected prompt: {prompt}"),
    )

    bead_cli.handle_bead_work(make_args(epic_id, json_output=True))

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["launched"] is True
    assert len(launched) == 1


def test_preview_renders_kill_remove_and_release(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owners: dict[str, dict[str, Any]] = {
        "live": {"state": "active", "artifacts_dir": "/agents/live"},
        "terminal": {"state": "done", "artifacts_dir": "/agents/terminal"},
        "stale": {"container_kind": "family", "state": "dismissed"},
    }
    monkeypatch.setattr(
        "sase.agent.names.lookup_registered_name",
        lambda name: owners.get(name),
    )
    monkeypatch.setattr(
        "sase.agent.names.get_live_agent_name_subset",
        lambda names: {"live": "/agents/live"} if "live" in names else {},
    )
    monkeypatch.setattr("sase.agent.names.find_agent_family", lambda name: None)
    monkeypatch.setattr("sase.agent.names.find_agent_clan", lambda name: None)
    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda name: (
            SimpleNamespace(
                name=name,
                artifacts_dir="/agents/terminal",
                is_done=True,
                outcome="completed",
            )
            if name == "terminal"
            else None
        ),
    )

    preview = preview_bead_work_force_reuse(
        "%id(!live)\n---\n%id(!terminal)\n---\n%id(!stale)",
        expected_names={"live", "terminal", "stale"},
    )
    render_cleanup_preview("epic", preview)

    rendered = capsys.readouterr().err
    assert "KILL" in rendered and "live" in rendered
    assert "REMOVE" in rendered and "terminal" in rendered
    assert "RELEASE" in rendered and "stale" in rendered


def test_orphaned_family_bundle_is_released_and_launch_proceeds(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.names import (
        find_agent_family,
        is_name_reserved,
        rebuild_name_registry,
    )

    epic_id, phase_ids = seed_diamond(project_dir)
    family_name = phase_ids[0]
    fake_home = tmp_path / "fake_home"
    bundle_path = (
        fake_home / ".sase" / "dismissed_bundles" / "202607" / "20260723120000.json"
    )
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text(
        json.dumps(
            {
                "raw_suffix": "20260723120000",
                "agent_name": f"{family_name}--code",
                "workflow_name": family_name,
                "agent_family": family_name,
                "status": "DONE",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    rebuild_name_registry()
    assert is_name_reserved(family_name)
    assert find_agent_family(family_name) is None

    launched: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))

    assert len(launched) == 1
    assert not bundle_path.exists()
    assert not is_name_reserved(family_name)


def test_orphaned_clan_bundle_is_released_and_launch_proceeds(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.names import (
        find_agent_clan,
        is_name_reserved,
        rebuild_name_registry,
    )

    epic_id, phase_ids = seed_diamond(project_dir)
    clan_name = phase_ids[0]
    fake_home = tmp_path / "fake_home"
    bundle_path = (
        fake_home / ".sase" / "dismissed_bundles" / "202607" / "20260723130000.json"
    )
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text(
        json.dumps(
            {
                "raw_suffix": "20260723130000",
                "agent_name": f"{clan_name}.member",
                "agent_clan": clan_name,
                "agent_clan_generation": "orphaned-generation",
                "status": "DONE",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    rebuild_name_registry()
    assert is_name_reserved(clan_name)
    assert find_agent_clan(clan_name) is None

    launched: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))

    assert len(launched) == 1
    assert not bundle_path.exists()
    assert not is_name_reserved(clan_name)


def test_yes_to_all_parser_flag() -> None:
    args = create_parser().parse_args(["bead", "work", "sase-1", "-Y"])
    assert args.yes_to_all is True
    assert args.yes is False


def test_confirm_launch_treats_eof_as_decline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def raise_eof(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr(builtins, "input", raise_eof)
    assert confirm_launch() is False
