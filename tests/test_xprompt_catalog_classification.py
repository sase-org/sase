from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.xprompt.catalog import _classify

from tests._xprompt_catalog_helpers import make_xprompt


def test_classify_builtin(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    source = pkg_dir / "foo.md"
    source.write_text("x")

    xp = make_xprompt("foo", source_path=str(source))

    with (
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir", return_value=pkg_dir
        ),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        entry = _classify(xp, project=None)

    assert entry.bucket == "built-in"
    assert entry.project is None


def test_classify_default_xprompts_builtin(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg"
    default_dir = tmp_path / "default_xprompts"
    default_dir.mkdir()
    source = default_dir / "research_swarm.md"
    source.write_text("x")

    xp = make_xprompt("research_swarm", source_path=str(source))

    with (
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=pkg_dir,
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_default_xprompts_dir",
            return_value=default_dir,
        ),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        entry = _classify(xp, project=None)

    assert entry.bucket == "built-in"
    assert entry.project is None


def test_classify_plugin_source() -> None:
    xp = make_xprompt("foo", source_path="plugin:some_module/foo.md")
    with (
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=Path("/nonexistent"),
        ),
    ):
        entry = _classify(xp, project=None)
    assert entry.bucket == "plugin"


def test_classify_config_label() -> None:
    xp = make_xprompt("foo", source_path="config")
    with (
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=Path("/nonexistent"),
        ),
    ):
        entry = _classify(xp, project=None)
    assert entry.bucket == "config"


def test_classify_project_explicit(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    xp = make_xprompt("foo", source_path=str(ws / "sase.yml"))
    with (
        patch(
            "sase.xprompt.catalog.get_known_project_workspaces",
            return_value={"myproj": ws},
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=Path("/nonexistent"),
        ),
    ):
        entry = _classify(xp, project="myproj")
    assert entry.bucket == "project"
    assert entry.project == "myproj"


def test_classify_project_inferred_from_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "proj-ws"
    ws.mkdir()
    source = ws / ".xprompts" / "bar.md"
    source.parent.mkdir(parents=True)
    source.write_text("x")
    xp = make_xprompt("bar", source_path=str(source))
    with (
        patch(
            "sase.xprompt.catalog.get_known_project_workspaces",
            return_value={"inferred": ws},
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=Path("/nonexistent"),
        ),
    ):
        entry = _classify(xp, project=None)
    assert entry.bucket == "project"
    assert entry.project == "inferred"
