"""Phase cli: the ``sase goal`` command group.

Covers epic ``sase-1bu`` phase ``cli``: every verb in local mode, the
human-only refusal matrix, renderer chips, fast/slow byte equality, the
fast-path import isolation, parser conventions, and registration.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

import sase.goals.cli as goal_cli
import sase.goals.store as goal_store
from sase.completion.run_policy import writes_for
from sase.core import goal_ledger_facade as facade
from sase.main.parser import create_parser

_PROJECT = "acme_cli"


@pytest.fixture()
def local_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Local-only ledger with a fixed project name for CLI tests."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.setattr(goal_store, "goals_visibility", lambda: "local")
    monkeypatch.setattr(goal_cli, "_current_project_name", lambda: _PROJECT)
    return tmp_path


def _args(argv: list[str]) -> argparse.Namespace:
    return create_parser().parse_args(argv)


def _new_goal(
    capsys: pytest.CaptureFixture[str] | None = None,
    title: str = "Try goals",
) -> str:
    args = _args(["goal", "new", "-t", title, "-o", "A goal is visible everywhere"])
    with pytest.raises(SystemExit) as excinfo:
        from sase.main.goal_handler import handle_goal_group

        handle_goal_group(args)
    assert excinfo.value.code == 0
    if capsys is not None:
        capsys.readouterr()
    return title


def _list_text(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    from sase.main.goal_handler import handle_goal_group

    with pytest.raises(SystemExit) as excinfo:
        handle_goal_group(_args(argv))
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return captured.out


class TestGoalVerbs:
    def test_new_list_show_round_trip(
        self, local_cli: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _new_goal(capsys)
        out = _list_text(["goal", "list"], capsys)
        assert "Goals feature" not in out
        assert "Try goals" in out
        assert "⌖" in out

        listed = facade.goal_ledger_list(goal_store.resolve_goal_ledger(_PROJECT).root)
        goal_id = listed["goals"][0]["id"]
        shown = _list_text(["goal", "show", goal_id], capsys)
        assert "OUTCOME" in shown
        assert f"goal:{goal_id}" in shown

    def test_new_prints_cite_hint(
        self, local_cli: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(["goal", "new", "-t", "T", "-o", "O"]))
        assert excinfo.value.code == 0
        captured = capsys.readouterr()
        assert "Created goal:" in captured.out
        assert "@goal:" in captured.out

    def test_edit_drop_reopen_cycle(
        self, local_cli: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        _new_goal(capsys, "Cycle goal")
        ledger = goal_store.resolve_goal_ledger(_PROJECT)
        goal_id = facade.goal_ledger_list(ledger.root)["goals"][0]["id"]

        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(["goal", "edit", goal_id, "-o", "New outcome"]))
        assert excinfo.value.code == 0
        assert "Edited goal:" in capsys.readouterr().out

        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(["goal", "drop", goal_id, "-w", "tried"]))
        assert excinfo.value.code == 0
        assert "Dropped goal:" in capsys.readouterr().out
        assert "Try goals" not in _list_text(["goal", "list"], capsys)

        dropped = _list_text(["goal", "list", "-s", "dropped"], capsys)
        assert "Cycle goal" in dropped

        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(["goal", "reopen", goal_id, "-m", "again"]))
        assert excinfo.value.code == 0
        assert "Cycle goal" in _list_text(["goal", "list"], capsys)

    def test_merge_settles_source(
        self, local_cli: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        _new_goal(capsys, "Source goal")
        _new_goal(capsys, "Target goal")
        ledger = goal_store.resolve_goal_ledger(_PROJECT)
        ids = [goal["id"] for goal in facade.goal_ledger_list(ledger.root)["goals"]]
        source = next(i for i in ids if i != ids[0])
        target = ids[0]
        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(
                _args(["goal", "merge", source, "-i", target, "-w", "same"])
            )
        assert excinfo.value.code == 0
        assert "Merged goal:" in capsys.readouterr().out

    def test_reopen_active_is_refused(
        self, local_cli: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        _new_goal(capsys)
        ledger = goal_store.resolve_goal_ledger(_PROJECT)
        goal_id = facade.goal_ledger_list(ledger.root)["goals"][0]["id"]
        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(["goal", "reopen", goal_id, "-m", "nope"]))
        assert excinfo.value.code == 1
        assert "not_settled" in capsys.readouterr().err

    def test_doctor_reports_healthy(
        self, local_cli: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        _new_goal(capsys)
        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(["goal", "doctor"]))
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "healthy" in out
        assert "push retries" in out

    def test_list_json_matches_wire(
        self, local_cli: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _new_goal(capsys)
        out = _list_text(["goal", "list", "-j"], capsys)
        payload = json.loads(out)
        assert payload["schema_version"] == 1
        assert len(payload["goals"]) == 1

    def test_empty_state(
        self, local_cli: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = _list_text(["goal", "list"], capsys)
        assert "No active goals in" in out
        assert "sase goal new" in out


class TestHumanOnlyRefusal:
    @pytest.mark.parametrize(
        "argv",
        [
            ["goal", "new", "-t", "T", "-o", "O"],
            ["goal", "edit", "7k2mq", "-t", "T"],
            ["goal", "drop", "7k2mq", "-w", "W"],
            ["goal", "reopen", "7k2mq", "-m", "M"],
            ["goal", "merge", "7k2mq", "-i", "3fq9t"],
            ["goal", "doctor", "--repair"],
        ],
    )
    def test_human_verbs_refuse_agents(
        self,
        local_cli: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        argv: list[str],
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        monkeypatch.setenv("SASE_AGENT", "1")
        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(argv))
        assert excinfo.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "is a human verb" in captured.err
        assert "sase goal list" in captured.err

    @pytest.mark.parametrize("argv", [["goal", "list"], ["goal", "doctor"]])
    def test_reads_allow_agents(
        self,
        local_cli: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        argv: list[str],
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        monkeypatch.setenv("SASE_AGENT", "1")
        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(argv))
        assert excinfo.value.code == 0


class TestGoalRendering:
    def test_unpublished_and_unreadable_chips(self) -> None:
        text = facade.goal_render_list(
            {
                "goals": [
                    {
                        "id": "zz999",
                        "title": "Broken goal",
                        "status": "active",
                        "readable": False,
                        "created_at": "2026-09-28T13:00:00Z",
                        "updated_at": "2026-09-28T13:00:00Z",
                    }
                ],
                "project": "sase",
                "mode": "shared",
                "synced_ago_seconds": 5.0,
                "unpublished": True,
                "refreshing": True,
                "color": False,
                "compact": True,
                "now": "2026-09-28T14:00:00Z",
            }
        )
        assert "↑ unpublished" in text
        assert "refreshing…" in text
        assert "1 unreadable (run sase goal doctor)" in text

    def test_id_forms_normalize(self) -> None:
        assert goal_cli._normalize_goal_id_token("7K2MQ") == (None, "7k2mq")
        assert goal_cli._normalize_goal_id_token("⌖7k2mq") == (None, "7k2mq")
        assert goal_cli._normalize_goal_id_token("goal:7k2mq") == (
            None,
            "7k2mq",
        )
        assert goal_cli._normalize_goal_id_token("goal:sase@7k2mq") == (
            "sase",
            "7k2mq",
        )


class TestFastSlowParity:
    def _seed_checkout(
        self, work: Path, monkeypatch: pytest.MonkeyPatch, now: str
    ) -> None:
        (work / ".sase").mkdir(parents=True, exist_ok=True)
        (work / ".sase" / "checkout.json").write_text(
            json.dumps({"project_name": _PROJECT}), encoding="utf-8"
        )
        monkeypatch.chdir(work)
        monkeypatch.setattr(goal_cli, "utc_now_iso", lambda: now)

    def test_list_and_show_match(
        self,
        local_cli: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        now = "2026-09-28T14:00:00Z"
        work = tmp_path / "work"
        work.mkdir()
        self._seed_checkout(work, monkeypatch, now)
        _new_goal(capsys, "Parity goal")
        ledger = goal_store.resolve_goal_ledger(_PROJECT)
        goal_id = facade.goal_ledger_list(ledger.root)["goals"][0]["id"]

        slow_list = _list_text(["goal", "list"], capsys)
        slow_show = _list_text(["goal", "show", goal_id], capsys)

        import os

        home = os.environ["SASE_HOME"]
        from sase.core.rust import require_rust_binding

        fast_binding = require_rust_binding("goal_fast_path")
        fast_list = fast_binding(
            {
                "argv": ["list"],
                "cwd": str(work),
                "sase_home": home,
                "color": False,
                "agent": True,
                "now": now,
            }
        )
        assert fast_list["handled"] is True
        assert fast_list["stdout"] == slow_list

        fast_show = fast_binding(
            {
                "argv": ["show", goal_id],
                "cwd": str(work),
                "sase_home": home,
                "color": False,
                "agent": True,
                "now": now,
            }
        )
        assert fast_show["handled"] is True
        assert fast_show["stdout"] == slow_show

    def test_fast_path_json_matches_slow(
        self,
        local_cli: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        now = "2026-09-28T14:00:00Z"
        work = tmp_path / "work"
        work.mkdir()
        self._seed_checkout(work, monkeypatch, now)
        _new_goal(capsys, "JSON goal")

        import os

        slow = _list_text(["goal", "list", "-j"], capsys)
        from sase.core.rust import require_rust_binding

        fast = require_rust_binding("goal_fast_path")(
            {
                "argv": ["list", "-j"],
                "cwd": str(work),
                "sase_home": os.environ["SASE_HOME"],
                "color": False,
                "agent": True,
                "now": now,
            }
        )
        assert fast["handled"] is True
        # Both paths reduce through the same core call; only the
        # per-call generation timestamp may differ.
        slow_payload = json.loads(slow)
        fast_payload = json.loads(fast["stdout"])
        assert slow_payload.keys() == fast_payload.keys()
        for key in slow_payload:
            if key != "generated_at":
                assert fast_payload[key] == slow_payload[key], key


def test_goal_fast_path_import_isolation() -> None:
    """The fast path stays lean: no argparse, rich, or sase.config."""
    script = """
