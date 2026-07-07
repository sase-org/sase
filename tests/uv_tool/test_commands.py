"""Tests for the pure ``uv`` argv builders."""

from __future__ import annotations

from sase.uv_tool.commands import (
    build_install,
    build_install_many,
    build_reinstall_set,
    build_uninstall,
    build_upgrade_all,
    build_upgrade_packages,
)
from sase.uv_tool.receipt import Requirement, parse_receipt

_DEV_RECEIPT = """
[tool]
requirements = [
    { name = "sase", editable = "/home/u/sase" },
    { name = "sase-github", editable = "/home/u/sase-github" },
    { name = "sase-telegram" },
    { name = "sase-github" },
]
"""

_PYPI_RECEIPT = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-edge", git = "https://github.com/acme/sase-edge", rev = "v1" },
]
"""


def test_build_upgrade_all_default() -> None:
    assert build_upgrade_all() == ["uv", "tool", "upgrade", "sase"]


def test_build_upgrade_all_with_color() -> None:
    assert build_upgrade_all(color="never") == [
        "uv",
        "tool",
        "upgrade",
        "--color",
        "never",
        "sase",
    ]


def test_build_install_reconstructs_editable_set() -> None:
    argv = build_install(parse_receipt(_DEV_RECEIPT))
    assert argv == [
        "uv",
        "tool",
        "install",
        "--editable",
        "/home/u/sase",
        "--with-editable",
        "/home/u/sase-github",
        "--with",
        "sase-telegram",
    ]


def test_build_install_appends_overrides_flag() -> None:
    argv = build_install(parse_receipt(_DEV_RECEIPT), overrides="/tmp/overrides.txt")
    assert argv[-2:] == ["--overrides", "/tmp/overrides.txt"]


def test_build_install_with_color_flag() -> None:
    argv = build_install(parse_receipt(_PYPI_RECEIPT), color="always")
    assert argv[:5] == ["uv", "tool", "install", "--color", "always"]


def test_build_install_bare_primary_from_index() -> None:
    argv = build_install(parse_receipt(_PYPI_RECEIPT))
    # Non-editable primary renders as a bare positional package.
    assert argv[:4] == ["uv", "tool", "install", "sase"]


def test_build_install_renders_git_plugin() -> None:
    argv = build_install(parse_receipt(_PYPI_RECEIPT))
    assert "--with" in argv
    assert "git+https://github.com/acme/sase-edge@v1" in argv


def test_build_reinstall_set_for_mode_switch() -> None:
    argv = build_reinstall_set(
        Requirement(name="sase", editable="/src/sase"),
        (
            Requirement(name="sase-github", editable="/src/sase-github"),
            Requirement(name="sase-telegram"),
        ),
        color="never",
    )

    assert argv == [
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "--force",
        "--reinstall",
        "--editable",
        "/src/sase",
        "--with-editable",
        "/src/sase-github",
        "--with",
        "sase-telegram",
    ]


def test_build_install_many_appends_overrides_flag() -> None:
    argv = build_install_many(
        parse_receipt(_PYPI_RECEIPT),
        add=(Requirement(name="sase-amd"),),
        overrides="/tmp/overrides.txt",
    )
    assert argv[-2:] == ["--overrides", "/tmp/overrides.txt"]


def test_build_reinstall_set_appends_overrides_flag() -> None:
    argv = build_reinstall_set(
        Requirement(name="sase", editable="/src/sase"),
        overrides="/tmp/overrides.txt",
    )
    assert argv[-2:] == ["--overrides", "/tmp/overrides.txt"]


def test_build_install_with_added_plugin() -> None:
    argv = build_install(parse_receipt(_PYPI_RECEIPT), add="sase-amd")
    assert argv[-2:] == ["--with", "sase-amd"]


def test_build_install_with_added_requirement_object() -> None:
    argv = build_install(
        parse_receipt(_PYPI_RECEIPT), add=Requirement(name="sase-amd", specifier=">=1")
    )
    assert argv[-2:] == ["--with", "sase-amd>=1"]


def test_build_uninstall_removes_one_plugin() -> None:
    # Removing one plugin re-injects the full set minus the target; primary and
    # the remaining plugin are preserved.
    argv = build_uninstall(parse_receipt(_PYPI_RECEIPT), remove="sase-edge")
    assert argv == ["uv", "tool", "install", "sase"]


def test_build_uninstall_preserves_other_plugins() -> None:
    argv = build_uninstall(parse_receipt(_DEV_RECEIPT), remove="sase-telegram")
    assert argv == [
        "uv",
        "tool",
        "install",
        "--editable",
        "/home/u/sase",
        "--with-editable",
        "/home/u/sase-github",
    ]


def test_build_uninstall_removes_all_dev_duplicate_entries() -> None:
    # The dev receipt lists sase-github twice (editable + bare index); uninstall
    # must drop *both* raw rows, not just the first deduped entry.
    argv = build_uninstall(parse_receipt(_DEV_RECEIPT), remove="sase-github")
    assert "/home/u/sase-github" not in argv
    assert "sase-github" not in argv
    assert argv == [
        "uv",
        "tool",
        "install",
        "--editable",
        "/home/u/sase",
        "--with",
        "sase-telegram",
    ]


def test_build_uninstall_normalizes_target_name() -> None:
    # A differently-cased / underscored target still matches the receipt entry.
    argv = build_uninstall(parse_receipt(_PYPI_RECEIPT), remove="SASE_EDGE")
    assert argv == ["uv", "tool", "install", "sase"]


def test_build_uninstall_with_color() -> None:
    argv = build_uninstall(
        parse_receipt(_PYPI_RECEIPT), remove="sase-edge", color="never"
    )
    assert argv[3:5] == ["--color", "never"]


def test_build_uninstall_appends_overrides_flag() -> None:
    argv = build_uninstall(
        parse_receipt(_DEV_RECEIPT),
        remove="sase-telegram",
        overrides="/tmp/overrides.txt",
    )
    assert argv[-2:] == ["--overrides", "/tmp/overrides.txt"]


def test_build_upgrade_packages_appends_upgrade_flags() -> None:
    argv = build_upgrade_packages(
        parse_receipt(_DEV_RECEIPT), ["sase-github", "sase-telegram"]
    )
    assert argv[:3] == ["uv", "tool", "install"]
    assert argv[-4:] == [
        "--upgrade-package",
        "sase-github",
        "--upgrade-package",
        "sase-telegram",
    ]


def test_build_upgrade_packages_with_color() -> None:
    argv = build_upgrade_packages(
        parse_receipt(_PYPI_RECEIPT), ["sase-edge"], color="never"
    )
    assert argv[3:5] == ["--color", "never"]
    assert argv[-2:] == ["--upgrade-package", "sase-edge"]


def test_build_upgrade_packages_passes_overrides_to_install() -> None:
    argv = build_upgrade_packages(
        parse_receipt(_DEV_RECEIPT),
        ["sase-github"],
        overrides="/tmp/overrides.txt",
    )
    assert argv[-4:] == [
        "--overrides",
        "/tmp/overrides.txt",
        "--upgrade-package",
        "sase-github",
    ]
