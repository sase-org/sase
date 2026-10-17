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

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from sase.agent.env_hygiene import (
    scrub_agent_identity_env,
    scrub_chop_context_env,
    scrub_executor_ownership_env,
    scrub_proc_operation_env,
)

ROOT = Path(__file__).resolve().parents[1]
START_DIR = ROOT / "docs" / "start"
# Pedagogical order, matching the Get started nav tab.
TUTORIAL_PAGES = ("index.md", "install.md", "first-run.md", "first-change.md")

SHELL_FENCES = frozenset({"bash", "sh", "shell"})
SKIP_RE = re.compile(r"<!--\s*tutorial-test:\s*skip\b\s*(.*?)\s*-->")
EXPECT_RE = re.compile(r'<!--\s*tutorial-test:\s*expect\s+"((?:[^"\\]|\\.)*)"\s*-->')
FENCE_OPEN_RE = re.compile(r"```(\S*)\s*$")
_LAUNCH_RE = re.compile(r"sase\s+run(?:\s|$)")

MACHINE_NAME = "tutorialtest"
FAKEY_SCENARIO = "@ok"
BLOCK_TIMEOUT_SECONDS = 180.0
WAIT_TIMEOUT_SECONDS = 300.0
APPEAR_TIMEOUT_SECONDS = 60.0

# Per-agent context from the ambient run that must never leak into the
# tutorial subprocess: the tutorial behaves as a fresh user, not as a nested
# agent of whoever runs the test.
_EXTRA_SCRUB_KEYS = (
    "SASE_ARTIFACTS_DIR",
    "SASE_BEAD_ID",
    "SASE_PROMPT_ORIGIN",
    "SASE_PROMPT_SOURCE_SURFACE",
    "SASE_INSTRUCTIONS_FILE",
    "SASE_FINAL_TURN_NONCE",
    "SASE_FINALIZER_PLAN_DIGEST",
    "SASE_LAUNCH_SCRATCH_KEY",
)


@dataclass(frozen=True)
class TutorialBlock:
    """One fenced shell block in a tutorial page."""

    page: str
    step: int  # 1-based among shell blocks in the page, skipped or not
    script: str
    skipped: bool
    skip_reason: str
    expects: tuple[str, ...]


class TutorialStepError(AssertionError):
    """A tutorial step failed; the message names the page, step, and block."""

    def __init__(
        self,
        block: TutorialBlock,
        *,
        detail: str,
        output: str = "",
    ) -> None:
        lines = [
            f"tutorial step failed: docs/start/{block.page} step {block.step}",
            "command:",
            *[f"  {line}" for line in block.script.splitlines()],
            f"detail: {detail}",
        ]
        if output:
            tail = "\n".join(output.splitlines()[-80:])
            lines += ["output (last 80 lines):", tail]
        super().__init__("\n".join(lines))
        self.block = block


def parse_tutorial_blocks(page: str, text: str) -> list[TutorialBlock]:
    """Extract shell blocks and their ``tutorial-test`` markers from Markdown."""
    blocks: list[TutorialBlock] = []
    pending_skip: str | None = None
    pending_expects: list[str] = []
    in_fence = False
    fence_lines: list[str] = []
    step = 0

    def flush_markers() -> tuple[str | None, list[str]]:
        nonlocal pending_skip, pending_expects
        skip, expects = pending_skip, pending_expects
        pending_skip, pending_expects = None, []
        return skip, expects

    for line in text.splitlines():
        if not in_fence:
            match = FENCE_OPEN_RE.match(line.strip())
            if match and match.group(1) in SHELL_FENCES:
                in_fence = True
                fence_lines = []
                continue
            skip_match = SKIP_RE.search(line)
            if skip_match:
                pending_skip = skip_match.group(1).strip()
                continue
            expect_match = EXPECT_RE.search(line)
            if expect_match:
                pending_expects.append(expect_match.group(1).replace('\\"', '"'))
                continue
            if line.strip() in ("", "-->"):
                continue
            if line.strip().startswith("<!--"):
                flush_markers()
                continue
            flush_markers()
            continue
        if line.strip() == "```":
            in_fence = False
            step += 1
            skip, expects = flush_markers()
            blocks.append(
                TutorialBlock(
                    page=page,
                    step=step,
                    script="\n".join(fence_lines).strip(),
                    skipped=skip is not None,
                    skip_reason=skip or "",
                    expects=tuple(expects),
                )
            )
            continue
        fence_lines.append(line)
    return blocks


