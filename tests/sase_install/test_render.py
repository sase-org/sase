"""Panel snapshots, JSON shape, and summary-line tests (fixed width, no color)."""

from __future__ import annotations

import json
from pathlib import Path

import tests._sase_install_testkit as kit
from tests._sase_install_testkit import install_plan, install_state, install_ui


def _flip_plan(tmp_path: Path) -> install_plan.InstallPlan:
    """A PyPI flip plan: editable host+plugins+local core move to PyPI."""
    checkout = kit.make_checkout(tmp_path)
    github = tmp_path / "sase-github"
    github.mkdir()
    chops = tmp_path / "bugyi-chops"
    chops.mkdir()
    tool_dir, _ = kit.make_tool_env(
        tmp_path,
        host=("editable", str(checkout)),
        plugins=(
            ("sase-github", "editable", str(github)),
            ("bugyi-chops", "editable", str(chops)),
        ),
        core=("local", "0.37.0"),
        checkout=checkout,
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI(
        {
            "sase": "0.17.1",
            "sase-core-rs": "0.35.4",
            "sase-github": "0.4.2",
        },
        unpublished=("bugyi-chops",),
    )
    return install_plan.build_plan(
        options=install_plan.PlanOptions(mode="pypi"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )


def _dev_plan(tmp_path: Path) -> install_plan.InstallPlan:
    checkout = kit.make_checkout(tmp_path)
    tool_dir, _ = kit.make_tool_env(tmp_path, checkout=checkout)
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    return install_plan.build_plan(
        options=install_plan.PlanOptions(mode="dev"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )


def test_flip_panel_fixed_width_no_color(tmp_path: Path) -> None:
    plan = _flip_plan(tmp_path)
    text = install_ui.render_plan_panel(plan, width=80, color=False, home="/home/u")
    lines = text.splitlines()
    assert len(lines) >= 8
    assert all(len(line) <= 80 for line in lines)
    assert lines[0].startswith("\u256d\u2500 just install \u00b7 your `sase`")
    assert lines[-1].startswith("\u2570") and lines[-1].endswith("\u256f")
    assert "Replaces your editable install" in text
    assert "\u26a0 downgrade" in text
    assert "stays editable \u00b7 not on PyPI" in text
    assert "\x1b[" not in text


def test_dev_panel_fixed_width_no_color(tmp_path: Path) -> None:
    plan = _dev_plan(tmp_path)
    assert plan.noop  # host keep + local core keep + python kept
    text = install_ui.render_plan_panel(plan, width=80, color=False, home="/home/u")
    lines = text.splitlines()
    assert all(len(line) <= 80 for line in lines)
    assert "just install-dev" in lines[0]
    assert "python" in text and "(kept)" in text
    assert "currently: dev" in text
    assert "\x1b[" not in text


def test_flip_panel_golden() -> None:
    """The exact PyPI-flip panel (the plan's design contract, pinned)."""
    receipt = install_state.ToolReceipt(
        primary=install_state.InstallRequirement(
            name="sase", editable="/home/u/proj/sase"
        ),
        plugins=(
            install_state.InstallRequirement(
                name="sase-github", editable="/home/u/proj/sase-github"
            ),
            install_state.InstallRequirement(
                name="bugyi-chops", editable="/home/u/proj/bugyi-chops"
            ),
        ),
    )
    state = install_state.InstallState(
        tool_dir="/home/u/.local/share/uv/tools/sase",  # type: ignore[arg-type]
        bin_dir="/home/u/.local/share/uv/tools/sase/bin",  # type: ignore[arg-type]
        env_exists=True,
        receipt=receipt,
        python_version="3.14.7",
        dists=(
            install_state.InstalledDist(
                name="sase",
                version="0.17.1",
                editable_path="/home/u/proj/sase",
            ),
            install_state.InstalledDist(name="sase-core-rs", version="0.37.0"),
            install_state.InstalledDist(
                name="sase-github",
                version="0.2.20",
                editable_path="/home/u/proj/sase-github",
            ),
            install_state.InstalledDist(
                name="bugyi-chops",
                version="0.9.0",
                editable_path="/home/u/proj/bugyi-chops",
            ),
        ),
        mode="dev",
    )
    env = {
        "HOME": "/home/u",
        "SASE_HOME": "/home/u/.sase",
        "SASE_WORKSPACE_ROOT": "/home/u/ws",
        "NO_COLOR": "1",
        "COLUMNS": "80",
        "PATH": "/usr/bin",
    }
    lookup = kit.FakePyPI(
        {"sase": "0.17.1", "sase-core-rs": "0.35.4", "sase-github": "0.4.2"},
        unpublished=("bugyi-chops",),
    )
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="pypi"),
        state=state,
        checkout_root="/home/u/proj/sase",
        core_dir="/home/u/proj/sase-core",
        env=env,
        pypi_lookup=lookup,
    )
    text = install_ui.render_plan_panel(plan, width=80, color=False, home="/home/u")
    assert text == "\n".join(
        [
            "╭─ just install · your `sase` → PyPI ──────────────────────────"
            "────────────────╮",
            "│ sase         editable 0.17.1  →  0.17.1 PyPI                   "
            "             │",
            "│ plugins      editable 0.2.20  →  0.4.2 PyPI                    "
            "             │",
            "│              ~/proj/bugyi-chops · 0.9.0  →  stays editable · no"
            "t on PyPI    │",
            "│ sase-core-rs 0.37.0 local build  →  0.35.4 PyPI   ⚠ downgrade  "
            "            │",
            "│ python       3.14.7 (kept)                                     "
            "             │",
            "│ target       ~/.local/share/uv/tools/sase  currently: dev      "
            "             │",
            "│              ⚠ Replaces your editable install from ~/proj/sase."
            "            │",
            "╰──────────────────────────────────────────────────────────────"
            "────────────────╯",
        ]
    )


def test_panel_width_clamp(tmp_path: Path) -> None:
    plan = _dev_plan(tmp_path)
    narrow = install_ui.render_plan_panel(plan, width=20, color=False)
    assert all(len(line) <= 60 for line in narrow.splitlines())
    wide = install_ui.render_plan_panel(plan, width=1000, color=False)
    assert all(len(line) <= 100 for line in wide.splitlines())


def test_panel_color_emits_ansi(tmp_path: Path) -> None:
    plan = _flip_plan(tmp_path)
    text = install_ui.render_plan_panel(plan, width=80, color=True, home="/home/u")
    assert "\x1b[36m" in text  # cyan borders
    assert "\x1b[33m" in text  # yellow consequential rows


def test_json_document_shape(tmp_path: Path) -> None:
    plan = _flip_plan(tmp_path)
    doc = json.loads(install_ui.render_json(plan, dry_run=True, outcome="plan"))
    assert doc["schema_version"] == 1
    assert doc["command"] == "just install"
    assert doc["mode"] == "pypi"
    assert doc["dry_run"] is True
    assert doc["outcome"] == "plan"
    assert doc["consequential"] is True
    assert doc["noop"] is False
    assert doc["error"] is None
    assert doc["log_path"] is None
    assert isinstance(doc["warnings"], list)
    assert set(doc["python"]) == {"current", "target", "requested", "change"}
    assert set(doc["target"]) == {"path", "current_mode"}
    assert isinstance(doc["steps"], list) and "swap" in doc["steps"]
    assert doc["commands"][0]["purpose"] == "swap"
    assert doc["commands"][0]["argv"] == list(plan.swap_argv)
    by_name = {pkg["name"]: pkg for pkg in doc["packages"]}
    assert set(by_name) == {"sase", "sase-github", "bugyi-chops", "sase-core-rs"}
    host = by_name["sase"]
    assert host["role"] == "host"
    assert host["change"] == "to-pypi"
    assert host["consequential"] is True
    assert set(host["current"]) == {"source", "version", "path"}
    assert host["target"]["source"] == "pypi"


def test_json_dev_steps_include_prepare_and_reapply(tmp_path: Path) -> None:
    plan = _dev_plan(tmp_path)
    doc = json.loads(install_ui.render_json(plan, dry_run=True, outcome="plan"))
    assert doc["mode"] == "dev"
    assert "prepare" in doc["steps"]
    assert "re-apply" in doc["steps"]


def test_summary_and_noop_lines(tmp_path: Path) -> None:
    flip = _flip_plan(tmp_path)
    summary = install_ui.render_summary_line(flip, dry_run=True)
    assert summary.startswith("just install: ")
    assert "consequential" in summary
    assert summary.endswith("dry run, nothing changed")
    assert "3 changes" in summary

    checkout = kit.make_checkout(tmp_path)
    tool_dir, _ = kit.make_tool_env(
        tmp_path,
        host=("pypi", "0.17.1"),
        core=("pypi", "0.35.4"),
        checkout=checkout,
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.35.4"})
    noop_plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="pypi"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )
    assert noop_plan.noop
    noop_line = install_ui.render_noop_line(noop_plan)
    assert noop_line == (
        "\u2713 sase 0.17.1 from PyPI is already installed "
        "\u2014 nothing to do (--force reinstalls)"
    )
    assert install_ui.render_summary_line(noop_plan, dry_run=True) == noop_line
