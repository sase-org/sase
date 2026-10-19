"""Unit tests for tools/check_family_install (phase sase-1my.2).

All PyPI reads use in-memory fixtures: no network. The four cases the epic
plan requires are covered by name: the 0.1.0 fallback reads red, a core
inside sase's window reads green while a newer core exists, a yanked newest
is ignored, and a backtracked plugin reads red.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "check_family_install"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("check_family_install_test", str(TOOL_PATH))
    spec = importlib.util.spec_from_loader("check_family_install_test", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


tool = _load_tool()


def _releases(*versions: str, yanked: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for version in versions:
        payload[version] = [
            {"filename": f"pkg-{version}-py3-none-any.whl", "yanked": False}
        ]
    if yanked:
        payload[yanked] = [
            {"filename": f"pkg-{yanked}-py3-none-any.whl", "yanked": "broken"}
        ]
    return payload


def _fetch_for(mapping: dict[str, Any]) -> Any:
    def _fetch(url: str) -> Any:
        return mapping[url]

    return _fetch


def _pypi_url(name: str) -> str:
    return f"https://pypi.org/pypi/{name}/json"


def _sase_version_url(version: str) -> str:
    return f"https://pypi.org/pypi/sase/{version}/json"


def _sase_info(version: str, core_spec: str) -> dict[str, Any]:
    return {
        "info": {
            "requires_dist": [
                "packaging",
                f"sase-core-rs{core_spec}",
            ]
        }
    }


def _full_fixture(
    *,
    sase_newest: str = "0.18.0",
    sase_releases: tuple[str, ...] = ("0.1.0", "0.17.1", "0.18.0"),
    plugin_newest: tuple[str, str, str] = ("0.2.24", "0.4.29", "0.2.0"),
    core_releases: tuple[str, ...] = ("0.42.0", "0.42.1"),
    core_spec: str = ">=0.42.0,<0.43.0",
    yanked: str = "",
) -> dict[str, Any]:
    fixture: dict[str, Any] = {
        _pypi_url("sase"): {"releases": _releases(*sase_releases, yanked=yanked)},
        _sase_version_url(sase_newest): _sase_info(sase_newest, core_spec),
        _pypi_url("sase-core-rs"): {"releases": _releases(*core_releases)},
    }
    for plugin, newest in zip(
        ("sase-github", "sase-telegram", "sase-research-artifacts"),
        plugin_newest,
        strict=True,
    ):
        fixture[_pypi_url(plugin)] = {"releases": _releases("0.1.0", newest)}
    return fixture


def _expectations(
    fetch: Any, installed_sase: str = "0.18.0"
) -> tuple[dict[str, str], str]:
    expected = tool.compute_expectations(fetch)
    return expected, tool.core_expectation(installed_sase, expected["sase"], fetch)


def _installed(
    *,
    sase: str | None = "0.18.0",
    core: str | None = "0.42.1",
    github: str = "0.2.24",
    telegram: str = "0.4.29",
    research: str = "0.2.0",
) -> dict[str, str | None]:
    return {
        "sase": sase,
        "sase-github": github,
        "sase-telegram": telegram,
        "sase-research-artifacts": research,
        "sase-core-rs": core,
    }


def test_sase_010_fallback_is_red_and_names_both_versions() -> None:
    fixture = _full_fixture()
    fetch = _fetch_for(fixture)
    expected, core_expected = _expectations(fetch)
    results = tool.evaluate(_installed(sase="0.1.0"), expected, core_expected, "newest")
    row = next(item for item in results if item.name == "sase")
    assert not row.ok
    assert row.reason == "sase 0.1.0 (expected 0.18.0)"
    assert "0.1.0" in (row.reason or "") and "0.18.0" in (row.reason or "")


def test_core_inside_sase_window_is_green_while_newer_core_exists() -> None:
    fixture = _full_fixture(core_releases=("0.42.0", "0.42.1", "0.43.0"))
    fetch = _fetch_for(fixture)
    expected, core_expected = _expectations(fetch)
    assert core_expected == "0.42.1"
    results = tool.evaluate(
        _installed(core="0.42.1"), expected, core_expected, "newest"
    )
    row = next(item for item in results if item.name == "sase-core-rs")
    assert row.ok
    assert row.rule == "window"
    assert all(item.ok for item in results)


def test_yanked_newest_version_is_ignored() -> None:
    fixture = _full_fixture(
        sase_newest="0.18.0",
        sase_releases=("0.1.0", "0.18.0"),
        yanked="0.19.0",
    )
    fetch = _fetch_for(fixture)
    assert tool.newest_usable("sase", fetch) == "0.18.0"


def test_backtracked_plugin_is_red() -> None:
    fixture = _full_fixture()
    fetch = _fetch_for(fixture)
    expected, core_expected = _expectations(fetch)
    bad = dict(_installed())
    bad["sase-github"] = "0.1.0"
    results = tool.evaluate(bad, expected, core_expected, "newest")
    row = next(item for item in results if item.name == "sase-github")
    assert not row.ok
    assert "expected 0.2.24" in (row.reason or "")


def test_prereleases_never_win_newest() -> None:
    fixture = _full_fixture(sase_releases=("0.18.0", "0.19.0rc1", "0.19.0.dev0"))
    fetch = _fetch_for(fixture)
    assert tool.newest_usable("sase", fetch) == "0.18.0"


def test_unreachable_pypi_fails_closed() -> None:
    def _boom(url: str) -> Any:
        raise tool.PypiUnavailable("HTTP 503 from PyPI")

    with pytest.raises(tool.PypiUnavailable):
        tool.compute_expectations(_boom)


def test_malformed_pypi_payload_fails_closed() -> None:
    fetch = _fetch_for({_pypi_url("sase"): {"releases": [1, 2, 3]}})
    with pytest.raises(tool.PypiUnavailable):
        tool.newest_usable("sase", fetch)


def test_missing_core_requirement_fails_closed() -> None:
    fixture = _full_fixture()
    fixture[_sase_version_url("0.18.0")] = {"info": {"requires_dist": ["packaging"]}}
    with pytest.raises(tool.PypiUnavailable):
        _expectations(_fetch_for(fixture))


def test_mismatch_refetches_once_before_going_red(monkeypatch: Any) -> None:
    fixture = _full_fixture()
    fetch = _fetch_for(fixture)
    expected, core_expected = _expectations(fetch)
    calls: list[None] = []

    def _refetch() -> tuple[dict[str, str], str]:
        calls.append(None)
        return expected, core_expected

    seen: list[dict[str, Any]] = []

    def _fake_read(exe: str) -> dict[str, str | None]:
        return dict(_installed(sase="0.1.0"))

    monkeypatch.setattr(tool, "read_installed_versions", _fake_read)
    result = tool.run_check(
        "sase",
        step="assert-newest-versions",
        identity={},
        mode="newest",
        expected=expected,
        core_expected=core_expected,
        refetch=_refetch,
    )
    assert result["verdict"] == "red"
    assert calls == [None]
    seen.append(result)


def test_result_contract_shape() -> None:
    expected = {
        "sase": "0.18.0",
        "sase-github": "0.2.24",
        "sase-telegram": "0.4.29",
        "sase-research-artifacts": "0.2.0",
    }
    results = tool.evaluate(_installed(), expected, "0.42.1", "newest")
    result = tool.build_result(
        results,
        step="assert-newest-versions",
        identity={"os": "ubuntu", "run_id": "7", "attempt": "1", "sha": "abc"},
        mode="newest",
    )
    assert result["schema_version"] == 1
    assert result["verdict"] == "green"
    assert result["failing_step"] is None
    assert result["reason"] is None
    rows = {row["name"]: row for row in result["packages"]}
    assert set(rows) == {
        "sase",
        "sase-github",
        "sase-telegram",
        "sase-research-artifacts",
        "sase-core-rs",
    }
    for row in result["packages"]:
        assert set(row) == {"name", "expected", "installed", "rule", "ok", "reason"}
    assert rows["sase-core-rs"]["rule"] == "window"
    assert rows["sase"]["rule"] == "newest"


def test_plugins_loaded_proof_and_missing_plugin() -> None:
    payload = {
        "packages": [
            {"name": "sase", "plugin_signals": []},
            {"name": "sase-github", "plugin_signals": ["entry_point:x"]},
            {"name": "sase-telegram", "plugin_signals": ["entry_point:y"]},
            {"name": "sase-research-artifacts", "plugin_signals": []},
        ]
    }
    assert tool.check_plugins_loaded(payload) == ["sase-research-artifacts"]
    full = {
        "packages": [
            {"name": name, "plugin_signals": ["entry_point:x"]}
            for name in (
                "sase",
                "sase-github",
                "sase-telegram",
                "sase-research-artifacts",
            )
        ]
    }
    assert tool.check_plugins_loaded(full) == []


def test_force_expect_override_drives_probe_red() -> None:
    fixture = _full_fixture()
    fetch = _fetch_for(fixture)
    expected = tool.apply_overrides(tool.compute_expectations(fetch), {"sase": "99.0"})
    core_expected = tool.core_expectation("0.18.0", expected["sase"], fetch)
    assert expected["sase"] == "99.0"
    results = tool.evaluate(_installed(), expected, core_expected, "newest")
    row = next(item for item in results if item.name == "sase")
    assert not row.ok
    assert "expected 99.0" in (row.reason or "")


def test_exact_mode_labels_rows_exact() -> None:
    expected = {
        "sase": "0.18.0",
        "sase-github": "0.2.24",
        "sase-telegram": "0.4.29",
        "sase-research-artifacts": "0.2.0",
    }
    results = tool.evaluate(_installed(), expected, "0.42.1", "exact")
    assert all(item.ok for item in results)
    assert {item.rule for item in results if item.name != "sase-core-rs"} == {"exact"}


def test_print_pins_lists_exact_family_install(monkeypatch: Any, capsys: Any) -> None:
    fixture = _full_fixture()
    monkeypatch.setattr(tool, "_fetch_json", _fetch_for(fixture))
    assert tool.main(["--print-pins"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == (
        "sase==0.18.0 --with sase-github==0.2.24 "
        "--with sase-telegram==0.4.29 --with sase-research-artifacts==0.2.0"
    )


def test_helper_cli_unreachable_pypi_is_red_and_writes_result(
    tmp_path: Path, monkeypatch: Any
) -> None:
    def _down(url: str) -> Any:
        raise tool.PypiUnavailable("HTTP 503 from PyPI")

    monkeypatch.setattr(tool, "_fetch_json", _down)
    out = tmp_path / "result.json"
    rc = tool.main(["--no-refetch", "--write-result", str(out)])
    assert rc == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["verdict"] == "red"
    assert payload["schema_version"] == 1
    assert all(row["rule"] == "unknown" for row in payload["packages"])
