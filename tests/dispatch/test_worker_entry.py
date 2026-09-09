"""Dispatch worker subprocess entry-point tests.

Recreates the dispatch-plugins verification suite that was lost when the
sase-xe.7 workspace was reaped before its commit landed (see the epic notes
on bead sase-xe).
"""

from __future__ import annotations

from collections.abc import Mapping
import importlib
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from sase.dispatch.worker_entry import main as dispatch_worker_main

MIXED_REF = "mixed-case-dispatch@lab"


def _install_dispatch_site(monkeypatch: pytest.MonkeyPatch, site: Path) -> None:
    site.mkdir(parents=True)
    (site / "mixed_case_dispatch.py").write_text(
        """
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.dispatch.providers import hookimpl

CALLS = []


class Provider:
    @hookimpl
    def dispatch_provider_specs(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "ref": "mixed-case-dispatch@lab",
                "display_name": "Mixed Lab",
                "supports_discovery": True,
            },
        )

    @hookimpl
    def dispatch_discover(
        self,
        provider_ref: str,
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> tuple[dict[str, object], ...]:
        CALLS.append(("discover", provider_ref, timeout_seconds))
        return (
            {
                "endpoint": config["endpoint"],
                "machine_selector": provider_ref,
            },
        )

    @hookimpl
    def dispatch_connection_plan(
        self,
        provider_ref: str,
        machine: Mapping[str, Any],
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> dict[str, object]:
        CALLS.append(("connection_plan", provider_ref, timeout_seconds))
        return {
            "schema_version": 1,
            "provider_ref": provider_ref,
            "endpoint": str(machine["endpoint"]) + "/" + str(config["suffix"]),
            "credential_ref": machine["credential_ref"],
            "pinned_installation_id": machine["pinned_installation_id"],
            "connection_kind": "gateway",
            "tls": machine["tls"],
        }
""".lstrip(),
        encoding="utf-8",
    )
    dist = site / "Mixed.Case_Dispatch-1.0.0.dist-info"
    dist.mkdir()
    dist.joinpath("METADATA").write_text(
        "Metadata-Version: 2.1\nName: Mixed.Case_Dispatch\nVersion: 1.0.0\n",
        encoding="utf-8",
    )
    dist.joinpath("entry_points.txt").write_text(
        "[sase_dispatch]\nlab = mixed_case_dispatch:Provider\n",
        encoding="utf-8",
    )
    sys.modules.pop("mixed_case_dispatch", None)
    monkeypatch.syspath_prepend(str(site))
    importlib.invalidate_caches()


def _run_dispatch_worker(
    monkeypatch: pytest.MonkeyPatch,
    provider_ref: str,
    request: Mapping[str, Any],
) -> tuple[int, dict[str, Any]]:
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(dict(request))))
    monkeypatch.setattr(sys, "stdout", stdout)
    returncode = dispatch_worker_main(
        ["--provider-ref", provider_ref, "--operation", str(request["operation"])]
    )
    return returncode, json.loads(stdout.getvalue())


def test_dispatch_worker_loads_selected_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_dispatch_site(monkeypatch, tmp_path / "site")

    returncode, payload = _run_dispatch_worker(
        monkeypatch,
        "Mixed.Case_Dispatch@lab",
        {
            "operation": "discover",
            "config": {"endpoint": "https://lab.example.test"},
            "timeout_seconds": 2,
        },
    )

    assert returncode == 0
    assert payload["provider_ref"] == MIXED_REF
    assert payload["candidates"] == [
        {
            "endpoint": "https://lab.example.test",
            "machine_selector": MIXED_REF,
        }
    ]


def test_dispatch_worker_runs_connection_plan_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_dispatch_site(monkeypatch, tmp_path / "site")

    returncode, payload = _run_dispatch_worker(
        monkeypatch,
        MIXED_REF,
        {
            "operation": "connection_plan",
            "config": {"suffix": "provider"},
            "machine": {
                "endpoint": "https://lab.example.test",
                "credential_ref": "fleet:lab",
                "pinned_installation_id": "sase_inst_v1_" + "a" * 64,
                "tls": {"schema_version": 1, "mode": "system_roots"},
            },
            "timeout_seconds": 2,
        },
    )

    assert returncode == 0
    assert payload["plan"]["endpoint"] == "https://lab.example.test/provider"