import sys

from sase.main.goal_fast_path import try_handle_goal_fast_path

assert "argparse" not in sys.modules
assert "rich" not in sys.modules
assert "sase.config" not in sys.modules
assert try_handle_goal_fast_path(["--help"]) is None
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_goal_parser_options_are_alphabetical_with_aliases() -> None:
    parser = create_parser()
    top = next(
        action
        for action in parser._actions
        if getattr(action, "choices", None) and "goal" in action.choices
    )
    goal = top.choices["goal"]
    sub = next(action for action in goal._actions if getattr(action, "choices", None))
    assert list(sub.choices) == [
        "doctor",
        "drop",
        "edit",
        "list",
        "merge",
        "new",
        "reopen",
        "show",
    ]
    for name, child in sub.choices.items():
        longs = sorted(
            option for option in child._option_string_actions if option.startswith("--")
        )
        assert longs == sorted(longs), name
        for long in longs:
            action = child._option_string_actions[long]
            assert any(
                short.startswith("-") and not short.startswith("--")
                for short in action.option_strings
            ), (name, long)


def test_goal_write_verbs_carry_writes_chip() -> None:
    for verb in ("new", "edit", "drop", "reopen", "merge"):
        assert writes_for(("goal", verb)) is True
    assert writes_for(("goal", "list")) is False
    assert writes_for(("goal", "show")) is False


