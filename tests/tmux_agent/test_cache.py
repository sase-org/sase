"""Tests for the fingerprinted tmux Agent catalog cache."""

from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path
from typing import Any

import pytest

from sase.config.tmux_agent import TmuxAgentConfig
from sase.tmux_agent import cache as cache_module
from sase.tmux_agent import catalog as catalog_module
from sase.tmux_agent.cache import (
    SCHEMA_VERSION,
    CachedProvider,
    CatalogCachePayload,
    _catalog_fingerprint,
    cached_tmux_agent_config,
    load_catalog_payload,
    read_cache,
    refresh_catalog_cache,
    write_cache,
)
from sase.tmux_agent.catalog import (
    _catalog_from_cache,
    build_tmux_agent_catalog,
    capture_catalog_snapshot,
)
from sase.tmux_agent.models import TmuxAgentEntry


def _provider(**overrides: Any) -> CachedProvider:
    values: dict[str, Any] = {
        "provider": "claude",
        "display_name": "Claude Code",
        "vendor": "Anthropic",
        "color": "#D97757",
        "binary": "claude",
        "descriptor": {
            "argv": ["claude"],
            "args": [],
            "bypass_args": ["--dangerously-skip-permissions"],
            "model_args": ["--model", "{model}"],
            "env": {},
            "menu_key": "c",
            "supported": True,
        },
        "key": "c",
        "install_hint": "npm install -g @anthropic-ai/claude-code",
        "autodetect_priority": 1,
        "argv": ("claude", "--dangerously-skip-permissions"),
        "env": (),
        "effort": None,
        "effort_skipped": None,
        "bypass": True,
    }
    values.update(overrides)
    return CachedProvider(**values)


def _fingerprint(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sase_version": "0.16.0",
        "entry_points": [["claude", "sase.llm_provider.claude:ClaudeProvider"]],
        "config_layers": [["/tmp/sase.yml", 1, 10]],
    }
    values.update(overrides)
    return values


def _payload(**overrides: Any) -> CatalogCachePayload:
    values: dict[str, Any] = {
        "fingerprint": _fingerprint(),
        "config": TmuxAgentConfig(),
        "effort": None,
        "configured_provider": "claude",
        "providers": (_provider(),),
    }
    values.update(overrides)
    return CatalogCachePayload(**values)


@pytest.fixture(autouse=True)
def _reset_last_payload() -> Iterator[None]:
    cache_module._last_payload = None
    yield
    cache_module._last_payload = None


def test_fingerprint_changes_when_sase_version_changes() -> None:
    first = _catalog_fingerprint(
        sase_version="1.0.0", entry_points=(), config_layers=()
    )
    second = _catalog_fingerprint(
        sase_version="1.0.1", entry_points=(), config_layers=()
    )

    assert first != second
    assert first["entry_points"] == second["entry_points"]
    assert first["config_layers"] == second["config_layers"]
    assert first["schema_version"] == second["schema_version"]


def test_fingerprint_changes_when_entry_points_change() -> None:
    first = _catalog_fingerprint(
        sase_version="1.0.0",
        entry_points=(("claude", "sase.llm_provider.claude:ClaudeProvider"),),
        config_layers=(),
    )
    second = _catalog_fingerprint(
        sase_version="1.0.0",
        entry_points=(
            ("claude", "sase.llm_provider.claude:ClaudeProvider"),
            ("codex", "sase.llm_provider.codex:CodexProvider"),
        ),
        config_layers=(),
    )

    assert first != second
    assert first["sase_version"] == second["sase_version"]
    assert first["config_layers"] == second["config_layers"]


def test_fingerprint_changes_when_config_layer_mtime_or_size_changes() -> None:
    first = _catalog_fingerprint(
        sase_version="1.0.0",
        entry_points=(),
        config_layers=(("/tmp/sase.yml", 100, 10),),
    )
    mtime_changed = _catalog_fingerprint(
        sase_version="1.0.0",
        entry_points=(),
        config_layers=(("/tmp/sase.yml", 200, 10),),
    )
    size_changed = _catalog_fingerprint(
        sase_version="1.0.0",
        entry_points=(),
        config_layers=(("/tmp/sase.yml", 100, 99),),
    )

    assert first != mtime_changed
    assert first != size_changed
    assert mtime_changed != size_changed


def test_fingerprint_changes_when_schema_version_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _catalog_fingerprint(
        sase_version="1.0.0", entry_points=(), config_layers=()
    )
    monkeypatch.setattr(cache_module, "SCHEMA_VERSION", SCHEMA_VERSION + 1)
    second = _catalog_fingerprint(
        sase_version="1.0.0", entry_points=(), config_layers=()
    )

    assert first["schema_version"] != second["schema_version"]
    assert first["sase_version"] == second["sase_version"]


