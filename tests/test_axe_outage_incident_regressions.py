"""Regression tests for production axe outage incidents."""

import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import pytest

import sase.axe.state as axe_state
from sase.axe.config import AxeConfig
from sase.axe.ensure import ensure_axe
from sase.axe._process_guard import AXE_LIFECYCLE_TEST_OVERRIDE_ENV
from sase.axe._process_types import AxeOrchestratorProbe, TerminateResult
from sase.axe.process import (
    restart_axe_daemon_result,
    start_axe_daemon_result,
    stop_axe_daemon_result,
)
from sase.axe.run_agent_wait import wait_for_dependencies

from tests._agent_names_fixtures import make_agent


pytest_plugins = ("tests._axe_outage_recovery_fixtures",)
pytestmark = pytest.mark.usefixtures("allow_axe_lifecycle_in_tests")


class TestLeakedOrchestratorIncidentRegression:
    """Cross-layer coverage for the leaked-pytest-orchestrator incident."""

    def test_imported_axe_modules_follow_redirected_home(
        self,
        tmp_path: Path,
    ) -> None:
        """Status and guarded start use the post-import test-home redirect."""
        preimport_sase_home = tmp_path / "preimport-home" / ".sase"
        redirected_sase_home = tmp_path / "redirected-home" / ".sase"
        script = dedent(
            """
            import json
            import os
            from pathlib import Path

            preimport_home = Path(os.environ["INCIDENT_PREIMPORT_SASE_HOME"])
            redirected_home = Path(os.environ["INCIDENT_REDIRECTED_SASE_HOME"])
            os.environ["SASE_HOME"] = str(preimport_home)

            preimport_axe = preimport_home / "axe"
            preimport_axe.mkdir(parents=True)
            (preimport_axe / "orchestrator.pid").write_text(
                f"{os.getpid()}\\n", encoding="utf-8"
            )
            (preimport_axe / "sentinel").write_text("untouched", encoding="utf-8")

            import sase.axe.lock as axe_lock
            import sase.axe.state as axe_state
            from sase.axe.config import AxeConfig
            from sase.axe.process import get_axe_status, start_axe_daemon_result

            def snapshot(root):
                return {
                    str(path.relative_to(root)): path.read_text(encoding="utf-8")
                    for path in sorted(root.rglob("*"))
                    if path.is_file()
                }

            before = snapshot(preimport_home)
            os.environ["SASE_HOME"] = str(redirected_home)
            os.environ["PYTEST_CURRENT_TEST"] = "incident regression"
            os.environ.pop("SASE_AXE_ALLOW_LIFECYCLE_IN_TESTS", None)

            status = get_axe_status()
            started = start_axe_daemon_result(AxeConfig())
            payload = {
                "axe_state_dir": str(axe_state.axe_state_dir()),
                "lifecycle_lock": str(axe_lock._axe_lifecycle_lock_path()),
                "status_is_none": status is None,
                "start_status": started.status,
                "outside_unchanged": snapshot(preimport_home) == before,
                "redirected_files": sorted(
                    str(path.relative_to(redirected_home))
                    for path in redirected_home.rglob("*")
                    if path.is_file()
                ),
            }
            print(json.dumps(payload))
            """
        )
        env = os.environ.copy()
        env.pop(AXE_LIFECYCLE_TEST_OVERRIDE_ENV, None)
        env["INCIDENT_PREIMPORT_SASE_HOME"] = str(preimport_sase_home)
        env["INCIDENT_REDIRECTED_SASE_HOME"] = str(redirected_sase_home)

        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            cwd=Path.cwd(),
            env=env,
            text=True,
        )
        payload = json.loads(completed.stdout.strip().splitlines()[-1])

        redirected_axe = redirected_sase_home / "axe"
        assert payload == {
            "axe_state_dir": str(redirected_axe),
            "lifecycle_lock": str(redirected_axe / "orchestrator.lock"),
            "status_is_none": True,
            "start_status": "blocked_in_tests",
            "outside_unchanged": True,
            "redirected_files": ["axe/orchestrator.lock"],
        }

    def test_public_lifecycle_facade_spawns_nothing_under_pytest(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Every public lifecycle transition is blocked before process work."""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "incident regression")
        monkeypatch.delenv(AXE_LIFECYCLE_TEST_OVERRIDE_ENV, raising=False)
        state_dir = axe_state.axe_state_dir()
        assert not state_dir.exists()

        with (
            patch("subprocess.Popen") as popen,
            patch("subprocess.run") as run,
        ):
            started = start_axe_daemon_result(AxeConfig())
            stopped = stop_axe_daemon_result()
            restarted = restart_axe_daemon_result(AxeConfig())

        assert started.status == "blocked_in_tests"
        assert stopped.blocked_in_tests is True
        assert restarted.status == "blocked_in_tests"
        popen.assert_not_called()
        run.assert_not_called()
        assert not state_dir.exists()

    def test_waiter_unblocks_without_waits_chop(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A completed dependency is enough even when no ready marker arrives."""
        dep_dir = make_agent(tmp_path, "proj", "20260720010101", "dep")
        waiter_dir = (
            tmp_path / ".sase/projects/proj/artifacts/ace-run/20260720010202-waiter"
        )
        waiter_dir.mkdir(parents=True)
        (waiter_dir / "agent_meta.json").write_text(
            json.dumps({"pid": 123}),
            encoding="utf-8",
        )
        monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
        polls: list[float] = []

        def finish_dependency(_seconds: float) -> None:
            polls.append(_seconds)
            assert not (waiter_dir / "ready.json").exists()
            (dep_dir / "done.json").write_text(
                json.dumps({"outcome": "completed"}),
                encoding="utf-8",
            )

        agent_meta = {"pid": 123}
        with (
            patch("sase.axe.run_agent_wait.was_killed", return_value=False),
            patch("sase.axe.run_agent_wait._WAIT_DEPENDENCY_FALLBACK_INTERVAL", 0),
            patch("sase.axe.run_agent_wait._opportunistic_ensure_axe"),
            patch(
                "sase.axe.run_agent_wait.time.sleep",
                side_effect=finish_dependency,
            ),
        ):
            blocked = wait_for_dependencies(
                ["dep"],
                str(waiter_dir),
                "incident",
                "20260720010202",
                agent_meta,
                project_name="proj",
            )

        assert blocked is True
        assert polls == [2]
        assert "Dependencies satisfied by runner fallback" in capsys.readouterr().out
        assert isinstance(agent_meta.get("wait_completed_at"), str)
        assert not (waiter_dir / "waiting.json").exists()
        assert not (waiter_dir / "ready.json").exists()

    def test_ensure_recovers_wedged_lock_and_restarts_axe(
        self,
        temp_state_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Ensure crosses the aged-lock recovery path into a fresh spawn."""
        holder_pid = 98_765
        (temp_state_dir / "wedged_lifecycle_lock.json").write_text(
            json.dumps(
                {
                    "observed_at_epoch": 100.0,
                    "lock_holder_pid": holder_pid,
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("SASE_AXE_WEDGED_LOCK_GRACE_SECONDS", "60")
        wedged_probe = AxeOrchestratorProbe(
            lock_held=True,
            lock_holder_pid=holder_pid,
            orchestrator_pid_file_pid=None,
            legacy_pid=None,
            running_pid=None,
        )
        free_probe = AxeOrchestratorProbe(
            lock_held=False,
            lock_holder_pid=None,
            orchestrator_pid_file_pid=None,
            legacy_pid=None,
            running_pid=None,
        )
        lifecycle_lock = MagicMock()
        lifecycle_lock.fd = 99
        spawned_process = MagicMock()

        with (
            patch(
                "sase.axe._process_start.get_pid_from_pid_files",
                return_value=None,
            ),
            patch(
                "sase.axe._process_start._acquire_lifecycle_lock_for_start",
                side_effect=[None, lifecycle_lock],
            ),
            patch(
                "sase.axe._process_start.probe_orchestrator",
                side_effect=[wedged_probe, wedged_probe, free_probe],
            ),
            patch(
                "sase.axe._process_stop.terminate_process",
                return_value=TerminateResult(
                    pid=holder_pid,
                    signaled=True,
                    stopped=True,
                ),
            ) as terminate,
            patch(
                "sase.axe._process_start._build_axe_start_command",
                return_value=["fake-sase"],
            ),
            patch(
                "sase.axe._process_start.subprocess.Popen",
                return_value=spawned_process,
            ) as popen,
            patch(
                "sase.axe._process_start._wait_for_daemon_start",
                return_value=4_321,
            ),
            patch("sase.axe._process_start.time.time", return_value=161.0),
            patch(
                "sase.axe._process_start._notify_wedged_lock_recovery"
            ) as notify_recovery,
        ):
            result = ensure_axe(
                now_fn=lambda: 161.0,
                running_fn=lambda: False,
                start_fn=lambda **kwargs: start_axe_daemon_result(
                    AxeConfig(), **kwargs
                ),
                notify_fn=lambda _downtime, _pid: "healed-notification",
            )

        assert result.status == "healed"
        assert result.pid == 4_321
        terminate.assert_called_once_with(holder_pid, timeout=5.0, kill_timeout=2.0)
        popen.assert_called_once()
        lifecycle_lock.close_after_handoff.assert_called_once_with()
        notify_recovery.assert_called_once_with(holder_pid, 4_321)
        assert not (temp_state_dir / "wedged_lifecycle_lock.json").exists()
