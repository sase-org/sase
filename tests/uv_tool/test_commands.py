"""Tests for the pure ``uv`` argv builders."""

from __future__ import annotations

from sase.uv_tool.commands import (
    build_install,
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


def test_build_install_with_added_plugin() -> None:
    argv = build_install(parse_receipt(_PYPI_RECEIPT), add="sase-amd")
    assert argv[-2:] == ["--with", "sase-amd"]


def test_build_install_with_added_requirement_object() -> None:
    argv = build_install(
        parse_receipt(_PYPI_RECEIPT), add=Requirement(name="sase-amd", specifier=">=1")
    )
    assert argv[-2:] == ["--with", "sase-amd>=1"]


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
