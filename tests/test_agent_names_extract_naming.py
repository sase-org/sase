"""Name derivation and precedence tests for agent directive extraction."""

import os
from pathlib import Path
from unittest.mock import patch

from sase.agent.fork_waits import fork_wait_dependency
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.procs import Proc, append_proc
from tests._agent_chat_from_name_helpers import write_agent
from tests._agent_names_extract_fixtures import run_extract


def _write_proc(
    proc_id: str,
    *,
    status: str = "running",
    shell_name: str = "build-docs",
) -> None:
    append_proc(
        Proc(
            proc_id=proc_id,
            label="Build docs",
            kind="command",
            status=status,
            command=["just", "docs"],
            cwd="/tmp/work",
            origin="xprompt-proc",
            created_at="2026-07-25T12:00:00Z",
            log_path="/tmp/proc.log",
            project="proj",
            shell_name=shell_name,
        )
    )


class TestExtractDirectivesNaming:
    def test_resume_prompt_gets_resume_derived_name(self, tmp_path: Path) -> None:
        """A raw top-level #fork picks the first available .f slot."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_multi_parent_fork_gets_neutral_auto_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:planner,coder do stuff",
            )
        assert result["info"].name == "0"
        assert result["meta"].get("name") == "0"

    def test_explicit_name_wins_over_multi_parent_neutral_name(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%id:merged expanded prompt",
                raw_resolved_prompt="%id:merged #fork:planner,coder do stuff",
            )
        assert result["info"].name == "merged"
        assert result["meta"].get("name") == "merged"

    def test_planned_name_wins_for_non_explicit_auto_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="planned",
                prompt="expanded prompt",
            )
        assert result["info"].name == "planned"
        assert result["meta"].get("name") == "planned"

    def test_planned_name_reserved_for_different_run_is_ignored(
        self, tmp_path: Path, caplog
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                planned_name="stale-worker",
                planned_name_owner=tmp_path / "other-artifacts",
                prompt="expanded prompt",
            )

        assert result["info"].name == "0"
        assert result["meta"].get("name") == "0"
        assert "Ignoring stale SASE_AGENT_PLANNED_NAME='stale-worker'" in caplog.text

    def test_explicit_name_wins_over_resume(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%id:bar expanded prompt",
                raw_resolved_prompt="%id:bar #fork:foo do stuff",
            )
        assert result["info"].name == "bar"
        assert result["meta"].get("name") == "bar"

    def test_bare_name_uses_resume_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%id expanded prompt",
                raw_resolved_prompt="%id #fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_matching_planned_resume_descendant_name_wins(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="foo.f0.cld",
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0.cld"
        assert result["meta"].get("name") == "foo.f0.cld"

    def test_matching_letter_planned_resume_descendant_name_wins(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="foo.f-a.cld",
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f-a.cld"
        assert result["meta"].get("name") == "foo.f-a.cld"

    def test_noncanonical_planned_resume_descendant_name_is_rejected(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="foo.f-1.cld",
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_auto_dismiss_suppresses_resume_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=True,
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name is None
        assert "name" not in result["meta"]

    def test_wait_prompt_gets_wait_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:foo do stuff",
            )
        assert result["info"].name == "foo.w0"
        assert result["meta"].get("name") == "foo.w0"

    def test_time_shaped_wait_name_reaches_launch_metadata(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(tmp_path, prompt="%w:4h\nDo work")

        assert result["info"].wait_names == ["4h"]
        assert result["meta"]["wait_for"] == ["4h"]

    def test_explicit_name_wins_over_wait_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%id:bar\n%wait:foo do stuff",
            )
        assert result["info"].name == "bar"
        assert result["meta"].get("name") == "bar"

    def test_resume_name_wins_over_wait_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:foo expanded prompt",
                raw_resolved_prompt="#fork:bar\n%wait:foo do stuff",
            )
        assert result["info"].name == "bar.f0"
        assert result["meta"].get("name") == "bar.f0"

    def test_resume_name_wins_over_wait_planned_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="foo.w0",
                prompt="%wait:foo expanded prompt",
                raw_resolved_prompt="%wait:foo\n#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_multiple_waits_fall_back_to_auto_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:foo\n%wait:bar\ndo stuff",
            )
        assert result["info"].name == "0"
        assert result["meta"].get("name") == "0"

    def test_auto_dismiss_suppresses_wait_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=True,
                prompt="%wait:foo do stuff",
            )
        assert result["info"].name is None
        assert "name" not in result["meta"]


class TestExtractDirectivesImplicitForkWait:
    """A top-level #fork:<name> implies %wait:<name> as runner metadata."""

    def test_bare_fork_target_implies_wait(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["meta"].get("wait_for") == ["foo"]
        assert result["meta"].get("wait_for_fork_sources") == [
            {"kind": "name", "name": "foo"}
        ]
        assert result["info"].wait_names == ["foo"]
        assert result["info"].wait_fork_sources == [{"kind": "name", "name": "foo"}]
        # Fork-derived naming still wins over the implicit wait.
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_failed_fork_target_records_terminal_aware_dependency(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
        parent_dir = write_agent(
            tmp_path,
            "20260504010101",
            "failed-parent",
            done={"outcome": "failed", "error": "boom"},
        )

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:failed-parent do stuff",
            )

        expected_source = {
            "kind": "agent",
            "name": "failed-parent",
            "artifact_dir": str(parent_dir),
            "timestamp": parent_dir.name,
            "project_name": "proj",
        }
        assert result["meta"].get("wait_for") == ["failed-parent"]
        assert result["meta"].get("wait_for_fork_sources") == [expected_source]
        assert result["info"].wait_names == ["failed-parent"]
        assert result["info"].wait_fork_sources == [expected_source]
        assert result["info"].name == "failed-parent.f0"

    def test_explicit_wait_for_failed_fork_target_is_preserved(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
        write_agent(
            tmp_path,
            "20260504010101",
            "failed-parent",
            done={"outcome": "failed", "error": "boom"},
        )

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:failed-parent expanded prompt",
                raw_resolved_prompt=(
                    "%wait:failed-parent\n#fork:failed-parent do stuff"
                ),
            )

        assert result["meta"].get("wait_for") == ["failed-parent"]
        assert result["info"].wait_names == ["failed-parent"]

    def test_failed_fork_target_shadowed_by_live_namesake_still_waits(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
        write_agent(
            tmp_path,
            "20260504010101",
            "failed-parent",
            done={"outcome": "failed", "error": "boom"},
        )
        write_agent(
            tmp_path,
            "20260504020202",
            "failed-parent",
            meta={"chat_path": str(tmp_path / "running.md"), "pid": os.getpid()},
        )

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:failed-parent do stuff",
            )

        assert result["meta"].get("wait_for") == ["failed-parent"]
        assert result["info"].wait_names == ["failed-parent"]

    def test_tribe_fork_implies_tribe_wait_and_neutral_name(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:@epic do stuff",
            )
        assert result["meta"].get("wait_for") == ["@epic"]
        assert result["info"].wait_names == ["@epic"]
        assert result["info"].name == "0"

    def test_multi_parent_fork_waits_for_every_parent(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork(planner, coder) do stuff",
            )
        assert result["meta"].get("wait_for") == ["planner", "coder"]
        assert result["info"].wait_names == ["planner", "coder"]
        assert result["info"].name == "0"

    def test_fork_appends_after_explicit_waits(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:bar expanded prompt",
                raw_resolved_prompt="#fork:foo\n%wait:bar do stuff",
            )
        assert result["meta"].get("wait_for") == ["bar", "foo"]
        assert result["info"].wait_names == ["bar", "foo"]
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_explicit_duplicate_wait_is_not_repeated(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:foo expanded prompt",
                raw_resolved_prompt="#fork:foo %wait:foo do stuff",
            )
        assert result["meta"].get("wait_for") == ["foo"]
        assert "wait_for_fork_sources" not in result["meta"]
        assert result["info"].wait_names == ["foo"]
        assert result["info"].wait_fork_sources == []
        assert result["info"].name == "foo.f0"

    def test_normalized_explicit_duplicate_wait_is_not_repeated(
        self, tmp_path: Path
    ) -> None:
        identity = AgentIdentitySnapshot(
            AgentOwnerIdentity(username="alice", machine_name="athena"),
            ("athena",),
        )
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch(
                "sase.core.agent_identity_facade.AgentIdentitySnapshot.current",
                return_value=identity,
            ),
        ):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:athena.foo expanded prompt",
                raw_resolved_prompt="#fork:foo %wait:athena.foo do stuff",
            )
        assert result["meta"].get("wait_for") == ["foo"]
        assert "wait_for_fork_sources" not in result["meta"]
        assert result["info"].wait_names == ["foo"]
        assert result["info"].wait_fork_sources == []
        assert result["info"].name == "foo.f0"

    def test_proc_fork_records_exact_proc_identity(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
        _write_proc("proc0123456789ab", shell_name="build-docs")

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:build-docs do stuff",
            )

        assert result["info"].wait_names == ["build-docs"]
        assert result["info"].wait_fork_sources == [
            {
                "kind": "proc",
                "name": "build-docs",
                "proc_id": "proc0123456789ab",
            }
        ]
        assert result["meta"]["wait_for_fork_sources"] == (
            result["info"].wait_fork_sources
        )

    def test_family_fork_records_root_identity(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
        root = write_agent(
            tmp_path,
            "20260801010101",
            "cx--plan",
            meta={"agent_family": "cx", "workflow_name": "cx"},
        )

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:cx do stuff",
            )

        assert result["info"].wait_names == ["cx"]
        assert result["info"].wait_fork_sources == [
            {
                "kind": "family",
                "name": "cx",
                "artifact_dir": str(root),
                "timestamp": root.name,
                "project_name": "proj",
            }
        ]

    def test_dotted_numeric_family_fork_records_root_identity(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
        base_name = "sase-x7.3.1.5"
        root = write_agent(
            tmp_path,
            "20260801010101",
            f"{base_name}--plan",
            meta={"agent_family": base_name, "workflow_name": base_name},
        )

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt=f"#fork:{base_name} do stuff",
            )

        assert result["info"].wait_names == [base_name]
        assert result["info"].wait_fork_sources == [
            {
                "kind": "family",
                "name": base_name,
                "artifact_dir": str(root),
                "timestamp": root.name,
                "project_name": "proj",
            }
        ]

    def test_monitor_member_fork_records_proc_identity(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
        write_agent(
            tmp_path,
            "20260801010101",
            "cx--mon",
            done={"outcome": "monitored"},
            meta={
                "agent_family": "cx",
                "agent_family_role": "monitor",
                "monitor_id": "mon0123456789ab",
            },
        )

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:cx--mon do stuff",
            )

        assert result["info"].wait_fork_sources == [
            {
                "kind": "proc",
                "name": "cx--mon",
                "proc_id": "mon0123456789ab",
            }
        ]

    def test_monitor_starter_fork_records_agent_identity(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
        starter = write_agent(
            tmp_path,
            "20260801010101",
            "starter",
            done={"outcome": "completed"},
            meta={"monitor_id": "mon0123456789ab"},
        )

        with patch.object(Path, "home", return_value=tmp_path):
            source = fork_wait_dependency("starter")

        assert source == {
            "kind": "agent",
            "name": "starter",
            "artifact_dir": str(starter),
            "timestamp": starter.name,
            "project_name": "proj",
        }

    def test_clan_fork_records_generation_identity(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
        write_agent(
            tmp_path,
            "20260801010101",
            "review.alpha",
            meta={
                "agent_clan": "review",
                "agent_clan_generation": "20260801010000",
            },
        )

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:review do stuff",
            )

        assert result["info"].wait_names == ["review"]
        assert result["info"].wait_fork_sources == [
            {
                "kind": "clan",
                "name": "review",
                "generation": "20260801010000",
            }
        ]

    def test_multi_parent_fork_deduplicates_explicit_waits(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:coder expanded prompt",
                raw_resolved_prompt="#fork:planner,coder %wait:coder do stuff",
            )
        assert result["meta"].get("wait_for") == ["coder", "planner"]
        assert result["info"].wait_names == ["coder", "planner"]
        assert result["info"].name == "0"

    def test_bare_fork_without_name_adds_no_implicit_wait(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork do stuff",
            )
        assert "wait_for" not in result["meta"]
        assert result["info"].wait_names == []

    def test_legacy_resume_adds_no_implicit_wait(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#resume:foo do stuff",
            )
        assert "wait_for" not in result["meta"]
        assert result["info"].wait_names == []
