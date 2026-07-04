from __future__ import annotations

from pathlib import Path

from sase.mode_switch.plan import plan_mode_switch
from sase.uv_tool.detect import UvToolInstall
from sase.version.inventory import RuntimeVersionInventory, VersionPackageRecord

_PYPI_RECEIPT = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-github" },
]
"""

_DEV_RECEIPT = """
[tool]
requirements = [
    { name = "sase", editable = "/src/sase" },
    { name = "sase-github", editable = "/src/sase-github" },
    { name = "sase-github" },
]
"""


def _install(tmp_path: Path, receipt_text: str) -> UvToolInstall:
    tool = tmp_path / "tool" / "sase"
    tool.mkdir(parents=True)
    receipt = tool / "uv-receipt.toml"
    receipt.write_text(receipt_text, encoding="utf-8")
    return UvToolInstall(
        uv_path="/usr/bin/uv",
        tool_dir=tmp_path / "tool",
        sase_dir=tool,
        receipt_path=receipt,
    )


def _record(name: str, role: str, version: str) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role=role,  # type: ignore[arg-type]
        display_version=version,
        distribution_version=version,
        source_version=None,
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root=None,
        distribution_location=None,
        install_type="wheel",
        git=None,
    )


def _inventory() -> RuntimeVersionInventory:
    return RuntimeVersionInventory(
        executable="sase",
        python_executable="/venv/bin/python",
        python_version="3.12",
        packages=(
            _record("sase", "host", "0.8.0"),
            _record("sase-core-rs", "core", "0.3.1"),
            _record("sase-github", "plugin", "0.1.0"),
        ),
    )


def test_plan_to_dev_builds_editable_reinstall_command(tmp_path: Path) -> None:
    plan = plan_mode_switch(
        _install(tmp_path, _PYPI_RECEIPT),
        target_mode="dev",
        config={"update": {"dev_root": str(tmp_path / "dev")}},
        inventory_fn=_inventory,
        which_fn=lambda name: f"/usr/bin/{name}",
    )

    assert plan.current_mode == "managed"
    assert plan.target_mode == "dev"
    assert [package.name for package in plan.packages] == [
        "sase",
        "sase-core-rs",
        "sase-github",
    ]
    uv_command = next(
        command for command in plan.commands if command.kind == "uv_tool_install"
    )
    assert uv_command.command[:7] == (
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "--force",
        "--reinstall",
    )
    assert "--editable" in uv_command.command
    assert str(tmp_path / "dev" / "sase") in uv_command.command
    assert "--with-editable" in uv_command.command
    assert str(tmp_path / "dev" / "sase-github") in uv_command.command


def test_plan_to_pypi_swaps_editables_for_index_specs(tmp_path: Path) -> None:
    plan = plan_mode_switch(
        _install(tmp_path, _DEV_RECEIPT),
        target_mode="pypi",
        config={"update": {"dev_root": str(tmp_path / "dev")}},
        inventory_fn=_inventory,
        latest_fn=lambda name: {"sase": "0.8.1", "sase-core-rs": "0.3.2"}.get(name),
        which_fn=lambda name: f"/usr/bin/{name}",
    )

    assert plan.current_mode == "dev"
    uv_command = plan.commands[0]
    assert uv_command.command == (
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "--force",
        "--reinstall",
        "sase",
        "--with",
        "sase-github",
    )
    assert plan.packages[0].target_version == "0.8.1"
    assert plan.packages[1].target_version == "0.3.2"


def test_plan_current_mode_is_noop(tmp_path: Path) -> None:
    plan = plan_mode_switch(
        _install(tmp_path, _PYPI_RECEIPT),
        target_mode="pypi",
        config={},
        inventory_fn=_inventory,
        which_fn=lambda name: f"/usr/bin/{name}",
    )

    assert plan.changed is False
    assert plan.commands == ()
