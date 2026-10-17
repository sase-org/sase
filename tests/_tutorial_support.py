"""Shared data models and helpers for the tutorial tests."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

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
