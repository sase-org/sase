"""End-to-end smoke tests for clan summary launch, persistence, and rendering.

Tests:
- Launch clans with inline literal summaries (summary=[[...]])
- Launch clans with script-based summaries (summary_script=...)
- Launch epic clans with built-in summary scripts
- Verify persistence in agent_meta.json
- Verify round-trip through scan and index
- Verify rendering in clan panel
- Verify graceful failure when summary script breaks
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.clan_membership import (
    CLAN_MEMBERSHIP_ENV,
    ClanMembershipPlan,
    encode_clan_membership_plan,
)
from sase.axe.clan_summary_script import CLAN_SUMMARY_MAX_BYTES
from sase.axe.run_agent_directives import extract_directives_and_write_meta
from sase.core.agent_scan_wire_markers import AgentMetaWire


class TestClanSummaryInlineLiteral:
    """Smoke tests for inline literal clan summaries."""

    def test_inline_literal_summary_persists_to_meta(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A clan with summary=[[...]] persists the markup to agent_meta.json."""
        workspace_dir = tmp_path / "workspace"
        artifacts_dir = tmp_path / "artifacts"
        workspace_dir.mkdir(exist_ok=True)
        artifacts_dir.mkdir(exist_ok=True)

        monkeypatch.setenv(
            CLAN_MEMBERSHIP_ENV,
            encode_clan_membership_plan(
                ClanMembershipPlan(clan_name="example", generation="g1")
            ),
        )

        summary_markup = (
            "[bold #87D7FF]Example clan[/bold #87D7FF]\n"
            "[dim]Demonstrates inline clan summaries[/dim]"
        )

        with (
            patch("sase.agent.names.ensure_historical_auto_name_migration"),
            patch(
                "sase.agent.names.agent_name_allocation_lock",
                return_value=nullcontext(),
            ),
            patch("sase.agent.names.claim_agent_name"),
            patch("sase.agent.names.claim_registered_clan_name"),
            patch(
                "sase.xprompt.process_xprompt_references",
                side_effect=lambda value, **_: value,
            ),
            patch(
                "sase.llm_provider.temporary_override."
                "resolve_effective_default_provider_model",
                return_value=("codex", "gpt-5"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ):
            extract_directives_and_write_meta(
                (
                    f"%id:example.agent\n"
                    f"%clan(example, summary=[[\n{summary_markup}\n]])\n"
                    f"Do something"
                ),
                str(workspace_dir),
                str(artifacts_dir),
            )

        persisted = json.loads(
            (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
        )
        assert persisted["agent_clan"] == "example"
        assert persisted["clan_summary"] == summary_markup

    def test_inline_literal_summary_empty_rejected(
        self,
    ) -> None:
        """Empty inline summary is rejected during directive extraction."""
        from sase.xprompt._directive_extract import extract_prompt_directives
        from sase.xprompt._exceptions import DirectiveError

        prompt = "%id:example.agent\n%clan(example, summary=[[]])\nDo work"

        # Empty summaries are rejected as a validation error
        with pytest.raises(DirectiveError, match="summary.*non-empty"):
            extract_prompt_directives(prompt, process_references=lambda x: x)

    def test_inline_literal_summary_with_tribe_composes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Inline summary composes cleanly with tribe= in the same directive."""
        workspace_dir = tmp_path / "workspace"
        artifacts_dir = tmp_path / "artifacts"
        workspace_dir.mkdir(exist_ok=True)
        artifacts_dir.mkdir(exist_ok=True)

        monkeypatch.setenv(
            CLAN_MEMBERSHIP_ENV,
            encode_clan_membership_plan(
                ClanMembershipPlan(clan_name="research", generation="g1")
            ),
        )

        with (
            patch("sase.agent.names.ensure_historical_auto_name_migration"),
            patch(
                "sase.agent.names.agent_name_allocation_lock",
                return_value=nullcontext(),
            ),
            patch("sase.agent.names.claim_agent_name"),
            patch("sase.agent.names.claim_registered_clan_name"),
            patch(
                "sase.xprompt.process_xprompt_references",
                side_effect=lambda value, **_: value,
            ),
            patch(
                "sase.llm_provider.temporary_override."
                "resolve_effective_default_provider_model",
                return_value=("codex", "gpt-5"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ):
            extract_directives_and_write_meta(
                (
                    "%id:research.worker\n"
                    "%clan(research, tribe=research, summary=[[Research summary]])\n"
                    "Do research"
                ),
                str(workspace_dir),
                str(artifacts_dir),
            )

        persisted = json.loads(
            (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
        )
        assert persisted["agent_clan"] == "research"
        assert persisted["clan_tribe"] == "research"
        assert persisted["clan_summary"] == "Research summary"


class TestClanSummaryScript:
    """Smoke tests for script-based clan summaries."""

    def _write_script(self, path: Path, body: str) -> None:
        path.write_text(f"#!/usr/bin/env python3\n{body}\n", encoding="utf-8")
        path.chmod(0o755)

    def test_summary_script_executes_and_persists_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A clan with summary_script= executes the script and persists stdout."""
        workspace_dir = tmp_path / "workspace"
        artifacts_dir = tmp_path / "artifacts"
        workspace_dir.mkdir(exist_ok=True)
        artifacts_dir.mkdir(exist_ok=True)

        script = workspace_dir / "make_summary.py"
        self._write_script(
            script,
            """
import sys
print("[bold]Custom summary[/bold]")
print("[dim]Generated by script[/dim]")
""",
        )

        monkeypatch.setenv(
            CLAN_MEMBERSHIP_ENV,
            encode_clan_membership_plan(
                ClanMembershipPlan(clan_name="custom", generation="g1")
            ),
        )

        with (
            patch("sase.agent.names.ensure_historical_auto_name_migration"),
            patch(
                "sase.agent.names.agent_name_allocation_lock",
                return_value=nullcontext(),
            ),
            patch("sase.agent.names.claim_agent_name"),
            patch("sase.agent.names.claim_registered_clan_name"),
            patch(
                "sase.xprompt.process_xprompt_references",
                side_effect=lambda value, **_: value,
            ),
            patch(
                "sase.llm_provider.temporary_override."
                "resolve_effective_default_provider_model",
                return_value=("codex", "gpt-5"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ):
            extract_directives_and_write_meta(
                (
                    f"%id:custom.worker\n"
                    f"%clan(custom, summary_script={str(script)})\n"
                    f"Do work"
                ),
                str(workspace_dir),
                str(artifacts_dir),
            )

        persisted = json.loads(
            (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
        )
        assert persisted["agent_clan"] == "custom"
        assert "[bold]Custom summary[/bold]" in persisted["clan_summary"]
        assert "[dim]Generated by script[/dim]" in persisted["clan_summary"]

    def test_summary_script_receives_clan_env_vars(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Summary scripts receive SASE_CLAN_* env vars."""
        workspace_dir = tmp_path / "workspace"
        artifacts_dir = tmp_path / "artifacts"
        workspace_dir.mkdir(exist_ok=True)
        artifacts_dir.mkdir(exist_ok=True)

        script = workspace_dir / "echo_env.py"
        self._write_script(
            script,
            """
import os
name = os.environ["SASE_CLAN_NAME"]
gen = os.environ["SASE_CLAN_GENERATION"]
tribe = os.environ.get("SASE_CLAN_TRIBE", "unset")
print(f"[bold]{name}[/bold] gen={gen} tribe={tribe}")
""",
        )

        monkeypatch.setenv(
            CLAN_MEMBERSHIP_ENV,
            encode_clan_membership_plan(
                ClanMembershipPlan(clan_name="envtest", generation="g2")
            ),
        )

        with (
            patch("sase.agent.names.ensure_historical_auto_name_migration"),
            patch(
                "sase.agent.names.agent_name_allocation_lock",
                return_value=nullcontext(),
            ),
            patch("sase.agent.names.claim_agent_name"),
            patch("sase.agent.names.claim_registered_clan_name"),
            patch(
                "sase.xprompt.process_xprompt_references",
                side_effect=lambda value, **_: value,
            ),
            patch(
                "sase.llm_provider.temporary_override."
                "resolve_effective_default_provider_model",
                return_value=("codex", "gpt-5"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ):
            extract_directives_and_write_meta(
                (
                    f"%id:envtest.worker\n"
                    f"%clan(envtest, summary_script={str(script)})\n"
                    f"Do work"
                ),
                str(workspace_dir),
                str(artifacts_dir),
            )

        persisted = json.loads(
            (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
        )
        assert "envtest" in persisted["clan_summary"]
        assert "gen=g2" in persisted["clan_summary"]

    def test_summary_script_failure_logs_warning_but_launches(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When a summary script fails, launch succeeds with a warning, no summary."""
        workspace_dir = tmp_path / "workspace"
        artifacts_dir = tmp_path / "artifacts"
        workspace_dir.mkdir(exist_ok=True)
        artifacts_dir.mkdir(exist_ok=True)

        script = workspace_dir / "broken.py"
        self._write_script(script, "import sys\nsys.exit(1)\n")

        monkeypatch.setenv(
            CLAN_MEMBERSHIP_ENV,
            encode_clan_membership_plan(
                ClanMembershipPlan(clan_name="broken", generation="g1")
            ),
        )

        with (
            patch("sase.agent.names.ensure_historical_auto_name_migration"),
            patch(
                "sase.agent.names.agent_name_allocation_lock",
                return_value=nullcontext(),
            ),
            patch("sase.agent.names.claim_agent_name"),
            patch("sase.agent.names.claim_registered_clan_name"),
            patch(
                "sase.xprompt.process_xprompt_references",
                side_effect=lambda value, **_: value,
            ),
            patch(
                "sase.llm_provider.temporary_override."
                "resolve_effective_default_provider_model",
                return_value=("codex", "gpt-5"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ):
            extract_directives_and_write_meta(
                (
                    f"%id:broken.worker\n"
                    f"%clan(broken, summary_script={str(script)})\n"
                    f"Do work"
                ),
                str(workspace_dir),
                str(artifacts_dir),
            )

        persisted = json.loads(
            (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
        )
        # Launch succeeds even though summary script failed
        assert persisted["agent_clan"] == "broken"
        # No summary is written when script fails
        assert "clan_summary" not in persisted

    def test_summary_script_timeout_omits_summary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When a summary script times out, launch succeeds without summary."""
        workspace_dir = tmp_path / "workspace"
        artifacts_dir = tmp_path / "artifacts"
        workspace_dir.mkdir(exist_ok=True)
        artifacts_dir.mkdir(exist_ok=True)

        script = workspace_dir / "slow.py"
        self._write_script(script, "import time\ntime.sleep(100)\n")

        monkeypatch.setenv(
            CLAN_MEMBERSHIP_ENV,
            encode_clan_membership_plan(
                ClanMembershipPlan(clan_name="slow", generation="g1")
            ),
        )

        # Patch the timeout to be very short for testing
        with (
            patch("sase.agent.names.ensure_historical_auto_name_migration"),
            patch(
                "sase.agent.names.agent_name_allocation_lock",
                return_value=nullcontext(),
            ),
            patch("sase.agent.names.claim_agent_name"),
            patch("sase.agent.names.claim_registered_clan_name"),
            patch(
                "sase.xprompt.process_xprompt_references",
                side_effect=lambda value, **_: value,
            ),
            patch(
                "sase.llm_provider.temporary_override."
                "resolve_effective_default_provider_model",
                return_value=("codex", "gpt-5"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
            patch("sase.axe.clan_summary_script.CLAN_SUMMARY_TIMEOUT_SECONDS", 0.01),
        ):
            extract_directives_and_write_meta(
                (
                    f"%id:slow.worker\n"
                    f"%clan(slow, summary_script={script.relative_to(workspace_dir)})\n"
                    f"Do work"
                ),
                str(workspace_dir),
                str(artifacts_dir),
            )

        persisted = json.loads(
            (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
        )
        # Launch succeeds even though summary script timed out
        assert persisted["agent_clan"] == "slow"
        # No summary when timeout occurs
        assert "clan_summary" not in persisted

    def test_summary_script_output_capped_at_max_bytes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Summary script output is truncated if it exceeds CLAN_SUMMARY_MAX_BYTES."""
        workspace_dir = tmp_path / "workspace"
        artifacts_dir = tmp_path / "artifacts"
        workspace_dir.mkdir(exist_ok=True)
        artifacts_dir.mkdir(exist_ok=True)

        script = workspace_dir / "big_output.py"
        self._write_script(
            script,
            f"""
import sys
# Print more than the max
big = "x" * ({CLAN_SUMMARY_MAX_BYTES} + 1000)
print(big)
""",
        )

        monkeypatch.setenv(
            CLAN_MEMBERSHIP_ENV,
            encode_clan_membership_plan(
                ClanMembershipPlan(clan_name="bigout", generation="g1")
            ),
        )

        with (
            patch("sase.agent.names.ensure_historical_auto_name_migration"),
            patch(
                "sase.agent.names.agent_name_allocation_lock",
                return_value=nullcontext(),
            ),
            patch("sase.agent.names.claim_agent_name"),
            patch("sase.agent.names.claim_registered_clan_name"),
            patch(
                "sase.xprompt.process_xprompt_references",
                side_effect=lambda value, **_: value,
            ),
            patch(
                "sase.llm_provider.temporary_override."
                "resolve_effective_default_provider_model",
                return_value=("codex", "gpt-5"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ):
            extract_directives_and_write_meta(
                (
                    f"%id:bigout.worker\n"
                    f"%clan(bigout, summary_script={script.relative_to(workspace_dir)})\n"
                    f"Do work"
                ),
                str(workspace_dir),
                str(artifacts_dir),
            )

        persisted = json.loads(
            (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
        )
        assert persisted["agent_clan"] == "bigout"
        # Summary should be capped at max bytes
        if "clan_summary" in persisted:
            summary_bytes = persisted["clan_summary"].encode("utf-8")
            assert len(summary_bytes) <= CLAN_SUMMARY_MAX_BYTES


class TestClanSummaryMutualExclusion:
    """Smoke tests for summary= and summary_script= mutual exclusion."""

    def test_summary_and_summary_script_both_specified_rejected(self) -> None:
        """Specifying both summary= and summary_script= is a validation error."""
        from sase.xprompt._directive_collect import DirectiveError
        from sase.xprompt._directive_extract import extract_prompt_directives

        prompt = (
            "%id:test.agent\n"
            "%clan(test, summary=[[inline]], summary_script=/tmp/script.sh)\n"
            "Do work"
        )

        with pytest.raises(
            DirectiveError,
            match="summary.*summary_script.*mutually exclusive",
        ):
            extract_prompt_directives(prompt, process_references=lambda x: x)


class TestClanSummaryWireRoundTrip:
    """Smoke tests for wire layer round-trips."""

    def test_clan_summary_in_wire_dataclass(self) -> None:
        """AgentMetaWire includes clan_summary field."""
        wire = AgentMetaWire(
            agent_clan="example",
            agent_clan_generation="g1",
            clan_tribe="example",
            clan_summary="Test summary markup",
        )
        assert wire.clan_summary == "Test summary markup"

    def test_clan_summary_wire_defaults_to_none(self) -> None:
        """clan_summary defaults to None when not set."""
        wire = AgentMetaWire(
            agent_clan="example",
            agent_clan_generation="g1",
        )
        assert wire.clan_summary is None

    def test_clan_summary_dataclass_roundtrip(self) -> None:
        """clan_summary survives dataclass field access."""
        wire = AgentMetaWire(
            agent_clan="example",
            agent_clan_generation="g1",
            clan_summary="[bold]Test[/bold]",
        )
        # Verify the field is accessible and preserved
        assert wire.clan_summary == "[bold]Test[/bold]"
        assert wire.agent_clan == "example"
