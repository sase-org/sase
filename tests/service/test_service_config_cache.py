"""The 1 s reconcile tick reuses config and package metadata while unchanged."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from sase.config import core as config_core
from sase.service import config as service_config
from sase.service.config import load_service_config
from sase.service.host_support import package_version


def _user_config(name: str) -> str:
    return f"service:\n  procs:\n    {name}:\n      command: [run-{name}]\n"


@pytest.fixture
def layer_loads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count full layer loads behind ``load_service_config``."""
    calls: list[int] = []
    real: Callable[[], list[config_core.ConfigLayer]] = (
        service_config.load_config_layers
    )

    def _counting() -> list[config_core.ConfigLayer]:
        calls.append(1)
        return real()

    monkeypatch.setattr(service_config, "load_config_layers", _counting)
    return calls


def _user_config_path() -> Path:
    path = config_core.CONFIG_DIR / "sase.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_unchanged_config_files_skip_every_layer_load(layer_loads: list[int]) -> None:
    _user_config_path().write_text(_user_config("tunnel"), encoding="utf-8")

    first = load_service_config()
    for _ in range(5):
        assert load_service_config() is first

    assert len(layer_loads) == 1
    assert first.get("tunnel") is not None


def test_a_config_edit_invalidates_the_cache(layer_loads: list[int]) -> None:
    path = _user_config_path()
    path.write_text(_user_config("tunnel"), encoding="utf-8")
    assert load_service_config().get("tunnel") is not None

    path.write_text(_user_config("tunnel-two"), encoding="utf-8")
    composition = load_service_config()

    assert len(layer_loads) == 2
    assert composition.get("tunnel") is None
    assert composition.get("tunnel-two") is not None


def test_an_atomic_replace_with_the_same_size_and_mtime_invalidates(
    layer_loads: list[int],
) -> None:
    """Only the inode differs: a rename-into-place lands in one mtime tick."""
    path = _user_config_path()
    path.write_text(_user_config("tunnel-a"), encoding="utf-8")
    assert load_service_config().get("tunnel-a") is not None
    before = path.stat()

    replacement = path.with_name("sase.yml.new")
    replacement.write_text(_user_config("tunnel-b"), encoding="utf-8")
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, path)
    after = path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    assert after.st_ino != before.st_ino

    composition = load_service_config()

    assert len(layer_loads) == 2
    assert composition.get("tunnel-b") is not None


def test_a_cache_clear_forces_a_reload(layer_loads: list[int]) -> None:
    load_service_config()
    config_core.clear_config_cache()
    load_service_config()

    assert len(layer_loads) == 2


def test_package_version_reads_metadata_once_per_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[str] = []

    def _version(name: str) -> str:
        reads.append(name)
        return "9.9.9"

    package_version.cache_clear()
    monkeypatch.setattr("importlib.metadata.version", _version)
    try:
        assert [package_version() for _ in range(3)] == ["9.9.9"] * 3
    finally:
        package_version.cache_clear()

    assert reads == ["sase"]