def test_cache_hit_does_not_recapture(tmp_path: Path) -> None:
    path = tmp_path / "catalog_cache.json"
    fingerprint = _fingerprint()
    payload = _payload(fingerprint=fingerprint)
    write_cache(payload, path=path)
    captures: list[str] = []

    def capture() -> CatalogCachePayload:
        captures.append("capture")
        raise AssertionError("cache hit must not rebuild")

    loaded = load_catalog_payload(
        path=path,
        capture_fn=capture,
        fingerprint_fn=lambda: fingerprint,
    )

    assert loaded == read_cache(path)
    assert loaded.providers[0].provider == "claude"
    assert captures == []


def test_cache_miss_rebuilds_and_writes(tmp_path: Path) -> None:
    path = tmp_path / "catalog_cache.json"
    fingerprint = _fingerprint()
    payload = _payload(fingerprint={})
    captures: list[str] = []

    def capture() -> CatalogCachePayload:
        captures.append("capture")
        return payload

    loaded = load_catalog_payload(
        path=path,
        capture_fn=capture,
        fingerprint_fn=lambda: fingerprint,
    )

    assert captures == ["capture"]
    assert loaded.fingerprint == fingerprint
    assert path.is_file()
    stored = read_cache(path)
    assert stored is not None
    assert stored.providers[0].display_name == "Claude Code"


@pytest.mark.parametrize(
    "changed",
    [
        {"sase_version": "9.9.9"},
        {"entry_points": [["codex", "sase.llm_provider.codex:CodexProvider"]]},
        {"config_layers": [["/tmp/sase.yml", 99, 10]]},
        {"schema_version": SCHEMA_VERSION + 1},
    ],
)
def test_fingerprint_mismatch_rebuilds(tmp_path: Path, changed: dict[str, Any]) -> None:
    path = tmp_path / "catalog_cache.json"
    stored_fingerprint = _fingerprint()
    write_cache(_payload(fingerprint=stored_fingerprint), path=path)
    captures: list[str] = []

    def capture() -> CatalogCachePayload:
        captures.append("capture")
        return _payload(fingerprint={})

    load_catalog_payload(
        path=path,
        capture_fn=capture,
        fingerprint_fn=lambda: _fingerprint(**changed),
    )

    assert captures == ["capture"]


def test_corrupt_json_is_a_miss(tmp_path: Path) -> None:
    path = tmp_path / "catalog_cache.json"
    path.write_text("{not json", encoding="utf-8")
    captures: list[str] = []

    def capture() -> CatalogCachePayload:
        captures.append("capture")
        return _payload(fingerprint=_fingerprint())

    loaded = load_catalog_payload(
        path=path,
        capture_fn=capture,
        fingerprint_fn=_fingerprint,
    )

    assert captures == ["capture"]
    assert loaded.providers[0].provider == "claude"


