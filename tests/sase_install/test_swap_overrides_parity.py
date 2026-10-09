"""Swap-argv and overrides parity with ``sase.uv_tool`` (byte-for-byte)."""

from __future__ import annotations

from pathlib import Path

import pytest

import tests._sase_install_testkit as kit
from tests._sase_install_testkit import install_env, install_plan, install_state
from sase.uv_tool import commands as sase_commands
from sase.uv_tool import overrides as sase_overrides
from sase.uv_tool import receipt as sase_receipt


SPEC_CASES = [
    "sase",
    "sase==0.17.1",
    "sase-github",
    "sase-github>=0.2.5",
    "sase-github[recommenders]>=0.2.5",
    "git+https://github.com/sase-org/sase-telegram@abc123",
    "/opt/plugins/docs-plugin",
]


def _both(spec: str) -> tuple[object, object]:
    return (
        sase_receipt.Requirement.from_spec(spec),
        install_state.InstallRequirement.from_spec(spec),
    )


@pytest.mark.parametrize("host_spec", ["sase", "sase==0.17.1"])
@pytest.mark.parametrize("overrides", [None, "/tmp/sase-home/uv/overrides.txt"])
def test_swap_argv_matches_build_reinstall_set(
    host_spec: str, overrides: str | None
) -> None:
    sase_plugins = [sase_receipt.Requirement.from_spec(s) for s in SPEC_CASES[2:]]
    engine_plugins = [
        install_state.InstallRequirement.from_spec(s) for s in SPEC_CASES[2:]
    ]
    sase_host, engine_host = _both(host_spec)
    expected = sase_commands.build_reinstall_set(
        sase_host,  # type: ignore[arg-type]
        sase_plugins,  # type: ignore[arg-type]
        color="never",
        overrides=overrides,
    )
    observed = install_plan.build_swap_argv(
        engine_host,  # type: ignore[arg-type]
        engine_plugins,  # type: ignore[arg-type]
        overrides=overrides,
    )
    assert observed == expected


def test_swap_argv_editable_host_matches() -> None:
    sase_host = sase_receipt.Requirement(name="sase", editable="/durable/sase")
    engine_host = install_state.InstallRequirement(
        name="sase", editable="/durable/sase"
    )
    sase_plugins = [
        sase_receipt.Requirement(name="sase-github", editable="/durable/sase-github")
    ]
    engine_plugins = [
        install_state.InstallRequirement(
            name="sase-github", editable="/durable/sase-github"
        )
    ]
    expected = sase_commands.build_reinstall_set(
        sase_host,
        sase_plugins,
        color="never",
        overrides="/home/u/.sase/uv/editable-overrides.txt",
    )
    observed = install_plan.build_swap_argv(
        engine_host,
        engine_plugins,
        overrides="/home/u/.sase/uv/editable-overrides.txt",
    )
    assert observed == expected
    assert "--force" in observed and "--reinstall" in observed
    assert "--python" not in observed


def test_overrides_content_matches_sase() -> None:
    sase_reqs = [
        sase_receipt.Requirement(name="sase", editable="/durable/sase"),
        sase_receipt.Requirement(name="sase-github", editable="/durable/sase-github"),
        sase_receipt.Requirement(name="sase-github", editable="/other/sase-github"),
        sase_receipt.Requirement(name="sase-telegram"),
    ]
    engine_reqs = [
        install_state.InstallRequirement(name="sase", editable="/durable/sase"),
        install_state.InstallRequirement(
            name="sase-github", editable="/durable/sase-github"
        ),
        install_state.InstallRequirement(
            name="sase-github", editable="/other/sase-github"
        ),
        install_state.InstallRequirement(name="sase-telegram"),
    ]
    assert (
        install_plan.editable_override_lines(engine_reqs)  # type: ignore[arg-type]
        == sase_overrides.editable_override_lines(sase_reqs)  # type: ignore[arg-type]
    )
    assert install_plan.editable_override_lines([]) == ()


def test_overrides_path_matches_sase(tmp_path: Path, monkeypatch: object) -> None:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))  # type: ignore[attr-defined]
    env = {"SASE_HOME": str(sase_home)}
    assert install_env.editable_overrides_path(env) == (
        sase_home / "uv" / "editable-overrides.txt"
    )
    from sase.core.paths import ensure_sase_directory

    expected_dir = ensure_sase_directory("uv")
    assert install_env.editable_overrides_path(env) == (
        Path(expected_dir) / "editable-overrides.txt"
    )


def test_plan_swap_argv_has_no_python_flag(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    tool_dir, bin_dir = kit.make_tool_env(tmp_path, checkout=checkout)
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=bin_dir)
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="dev", python="3.13"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )
    assert "--python" not in plan.swap_argv
    assert plan.python.change
    assert plan.python.target == "3.13"