def _goal_id_with_criteria(
    capsys: pytest.CaptureFixture[str],
    criteria: list[str],
) -> str:
    from sase.main.goal_handler import handle_goal_group

    argv = ["goal", "new", "-t", "Numbered", "-o", "Criteria map by number"]
    for text in criteria:
        argv.extend(["-c", text])
    with pytest.raises(SystemExit) as excinfo:
        handle_goal_group(_args(argv))
    assert excinfo.value.code == 0
    capsys.readouterr()
    ledger = goal_store.resolve_goal_ledger(_PROJECT)
    return str(facade.goal_ledger_list(ledger.root)["goals"][0]["id"])


class TestRemoveCriterionNumbering:
    def test_remove_first_criterion_by_number(
        self, local_cli: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        goal_id = _goal_id_with_criteria(capsys, ["First", "Second"])
        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(["goal", "edit", goal_id, "-x", "1"]))
        assert excinfo.value.code == 0
        capsys.readouterr()
        ledger = goal_store.resolve_goal_ledger(_PROJECT)
        state = facade.goal_ledger_show(ledger.root, goal_id)
        assert [c["text"] for c in state["criteria"]] == ["Second"]

    def test_out_of_range_number_exits_2_without_writing(
        self, local_cli: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        goal_id = _goal_id_with_criteria(capsys, ["First", "Second"])
        ledger = goal_store.resolve_goal_ledger(_PROJECT)
        events = ledger.root / "items" / goal_id / "events"
        before = sorted(path.name for path in events.iterdir())
        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(["goal", "edit", goal_id, "-x", "9"]))
        assert excinfo.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "\n" not in captured.err.strip()
        assert sorted(path.name for path in events.iterdir()) == before


