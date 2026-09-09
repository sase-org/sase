"""Provider entry-point inventory tests for remote dispatch.

Recreates the dispatch-plugins verification suite that was lost when the
sase-xe.7 workspace was reaped before its commit landed (see the epic notes
on bead sase-xe).
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from sase.dispatch.config import load_dispatch_config
from sase.dispatch.providers import (
    collect_dispatch_providers,
    discover_dispatch_candidates,
    hookimpl,
)

LAB_REF = "fake-dispatch-plugin@lab"


class _FakeDist:
    def __init__(self, name: str, version: str) -> None:
        self.metadata = {"Name": name}
        self.version = version


class _FakeEntryPoint:
    def __init__(
        self,
        name: str,
        plugin: object,
        *,
        package: str = "fake-dispatch-plugin",
        version: str = "1.0.0",
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.value = f"fake_dispatch_plugin:{name}"
        self.dist = _FakeDist(package, version)
        self.load_calls = 0
        self._plugin = plugin
        self._error = error

    def load(self) -> object:
        self.load_calls += 1
        if self._error is not None:
            raise self._error
        return self._plugin


def _entry_points_fn(*entry_points: _FakeEntryPoint) -> Any:
    def fake_entry_points(*, group: str) -> tuple[_FakeEntryPoint, ...]:
        assert group == "sase_dispatch"
        return entry_points

    return fake_entry_points


class _FakeProvider:
    @hookimpl
    def dispatch_provider_specs(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "ref": LAB_REF,
                "display_name": "Lab Fleet Gateway",
                "supports_discovery": True,
            },
        )

    @hookimpl
    def dispatch_discover(
        self,
        provider_ref: str,
        config: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[dict[str, Any], ...]:
        del config, timeout_seconds
        if provider_ref != LAB_REF:
            return ()
        return (
            {
                "endpoint": "https://lab.example.test",
                "display_name": "Lab Box",
                "machine_selector": "lab",
            },
            # Duplicate of the first candidate; discovery must dedupe it.
            {
                "endpoint": "https://lab.example.test",
                "display_name": "Lab Box",
                "machine_selector": "lab",
            },
            # Candidates without an endpoint are dropped, not fatal.
            {"display_name": "no endpoint"},
        )


def _lab_config(*, enabled: bool) -> Any:
    return load_dispatch_config(
        {
            "dispatch": {
                "providers": {LAB_REF: enabled},
                "discovery": {"enabled_providers": [LAB_REF]},
            }
        }
    )


def test_collect_includes_builtin_providers_without_entry_points() -> None:
    inventory = collect_dispatch_providers(entry_points_fn=_entry_points_fn())

    refs = [spec.ref for spec in inventory.specs]
    assert refs == ["builtin@https", "builtin@tailnet"]
    assert all(spec.builtin for spec in inventory.specs)
    assert all(spec.package == "sase" for spec in inventory.specs)
    assert inventory.diagnostics == ()


def test_collect_includes_third_party_provider_specs() -> None:
    lab_ep = _FakeEntryPoint("lab", _FakeProvider())

    inventory = collect_dispatch_providers(entry_points_fn=_entry_points_fn(lab_ep))

    by_ref = inventory.by_ref()
    assert set(by_ref) == {"builtin@https", "builtin@tailnet", LAB_REF}
    assert lab_ep.load_calls == 0
    lab = by_ref[LAB_REF]
    assert lab.display_name == "lab"
    assert lab.supports_discovery is True
    assert lab.package == "fake-dispatch-plugin"
    assert lab.version == "1.0.0"
    assert lab.builtin is False


def test_collect_skips_the_builtin_entry_point() -> None:
    # The sase package registers its builtin providers both in code and as a
    # pyproject entry point for inventory visibility; collection must not load
    # or register the entry point a second time.
    builtin_ep = _FakeEntryPoint(
        "builtin",
        object(),
        package="sase",
        error=AssertionError("builtin entry point must not be loaded"),
    )

    inventory = collect_dispatch_providers(entry_points_fn=_entry_points_fn(builtin_ep))

    assert builtin_ep.load_calls == 0
    assert [spec.ref for spec in inventory.specs] == [
        "builtin@https",
        "builtin@tailnet",
    ]
    assert not any(
        diagnostic.code == "dispatch_provider_duplicate"
        for diagnostic in inventory.diagnostics
    )


def test_collect_does_not_load_failing_third_party_entry_point() -> None:
    broken = _FakeEntryPoint("broken", object(), error=RuntimeError("boom"))

    inventory = collect_dispatch_providers(entry_points_fn=_entry_points_fn(broken))

    assert broken.load_calls == 0
    assert "fake-dispatch-plugin@broken" in inventory.by_ref()
    codes = [diagnostic.code for diagnostic in inventory.diagnostics]
    assert "dispatch_provider_load_failed" not in codes


def test_collect_reports_duplicate_and_invalid_metadata_refs() -> None:
    inventory = collect_dispatch_providers(
        entry_points_fn=_entry_points_fn(
            _FakeEntryPoint(
                "lab",
                object(),
                package="Fake.Dispatch_Plugin",
            ),
            _FakeEntryPoint("lab", object()),
            _FakeEntryPoint("BadName", object()),
        )
    )

    codes = [diagnostic.code for diagnostic in inventory.diagnostics]
    assert "dispatch_provider_duplicate" in codes
    assert "dispatch_provider_ref_invalid" in codes
    # First registration wins: the builtin spec is kept.
    assert inventory.by_ref()["builtin@https"].builtin is True


@pytest.mark.parametrize(
    "env_key",
    ["SASE_DISABLE_PLUGINS", "SASE_DISABLE_PLUGIN_DISPATCH"],
)
def test_disable_env_skips_third_party_providers(
    env_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(env_key, "1")
    lab_ep = _FakeEntryPoint("lab", _FakeProvider())

    inventory = collect_dispatch_providers(entry_points_fn=_entry_points_fn(lab_ep))

    assert lab_ep.load_calls == 0
    assert [spec.ref for spec in inventory.specs] == [
        "builtin@https",
        "builtin@tailnet",
    ]
    disabled = [
        diagnostic
        for diagnostic in inventory.diagnostics
        if diagnostic.code == "dispatch_plugins_disabled"
    ]
    assert len(disabled) == 1
    assert env_key in disabled[0].message

    candidates = discover_dispatch_candidates(
        config=_lab_config(enabled=True),
        entry_points_fn=_entry_points_fn(lab_ep),
    )
    assert candidates == ()
    assert lab_ep.load_calls == 0


def test_importing_sase_never_imports_dispatch_providers() -> None:
    # Provider modules load only during explicit discovery, never as an
    # import side effect of the sase package or the dispatch package.
    code = "\n".join(
        [
            "import sys",
            "import sase",
            "assert 'sase.dispatch' not in sys.modules, 'sase.dispatch imported'",
            "import sase.dispatch",
            "assert 'sase.dispatch.providers' not in sys.modules, (",
            "    'sase.dispatch.providers imported'",
            ")",
        ]
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=120)
