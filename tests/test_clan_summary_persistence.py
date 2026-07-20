"""Runner coverage for launch-time clan summary persistence."""

from __future__ import annotations

from contextlib import nullcontext
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.text import Text

from sase.agent.clan_membership import (
    CLAN_MEMBERSHIP_ENV,
    ClanMembershipPlan,
    encode_clan_membership_plan,
)
from sase.axe.clan_summary_script import (
    CLAN_SUMMARY_MAX_BYTES,
    CLAN_SUMMARY_TIMEOUT_SECONDS,
)
from sase.axe.run_agent_directives import extract_directives_and_write_meta
from tests.plan_validation_helpers import VALID_EPIC_PLAN


def _write_script(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env python3\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def test_summary_script_default_timeout_covers_blocking_refresh() -> None:
    assert CLAN_SUMMARY_TIMEOUT_SECONDS == 20.0


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
    ("script_name", "script_value", "use_path"),
    [
        (
            "make_summary",
            'make_summary alpha "two words"',
            True,
        ),
        (
            "make_summary",
            './make_summary alpha "two words"',
            False,
        ),
    ],
    ids=["bare-command-argv", "relative-path-argv"],
)
def test_summary_script_persists_shell_quoted_argv_without_a_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script_name: str,
    script_value: str,
    use_path: bool,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(
        workspace_dir / script_name,
        "import json\nimport sys\nprint(json.dumps(sys.argv[1:]))",
    )
    if use_path:
        monkeypatch.setenv("PATH", f"{workspace_dir}{os.pathsep}{os.environ['PATH']}")

    meta = _extract_clan_meta(
        tmp_path,
        f"summary_script=[[{script_value}]]",
        monkeypatch,
    )

    assert json.loads(str(meta["clan_summary"])) == ["alpha", "two words"]


def test_summary_script_literal_executable_path_with_spaces_wins_before_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(workspace_dir / "make summary", "print('literal path')")

    meta = _extract_clan_meta(
        tmp_path,
        "summary_script=[[./make summary]]",
        monkeypatch,
    )

    assert meta["clan_summary"] == "literal path"


def test_summary_script_inherits_launch_environment_and_epic_variables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_script(
        workspace_dir / "make_summary",
        """import json
import os
print(json.dumps({
    key: os.environ.get(key)
    for key in (
        "CUSTOM_LAUNCH_VALUE",
        "SASE_EPIC_PLAN_REF",
        "SASE_EPIC_BEAD_ID",
        "SASE_EPIC_CLAN_TRIBE",
        "SASE_CLAN_TRIBE",
    )
}))""",
    )
    monkeypatch.setenv("CUSTOM_LAUNCH_VALUE", "preserved")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", "plans/epic.md")
    monkeypatch.setenv("SASE_EPIC_BEAD_ID", "sase-epic")
    monkeypatch.setenv("SASE_EPIC_CLAN_TRIBE", "epic")
    monkeypatch.setenv("SASE_CLAN_TRIBE", "ambient-value-must-not-leak")

    meta = _extract_clan_meta(
        tmp_path,
        "summary_script=./make_summary",
        monkeypatch,
    )

    assert meta["epic_plan_ref"] == "plans/epic.md"
    assert meta["epic_bead_id"] == "sase-epic"
    inherited = json.loads(str(meta["clan_summary"]))
    assert inherited == {
        "CUSTOM_LAUNCH_VALUE": "preserved",
        "SASE_EPIC_PLAN_REF": "plans/epic.md",
        "SASE_EPIC_BEAD_ID": "sase-epic",
        "SASE_EPIC_CLAN_TRIBE": "epic",
        "SASE_CLAN_TRIBE": None,
    }


def test_generic_plan_summary_entry_point_uses_epic_environment_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    (workspace_dir / "epic.md").write_text(VALID_EPIC_PLAN, encoding="utf-8")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", "epic.md")

    meta = _extract_clan_meta(
        tmp_path,
        "summary_script=sase_clan_summary_plan",
        monkeypatch,
    )

    rendered = Text.from_markup(str(meta["clan_summary"]))
    assert "▸ PLAN · epic · 1 phase" in rendered.plain
    assert "Title: Approved implementation" in rendered.plain
    assert "Implement the requested change" in rendered.plain


def test_malformed_summary_script_quoting_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = _extract_clan_meta(
            tmp_path,
            'summary_script=[[missing "quote]]',
            monkeypatch,
        )

    assert "clan_summary" not in meta
    assert "No closing quotation" in caplog.text


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
        "print('x' * 40000, end='')",
    )

    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
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
