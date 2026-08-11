from __future__ import annotations

from pathlib import Path

import pytest

from sase.config.layers import ConfigLayer
from sase.doctor.checks_config_artifact_refs import check_config_artifact_refs


def _layer(name: str, roots: object, path: Path | None = None) -> ConfigLayer:
    return ConfigLayer(
        name=name,
        path=str(path) if path is not None else None,
        exists=True,
        list_strategy="concatenate",
        data={"artifact_refs": {"file": {"roots": roots}}},
    )


def test_artifact_refs_check_ok_for_existing_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "bob"
    root.mkdir()
    monkeypatch.setattr(
        "sase.config.core.load_config_layers",
        lambda: [_layer("user", [{"name": "bob", "path": str(root)}])],
    )

    check = check_config_artifact_refs()

    assert check.status == "OK"
    assert check.data["problems"] == ()


def test_artifact_refs_check_reports_path_and_shape_problems(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    nested = root / "nested"
    file = tmp_path / "file.txt"
    nested.mkdir(parents=True)
    file.write_text("file", encoding="utf-8")
    missing = tmp_path / "missing"
    source = tmp_path / "sase.yml"
    monkeypatch.setattr(
        "sase.config.core.load_config_layers",
        lambda: [
            _layer(
                "user",
                [
                    {"name": "root", "path": str(root)},
                    {"name": "nested", "path": str(nested)},
                    {"name": "root", "path": str(root)},
                    {"name": "file", "path": str(file)},
                    {"name": "missing", "path": str(missing)},
                    {"name": "Bad", "path": str(root)},
                    {"name": "badglob", "path": str(root), "path_globs": [""]},
                ],
                path=source,
            )
        ],
    )

    check = check_config_artifact_refs()

    messages = [row["message"] for row in check.data["problems"]]
    assert check.status == "WARN"
    assert any(str(source) in message for message in messages)
    assert any("nested inside" in message for message in messages)
    assert any("duplicate root name" in message for message in messages)
    assert any("not a directory" in message for message in messages)
    assert any("is missing" in message for message in messages)
    assert any("'name' must be" in message for message in messages)
    assert any("'path_globs' is invalid" in message for message in messages)


def test_artifact_refs_check_reports_zero_usable_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_config_layers",
        lambda: [_layer("user", [{"name": "missing", "path": str(tmp_path / "x")}])],
    )

    check = check_config_artifact_refs()

    assert check.status == "WARN"
    assert any("zero usable" in row["message"] for row in check.data["problems"])
