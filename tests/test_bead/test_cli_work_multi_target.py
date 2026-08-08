"""Sequential multi-target coverage for ``sase bead work``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

import pytest

from sase.bead import cli_work_entry
from sase.main.parser import create_parser


class _FakeCodeSwapLock:
    def __init__(self, *, acquired: bool = True, blocked_by: str | None = None) -> None:
        self.acquired = acquired
        self.blocked_by = blocked_by
        self.enter_count = 0
        self.exit_count = 0
        self.active = False

    def __enter__(self) -> _FakeCodeSwapLock:
        self.enter_count += 1
        self.active = True
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.active = False
        self.exit_count += 1


def _timer_factory(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("stubbed single-target dispatcher should own timer creation")


def test_bead_work_parser_accepts_one_or_more_targets_in_order() -> None:
    parser = create_parser()

    single = parser.parse_args(["bead", "work", "sase-1"])
    mixed = parser.parse_args(
        ["bead", "work", "./epic_plan.md", "sase-2", "sase-task", "--yes"]
    )

    assert single.target == ["sase-1"]
    assert mixed.target == ["./epic_plan.md", "sase-2", "sase-task"]
    assert mixed.yes is True


def test_bead_work_parser_still_requires_at_least_one_target() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["bead", "work"])

    assert exc_info.value.code == 2


def test_scalar_namespace_target_remains_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    lock = _FakeCodeSwapLock()
    monkeypatch.setattr(
        "sase.dev_update.code_swap_lock.code_swap_reader_lock",
        lambda **_kwargs: lock,
    )
    monkeypatch.setattr(
        cli_work_entry,
        "_handle_bead_work_locked",
        lambda _args, **kwargs: calls.append(kwargs["target"]),
    )

    cli_work_entry.handle_bead_work(
        argparse.Namespace(target="sase-one", json=False),
        timer_factory=_timer_factory,
    )

    assert calls == ["sase-one"]
    assert lock.enter_count == 1
    assert lock.exit_count == 1


def test_legacy_id_namespace_target_remains_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.dev_update.code_swap_lock.code_swap_reader_lock",
        lambda **_kwargs: _FakeCodeSwapLock(),
    )
    monkeypatch.setattr(
        cli_work_entry,
        "_handle_bead_work_locked",
        lambda _args, **kwargs: calls.append(kwargs["target"]),
    )

    cli_work_entry.handle_bead_work(
        argparse.Namespace(id="sase-legacy", json=False),
        timer_factory=_timer_factory,
    )

    assert calls == ["sase-legacy"]


def test_multi_target_dispatch_reuses_options_and_one_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool, str | None, bool]] = []
    lock = _FakeCodeSwapLock()
    monkeypatch.setattr(
        "sase.dev_update.code_swap_lock.code_swap_reader_lock",
        lambda **_kwargs: lock,
    )

    def fake_dispatch(
        args: argparse.Namespace,
        *,
        timer_factory: Callable[..., Any],
        json_output: bool,
        target: str,
    ) -> None:
        assert timer_factory is _timer_factory
        assert lock.active is True
        calls.append((target, args.yes, args.parent, json_output))

    monkeypatch.setattr(cli_work_entry, "_handle_bead_work_locked", fake_dispatch)

    cli_work_entry.handle_bead_work(
        argparse.Namespace(
            target=["./epic.md", "sase-task"],
            json=True,
            yes=True,
            parent="top-level",
        ),
        timer_factory=_timer_factory,
    )

    assert calls == [
        ("./epic.md", True, "top-level", True),
        ("sase-task", True, "top-level", True),
    ]
    assert lock.enter_count == 1
    assert lock.exit_count == 1


def test_multi_target_short_circuits_on_first_failure_with_json_lines(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.dev_update.code_swap_lock.code_swap_reader_lock",
        lambda **_kwargs: _FakeCodeSwapLock(),
    )

    def fake_dispatch(
        _args: argparse.Namespace,
        *,
        timer_factory: Callable[..., Any],
        json_output: bool,
        target: str,
    ) -> None:
        assert timer_factory is _timer_factory
        assert json_output is True
        calls.append(target)
        print(json.dumps({"ok": target != "bad", "target": target}, sort_keys=True))
        if target == "bad":
            raise SystemExit(7)

    monkeypatch.setattr(cli_work_entry, "_handle_bead_work_locked", fake_dispatch)

    with pytest.raises(SystemExit) as exc_info:
        cli_work_entry.handle_bead_work(
            argparse.Namespace(target=["first", "bad", "later"], json=True),
            timer_factory=_timer_factory,
        )

    assert exc_info.value.code == 7
    assert calls == ["first", "bad"]
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line) for line in lines] == [
        {"ok": True, "target": "first"},
        {"ok": False, "target": "bad"},
    ]


def test_code_swap_lock_failure_prevents_all_targets_and_reports_first(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    lock = _FakeCodeSwapLock(acquired=False, blocked_by="writer pid 123")
    monkeypatch.setattr(sys, "argv", ["sase", "bead", "work", "first", "second"])
    monkeypatch.setattr(
        "sase.dev_update.code_swap_lock.code_swap_reader_lock",
        lambda **_kwargs: lock,
    )
    monkeypatch.setattr(
        cli_work_entry,
        "_handle_bead_work_locked",
        lambda _args, **kwargs: calls.append(kwargs["target"]),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli_work_entry.handle_bead_work(
            argparse.Namespace(target=["first", "second"], json=True),
            timer_factory=_timer_factory,
        )

    assert exc_info.value.code == 1
    assert calls == []
    assert lock.enter_count == 1
    assert lock.exit_count == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["target"] == "first"
    assert "writer pid 123" in payload["error"]
