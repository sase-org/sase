from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from sase.config import artifact_ref_files
from sase.config.artifact_ref_files import _load_artifact_file_roots
from sase.config.layers import ConfigLayer


def _layer(
    name: str,
    roots: object,
    *,
    strategy: str = "concatenate",
) -> ConfigLayer:
    return ConfigLayer(
        name=name,
        path=None,
        exists=True,
        list_strategy=strategy,
        data={"artifact_refs": {"file": {"roots": roots}}},
    )


def test_loader_merges_layers_replace_and_duplicate_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    third = tmp_path / "third"
    for path in (first, second, third):
        path.mkdir()
    layers = [
        _layer("default", [{"name": "bob", "path": str(first)}]),
        _layer("user", [{"name": "bob", "path": str(second)}]),
        _layer("local", [{"name": "docs", "path": str(third)}]),
    ]
    monkeypatch.setattr(artifact_ref_files, "current_config_token", lambda: ("a",))
    monkeypatch.setattr(artifact_ref_files, "load_config_layers", lambda: layers)

    roots = _load_artifact_file_roots()

    assert [(root.name, root.path) for root in roots] == [
        ("bob", second.resolve()),
        ("docs", third.resolve()),
    ]
    assert _load_artifact_file_roots() is roots

    replacement = [
        _layer("user", [{"name": "only", "path": str(first)}], strategy="replace")
    ]
    monkeypatch.setattr(artifact_ref_files, "current_config_token", lambda: ("b",))
    monkeypatch.setattr(artifact_ref_files, "load_config_layers", lambda: replacement)
    assert [root.name for root in _load_artifact_file_roots()] == ["only"]


def test_loader_expands_home_and_preserves_glob_intent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    bob = home / "bob"
    bob.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(artifact_ref_files, "current_config_token", lambda: ("home",))
    monkeypatch.setattr(
        artifact_ref_files,
        "load_config_layers",
        lambda: [
            _layer(
                "user",
                [{"name": "bob", "path": "~/bob", "path_globs": ["**/*.md"]}],
            )
        ],
    )

    [root] = _load_artifact_file_roots()

    assert root.path == bob.resolve()
    assert root.path_globs == ("**/*.md",)
    assert root.source_layer == "user"


def test_loader_skips_bad_entries_per_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    good = tmp_path / "good"
    good.mkdir()
    layers = [
        _layer(
            "user",
            [
                {"name": "good", "path": str(good)},
                {"name": "Bad", "path": str(good)},
                {"name": "relative", "path": "notes"},
                {"name": "badglob", "path": str(good), "path_globs": [""]},
                "not a mapping",
            ],
        )
    ]
    monkeypatch.setattr(artifact_ref_files, "current_config_token", lambda: ("bad",))
    monkeypatch.setattr(artifact_ref_files, "load_config_layers", lambda: layers)

    with caplog.at_level(logging.WARNING):
        roots = _load_artifact_file_roots()

    assert [root.name for root in roots] == ["good"]
    assert "Skipping invalid artifact file root" in caplog.text
