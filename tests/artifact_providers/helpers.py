from __future__ import annotations

from pathlib import Path
import subprocess

from sase.artifact_ref_models import ArtifactRefContext, ArtifactRefRepository
from sase.artifact_ref_prompt_context import PromptRefContext


def init_git_repo(path: Path) -> str:
    """Initialize a throwaway git repo at *path* and return HEAD's full sha."""

    path.mkdir(parents=True, exist_ok=True)
    run = lambda *args: subprocess.run(  # noqa: E731
        ["git", *args], cwd=path, check=True, capture_output=True, text=True
    )
    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    # A resolvable origin remote is required for VCS-provider classification
    # (see vcs_provider._registry._classify_by_url); any local path works.
    run("remote", "add", "origin", str(path))
    (path / "README.md").write_text("# Test\n", encoding="utf-8")
    run("add", "README.md")
    run("commit", "-q", "-m", "Initial commit")
    return run("rev-parse", "HEAD").stdout.strip()


def stitch_context(
    repo_path: Path,
    *,
    repo_name: str = "sase",
    kind: str = "primary",
) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(),
        chats_root=repo_path / "chats",
        artifact_index_path=repo_path / "artifacts" / "index.jsonl",
        repositories=(
            ArtifactRefRepository(
                name=repo_name,
                checkout_paths=(repo_path,),
                kind=kind,
            ),
        ),
        projects=(),
    )


def ref_context_for(
    context: ArtifactRefContext,
    *,
    primary_repo: str | None = None,
) -> PromptRefContext:
    return PromptRefContext(
        artifact_context=context,
        project=None,
        primary_repo=primary_repo,
        workspace_dir=None,
        workspace_num=None,
        origin="explicit",
        vcs_ref=None,
    )
