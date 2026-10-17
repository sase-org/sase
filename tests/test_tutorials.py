"""Executable checks for the Get started tutorials (``docs/start/``).

Every fenced shell block in ``docs/start/`` is a tutorial step by default.
The slow end-to-end test below executes the unskipped blocks in a fresh
temporary ``HOME`` against :doc:`fakey </fakey>` (the default model is pinned
to ``fakey-large`` through configuration, never by editing the page text),
asserts exit codes and ``expect`` markers, and waits for each launched run to
succeed. Blocks that need a human carry ``tutorial-test`` markers on the line
before their fence::

    <!-- tutorial-test: skip <reason> -->
    <!-- tutorial-test: expect "<substring>" -->
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from tests._tutorial_launch import AgentListProbe, known_agent_names, wait_for_launch
from tests._tutorial_support import (
    APPEAR_TIMEOUT_SECONDS,
    BLOCK_TIMEOUT_SECONDS,
    EXPECT_RE,
    FAKEY_SCENARIO,
    FENCE_OPEN_RE,
    MACHINE_NAME,
    ROOT,
    SHELL_FENCES,
    SKIP_RE,
    START_DIR,
    TUTORIAL_PAGES,
    WAIT_TIMEOUT_SECONDS,
    TutorialBlock,
    TutorialEnv,
    TutorialStepError,
    execute_block,
    is_launch_block,
    parse_tutorial_blocks,
    prepare_tutorial_env,
    sase_binary,
    tutorial_pages_in_order,
)


def run_tutorial_file(path: Path, tutorial: TutorialEnv) -> int:
    """Execute every unskipped block in one page; return the executed count."""
    blocks = parse_tutorial_blocks(path.name, path.read_text(encoding="utf-8"))
    executed = 0
    for block in blocks:
        if block.skipped:
            continue
        executed += 1
        known_names = (
            known_agent_names(tutorial)
            if is_launch_block(block.script)
            else frozenset()
        )
        try:
            result = execute_block(block.script, cwd=tutorial.work, env=tutorial.env)
        except subprocess.TimeoutExpired as exc:
            raise TutorialStepError(
                block, detail=f"timed out after {BLOCK_TIMEOUT_SECONDS:.0f}s"
            ) from exc
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            raise TutorialStepError(
                block,
                detail=f"exit code {result.returncode}, expected 0",
                output=output,
            )
        for expected in block.expects:
            if expected not in output:
                raise TutorialStepError(
                    block,
                    detail=f"expected output {expected!r} not found",
                    output=output,
                )
        if is_launch_block(block.script):
            wait_for_launch(
                block,
                tutorial,
                launch_result=result,
                known_names=known_names,
            )
    return executed


def test_tutorial_markers_parse(tmp_path: Path) -> None:
    text = (
        "Some prose.\n"
        "\n"
        '<!-- tutorial-test: expect "sase" -->\n'
        "```bash\n"
        "sase version\n"
        "```\n"
        "\n"
        "<!-- tutorial-test: skip opens a TUI -->\n"
        "```bash\n"
        "sase tui\n"
        "```\n"
        "\n"
        "```text\n"
        "not a shell block\n"
        "```\n"
    )
    blocks = parse_tutorial_blocks("sample.md", text)
    assert len(blocks) == 2
    assert blocks[0].step == 1
    assert not blocks[0].skipped
    assert blocks[0].expects == ("sase",)
    assert blocks[1].step == 2
    assert blocks[1].skipped
    assert blocks[1].skip_reason == "opens a TUI"
    assert blocks[1].expects == ()


def test_tutorial_launch_detection() -> None:
    assert is_launch_block('sase run "+home do a thing"')
    assert is_launch_block('# comment\nsase run "+home do a thing"')
    assert not is_launch_block("sase version")
    assert not is_launch_block("sase agent list")


def test_tutorial_broken_step_reports_page_step_and_block(
    tmp_path: Path,
) -> None:
    page = tmp_path / "broken.md"
    page.write_text("```bash\nexit 3\n```\n", encoding="utf-8")
    tutorial = TutorialEnv(
        root=tmp_path, home=tmp_path, work=tmp_path, env=dict(os.environ)
    )
    with pytest.raises(TutorialStepError, match=r"broken\.md step 1") as exc_info:
        run_tutorial_file(page, tutorial)
    message = str(exc_info.value)
    assert "exit 3" in message
    assert "exit code 3" in message


def test_tutorial_unmet_expect_reports_readably(tmp_path: Path) -> None:
    page = tmp_path / "expect.md"
    page.write_text(
        '<!-- tutorial-test: expect "goodbye" -->\n```bash\necho hello\n```\n',
        encoding="utf-8",
    )
    tutorial = TutorialEnv(
        root=tmp_path, home=tmp_path, work=tmp_path, env=dict(os.environ)
    )
    with pytest.raises(TutorialStepError, match="expected output") as exc_info:
        run_tutorial_file(page, tutorial)
    assert "'goodbye'" in str(exc_info.value)


def _launch_block() -> TutorialBlock:
    return TutorialBlock(
        page="first-change.md",
        step=1,
        script='sase run "+home create welcome.txt"',
        skipped=False,
        skip_reason="",
        expects=(),
    )


def _wait_tutorial(tmp_path: Path) -> TutorialEnv:
    home = tmp_path / "home"
    work = tmp_path / "work"
    sase_home = home / ".sase"
    work.mkdir()
    sase_home.mkdir(parents=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["SASE_HOME"] = str(sase_home)
    return TutorialEnv(root=tmp_path, home=home, work=work, env=env)


def test_wait_for_launch_treats_starting_as_appeared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tutorial = _wait_tutorial(tmp_path)
    monkeypatch.setattr(
        "tests._tutorial_launch._list_agent_rows",
        lambda _tutorial: AgentListProbe(
            rows=[{"name": "home-2", "status": "STARTING"}],
            returncode=0,
            stdout='[{"name":"home-2","status":"STARTING"}]',
        ),
    )
    monkeypatch.setattr("tests._tutorial_launch._artifact_agent_names", lambda _t: [])
    waited: list[list[str]] = []

    def fake_run(
        argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        waited.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    wait_for_launch(_launch_block(), tutorial, known_names=frozenset({"home-1"}))
    assert waited and "home-2" in waited[0]


def test_wait_for_launch_treats_already_done_as_appeared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tutorial = _wait_tutorial(tmp_path)
    monkeypatch.setattr(
        "tests._tutorial_launch._list_agent_rows",
        lambda _tutorial: AgentListProbe(
            rows=[{"name": "home-2", "status": "DONE"}],
            returncode=0,
            stdout='[{"name":"home-2","status":"DONE"}]',
        ),
    )
    monkeypatch.setattr("tests._tutorial_launch._artifact_agent_names", lambda _t: [])
    waited: list[list[str]] = []

    def fake_run(
        argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        waited.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    wait_for_launch(_launch_block(), tutorial, known_names=frozenset({"home-1"}))
    assert waited and "home-2" in waited[0]


def test_wait_for_launch_uses_disk_meta_when_listing_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tutorial = _wait_tutorial(tmp_path)
    monkeypatch.setattr(
        "tests._tutorial_launch._list_agent_rows",
        lambda _tutorial: AgentListProbe(rows=[], returncode=0, stdout="[]"),
    )
    monkeypatch.setattr(
        "tests._tutorial_launch._artifact_agent_names", lambda _t: ["home-2"]
    )
    waited: list[list[str]] = []

    def fake_run(
        argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        waited.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    wait_for_launch(_launch_block(), tutorial, known_names=frozenset({"home-1"}))
    assert waited and "home-2" in waited[0]


def test_wait_for_launch_timeout_includes_run_output_and_home_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tutorial = _wait_tutorial(tmp_path)
    meta = (
        Path(tutorial.env["SASE_HOME"])
        / "projects"
        / "home"
        / "artifacts"
        / "ace-run"
        / "agent_meta.json"
    )
    meta.parent.mkdir(parents=True)
    meta.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "tests._tutorial_launch._list_agent_rows",
        lambda _tutorial: AgentListProbe(
            rows=[],
            returncode=0,
            stdout="[]",
            stderr="listing skipped",
        ),
    )
    monkeypatch.setattr("tests._tutorial_launch._artifact_agent_names", lambda _t: [])
    monkeypatch.setattr("tests._tutorial_launch.APPEAR_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    launch_result = subprocess.CompletedProcess(
        ["bash", "-c", "sase run"],
        0,
        "Agent started (PID 12345)\n",
        "warning: fakey\n",
    )
    with pytest.raises(TutorialStepError, match="no agents appeared") as exc_info:
        wait_for_launch(
            _launch_block(),
            tutorial,
            launch_result=launch_result,
            known_names=frozenset({"home-1"}),
        )
    message = str(exc_info.value)
    assert "sase run exit 0" in message
    assert "Agent started (PID 12345)" in message
    assert "warning: fakey" in message
    assert "sase agent list -a exit 0" in message
    assert "known names before launch: home-1" in message
    assert "agent_meta.json" in message


@pytest.mark.slow
def test_start_tutorials_pass_on_fakey(tmp_path: Path) -> None:
    """Run every marked ``docs/start/`` shell block against fakey."""
    try:
        sase_binary()
    except FileNotFoundError:
        pytest.skip("no sase binary for tutorial tests")
    tutorial = prepare_tutorial_env(tmp_path / "tutorial-home")
    pages = tutorial_pages_in_order()
    assert [path.name for path in pages[:4]] == list(TUTORIAL_PAGES)
    executed = 0
    for path in pages:
        executed += run_tutorial_file(path, tutorial)
    # Guard against a silent skip-all pass: install, first-run, and
    # first-change each contribute at least one executable step today.
    assert executed >= 4
