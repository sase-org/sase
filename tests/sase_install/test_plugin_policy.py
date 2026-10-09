"""Plugin source-policy tests: the receipt picks plugins, the mode sources them."""

from __future__ import annotations

from pathlib import Path

import tests._sase_install_testkit as kit
from tests._sase_install_testkit import install_plan, install_state


def _dev_plan(
    tmp_path: Path,
    *,
    plugins: tuple[tuple[str, str, str | None], ...] = (),
    keep_sources: bool = False,
    with_specs: tuple[str, ...] = (),
    versions: dict[str, str] | None = None,
    host: tuple[str, str | None] | None = ("editable", None),
    core: tuple[str, str | None] | None = ("local", "0.37.0"),
) -> install_plan.InstallPlan:
    checkout = kit.make_checkout(tmp_path)
    tool_dir, _ = kit.make_tool_env(
        tmp_path, host=host, plugins=plugins, core=core, checkout=checkout
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI(
        {"sase": "0.17.1", "sase-core-rs": "0.37.0", **(versions or {})}
    )
    return install_plan.build_plan(
        options=install_plan.PlanOptions(
            mode="dev", keep_plugin_sources=keep_sources, with_specs=with_specs
        ),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )


def _rows_by_name(
    plan: install_plan.InstallPlan,
) -> dict[str, install_plan.PlanRow]:
    return {row.name: row for row in plan.rows}


def test_dev_keeps_durable_editable_plugin(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "sase-github"
    plugin_dir.mkdir()
    plan = _dev_plan(tmp_path, plugins=(("sase-github", "editable", str(plugin_dir)),))
    row = _rows_by_name(plan)["sase-github"]
    assert row.kind == "keep"
    assert not row.consequential
    assert row.target.kind == "editable"
    assert row.target.path == str(plugin_dir)


def test_dev_prefers_durable_sibling_over_pypi(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    sibling = kit.make_sibling(tmp_path, "sase-github")
    tool_dir, _ = kit.make_tool_env(
        tmp_path,
        plugins=(("sase-github", "pypi", "0.2.0"),),
        checkout=checkout,
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI(
        {"sase": "0.17.1", "sase-core-rs": "0.37.0", "sase-github": "0.4.2"}
    )
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="dev"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )
    row = _rows_by_name(plan)["sase-github"]
    assert row.kind == "to-editable"
    assert row.consequential
    assert row.target.path == str(sibling)


def test_dev_falls_back_to_pypi_without_sibling(tmp_path: Path) -> None:
    plan = _dev_plan(
        tmp_path,
        plugins=(("sase-github", "pypi", "0.2.0"),),
        versions={"sase-github": "0.4.2"},
    )
    row = _rows_by_name(plan)["sase-github"]
    assert row.kind == "upgrade"
    assert not row.consequential
    assert row.target.kind == "pypi"
    assert row.target.version == "0.4.2"


def test_dev_ephemeral_plugin_resolves_durable(tmp_path: Path) -> None:
    env = kit.make_env(tmp_path)
    ws_root = Path(env["SASE_WORKSPACE_ROOT"])
    ephemeral = ws_root / "proj" / "sase-github"
    ephemeral.mkdir(parents=True)
    plan = _dev_plan(tmp_path, plugins=(("sase-github", "editable", str(ephemeral)),))
    row = _rows_by_name(plan)["sase-github"]
    assert row.kind == "to-pypi"
    assert row.consequential
    assert any("ephemeral or missing" in w for w in plan.warnings)


def test_dev_keep_plugin_sources(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "sase-github"
    plugin_dir.mkdir()
    plan = _dev_plan(
        tmp_path,
        plugins=(
            ("sase-github", "editable", str(plugin_dir)),
            ("sase-telegram", "pypi", "0.4.26"),
        ),
        keep_sources=True,
        versions={"sase-github": "0.4.2", "sase-telegram": "0.4.26"},
    )
    rows = _rows_by_name(plan)
    assert rows["sase-github"].kind == "keep"
    assert rows["sase-github"].note == "kept source"
    assert rows["sase-telegram"].kind == "keep"
    assert rows["sase-telegram"].note == "kept source"


def test_pypi_moves_everything_to_pypi(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    plugin_dir = tmp_path / "sase-github"
    plugin_dir.mkdir()
    tool_dir, _ = kit.make_tool_env(
        tmp_path,
        plugins=(("sase-github", "editable", str(plugin_dir)),),
        checkout=checkout,
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI(
        {"sase": "0.17.1", "sase-core-rs": "0.37.0", "sase-github": "0.4.2"}
    )
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="pypi"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )
    rows = _rows_by_name(plan)
    assert rows["sase"].kind == "to-pypi"
    assert rows["sase"].consequential
    assert rows["sase-github"].kind == "to-pypi"
    assert rows["sase-core-rs"].kind == "to-pypi"


def test_pypi_unpublished_plugin_stays_editable(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    plugin_dir = tmp_path / "bugyi-chops"
    plugin_dir.mkdir()
    tool_dir, _ = kit.make_tool_env(
        tmp_path,
        plugins=(("bugyi-chops", "editable", str(plugin_dir)),),
        checkout=checkout,
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI(
        {"sase": "0.17.1", "sase-core-rs": "0.37.0"},
        unpublished=("bugyi-chops",),
    )
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="pypi"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )
    row = _rows_by_name(plan)["bugyi-chops"]
    assert row.kind == "keep"
    assert not row.consequential
    assert "not on PyPI" in row.note
    assert row.target.kind == "editable"


def test_pypi_unpublished_without_source_removes(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    tool_dir, bin_dir = kit.make_tool_env(tmp_path, checkout=checkout)
    kit.write_receipt(
        tool_dir,
        [
            {"name": "sase", "specifier": "==0.17.1"},
            {"name": "ghost-plugin", "specifier": ">=1.0"},
        ],
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=bin_dir)
    lookup = kit.FakePyPI(
        {"sase": "0.17.1", "sase-core-rs": "0.37.0"},
        unpublished=("ghost-plugin",),
    )
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="pypi"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )
    row = _rows_by_name(plan)["ghost-plugin"]
    assert row.kind == "remove"
    assert row.consequential
    assert plan.consequential


def test_offline_pypi_keeps_sources_with_warning(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    plugin_dir = tmp_path / "sase-github"
    plugin_dir.mkdir()
    tool_dir, _ = kit.make_tool_env(
        tmp_path,
        host=("pypi", "0.17.1"),
        plugins=(("sase-github", "editable", str(plugin_dir)),),
        core=("pypi", "0.37.0"),
        checkout=checkout,
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI(unreachable=("sase", "sase-github", "sase-core-rs"))
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="pypi"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )
    rows = _rows_by_name(plan)
    assert rows["sase-github"].kind == "keep"
    assert rows["sase-github"].target.kind == "editable"
    assert not rows["sase-github"].consequential
    assert any("could not reach PyPI" in w for w in plan.warnings)


def test_with_adds_new_plugin(tmp_path: Path) -> None:
    plan = _dev_plan(
        tmp_path,
        with_specs=("sase-github>=0.2.5",),
        versions={"sase-github": "0.4.2"},
    )
    row = _rows_by_name(plan)["sase-github"]
    assert row.kind == "add"
    assert not row.consequential
    assert any("--with" in arg for arg in plan.swap_argv)


def test_with_malformed_spec_warns(tmp_path: Path) -> None:
    plan = _dev_plan(tmp_path, with_specs=("",))
    assert any("malformed --with" in w for w in plan.warnings)


def test_with_host_name_is_ignored_with_warning(tmp_path: Path) -> None:
    plan = _dev_plan(tmp_path, with_specs=("sase==0.17.1",))
    assert "sase" not in [row.name for row in plan.rows if row.role == "plugin"]
    assert any("--with entry" in w for w in plan.warnings)


def test_fresh_install_adds_host_only(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    tool_dir = tmp_path / "tool" / "sase"
    (tool_dir / "bin").mkdir(parents=True)
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    assert state.receipt is None
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="pypi", with_specs=("sase-github",)),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )
    assert plan.fresh
    assert not plan.noop
    assert not plan.consequential
    rows = _rows_by_name(plan)
    assert rows["sase"].kind == "add"
    assert rows["sase-github"].kind == "add"


def test_fresh_env_without_receipt_warns_force(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    tool_dir, _ = kit.make_tool_env(tmp_path, checkout=checkout, with_receipt=False)
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    assert state.env_exists and state.receipt is None
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="pypi"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )
    assert plan.force_foreign_env
    assert any("--force" in w for w in plan.warnings)


def test_version_pin_targets_exact_release(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    tool_dir, _ = kit.make_tool_env(
        tmp_path,
        host=("pypi", "0.17.1"),
        core=("pypi", "0.37.0"),
        checkout=checkout,
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI({"sase": "0.18.0", "sase-core-rs": "0.37.0"})
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="pypi", version="0.17.1"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )
    row = _rows_by_name(plan)["sase"]
    assert row.kind == "keep"
    assert row.target.version == "0.17.1"
    assert "sase==0.17.1" in plan.swap_argv


def test_index_upgrade_and_downgrade(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    tool_dir, _ = kit.make_tool_env(
        tmp_path,
        host=("pypi", "0.17.1"),
        core=("pypi", "0.37.0"),
        plugins=(("sase-github", "pypi", "0.2.0"), ("sase-telegram", "pypi", "0.5.0")),
        checkout=checkout,
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI(
        {
            "sase": "0.17.1",
            "sase-core-rs": "0.37.0",
            "sase-github": "0.4.2",
            "sase-telegram": "0.4.26",
        }
    )
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="pypi"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )
    rows = _rows_by_name(plan)
    assert rows["sase-github"].kind == "upgrade"
    assert not rows["sase-github"].consequential
    assert rows["sase-telegram"].kind == "downgrade"
    assert rows["sase-telegram"].consequential
