"""Tests for the Command Line spec contract (bead sase-17x.2)."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sase.completion.build import build_spec
from sase.completion.command_line_spec import (
    _command_line_spec_path,
    ensure_command_line_spec,
)
from sase.completion.kinds import ValueKind
from sase.completion.model import (
    CommandSpec,
    CompletionSpec,
    OptionSpec,
    PositionalSpec,
)
from sase.completion.run_policy import (
    _RUN_POLICY_TABLE,
    _STDIN_PATHS,
    _WRITES_FALSE_OVERRIDES,
    _WRITES_TRUE_OVERRIDES,
)


def _policy_table_paths() -> tuple[tuple[str, ...], ...]:
    paths: set[tuple[str, ...]] = set(_RUN_POLICY_TABLE)
    paths |= set(_WRITES_TRUE_OVERRIDES)
    paths |= set(_WRITES_FALSE_OVERRIDES)
    paths |= set(_STDIN_PATHS)
    return tuple(sorted(paths))


def _all_commands(root: CommandSpec) -> Iterator[CommandSpec]:
    yield root
    for child in root.subcommands:
        yield from _all_commands(child)


def test_option_spec_round_trips_with_new_fields() -> None:
    option = OptionSpec(
        strings=("--limit",),
        dest="limit",
        summary="Limit rows",
        takes_value=True,
        repeatable=False,
        choices=None,
        kind=None,
        hidden=False,
        required=False,
        metavar="N",
        default="50",
        value_hint="int",
    )
    assert OptionSpec.from_json(option.to_json()) == option
    # Older caches without the additive fields still load.
    payload = option.to_json()
    for key in ("required", "metavar", "default", "value_hint"):
        del payload[key]
    assert OptionSpec.from_json(payload) == OptionSpec(
        strings=option.strings,
        dest=option.dest,
        summary=option.summary,
        takes_value=option.takes_value,
        repeatable=option.repeatable,
        choices=option.choices,
        kind=option.kind,
        hidden=option.hidden,
    )


def test_positional_spec_round_trips_with_new_fields() -> None:
    positional = PositionalSpec(
        metavar="ID",
        dest="ids",
        summary="Bead ids",
        nargs="+",
        choices=None,
        kind=ValueKind.BEAD,
        is_remainder=False,
        required=True,
        value_hint=None,
    )
    assert PositionalSpec.from_json(positional.to_json()) == positional
    payload = positional.to_json()
    del payload["required"]
    del payload["value_hint"]
    assert PositionalSpec.from_json(payload) == positional


def test_command_spec_round_trips_with_policy_writes_stdin() -> None:
    command = CommandSpec(
        name="answer",
        path=("sudo", "answer"),
        aliases=(),
        hidden=False,
        summary="Answer a sudo gate",
        options=(),
        positionals=(),
        subcommands=(),
        default_child=None,
        mutex_groups=(),
        run_policy=(),
        writes=True,
        stdin=False,
    )
    assert CommandSpec.from_json(command.to_json()) == command
    payload = command.to_json()
    for key in ("run_policy", "writes", "stdin"):
        del payload[key]
    assert CommandSpec.from_json(payload) == CommandSpec(
        name=command.name,
        path=command.path,
        aliases=command.aliases,
        hidden=command.hidden,
        summary=command.summary,
        options=command.options,
        positionals=command.positionals,
        subcommands=command.subcommands,
        default_child=command.default_child,
        mutex_groups=command.mutex_groups,
    )


def test_full_spec_round_trips_with_new_fields() -> None:
    spec = build_spec()
    assert CompletionSpec.from_json(spec.to_json()) == spec


def _spec_from_synthetic(parser: argparse.ArgumentParser) -> CompletionSpec:
    return build_spec(parser)


def test_required_derivation_for_every_nargs_shape() -> None:
    cases: list[tuple[Any, bool]] = [
        (None, True),
        ("?", False),
        ("*", False),
        ("+", True),
        (2, True),
        (argparse.REMAINDER, False),
        ("...", False),
        (argparse.PARSER, False),
        (argparse.SUPPRESS, False),
    ]
    for nargs, expected in cases:
        parser = argparse.ArgumentParser(prog="sase")
        parser.add_argument("slot", nargs=nargs)
        spec = _spec_from_synthetic(parser)
        assert len(spec.root.positionals) == 1
        assert spec.root.positionals[0].required is expected, f"nargs={nargs!r}"


def test_display_safe_defaults() -> None:
    parser = argparse.ArgumentParser(prog="sase")
    parser.add_argument("--short", default="abc")
    parser.add_argument("--num", type=int, default=88)
    parser.add_argument("--flag", action="store_true")
    parser.add_argument("--long", default="x" * 41)
    parser.add_argument("--obj", default=["a"])
    parser.add_argument("--suppressed", default=argparse.SUPPRESS)
    parser.add_argument("--none", default=None)
    spec = _spec_from_synthetic(parser)
    by_dest = {option.dest: option for option in spec.root.options}
    assert by_dest["short"].default == "abc"
    assert by_dest["num"].default == "88"
    assert by_dest["flag"].default == "False"
    assert by_dest["long"].default is None
    assert by_dest["obj"].default is None
    assert by_dest["suppressed"].default is None
    assert by_dest["none"].default is None


def test_option_metavar_plain_string_or_none() -> None:
    parser = argparse.ArgumentParser(prog="sase")
    parser.add_argument("--named", metavar="NAME")
    parser.add_argument("--plain")
    spec = _spec_from_synthetic(parser)
    by_dest = {option.dest: option for option in spec.root.options}
    assert by_dest["named"].metavar == "NAME"
    assert by_dest["plain"].metavar is None


def test_run_policy_tables_match_live_parser() -> None:
    spec = build_spec()
    known = {command.path for command in _all_commands(spec.root)}
    missing = [path for path in _policy_table_paths() if path not in known]
    assert not missing, (
        "run_policy tables reference commands missing from build_spec(): "
        + ", ".join(" ".join(path) for path in missing)
        + ". Re-verify each name against the live parser: fix the path in "
        "src/sase/completion/run_policy.py, or classify the new command there "
        "(run-policy rule, writes override, or stdin set)."
    )


def test_run_policy_spot_checks() -> None:
    spec = build_spec()
    by_path = {command.path: command for command in _all_commands(spec.root)}
    assert by_path[("tui",)].run_policy[0].policy == "deny"
    assert by_path[("pager",)].run_policy[0].policy == "foreground"
    assert by_path[("notify", "create")].stdin is True
    assert by_path[("comments",)].stdin is True
    assert by_path[("bead", "close")].writes is True
    assert by_path[("bead", "show")].writes is False
    assert by_path[("artifact", "open")].writes is False
    assert by_path[("tool", "stop")].writes is True
    assert by_path[("plan", "approve")].writes is True
    assert by_path[("plan", "reject")].writes is True


def _write_spec_json(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"prog": "sase", "version": "test", "root": {}}),
        encoding="utf-8",
    )


def test_command_line_spec_cache_hit_returns_without_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    path = _command_line_spec_path()
    _write_spec_json(path)

    def _fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("subprocess must not run on a cache hit")

    monkeypatch.setattr(subprocess, "run", _fail)
    assert ensure_command_line_spec() == path


def test_command_line_spec_cache_miss_builds_via_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    calls: list[list[str]] = []

    def _fake_run(argv: list[str], **kwargs: Any) -> Any:
        calls.append(list(argv))
        assert "spec" in argv
        assert "-d" in argv
        assert "-j" in argv
        out_index = argv.index("-o") + 1
        out_path = Path(argv[out_index])
        _write_spec_json(out_path)

        class _Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Completed()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    path = ensure_command_line_spec(timeout=30)
    assert path.exists()
    assert len(calls) == 1
    # Second call is a hit: no further subprocess.
    assert ensure_command_line_spec() == path
    assert len(calls) == 1


def test_command_line_spec_prunes_stale_siblings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    current = _command_line_spec_path()
    current.parent.mkdir(parents=True, exist_ok=True)
    stale = current.parent / "command_line_spec-stale.json"
    _write_spec_json(stale)
    _write_spec_json(current)
    # Hit path still prunes only on build; force a rebuild by removing current.
    current.unlink()
    _write_spec_json(stale)

    def _fake_run(argv: list[str], **kwargs: Any) -> Any:
        out_path = Path(argv[argv.index("-o") + 1])
        _write_spec_json(out_path)

        class _Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Completed()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    path = ensure_command_line_spec(timeout=30)
    assert path.exists()
    assert not stale.exists()
