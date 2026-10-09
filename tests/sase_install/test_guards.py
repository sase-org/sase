"""Agent-guard, bypass, and ephemeral-path tests for the installer engine."""

from __future__ import annotations

from pathlib import Path

import tests._sase_install_testkit as kit
from tests._sase_install_testkit import install_env


def _dev_args() -> list[str]:
    return ["dev", "-n"]


def test_agent_env_refuses_with_placeholder_text(tmp_path: Path) -> None:
    entry = kit.load_entry()
    env = kit.make_env(tmp_path, SASE_AGENT="1")
    exit_code, out, err = kit.run_entry(entry, _dev_args(), env=env)
    assert exit_code == 2
    assert out == ""
    assert "won't run inside a SASE agent" in err
    assert "just install-venv" in err
    assert "SASE_GLOBAL_INSTALL_BYPASS" in err


def test_monitor_id_refuses_for_pypi_mode(tmp_path: Path) -> None:
    entry = kit.load_entry()
    env = kit.make_env(tmp_path, SASE_MONITOR_ID="abc123")
    exit_code, out, err = kit.run_entry(entry, ["pypi", "-n"], env=env)
    assert exit_code == 2
    assert out == ""
    assert "just install won't run inside a SASE agent" in err


def test_empty_bypass_still_refuses(tmp_path: Path) -> None:
    entry = kit.load_entry()
    env = kit.make_env(tmp_path, SASE_AGENT="1", SASE_GLOBAL_INSTALL_BYPASS="  ")
    exit_code, _, _ = kit.run_entry(entry, _dev_args(), env=env)
    assert exit_code == 2


def test_bypass_names_reason_and_proceeds(tmp_path: Path, monkeypatch: object) -> None:
    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    checkout = kit.make_checkout(tmp_path)
    tool_dir, bin_dir = kit.make_tool_env(
        tmp_path, host=("pypi", "0.17.1"), checkout=checkout
    )
    env = kit.make_env(
        tmp_path, SASE_AGENT="1", SASE_GLOBAL_INSTALL_BYPASS="user asked in chat"
    )
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    exit_code, out, err = kit.run_entry(
        entry,
        ["dev", "-n"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 0
    assert "SASE_GLOBAL_INSTALL_BYPASS='user asked in chat'" in err
    assert "just install-dev" in out


def test_no_agent_env_needs_no_bypass(tmp_path: Path, monkeypatch: object) -> None:
    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    checkout = kit.make_checkout(tmp_path)
    tool_dir, bin_dir = kit.make_tool_env(tmp_path, checkout=checkout)
    env = kit.make_env(tmp_path)
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    exit_code, _, err = kit.run_entry(
        entry,
        ["dev", "-n"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 0
    assert "SASE_GLOBAL_INSTALL_BYPASS" not in err


def test_ephemeral_classifier_matches_sase(tmp_path: Path, monkeypatch: object) -> None:
    from sase.uv_tool.preflight import _is_ephemeral_plugin_path

    workspace_root = tmp_path / "ws-root"
    # Point sase's classifier at the same root so both sides agree on it.
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(workspace_root))  # type: ignore[attr-defined]
    cases = [
        str(workspace_root / "sase-org" / "sase" / "sase_1"),
        str(tmp_path / "sase" / "repos" / "linked" / "sase-github"),
        str(tmp_path / "sase" / "repos" / "external" / "foo"),
        str(tmp_path / "projects" / "github" / "sase-org" / "sase"),
        str(tmp_path / "home" / "projects" / "sase"),
    ]
    for case in cases:
        expected = _is_ephemeral_plugin_path(case)
        observed = install_env.is_ephemeral_path(
            case, workspace_root=str(workspace_root)
        )
        assert observed == expected, case


def test_ephemeral_classifier_default_root_matches_sase(
    tmp_path: Path, monkeypatch: object
) -> None:
    from sase.uv_tool.preflight import _is_ephemeral_plugin_path

    import os

    root = str(tmp_path / "managed")
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", root)  # type: ignore[attr-defined]
    for case in (
        os.path.join(root, "proj", "sase_x1"),
        str(tmp_path / "durable" / "sase"),
    ):
        assert install_env.is_ephemeral_path(case) == _is_ephemeral_plugin_path(case), (
            case
        )


def test_ephemeral_dev_checkout_refuses_with_durable_hint(
    tmp_path: Path, monkeypatch: object
) -> None:
    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    env = kit.make_env(tmp_path)
    ws_root = Path(env["SASE_WORKSPACE_ROOT"])
    checkout = kit.make_checkout(ws_root / "proj", name="sase")
    durable = kit.make_checkout(tmp_path / "durable")
    tool_dir, bin_dir = kit.make_tool_env(
        tmp_path,
        host=("editable", str(durable)),
        checkout=checkout,
    )
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    exit_code, out, err = kit.run_entry(
        entry,
        ["dev", "-n"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 2
    assert out == ""
    assert "durable sase checkout" in err
    assert f"just -f {durable}/Justfile install-dev" in err


def test_ephemeral_core_checkout_refuses(tmp_path: Path, monkeypatch: object) -> None:
    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    env = kit.make_env(tmp_path)
    ws_root = Path(env["SASE_WORKSPACE_ROOT"])
    checkout = kit.make_checkout(tmp_path)
    ephemeral_core = ws_root / "proj" / "sase-core"
    ephemeral_core.mkdir(parents=True, exist_ok=True)
    tool_dir, bin_dir = kit.make_tool_env(tmp_path, checkout=checkout)
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    env_ephemeral_core = kit.make_env(tmp_path, SASE_CORE_DIR=str(ephemeral_core))
    exit_code, out, err = kit.run_entry(
        entry,
        ["dev", "-n"],
        env=env_ephemeral_core,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 2
    assert out == ""
    assert "durable sase checkout" in err


def test_pypi_mode_has_no_durable_guard(tmp_path: Path, monkeypatch: object) -> None:
    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    env = kit.make_env(tmp_path)
    ws_root = Path(env["SASE_WORKSPACE_ROOT"])
    checkout = kit.make_checkout(ws_root / "proj", name="sase")
    tool_dir, bin_dir = kit.make_tool_env(tmp_path, checkout=checkout)
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    exit_code, out, _ = kit.run_entry(
        entry,
        ["pypi", "-n"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 0
    assert "just install" in out
