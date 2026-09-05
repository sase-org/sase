"""Successful clan summary script execution coverage."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

import pytest
from rich.text import Text

from sase.axe.clan_summary_script import CLAN_SUMMARY_STDERR_LOG
from tests._clan_summary_persistence_helpers import (
    extract_clan_meta,
    write_script,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN


@pytest.mark.parametrize("bare_name", [False, True], ids=["relative-path", "path"])
def test_summary_script_persists_output_env_and_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bare_name: bool,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    script = workspace_dir / "make_summary"
    write_script(
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

    meta = extract_clan_meta(
        tmp_path,
        f"tribe=research, summary_script={script_ref}",
        monkeypatch,
        output_path=output_path,
    )

    assert meta["clan_tribe"] == "research"
    assert meta["clan_summary"] == "research|g1|research"
    assert "summary diagnostic" in output_path.read_text(encoding="utf-8")
    artifact = (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).read_text(
        encoding="utf-8"
    )
    assert "attempt: directive-extraction" in artifact
    assert "outcome: ok" in artifact
    assert f"argv: {script}" in artifact
    assert "SASE_CLAN_NAME" in artifact
    assert "SASE_CLAN_GENERATION" in artifact
    assert "SASE_CLAN_TRIBE" in artifact
    assert "summary diagnostic" in artifact
    assert "research|g1|research" not in artifact


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
    write_script(
        workspace_dir / script_name,
        "import json\nimport sys\nprint(json.dumps(sys.argv[1:]))",
    )
    if use_path:
        monkeypatch.setenv("PATH", f"{workspace_dir}{os.pathsep}{os.environ['PATH']}")

    meta = extract_clan_meta(
        tmp_path,
        f"summary_script=[[{script_value}]]",
        monkeypatch,
    )

    assert json.loads(str(meta["clan_summary"])) == ["alpha", "two words"]
    assert not (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).exists()


def test_summary_script_literal_executable_path_with_spaces_wins_before_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    write_script(workspace_dir / "make summary", "print('literal path')")

    meta = extract_clan_meta(
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
    write_script(
        workspace_dir / "make_summary",
        """import json
import os
print(json.dumps({
    key: os.environ.get(key)
    for key in (
        "CUSTOM_LAUNCH_VALUE",
        "SASE_EPIC_PLAN_REF",
        "SASE_EPIC_PLAN_SNAPSHOT",
        "SASE_EPIC_BEAD_ID",
        "SASE_EPIC_CLAN_TRIBE",
        "SASE_CLAN_TRIBE",
    )
}))""",
    )
    monkeypatch.setenv("CUSTOM_LAUNCH_VALUE", "preserved")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", "plans/epic.md")
    monkeypatch.setenv("SASE_EPIC_PLAN_SNAPSHOT", "/state/epic.md")
    monkeypatch.setenv("SASE_EPIC_BEAD_ID", "sase-epic")
    monkeypatch.setenv("SASE_EPIC_CLAN_TRIBE", "epic")
    monkeypatch.setenv("SASE_CLAN_TRIBE", "ambient-value-must-not-leak")

    meta = extract_clan_meta(
        tmp_path,
        "summary_script=./make_summary",
        monkeypatch,
    )

    assert meta["epic_plan_ref"] == "plans/epic.md"
    assert meta["epic_plan_snapshot"] == "/state/epic.md"
    assert meta["epic_bead_id"] == "sase-epic"
    inherited = json.loads(str(meta["clan_summary"]))
    assert inherited == {
        "CUSTOM_LAUNCH_VALUE": "preserved",
        "SASE_EPIC_PLAN_REF": "plans/epic.md",
        "SASE_EPIC_PLAN_SNAPSHOT": "/state/epic.md",
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

    meta = extract_clan_meta(
        tmp_path,
        "summary_script=sase_clan_summary_plan",
        monkeypatch,
    )

    rendered = Text.from_markup(str(meta["clan_summary"]))
    assert "▸ PLAN · epic · 1 phase" in rendered.plain
    assert "Title: Approved implementation" in rendered.plain
    assert "Implement the requested change" in rendered.plain


def _spy_killpg(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    signals: list[int] = []
    real_killpg = os.killpg

    def spy_killpg(pid: int, sig: int) -> None:
        signals.append(sig)
        real_killpg(pid, sig)

    monkeypatch.setattr("sase.axe.clan_summary_script.os.killpg", spy_killpg)
    return signals


@pytest.mark.skipif(os.name != "posix", reason="process-group SIGTERM/SIGKILL")
def test_timed_out_summary_script_exits_on_sigterm_without_sigkill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    write_script(
        workspace_dir / "make_summary",
        "import signal\n"
        "import sys\n"
        "import time\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "time.sleep(30)\n",
    )
    monkeypatch.setattr(
        "sase.axe.clan_summary_script.CLAN_SUMMARY_TIMEOUT_SECONDS",
        0.4,
    )
    monkeypatch.setattr(
        "sase.axe.clan_summary_script.CLAN_SUMMARY_KILL_GRACE_SECONDS",
        2.0,
    )
    signals = _spy_killpg(monkeypatch)
    started = time.monotonic()

    meta = extract_clan_meta(
        tmp_path,
        "summary_script=./make_summary",
        monkeypatch,
    )

    elapsed = time.monotonic() - started
    assert "clan_summary" not in meta
    assert signal.SIGTERM in signals
    assert signal.SIGKILL not in signals
    assert elapsed < 2.0
    artifact = (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).read_text(
        encoding="utf-8"
    )
    assert "outcome: timeout" in artifact


@pytest.mark.skipif(os.name != "posix", reason="process-group SIGTERM/SIGKILL")
def test_timed_out_summary_script_escalates_to_sigkill_when_sigterm_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    write_script(
        workspace_dir / "make_summary",
        "import signal\n"
        "import time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(30)\n",
    )
    monkeypatch.setattr(
        "sase.axe.clan_summary_script.CLAN_SUMMARY_TIMEOUT_SECONDS",
        0.4,
    )
    monkeypatch.setattr(
        "sase.axe.clan_summary_script.CLAN_SUMMARY_KILL_GRACE_SECONDS",
        0.3,
    )
    signals = _spy_killpg(monkeypatch)
    started = time.monotonic()

    meta = extract_clan_meta(
        tmp_path,
        "summary_script=./make_summary",
        monkeypatch,
    )

    elapsed = time.monotonic() - started
    assert "clan_summary" not in meta
    assert signal.SIGTERM in signals
    assert signal.SIGKILL in signals
    assert elapsed >= 0.3
    artifact = (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).read_text(
        encoding="utf-8"
    )
    assert "outcome: timeout" in artifact
