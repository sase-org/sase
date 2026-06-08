"""Tests for the ``sase version`` command."""

from __future__ import annotations

import argparse
import json
from io import StringIO
from typing import Literal

import pytest
from rich.console import Console

from sase.main import version_handler
from sase.main.parser import create_parser
from sase.version.inventory import (
    GitVersionMetadata,
    RuntimeVersionInventory,
    VersionPackageRecord,
)
from sase.version.render import (
    render_runtime_version_inventory,
    runtime_version_inventory_to_json_payload,
)


def _record(
    *,
    name: str,
    role: Literal["host", "core", "plugin"],
    version: str,
    code_directory: str | None,
    source_root: str | None = None,
    import_path: str | None = None,
    install_type: Literal["editable", "wheel", "unknown"] = "editable",
    git: GitVersionMetadata | None = None,
    plugin_signals: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role=role,
        display_version=version,
        distribution_version="0.1.0",
        source_version="0.1.3" if install_type == "editable" else None,
        import_module=name.replace("-", "_"),
        import_path=import_path,
        code_directory=code_directory,
        source_root=source_root,
        distribution_location="/venv/lib/python3.12/site-packages",
        install_type=install_type,
        git=git,
        plugin_signals=plugin_signals,
        warnings=warnings,
    )


def _inventory() -> RuntimeVersionInventory:
    git = GitVersionMetadata(
        root="/repo/sase",
        commit="abcdef123456",
        short_commit="abcdef123",
        tag="v0.1.3",
        distance=2,
        dirty=False,
    )
    return RuntimeVersionInventory(
        executable="/home/bryan/.local/bin/sase",
        python_executable="/home/bryan/.local/share/uv/tools/sase/bin/python",
        python_version="3.12.8",
        packages=(
            _record(
                name="sase",
                role="host",
                version="0.1.3+2.gabcdef123",
                code_directory="/repo/sase/src/sase",
                source_root="/repo/sase",
                import_path="/repo/sase/src/sase",
                git=git,
            ),
            _record(
                name="sase-core-rs",
                role="core",
                version="0.1.1",
                code_directory="/repo/sase-core",
                source_root="/repo/sase-core",
                import_path="/venv/lib/python3.12/site-packages/sase_core_rs.abi3.so",
            ),
            _record(
                name="sase-github",
                role="plugin",
                version="0.1.0",
                code_directory="/repo/sase-github/src/sase_github",
                source_root="/repo/sase-github",
                import_path="/repo/sase-github/src/sase_github",
                plugin_signals=(
                    "entry_point:sase_vcs:github=sase_github.plugin:Plugin",
                ),
            ),
        ),
    )


def _render(inventory: RuntimeVersionInventory, *, verbose: bool = False) -> str:
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=180)

    render_runtime_version_inventory(inventory, verbose=verbose, console=console)

    return output.getvalue()


def test_parser_accepts_version_flags() -> None:
    parser = create_parser()

    short_args = parser.parse_args(["version", "-j", "-v"])
    assert short_args.command == "version"
    assert short_args.json is True
    assert short_args.verbose is True

    long_args = parser.parse_args(["version", "--json", "--verbose"])
    assert long_args.command == "version"
    assert long_args.json is True
    assert long_args.verbose is True


def test_version_top_level_help_entry_is_sorted() -> None:
    parser = create_parser()
    subparser_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    commands = list(subparser_action.choices)

    assert "version" in commands
    assert commands == sorted(commands)


def test_human_output_includes_package_version_and_code_directory() -> None:
    text = _render(_inventory())

    assert "SASE Runtime" in text
    assert "/home/bryan/.local/bin/sase" in text
    assert "sase" in text
    assert "0.1.3+2.gabcdef123" in text
    assert "/repo/sase/src/sase" in text
    assert "sase-core-rs" in text
    assert "/repo/sase-core" in text


def test_verbose_output_includes_audit_fields_and_plugin_signals() -> None:
    text = _render(_inventory(), verbose=True)

    assert "Package Audit" in text
    assert "editable" in text
    assert "abcdef123" in text
    assert "tag v0.1.3" in text
    assert "distance" in text
    assert "Plugin Signals" in text
    assert "entry_point:sase_vcs:github=sase_github.plugin:Plugin" in text


def test_warning_rendering_for_incomplete_package_records() -> None:
    inventory = RuntimeVersionInventory(
        executable="/bin/sase",
        python_executable="/bin/python",
        python_version="3.12.8",
        packages=(
            _record(
                name="sase-broken",
                role="plugin",
                version="9.9.9",
                code_directory=None,
                install_type="wheel",
                warnings=(
                    "falling back to distribution location for sase-broken; "
                    "import module path could not be resolved",
                ),
            ),
        ),
    )

    text = _render(inventory)

    assert "WARN" in text
    assert "Warnings" in text
    assert "sase-broken: falling back to distribution location" in text


def test_json_payload_has_schema_and_representative_fields() -> None:
    payload = runtime_version_inventory_to_json_payload(_inventory())

    assert payload["schema_version"] == 1
    assert payload["runtime"] == {
        "executable": "/home/bryan/.local/bin/sase",
        "python_executable": "/home/bryan/.local/share/uv/tools/sase/bin/python",
        "python_version": "3.12.8",
    }
    packages = payload["packages"]
    assert [record["name"] for record in packages] == [
        "sase",
        "sase-core-rs",
        "sase-github",
    ]
    assert packages[0]["git"]["short_commit"] == "abcdef123"
    assert packages[2]["plugin_signals"] == [
        "entry_point:sase_vcs:github=sase_github.plugin:Plugin"
    ]
    assert "distribution_version" in packages[0]
    assert "source_version" in packages[0]
    assert "warnings" in packages[0]


def test_handler_json_output_uses_collector_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        version_handler,
        "collect_runtime_version_inventory",
        _inventory,
    )

    code = version_handler.handle_version_command(
        argparse.Namespace(json=True, verbose=False)
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["packages"][0]["name"] == "sase"