def test_unreadable_cache_is_a_miss(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "catalog_cache.json"
    assert read_cache(path) is None


def test_readonly_cache_directory_does_not_raise(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("blocked", encoding="utf-8")
    path = blocker / "catalog_cache.json"

    write_cache(_payload(), path=path)

    assert not path.exists()


def test_installed_state_is_absent_from_cache_payload(tmp_path: Path) -> None:
    path = tmp_path / "catalog_cache.json"
    write_cache(_payload(), path=path)
    envelope = json.loads(path.read_text(encoding="utf-8"))

    assert "installed" not in envelope
    assert envelope["providers"]
    for item in envelope["providers"]:
        assert "installed" not in item
        assert "executable" not in item
        assert "routing_disabled" not in item
        assert "binary" in item
        assert "descriptor" in item
        assert "key" in item


def test_payload_with_installed_state_is_treated_as_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "catalog_cache.json"
    write_cache(_payload(), path=path)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["providers"][0]["installed"] = True
    path.write_text(json.dumps(envelope), encoding="utf-8")

    assert read_cache(path) is None


def test_schema_mismatch_is_a_miss(tmp_path: Path) -> None:
    path = tmp_path / "catalog_cache.json"
    write_cache(_payload(), path=path)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["schema_version"] = SCHEMA_VERSION + 1
    path.write_text(json.dumps(envelope), encoding="utf-8")

    assert read_cache(path) is None


def test_refresh_forces_rebuild_on_valid_cache(tmp_path: Path) -> None:
    path = tmp_path / "catalog_cache.json"
    fingerprint = _fingerprint()
    write_cache(_payload(fingerprint=fingerprint), path=path)
    captures: list[str] = []

    def capture() -> CatalogCachePayload:
        captures.append("capture")
        return _payload(fingerprint={}, providers=(_provider(provider="codex"),))

    loaded = refresh_catalog_cache(
        path=path,
        capture_fn=capture,
        fingerprint_fn=lambda: fingerprint,
    )

    assert captures == ["capture"]
    assert loaded.providers[0].provider == "codex"


def test_catalog_from_cache_probes_install_state_live() -> None:
    payload = _payload()

    missing = _catalog_from_cache(
        payload,
        directory="/proj",
        resolve_executable_fn=lambda _provider, _binary: None,
        disables_fn=lambda _now: {},
    )
    present = _catalog_from_cache(
        payload,
        directory="/proj",
        resolve_executable_fn=lambda _provider, binary: f"/usr/bin/{binary}",
        disables_fn=lambda _now: {},
    )

    assert missing.entries[0].installed is False
    assert missing.entries[0].executable is None
    assert present.entries[0].installed is True
    assert present.entries[0].executable == "/usr/bin/claude"
    assert present.directory == "/proj"
    assert present.default_provider == "claude"


def test_catalog_from_cache_keeps_disables_live() -> None:
    from sase.llm_provider.provider_disable import (
        PROVIDER_DISABLE_MODE_HARD,
        TemporaryProviderDisable,
    )

    disable = TemporaryProviderDisable(
        version=2,
        provider="claude",
        created_at=0.0,
        expires_at=None,
        source="test",
        mode=PROVIDER_DISABLE_MODE_HARD,
    )
    catalog = _catalog_from_cache(
        _payload(),
        directory="/proj",
        resolve_executable_fn=lambda _provider, binary: f"/usr/bin/{binary}",
        disables_fn=lambda _now: {"claude": disable},
    )

    assert catalog.entries[0].routing_disabled == disable


def test_build_without_statuses_uses_the_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    monkeypatch.setattr(catalog_module, "load_catalog_payload", lambda **_k: payload)
    monkeypatch.setattr(
        catalog_module,
        "_probe_executable",
        lambda _provider, binary: f"/usr/bin/{binary}",
    )
    monkeypatch.setattr(
        catalog_module, "get_active_provider_disables", lambda now=None: {}
    )

    result = build_tmux_agent_catalog(directory="/workspace")

    assert result.directory == "/workspace"
    assert [entry.provider for entry in result.entries] == ["claude"]
    assert result.entries[0].installed is True


def test_capture_omits_live_install_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tmux_agent.catalog import _ResolvedProvider

    row = _ResolvedProvider(
        provider="claude",
        display_name="Claude Code",
        vendor="Anthropic",
        color="#D97757",
        key="c",
        binary="claude",
        executable="/usr/bin/claude",
        installed=True,
        install_hint="npm install -g @anthropic-ai/claude-code",
        routing_disabled=None,
        argv=("claude",),
        env=(),
        effort=None,
        effort_skipped=None,
        bypass=True,
        descriptor={"argv": ["claude"], "supported": True},
        autodetect_priority=1,
    )
    monkeypatch.setattr(catalog_module, "collect_agent_cli_statuses", lambda **_k: ())
    monkeypatch.setattr(
        catalog_module,
        "_resolved_rows",
        lambda _statuses, now=None: ([row], TmuxAgentConfig(), None, "claude"),
    )

    payload = capture_catalog_snapshot()
    path = tmp_path / "catalog_cache.json"
    write_cache(payload, path=path)
    envelope = json.loads(path.read_text(encoding="utf-8"))

    assert envelope["providers"][0]["provider"] == "claude"
    assert "installed" not in envelope["providers"][0]
    assert "executable" not in envelope["providers"][0]
    assert envelope["providers"][0]["binary"] == "claude"


def test_cached_tmux_agent_config_tracks_last_load(tmp_path: Path) -> None:
    path = tmp_path / "catalog_cache.json"
    config = TmuxAgentConfig(window_name="bots")
    fingerprint = _fingerprint()

    assert cached_tmux_agent_config() is None
    load_catalog_payload(
        path=path,
        capture_fn=lambda: _payload(fingerprint={}, config=config),
        fingerprint_fn=lambda: fingerprint,
    )
    cached = cached_tmux_agent_config()
    assert cached is not None
    assert cached.window_name == "bots"


def test_default_provider_from_cache_requires_live_install() -> None:
    payload = _payload()
    catalog = _catalog_from_cache(
        payload,
        directory="/proj",
        resolve_executable_fn=lambda _provider, _binary: None,
        disables_fn=lambda _now: {},
    )

    assert catalog.default_provider is None
    assert isinstance(catalog.entries[0], TmuxAgentEntry)