class TestStatusChoices:
    def test_bogus_status_exits_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            _args(["goal", "list", "-s", "bogus"])
        assert excinfo.value.code == 2
        assert "invalid choice" in capsys.readouterr().err


class TestCrossProjectIds:
    def test_cross_project_drop_settles_named_ledger(
        self,
        local_cli: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        _new_goal(capsys)
        ledger = goal_store.resolve_goal_ledger(_PROJECT)
        goal_id = str(facade.goal_ledger_list(ledger.root)["goals"][0]["id"])
        monkeypatch.setattr(goal_cli, "_current_project_name", lambda: "acme_elsewhere")
        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(
                _args(["goal", "drop", f"goal:{_PROJECT}@{goal_id}", "-w", "done"])
            )
        assert excinfo.value.code == 0
        capsys.readouterr()
        state = facade.goal_ledger_show(ledger.root, goal_id)
        assert state["status"] == "dropped"
        elsewhere = goal_store.resolve_goal_ledger("acme_elsewhere")
        assert facade.goal_ledger_list(elsewhere.root)["goals"] == []

    def test_merge_across_projects_refuses(
        self,
        local_cli: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(
                _args(["goal", "merge", "goal:projA@abcde", "-i", "goal:projB@fghij"])
            )
        assert excinfo.value.code == 2
        assert "different projects" in capsys.readouterr().err

    def test_doctor_repair_keeps_header_and_fast_path_lists(
        self, local_cli: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        _new_goal(capsys)
        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(["goal", "doctor", "--repair"]))
        assert excinfo.value.code == 0
        capsys.readouterr()
        ledger = goal_store.resolve_goal_ledger(_PROJECT)
        assert ledger.projection_path.is_file()
        assert "Try goals" in _list_text(["goal", "list"], capsys)

    def test_doctor_repair_refusal_names_doctor_flag(
        self,
        local_cli: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        monkeypatch.setenv("SASE_AGENT", "1")
        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(["goal", "doctor", "--repair"]))
        assert excinfo.value.code == 2
        assert "sase goal doctor --repair is a human verb" in capsys.readouterr().err


class TestPhantomGoals:
    @pytest.mark.parametrize("argv", [["edit", "-t"], ["drop", "-w"]])
    def test_unknown_id_refuses_without_live_marker(
        self,
        local_cli: Path,
        capsys: pytest.CaptureFixture[str],
        argv: list[str],
    ) -> None:
        from sase.main.goal_handler import handle_goal_group

        verb, flag = argv
        with pytest.raises(SystemExit) as excinfo:
            handle_goal_group(_args(["goal", verb, "zzzzz", flag, "x"]))
        assert excinfo.value.code != 0
        assert "goal_not_found" in capsys.readouterr().err
        ledger = goal_store.resolve_goal_ledger(_PROJECT)
        assert not (ledger.root / "live" / "zzzzz").exists()
        assert not (ledger.root / "items" / "zzzzz").exists()
