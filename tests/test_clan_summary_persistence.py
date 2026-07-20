"""Runner coverage for launch-time clan summary persistence."""

from __future__ import annotations

from contextlib import nullcontext
import json
import os
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


def _write_script(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env python3\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _extract_clan_meta(
    tmp_path: Path,
    clan_args: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    output_path: Path | None = None,
) -> dict[str, object]:
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
        info = extract_directives_and_write_meta(
            f"%id:research.worker\n%clan(research, {clan_args})\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
            output_path=str(output_path) if output_path is not None else None,
        )

    persisted = json.loads(
        (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert info.meta == persisted
    assert persisted["agent_clan"] == "research"
    assert persisted["agent_clan_generation"] == "g1"
    return persisted


@pytest.mark.parametrize("bare_name", [False, True], ids=["relative-path", "path"])
def test_summary_script_persists_output_env_and_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bare_name: bool,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    script = workspace_dir / "make_summary"
    _write_script(
        script,
        """import os
import sys
sys.stderr.write("summary diagnostic\\n")
print(
    os.environ["SASE_CLAN_NAME"]
    + "|"
    + os.environ["SASE_CLAN_GENERATION"]
    + "|"
    + os.environ["SASE_CLAN_TRIBE"]
    + "   "
)""",
    )
    script_ref = "make_summary" if bare_name else "./make_summary"
    if bare_name:
        monkeypatch.setenv("PATH", f"{workspace_dir}{os.pathsep}{os.environ['PATH']}")
    output_path = tmp_path / "agent.log"

    meta = _extract_clan_meta(
        tmp_path,
        f"tribe=research, summary_script={script_ref}",
        monkeypatch,
        output_path=output_path,
    )

    assert meta["clan_tribe"] == "research"
    assert meta["clan_summary"] == "research|g1|research"
    assert "summary diagnostic" in output_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("script_body", "warning"),
    [
        ("raise SystemExit(7)", "exited with status 7"),
        ("print('   ')", "produced no output"),
    ],
    ids=["non-zero", "empty"],
)
def test_failed_summary_script_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    script_body: str,
    warning: str,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(workspace_dir / "make_summary", script_body)

    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = _extract_clan_meta(
            tmp_path,
            "summary_script=./make_summary",
            monkeypatch,
        )

    assert "clan_summary" not in meta
    assert warning in caplog.text


def test_timed_out_summary_script_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(workspace_dir / "make_summary", "import time\ntime.sleep(60)")
    monkeypatch.setattr(
        "sase.axe.clan_summary_script.CLAN_SUMMARY_TIMEOUT_SECONDS",
        0.05,
    )

    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = _extract_clan_meta(
            tmp_path,
            "summary_script=./make_summary",
            monkeypatch,
        )

    assert "clan_summary" not in meta
    assert "timed out after 0.1s" in caplog.text


def test_missing_summary_script_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = _extract_clan_meta(
            tmp_path,
            "summary_script=definitely_missing_summary_script",
            monkeypatch,
        )

    assert "clan_summary" not in meta
    assert "was not found" in caplog.text


def test_summary_script_output_is_capped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(
        workspace_dir / "make_summary",
        f"print('x' * {CLAN_SUMMARY_MAX_BYTES * 4}, end='')",
    )

    with (
        caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"),
        patch(
            "tempfile.TemporaryFile",
            side_effect=AssertionError("summary output must not use an uncapped spool"),
        ),
    ):
        meta = _extract_clan_meta(
            tmp_path,
            "summary_script=./make_summary",
            monkeypatch,
        )

    assert meta["clan_summary"] == "x" * CLAN_SUMMARY_MAX_BYTES
    assert "exceeded 32 KiB and was truncated" in caplog.text


def test_literal_summary_is_capped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta = _extract_clan_meta(
        tmp_path,
        f"summary=[[{'x' * 40000}]]",
        monkeypatch,
    )

    assert meta["clan_summary"] == "x" * CLAN_SUMMARY_MAX_BYTES
