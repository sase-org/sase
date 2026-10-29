"""Shared builders for rebase gate runner tests.

Not collected by pytest (``_``-prefixed); split test modules import these
public helpers instead of duplicating them.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from sase.workflows.commit import rebase_gate_settings as settings

__all__ = [
    "FINDING_PATH",
    "GateHarness",
    "HEAD",
    "TREE",
    "harness",
    "make_context",
    "make_report",
    "write_checker",
]

HEAD = "a" * 40
TREE = "b" * 40
FINDING_PATH = "src/sase/example.py"


def make_context(**overrides: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "schema_version": 1,
        "repository_root": "/repo",
        "inputs": [
            {
                "old_head": "1" * 40,
                "upstream_tip": "2" * 40,
                "merge_base": "3" * 40,
            }
        ],
        "current_head": HEAD,
        "current_tree": TREE,
        "changed_paths": [{"path": FINDING_PATH, "kind": "modified"}],
    }
    context.update(overrides)
    return context


def make_report(status: str, **overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "checked_head": HEAD,
        "checked_tree": TREE,
        "status": status,
        "findings": [],
    }
    if status == "findings":
        report["findings"] = [
            {
                "path": FINDING_PATH,
                "line": 3,
                "module": "sase.example",
                "imported_name": "thing",
                "explanation": "renamed upstream",
            }
        ]
    report.update(overrides)
    return report


def write_checker(
    path: Path,
    *,
    exit_code: int,
    report: dict[str, Any] | None = None,
    raw_body: str | None = None,
    preamble: str = "",
) -> str:
    """Write a checker script; return a shell command running it."""
    lines = ["import json, os, sys"]
    if preamble:
        lines.append(preamble)
    lines.extend(
        [
            "ctx_path = os.environ.get('SASE_REBASE_CONTEXT', '')",
            "res_path = os.environ.get('SASE_REBASE_RESULT', '')",
            "assert ctx_path and res_path, 'gate env vars missing'",
            "ctx = json.load(open(ctx_path))",
            f"assert ctx['current_head'] == {HEAD!r}, ctx",
        ]
    )
    if raw_body is not None:
        lines.append(f"open(res_path, 'w').write({raw_body!r})")
    elif report is not None:
        lines.append(f"open(res_path, 'w').write({json.dumps(report)!r})")
    lines.append(f"sys.exit({exit_code})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"{sys.executable} {path}"


class GateHarness:
    """Patch config loading and the facade; capture delegation."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.captured: dict[str, Any] = {}
        self.configs: dict[str, dict[str, Any]] = {}
        self.loaded_for: list[str] = []
        self.monkeypatch = monkeypatch
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))

        def fake_load(local_path: Path) -> dict[str, Any]:
            self.loaded_for.append(str(local_path))
            return self.configs.get(
                str(local_path),
                {"commit_hooks": {"after_rebase": ""}},
            )

        monkeypatch.setattr(settings, "load_merged_config_for_local_path", fake_load)

        def validate_timeout(value: float) -> float:
            if not math.isfinite(value) or value <= 0 or value > 30:
                raise ValueError(
                    "timeout_seconds must be finite, greater than 0, and at most 30"
                )
            return value

        monkeypatch.setattr(
            "sase.core.rebase_gate.validate_rebase_gate_timeout_seconds",
            validate_timeout,
        )

    def configure(
        self,
        root: Path,
        hook: Any,
        timeout: Any = 5.0,
    ) -> None:
        self.configs[os.path.abspath(str(root))] = {
            "commit_hooks": {
                "after_rebase": hook,
                "after_rebase_timeout_seconds": timeout,
            }
        }

    def fake_classify(self, verdict: str, **overrides: Any) -> None:
        def classify(
            context: Any,
            config: Any,
            command: Any,
            report: Any,
        ) -> dict[str, Any]:
            self.captured.update(
                context=context, config=config, command=command, report=report
            )
            decision: dict[str, Any] = {
                "schema_version": 1,
                "verdict": verdict,
                "reason": f"test {verdict}",
                "findings": [],
                "diagnostics": None,
            }
            decision.update(overrides)
            return decision  # type: ignore[return-value]

        self.monkeypatch.setattr(
            "sase.core.rebase_gate.classify_rebase_gate_result", classify
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> GateHarness:
    return GateHarness(monkeypatch, tmp_path)
