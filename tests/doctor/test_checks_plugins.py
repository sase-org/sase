"""Tests for the split ``sase doctor`` plugin checks."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.doctor.checks_plugins import (
    _check_plugins_github,
    _check_plugins_required,
    _check_plugins_resources,
    plugin_check_specs,
)
from sase.doctor.runner import DoctorContext


class _FakeDist:
    def __init__(self, name: str, version: str) -> None:
        self.metadata = {"Name": name, "Version": version}
        self.version = version


class _FakeEntryPoint:
    def __init__(
        self,
        *,
        name: str,
        value: str,
        package: str,
        version: str = "1.2.3",
        load_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.value = value
        self.dist = _FakeDist(package, version)
        self.load_error = load_error
        self.load_calls = 0

    def load(self) -> object:
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error
        return object()


def _patch_entry_points(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, list[_FakeEntryPoint]],
) -> None:
    def fake_entry_points(*, group: str) -> list[_FakeEntryPoint]:
        return mapping.get(group, [])

    monkeypatch.setattr(
        "sase.plugins.inventory.importlib.metadata.entry_points",
        fake_entry_points,
    )


def _context(cwd: Path) -> DoctorContext:
    return DoctorContext(cwd=cwd, project=None, sase_home=cwd / ".sase")


def test_plugin_check_specs_register_required_beside_resources(tmp_path: Path) -> None:
    ids = [spec.id for spec in plugin_check_specs(_context(tmp_path))]
    assert ids[:2] == ["plugins.required", "plugins.resources"]


def test_plugins_required_ok_when_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    config = tmp_path / "sase" / "sase.yml"
    config.parent.mkdir()
    config.write_text(
        "plugins:\n  required:\n    - sase-github\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.plugins.required._installed_plugin_versions",
        lambda *args, **kwargs: {"sase-github": "1.2.3"},
    )

    check = _check_plugins_required(_context(tmp_path))

    assert check.id == "plugins.required"
    assert check.status == "OK"
    assert check.data["required_count"] == 1


def test_plugins_required_errors_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    config = tmp_path / "sase" / "sase.yml"
    config.parent.mkdir()
    config.write_text(
        "plugins:\n  required:\n    - sase-github\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.plugins.required._installed_plugin_versions",
        lambda *args, **kwargs: {},
    )

    check = _check_plugins_required(_context(tmp_path))

    assert check.status == "ERROR"
    assert check.details
    assert "required plugin `sase-github` is not installed" in check.details[0]
    assert check.next_steps == ("sase plugin install sase-github",)


def test_plugins_required_skips_without_project(tmp_path: Path) -> None:
    check = _check_plugins_required(_context(tmp_path))

    assert check.status == "SKIP"


# --- plugins.resources ---


def test_plugins_resources_errors_on_resource_load_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = _FakeEntryPoint(
        name="resources",
        value="fake_resources",
        package="sase-resources",
        load_error=ImportError("boom"),
    )
    _patch_entry_points(monkeypatch, {"sase_xprompts": [resource]})

    check = _check_plugins_resources()

    assert check.id == "plugins.resources"
    assert check.group == "plugins"
    assert check.status == "ERROR"
    assert check.data["resource_error_count"] == 1
    assert resource.load_calls == 1


def test_plugins_resources_warns_when_disabled_by_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = _FakeEntryPoint(
        name="resources",
        value="fake_resources",
        package="sase-resources",
    )
    _patch_entry_points(monkeypatch, {"sase_xprompts": [resource]})
    monkeypatch.setenv("SASE_DISABLE_PLUGIN_XPROMPTS", "1")

    check = _check_plugins_resources()

    assert check.status == "WARN"
    assert "SASE_DISABLE_PLUGIN_XPROMPTS" in check.data["disabled_env"]
    assert resource.load_calls == 0


def test_plugins_resources_ok_when_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(monkeypatch, {})
    monkeypatch.delenv("SASE_DISABLE_PLUGINS", raising=False)
    monkeypatch.delenv("SASE_DISABLE_PLUGIN_XPROMPTS", raising=False)
    monkeypatch.delenv("SASE_DISABLE_PLUGIN_CONFIG", raising=False)

    check = _check_plugins_resources()

    assert check.status == "OK"
    assert check.data["resource_error_count"] == 0


# --- plugins.github ---


def test_plugins_github_skipped_without_github_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_entry_points(monkeypatch, {})

    checks = _check_plugins_github(which_fn=lambda _: None)

    assert checks == ()


def test_plugins_github_warns_when_gh_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github = _FakeEntryPoint(
        name="github",
        value="sase_github:Plugin",
        package="sase-github",
    )
    _patch_entry_points(monkeypatch, {"sase_vcs": [github]})

    checks = _check_plugins_github(which_fn=lambda _: None)

    assert len(checks) == 1
    assert checks[0].id == "plugins.github"
    assert checks[0].status == "WARN"
    assert checks[0].data["gh_installed"] is False


def test_plugins_github_ok_when_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github = _FakeEntryPoint(
        name="github",
        value="sase_github:Plugin",
        package="sase-github",
    )
    _patch_entry_points(monkeypatch, {"sase_workspace": [github]})

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="", stderr=""
        )

    checks = _check_plugins_github(
        which_fn=lambda _: "/usr/bin/gh",
        run_fn=fake_run,
    )

    assert len(checks) == 1
    assert checks[0].status == "OK"
    assert checks[0].data["gh_authenticated"] is True
