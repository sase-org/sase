"""Tests for sase.workspace_provider.marker (Phase 3 of sase-3p)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.workspace_provider.marker import (
    CheckoutMarker,
    find_marker_from_cwd,
    read_marker,
    write_marker,
)
from sase.workspace_provider.registry import registry_path
from sase.workspace_provider.store import (
    PRIMARY_WORKSPACE_NUM,
    WorkspaceStore,
)


def _make_managed_store(tmp_path: Path) -> WorkspaceStore:
    primary = tmp_path / "proj"
    primary.mkdir()
    return WorkspaceStore(
        str(primary),
        config={
            "workspace": {
                "root": str(tmp_path / "root"),
                "project_key": "k",
            }
        },
        env={},
    )


class TestWriteMarker:
    def test_writes_marker_for_managed_workspace(self, tmp_path: Path) -> None:
        store = _make_managed_store(tmp_path)
        wp = store.resolve(10)
        Path(wp.checkout_dir).mkdir(parents=True)

        path = write_marker(store, wp)
        assert path is not None
        assert Path(path).exists()

        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        assert raw["project_key"] == store.project_key
        assert raw["workspace_num"] == 10
        assert raw["project_name"] == "proj"
        assert raw["primary_workspace_dir"] == store.primary_workspace_dir
        assert raw["registry_path"] == registry_path(store.root_dir)

    def test_skips_primary_checkout(self, tmp_path: Path) -> None:
        store = _make_managed_store(tmp_path)
        wp = store.resolve(PRIMARY_WORKSPACE_NUM)
        path = write_marker(store, wp)
        assert path is None
        assert not (Path(store.primary_workspace_dir) / ".sase").exists()

    def test_skips_missing_checkout_dir(self, tmp_path: Path) -> None:
        store = _make_managed_store(tmp_path)
        wp = store.resolve(10)
        # Checkout dir does not exist on disk yet.
        assert write_marker(store, wp) is None


class TestReadMarker:
    def test_round_trip(self, tmp_path: Path) -> None:
        store = _make_managed_store(tmp_path)
        wp = store.resolve(10)
        Path(wp.checkout_dir).mkdir(parents=True)
        write_marker(store, wp)

        marker = read_marker(wp.checkout_dir)
        assert isinstance(marker, CheckoutMarker)
        assert marker.project_key == store.project_key
        assert marker.workspace_num == 10

    def test_missing_marker_returns_none(self, tmp_path: Path) -> None:
        empty = tmp_path / "no-marker"
        empty.mkdir()
        assert read_marker(str(empty)) is None

    def test_malformed_marker_returns_none(self, tmp_path: Path) -> None:
        checkout = tmp_path / "broken"
        (checkout / ".sase").mkdir(parents=True)
        (checkout / ".sase" / "checkout.json").write_text("not json", encoding="utf-8")
        assert read_marker(str(checkout)) is None

    def test_non_dict_marker_returns_none(self, tmp_path: Path) -> None:
        checkout = tmp_path / "listy"
        (checkout / ".sase").mkdir(parents=True)
        (checkout / ".sase" / "checkout.json").write_text("[1, 2]", encoding="utf-8")
        assert read_marker(str(checkout)) is None

    @pytest.mark.parametrize(
        "field, value, match",
        [
            ("project_name", "../evil", "invalid SASE project name"),
            ("project_key", "../evil", "invalid SASE project key"),
            ("project_name", "/tmp/pwn", "invalid SASE project name"),
            ("project_key", "..", "invalid SASE project key"),
            ("project_key", "/tmp/pwn", "invalid SASE project key"),
            ("project_name", ".hidden", "invalid SASE project name"),
        ],
    )
    def test_from_dict_rejects_unsafe_project_identity(
        self, field: str, value: str, match: str
    ) -> None:
        raw = {
            "project_name": "proj",
            "project_key": "k",
            "workspace_num": 10,
            "primary_workspace_dir": "/work/proj",
            "registry_path": "/work/registry.json",
        }
        raw[field] = value
        with pytest.raises(ValueError, match=match):
            CheckoutMarker.from_dict(raw)

    def test_from_dict_allows_slash_separated_project_key(self) -> None:
        marker = CheckoutMarker.from_dict(
            {
                "project_name": "sase",
                "project_key": "sase-org/sase",
                "workspace_num": 20,
                "primary_workspace_dir": "/work/sase",
                "registry_path": "/work/registry.json",
            }
        )
        assert marker.project_key == "sase-org/sase"
        assert marker.project_name == "sase"

    @pytest.mark.parametrize(
        "project_name, project_key",
        [
            ("sase", ""),
            ("", "foo-org/foo"),
        ],
    )
    def test_from_dict_allows_empty_optional_identity_fields(
        self, project_name: str, project_key: str
    ) -> None:
        marker = CheckoutMarker.from_dict(
            {
                "project_name": project_name,
                "project_key": project_key,
                "workspace_num": 7,
                "primary_workspace_dir": "",
                "registry_path": "/work/registry.json",
            }
        )
        assert marker.project_name == project_name
        assert marker.project_key == project_key

    def test_read_marker_treats_traversal_names_as_absent(self, tmp_path: Path) -> None:
        checkout = tmp_path / "ws"
        (checkout / ".sase").mkdir(parents=True)
        (checkout / ".sase" / "checkout.json").write_text(
            json.dumps(
                {
                    "project_name": "../evil",
                    "project_key": "k",
                    "workspace_num": 10,
                    "primary_workspace_dir": "/work/proj",
                    "registry_path": "/work/registry.json",
                }
            ),
            encoding="utf-8",
        )
        assert read_marker(str(checkout)) is None


class TestFindMarkerFromCwd:
    def test_finds_marker_in_ancestor(self, tmp_path: Path) -> None:
        store = _make_managed_store(tmp_path)
        wp = store.resolve(10)
        checkout = Path(wp.checkout_dir.rstrip("/"))
        checkout.mkdir(parents=True)
        write_marker(store, wp)

        nested = checkout / "src" / "deep"
        nested.mkdir(parents=True)
        result = find_marker_from_cwd(str(nested))
        assert result is not None
        found_checkout, marker = result
        assert Path(found_checkout) == checkout
        assert marker.workspace_num == 10

    def test_returns_none_when_no_marker(self, tmp_path: Path) -> None:
        nested = tmp_path / "nothing" / "here"
        nested.mkdir(parents=True)
        assert find_marker_from_cwd(str(nested)) is None

    def test_pytest_sandbox_stops_marker_walk_at_boundary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = _make_managed_store(tmp_path)
        wp = store.resolve(10)
        checkout = Path(wp.checkout_dir.rstrip("/"))
        checkout.mkdir(parents=True)
        write_marker(store, wp)

        sandbox = checkout / "sandbox"
        nested = sandbox / "nested"
        nested.mkdir(parents=True)
        monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(sandbox))

        assert find_marker_from_cwd(str(nested)) is None