def is_launch_block(script: str) -> bool:
    """True when the block launches an agent the runner must wait for."""
    for line in script.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return bool(_LAUNCH_RE.match(stripped))
    return False


def sase_binary() -> Path:
    """Return the ``sase`` binary paired with the test interpreter."""
    candidate = Path(sys.executable).with_name("sase")
    if candidate.is_file():
        return candidate
    found = shutil.which("sase")
    if found:
        return Path(found)
    raise FileNotFoundError("no sase binary for tutorial tests")


@dataclass
class TutorialEnv:
    """Isolated HOME, work directory, and subprocess environment."""

    root: Path
    home: Path
    work: Path
    env: dict[str, str]


@dataclass
class AgentListProbe:
    """One ``sase agent list -a -j`` invocation, including failures."""

    rows: list[dict[str, object]]
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""


def prepare_tutorial_env(root: Path) -> TutorialEnv:
    """Build a fresh temporary HOME pinned to fakey for one tutorial run."""
    home = root / "home"
    work = root / "work"
    state_dir = root / "fakey-state"
    tmpdir = root / "tmp"
    config_dir = home / ".config" / "sase"
    sase_home = home / ".sase"
    for path in (config_dir, sase_home, work, state_dir, tmpdir):
        path.mkdir(parents=True, exist_ok=True)
    (sase_home / "machine_name").write_text(MACHINE_NAME + "\n", encoding="utf-8")
    (config_dir / "sase.yml").write_text(
        'llm_provider:\n  default_model: "fakey-large"\n', encoding="utf-8"
    )
    (config_dir / f"sase_{MACHINE_NAME}.yml").write_text(
        "id:\n"
        f"  username: {MACHINE_NAME}\n"
        f"  machine_name: {MACHINE_NAME}\n"
        'llm_provider:\n  default_model: "fakey-large"\n',
        encoding="utf-8",
    )
    env = dict(os.environ)
    scrub_agent_identity_env(env)
    scrub_chop_context_env(env)
    scrub_proc_operation_env(env)
    scrub_executor_ownership_env(env)
    for key in _EXTRA_SCRUB_KEYS:
        env.pop(key, None)
    binary = sase_binary()
    env["HOME"] = str(home)
    env["SASE_HOME"] = str(sase_home)
    env["SASE_TMPDIR"] = str(tmpdir)
    env["FAKEY_SCENARIO"] = FAKEY_SCENARIO
    env["FAKEY_STATE_DIR"] = str(state_dir)
    env["PATH"] = str(binary.parent) + os.pathsep + env.get("PATH", "")
    return TutorialEnv(root=root, home=home, work=work, env=env)


