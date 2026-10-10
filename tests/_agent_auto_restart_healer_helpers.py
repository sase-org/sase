"""Shared fixtures and builders for auto-restart healer tests.

Split from ``tests.test_agent_auto_restart_healer``. Not a conftest so
files opt in by importing the helpers directly. Names are public so the
``test_agent_auto_restart_healer_*`` split modules can share them without
importing ``_``-prefixed names across files.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
import pytest

from sase.agent.auto_restart.healer import HealerTarget

__all__ = [
    "healer_failed_row",
    "healer_quiet_notifications",
    "healer_target",
    "healer_tmp_home",
    "ok_probe_result",
    "ok_quiescence",
    "plan_double",
    "relaunch_verdict",
]


@pytest.fixture(name="tmp_home")
def healer_tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate all state-dir writes (ledger, evidence, storm state)."""
    home = tmp_path / "home"
    home.mkdir()
    import sase.core.paths as paths

    monkeypatch.setattr(paths, "sase_home", lambda: home)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture(name="failed_row")
def healer_failed_row(tmp_path: Path) -> Path:
    """One minimal failed agent row the healer may attempt."""
    artifacts = tmp_path / "artifacts" / "ace-run" / "20261009T120000"
    artifacts.mkdir(parents=True)
    (artifacts / "done.json").write_text(
        json.dumps(
            {
                "outcome": "failed",
                "error": "ImportError: cannot import name 'auto_launch_prefix'",
                "finished_at": 1720000000.0,
                # Skew-suspect so the row passes the healer candidate
                # pre-check (sweep-safety); the stale timestamp proves the
                # suspect path does not depend on legacy recency.
                "failure_facts": {
                    "lifecycle_phase": "waiting",
                    "skew_suspect": True,
                },
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": f"healer-test-{uuid.uuid4().hex[:8]}"}),
        encoding="utf-8",
    )
    (artifacts / "error_report.md").write_text("# boom\n", encoding="utf-8")
    return artifacts


def healer_target(artifacts: Path) -> HealerTarget:
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    return HealerTarget(
        artifacts_dir=artifacts, project="sase", agent_name=str(meta["name"])
    )


def relaunch_verdict() -> SimpleNamespace:
    return SimpleNamespace(
        tier="1",
        family="torn_python_import",
        signature="ImportError: cannot import name 'auto_launch_prefix'",
        origin_module="sase.monitor.continuation_delivery",
        missing_symbol="auto_launch_prefix",
        phase_class="pre_provider",
        mode="relaunch",
        reason="torn_python",
        reason_text="in-memory code asked the new tree for a removed symbol",
        witnesses_fired=("W1", "W4"),
        episode_id="sase@9fd8a08",
    )


def ok_quiescence() -> SimpleNamespace:
    return SimpleNamespace(ok=True, reason="quiet", quiet_seconds=60.0)


def ok_probe_result() -> SimpleNamespace:
    return SimpleNamespace(ok=True, failures=(), detail="clean")


def plan_double(target: HealerTarget) -> SimpleNamespace:
    return SimpleNamespace(
        rewritten_prompt="relaunch prompt",
        artifacts_dir=target.artifacts_dir,
        force_reuse_plan=SimpleNamespace(segment_envs=[None]),
        preview=SimpleNamespace(is_live=False),
        wipe_preview=SimpleNamespace(artifact_dirs=[str(target.artifacts_dir)]),
    )


@pytest.fixture(name="quiet_notifications")
def healer_quiet_notifications(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """Capture healer notifications without touching the real store."""
    import sase.agent.auto_restart.notify as notify

    calls: dict[str, list] = {"relaunch": [], "escalation": [], "resurface": []}
    monkeypatch.setattr(
        notify, "publish_relaunch", lambda **kw: calls["relaunch"].append(kw)
    )
    monkeypatch.setattr(
        notify, "publish_escalation", lambda **kw: calls["escalation"].append(kw)
    )
    monkeypatch.setattr(
        notify, "resurface_failure", lambda **kw: calls["resurface"].append(kw)
    )
    return calls
