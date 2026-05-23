"""Shared helpers for run_agent_exec tests."""

import subprocess
from pathlib import Path

from sase.axe.run_agent_exec import AgentExecContext


def make_exec_ctx(
    tmp_path: Path,
    *,
    is_home_mode: bool,
    project_name: str = "sase",
) -> AgentExecContext:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.sase"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        workspace_num=1,
        timestamp="20260408_120000",
        update_target="",
        project_name=project_name,
        is_home_mode=is_home_mode,
        artifacts_dir=str(artifacts),
        artifacts_timestamp="20260408_120000",
        vcs_tag=None,
        agent_name="agent",
        agent_model=None,
        agent_llm_provider=None,
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
    )


def run_command(cwd: Path, *args: str) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def write_markdown_sources(tmp_path: Path, count: int) -> list[str]:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    sources = []
    for index in range(count):
        path = docs / f"note_{index:02d}.md"
        path.write_text(f"# Note {index}\n")
        sources.append(str(path))
    return sources
