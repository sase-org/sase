"""Tests for ``sase flag show``."""

from __future__ import annotations

import io
from datetime import date

import pytest
from rich.console import Console

from sase.feature_flags.cli_show import handle_flag_show
from sase.feature_flags.references import FlagCallSite
from sase.main.parser import create_parser
from tests.feature_flags._helpers import demo_flag, flag_bead, snapshot_for


def _console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=160, color_system=None, highlight=False), buf


def test_flag_show_unknown_key_errors(capsys: pytest.CaptureFixture[str]) -> None:
    args = create_parser().parse_args(["flag", "show", "missing_flag"])

    exit_code = handle_flag_show(args, definitions={}, snapshot=snapshot_for())

    assert exit_code == 1
    assert "unknown feature flag: missing_flag" in capsys.readouterr().err


def test_flag_show_includes_layers_bead_and_call_sites() -> None:
    console, buf = _console()
    flag = demo_flag("demo_flag")
    args = create_parser().parse_args(["flag", "show", "demo_flag"])

    exit_code = handle_flag_show(
        args,
        console=console,
        definitions={str(flag.key): flag},
        snapshot=snapshot_for(flag, enabled={"demo_flag": True}, source="user"),
        beads=(flag_bead("demo_flag"),),
        layers=(),
        call_sites=(
            FlagCallSite(
                path="consumer.py",
                line=12,
                text="return snapshot.enabled(FeatureFlag.demo_flag)",
            ),
        ),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    assert exit_code == 0
    out = buf.getvalue()
    assert "demo_flag" in out
    assert "kind:" in out
    assert "VALUE" in out
    assert "LAYERS" in out
    assert "BEAD" in out
    assert "sase-nb.test" in out
    assert "2026-12-01" in out
    assert "CALL SITES" in out
    assert "consumer.py:12" in out


def test_flag_show_renders_cli_layer_without_env_row() -> None:
    console, buf = _console()
    flag = demo_flag("demo_flag")
    args = create_parser().parse_args(["flag", "show", "demo_flag"])

    exit_code = handle_flag_show(
        args,
        console=console,
        definitions={str(flag.key): flag},
        snapshot=snapshot_for(
            flag,
            enabled={"demo_flag": False},
            source="cli",
            source_detail="--disable-feature",
        ),
        beads=(flag_bead("demo_flag"),),
        layers=(),
        call_sites=(),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    assert exit_code == 0
    out = buf.getvalue()
    assert "CLI:--disable-feature" in out
    assert "effective:  off" in out
    layer_names = [
        line.split()[0]
        for line in out.splitlines()
        if line.startswith("  ")
        and line.split()[0] in {"default", "env", "cli", "user", "local"}
    ]
    assert "cli" in layer_names
    assert "env" not in layer_names
    assert "state" not in layer_names
    assert "--disable-feature" in out
    assert "saved:      —" in out


def test_flag_show_explains_saved_value_when_cli_wins() -> None:
    console, buf = _console()
    flag = demo_flag("demo_flag")
    args = create_parser().parse_args(["flag", "show", "demo_flag"])
    state_path = "/tmp/feature_flags.json"

    exit_code = handle_flag_show(
        args,
        console=console,
        definitions={str(flag.key): flag},
        snapshot=snapshot_for(
            flag,
            enabled={"demo_flag": False},
            source="cli",
            source_detail="--disable-feature",
            saved={"demo_flag": True},
            state_path=state_path,
        ),
        beads=(flag_bead("demo_flag"),),
        layers=(),
        call_sites=(),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    assert exit_code == 0
    out = buf.getvalue()
    assert "CLI:--disable-feature" in out
    assert "effective:  off" in out
    assert "saved:      on" in out
    layer_names = [
        line.split()[0]
        for line in out.splitlines()
        if line.startswith("  ")
        and line.split()[0] in {"default", "state", "env", "cli", "user", "local"}
    ]
    assert layer_names.index("state") < layer_names.index("cli")
    assert state_path in out