def execute_block(
    script: str,
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float = BLOCK_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run one tutorial block the way a reader's shell would."""
    return subprocess.run(
        ["bash", "-c", script],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _sase_home(tutorial: TutorialEnv) -> Path:
    raw = tutorial.env.get("SASE_HOME")
    if raw:
        return Path(raw)
    return tutorial.home / ".sase"


def _bounded_text(text: str, *, max_lines: int = 40, max_chars: int = 4000) -> str:
    if not text:
        return "(empty)"
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = ["...", *lines[-max_lines:]]
    clipped = "\n".join(lines)
    if len(clipped) > max_chars:
        return "..." + clipped[-max_chars:]
    return clipped


def _artifact_agent_names(tutorial: TutorialEnv) -> list[str]:
    """Return agent names recorded in ``agent_meta.json`` under the tutorial HOME."""
    names: list[str] = []
    seen: set[str] = set()
    projects = _sase_home(tutorial) / "projects"
    if not projects.is_dir():
        return names
    for meta in projects.rglob("agent_meta.json"):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        name = data.get("name")
        if not name or not isinstance(name, str) or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _artifact_dir_dump(tutorial: TutorialEnv, *, max_paths: int = 20) -> str:
    projects = _sase_home(tutorial) / "projects"
    if not projects.is_dir():
        return f"(no projects dir at {projects})"
    paths = sorted(projects.rglob("agent_meta.json"))
    if not paths:
        children = sorted(path.name for path in projects.iterdir())
        label = ", ".join(children) if children else "none"
        return f"(no agent_meta.json under {projects}; children: {label})"
    lines: list[str] = []
    for path in paths[:max_paths]:
        done = path.with_name("done.json").is_file()
        running = path.with_name("running.json").is_file()
        lines.append(f"  {path} done={done} running={running}")
    extra = len(paths) - max_paths
    if extra > 0:
        lines.append(f"  ... {extra} more")
    return "\n".join(lines)


def _list_agent_rows(tutorial: TutorialEnv) -> AgentListProbe:
    """List running and recently completed agents in the tutorial HOME."""
    binary = sase_binary()
    try:
        result = subprocess.run(
            [str(binary), "agent", "list", "-a", "-j"],
            cwd=str(tutorial.work),
            env=tutorial.env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except OSError as exc:
        return AgentListProbe(rows=[], error=f"OSError: {exc}")
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return AgentListProbe(
            rows=[],
            returncode=None,
            stdout=stdout,
            stderr=stderr,
            error="timed out after 60s",
        )
    rows: list[dict[str, object]] = []
    try:
        parsed = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        return AgentListProbe(
            rows=[],
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            error=f"invalid JSON: {exc}",
        )
    if isinstance(parsed, list):
        rows = [row for row in parsed if isinstance(row, dict)]
    return AgentListProbe(
        rows=rows,
        returncode=result.returncode,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
        error="" if result.returncode == 0 else f"exit {result.returncode}",
    )


def _new_agent_names(
    rows: list[dict[str, object]],
    *,
    known_names: frozenset[str],
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        name = row.get("name")
        if not isinstance(name, str) or not name or name in known_names or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _known_agent_names(tutorial: TutorialEnv) -> frozenset[str]:
    listed = _new_agent_names(_list_agent_rows(tutorial).rows, known_names=frozenset())
    return frozenset(listed) | frozenset(_artifact_agent_names(tutorial))


def _launch_diagnostics(
    tutorial: TutorialEnv,
    *,
    launch_result: subprocess.CompletedProcess[str] | None,
    probe: AgentListProbe,
    known_names: frozenset[str],
) -> str:
    parts: list[str] = []
    if launch_result is None:
        parts.append("sase run result: (not captured)")
    else:
        parts.append(f"sase run exit {launch_result.returncode}")
        parts.append("sase run stdout:")
        parts.append(_bounded_text(launch_result.stdout or ""))
        parts.append("sase run stderr:")
        parts.append(_bounded_text(launch_result.stderr or ""))
    if probe.error:
        parts.append(f"sase agent list -a error: {probe.error}")
    rc = "n/a" if probe.returncode is None else str(probe.returncode)
    parts.append(f"sase agent list -a exit {rc}")
    parts.append("sase agent list -a stdout:")
    parts.append(_bounded_text(probe.stdout))
    if probe.stderr.strip():
        parts.append("sase agent list -a stderr:")
        parts.append(_bounded_text(probe.stderr))
    listed = [
        f"{row.get('name')}:{row.get('status')}"
        for row in probe.rows
        if row.get("name")
    ]
    parts.append(f"listed agents: {listed or '(none)'}")
    parts.append(
        "known names before launch: "
        + (", ".join(sorted(known_names)) if known_names else "(none)")
    )
    disk_names = _artifact_agent_names(tutorial)
    parts.append(
        "artifact agent_meta names: "
        + (", ".join(disk_names) if disk_names else "(none)")
    )
    parts.append("artifact dirs:")
    parts.append(_artifact_dir_dump(tutorial))
    return "\n".join(parts)


def wait_for_launch(
    block: TutorialBlock,
    tutorial: TutorialEnv,
    *,
    launch_result: subprocess.CompletedProcess[str] | None = None,
    known_names: frozenset[str] = frozenset(),
) -> None:
    """Wait for a ``sase run`` block's agents to reach a terminal success.

    Fakey can finish between ``sase run`` returning and the first poll, and a
    just-spawned agent is ``STARTING`` before ``RUNNING``. Listing therefore
    includes recently completed agents, treats any new name as appeared, and
    falls back to ``agent_meta.json`` on disk when the listing index is stale.
    """
    deadline = time.monotonic() + APPEAR_TIMEOUT_SECONDS
    probe = AgentListProbe(rows=[])
    names: list[str] = []
    while True:
        probe = _list_agent_rows(tutorial)
        names = _new_agent_names(probe.rows, known_names=known_names)
        if not names:
            names = [
                name
                for name in _artifact_agent_names(tutorial)
                if name not in known_names
            ]
        if names or time.monotonic() >= deadline:
            break
        time.sleep(2)  # sase-test-wait: poll for agent registration
    if not names:
        raise TutorialStepError(
            block,
            detail="no agents appeared after `sase run` within 60s",
            output=_launch_diagnostics(
                tutorial,
                launch_result=launch_result,
                probe=probe,
                known_names=known_names,
            ),
        )
    binary = sase_binary()
    try:
        settled = subprocess.run(
            [str(binary), "agent", "wait", *names, "-t", "300", "-q"],
            cwd=str(tutorial.work),
            env=tutorial.env,
            capture_output=True,
            text=True,
            timeout=WAIT_TIMEOUT_SECONDS + 60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TutorialStepError(
            block,
            detail=f"timed out waiting 300s for agents {names}",
            output=_launch_diagnostics(
                tutorial,
                launch_result=launch_result,
                probe=probe,
                known_names=known_names,
            ),
        ) from exc
    output = (settled.stdout or "") + (settled.stderr or "")
    if settled.returncode != 0:
        raise TutorialStepError(
            block,
            detail=f"`sase agent wait` exited {settled.returncode}",
            output=output
            + "\n"
            + _launch_diagnostics(
                tutorial,
                launch_result=launch_result,
                probe=probe,
                known_names=known_names,
            ),
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
            _known_agent_names(tutorial)
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


def tutorial_pages_in_order() -> list[Path]:
    """Return ``docs/start/`` pages in nav order, then any stragglers sorted."""
    pages = [
        START_DIR / name for name in TUTORIAL_PAGES if (START_DIR / name).is_file()
    ]
    known = set(TUTORIAL_PAGES)
    pages += sorted(
        (path for path in START_DIR.glob("*.md") if path.name not in known),
        key=lambda path: path.name,
    )
    return pages


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
        "tests.test_tutorials._list_agent_rows",
        lambda _tutorial: AgentListProbe(
            rows=[{"name": "home-2", "status": "STARTING"}],
            returncode=0,
            stdout='[{"name":"home-2","status":"STARTING"}]',
        ),
    )
    monkeypatch.setattr("tests.test_tutorials._artifact_agent_names", lambda _t: [])
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
        "tests.test_tutorials._list_agent_rows",
        lambda _tutorial: AgentListProbe(
            rows=[{"name": "home-2", "status": "DONE"}],
            returncode=0,
            stdout='[{"name":"home-2","status":"DONE"}]',
        ),
    )
    monkeypatch.setattr("tests.test_tutorials._artifact_agent_names", lambda _t: [])
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
        "tests.test_tutorials._list_agent_rows",
        lambda _tutorial: AgentListProbe(rows=[], returncode=0, stdout="[]"),
    )
    monkeypatch.setattr(
        "tests.test_tutorials._artifact_agent_names", lambda _t: ["home-2"]
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
        "tests.test_tutorials._list_agent_rows",
        lambda _tutorial: AgentListProbe(
            rows=[],
            returncode=0,
            stdout="[]",
            stderr="listing skipped",
        ),
    )
    monkeypatch.setattr("tests.test_tutorials._artifact_agent_names", lambda _t: [])
    monkeypatch.setattr("tests.test_tutorials.APPEAR_TIMEOUT_SECONDS", 0)
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
