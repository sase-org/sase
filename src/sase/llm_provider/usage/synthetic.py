"""Synthetic fourth-provider fixture used by probe-runtime tests.

Not registered as a ``sase_llm`` entry point. Tests import and instantiate it
directly so adding a collector does not require core or CLI changes.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

from sase.llm_provider._hookspec import hookimpl
from sase.llm_provider.usage.types import UsageProbeContext

SYNTHETIC_PROVIDER_NAME = "synth"
SYNTHETIC_MODE_ENV = "SASE_USAGE_SYNTHETIC_MODE"
SYNTHETIC_PIDFILE_ENV = "SASE_USAGE_SYNTHETIC_PIDFILE"
SECRET_CANARY = "token=SECRET_CANARY_USAGE"
SYNTHETIC_PLUGIN_SPEC = {
    "kind": "import",
    "module": "sase.llm_provider.usage.synthetic",
    "qualname": "_SyntheticUsageProvider",
}


class _SyntheticUsageProvider:
    """Deterministic usage collector with optional adversarial fixture modes."""

    @hookimpl
    def llm_provider_name(self) -> str:
        return SYNTHETIC_PROVIDER_NAME

    @hookimpl
    def llm_usage_capabilities(self) -> dict[str, object]:
        return {"probe": True, "passive_events": False}

    @hookimpl
    def llm_usage_probe(self, context: UsageProbeContext) -> dict[str, Any] | None:
        mode = os.environ.get(SYNTHETIC_MODE_ENV, "ok")
        if mode == "hang":
            time.sleep(3600)
            return None
        if mode == "secret":
            raise RuntimeError(SECRET_CANARY)
        if mode == "none":
            return None
        if mode == "descendants":
            child = subprocess.Popen(["sleep", "30"])
            pidfile = os.environ.get(SYNTHETIC_PIDFILE_ENV)
            if pidfile:
                with open(pidfile, "w", encoding="utf-8") as handle:
                    handle.write(str(child.pid))
            time.sleep(3600)
            return None
        if mode == "invalid":
            return {"not": "an observation"}
        return _ok_observation(context)


def _ok_observation(context: UsageProbeContext) -> dict[str, Any]:
    observed_at = context.request_started_at
    return {
        "schema_version": context.schema_version,
        "provider": context.provider,
        "context_id": context.context_id,
        "account_generation": context.account_generation,
        "ordering_token": context.request_started_at,
        "received_at": context.request_started_at,
        "source": "probe",
        "outcome": "ok",
        "reason_code": None,
        "diagnostic": None,
        "completeness": "complete",
        "authoritative_empty": False,
        "account_mode": "subscription",
        "plan": "synthetic",
        "windows": [
            {
                "key": "week",
                "label": "Synthetic week",
                "used_percent": 12.5,
                "resets_at": observed_at + 3600.0,
                "duration_seconds": 3600.0,
                "period_start": observed_at,
                "applicability": {"kind": "account"},
                "observed_at": observed_at,
                "source": "probe",
                "vendor_state": "allowed",
            }
        ],
    }
