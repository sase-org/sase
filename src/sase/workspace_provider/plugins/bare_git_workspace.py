"""Bare-git workspace plugin implementation.

Handles workspace management for git repositories backed by a local bare
remote (i.e. the origin URL is a filesystem path rather than a hosted
service like GitHub).
"""

import configparser
from itertools import islice
import os
import re
import subprocess
from pathlib import Path

from sase.core.paths import is_valid_sase_project_name, sase_subdir
from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider._hookspec import (
    LocalRepoCandidate,
    LocalRepoCandidates,
    ParsedRepoRef,
    RepoCreateResult,
    RepoCreationField,
    RepoCreationForm,
    RepoProbe,
    ResolvedRef,
    WorkflowMetadata,
    hookimpl,
)
from sase.workspace_provider.plugins.bare_git_ref import (
    ResolvedGitRef,
    is_bare_git_project,
    resolve_git_ref,
    set_bare_repo_dir,
)
from sase.workspace_provider.plugins.bare_git_init import init_bare_git_project
from sase.workspace_provider.plugins.bare_git_submit import (
    prepare_mail_git,
    submit_bare_git,
)

# Re-export for backwards compatibility with external imports
__all__ = [
    "BareGitWorkspacePlugin",
    "ResolvedGitRef",
    "init_bare_git_project",
    "resolve_git_ref",
    "set_bare_repo_dir",
]


def _valid_project_name_from_git_name(name: str) -> str | None:
    project_name = re.sub(r"_\d+$", "", name)
    if not is_valid_sase_project_name(project_name):
        return None
    return project_name


def _run_git(args: list[str], *, cwd: str) -> subprocess.CompletedProcess[str]:
    result, _ = run_with_git_lock_retry(
        lambda: subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        ),
        cwd=cwd,
    )
    return result


def _absolute_path(value: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def _origin_from_config(config_path: Path) -> str:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(config_path, encoding="utf-8")
        return parser.get('remote "origin"', "url", fallback="").strip()
    except (OSError, configparser.Error):
        return ""


def _is_bare_git_directory(path: Path) -> bool:
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read(path / "config", encoding="utf-8")
        return (
            path.is_dir()
            and (path / "HEAD").is_file()
            and config.getboolean("core", "bare", fallback=False)
        )
    except (OSError, configparser.Error, ValueError):
        return False


def _bare_repo_is_empty(path: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "--git-dir", str(path), "show-ref", "--quiet"],
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=2,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 1:
        return True
    if result.returncode == 0:
        return False
    return None


def _sase_managed_in_bare_repo(path: Path, branch: str) -> bool | None:
    if not branch:
        return None
    try:
        result = subprocess.run(
            ["git", "--git-dir", str(path), "show", f"{branch}:sase/sase.yml"],
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=2,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return False
    return (
        re.search(
            r"(?im)^\s*is_sase_managed\s*:\s*(?:true|yes|1)\s*(?:#.*)?$",
            result.stdout,
        )
        is not None
    )


class BareGitWorkspacePlugin:
    """Pluggy plugin for bare-git workspace management."""

    def _is_bare_git_project(self, project_file: str) -> bool:
        """Check if *project_file* represents a bare-git project."""
        return is_bare_git_project(project_file)

    @hookimpl
    def ws_get_workflow_metadata(self) -> WorkflowMetadata | None:
        return WorkflowMetadata(
            workflow_type="git",
            ref_pattern=r"(?:^|(?<=\s))#git(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="Git (bare)",
            pre_allocated_env_prefix="SASE_GIT",
            vcs_family="git",
            vcs_provider_name="bare_git",
            sdd_storage_policy="in_tree",
        )

    @hookimpl
    def ws_detect_workflow_type(self, project_file: str) -> str | None:
        if self._is_bare_git_project(project_file):
            return "git"
        return None

    @hookimpl
    def ws_get_change_label(self, project_file: str) -> str | None:
        if self._is_bare_git_project(project_file):
            return "PR"
        return None

    @hookimpl
    def ws_resolve_ref(self, ref: str, workflow_type: str) -> ResolvedRef | None:
        if workflow_type != "git":
            return None
        resolved = resolve_git_ref(ref)
        return ResolvedRef(
            project_file=resolved.project_file,
            project_name=resolved.project_name,
            primary_workspace_dir=resolved.primary_workspace_dir,
            checkout_target=resolved.checkout_target,
            extra={"bare_repo_dir": resolved.bare_repo_dir},
            canonical_ref=resolved.project_name if "/" in ref else None,
        )

    @hookimpl
    def ws_parse_repo_ref(self, workflow_type: str, text: str) -> ParsedRepoRef | None:
        if workflow_type != "git":
            return None
        original = text
        value = text.strip()
        if value.startswith("git:"):
            value = value[4:]
        if not value:
            return None

        is_path = value.startswith("~") or os.path.isabs(value)
        if is_path:
            bare_path = _absolute_path(value)
            name = bare_path.name.removesuffix(".git")
            ref = str(bare_path)
        else:
            if "/" in value or "\\" in value or value in {".", ".."}:
                return None
            name = value
            if not is_valid_sase_project_name(name):
                return None
            bare_path = _absolute_path(sase_subdir("repos") / f"{name}.git")
            ref = name

        if not is_valid_sase_project_name(name):
            return None
        checkout_dir = str(Path.home() / "projects" / "git" / name) + "/"
        normalized_from = original if ref != original.strip() else ""
        return ParsedRepoRef(
            workflow_type="git",
            ref=ref,
            identity_key=f"git:{bare_path}",
            display=name,
            name=name,
            project_key_base=name,
            project_name_base=name,
            checkout_dir=checkout_dir,
            normalized_from=normalized_from,
        )

    @hookimpl
    def ws_list_local_repo_candidates(
        self, workflow_type: str
    ) -> LocalRepoCandidates | None:
        if workflow_type != "git":
            return None

        candidates: dict[tuple[str, str], LocalRepoCandidate] = {}
        bare_root = sase_subdir("repos")
        checkout_root = Path.home() / "projects" / "git"
        for root, pattern, bare in (
            (bare_root, "*.git", True),
            (checkout_root, "*", False),
        ):
            try:
                paths = sorted(
                    (path for path in islice(root.glob(pattern), 500) if path.is_dir()),
                    key=lambda path: path.name.casefold(),
                )
            except OSError:
                continue
            for path in paths:
                config_path = path / "config" if bare else path / ".git" / "config"
                if not bare and not (path / ".git").is_dir():
                    continue
                origin = "" if bare else _origin_from_config(config_path)
                parsed: ParsedRepoRef | None = None
                if origin:
                    origin_path = origin
                    if not origin.startswith(("/", "~", "file://")):
                        origin_path = str(_absolute_path(path / origin))
                    elif origin.startswith("file://"):
                        origin_path = origin.removeprefix("file://")
                    parsed = self.ws_parse_repo_ref("git", origin_path)
                if parsed is None:
                    parsed = self.ws_parse_repo_ref(
                        "git", str(path if bare else path.name)
                    )
                if parsed is None:
                    continue
                absolute_candidate_path = str(_absolute_path(path))
                candidate = LocalRepoCandidate(
                    parsed=parsed,
                    path=absolute_candidate_path,
                    origin_url=origin,
                    numbered_copy=not bare
                    and re.search(r"_\d+$", path.name) is not None,
                )
                candidates[(absolute_candidate_path, parsed.identity_key)] = candidate
        return LocalRepoCandidates(
            entries=tuple(
                sorted(
                    candidates.values(),
                    key=lambda candidate: (
                        candidate.parsed.name.casefold(),
                        candidate.path.casefold(),
                    ),
                )
            )
        )

    @hookimpl
    def ws_probe_repo(self, workflow_type: str, ref: str) -> RepoProbe | None:
        parsed = self.ws_parse_repo_ref(workflow_type, ref)
        if parsed is None:
            return None
        bare_path = Path(parsed.identity_key.removeprefix("git:"))
        if not bare_path.is_dir():
            return RepoProbe(status="not_found", parsed=parsed, repo_id=str(bare_path))
        if not _is_bare_git_directory(bare_path):
            return RepoProbe(
                status="unavailable",
                parsed=parsed,
                repo_id=str(bare_path),
                error_kind="unknown",
                message=f"Path is not a bare git repository: {bare_path}",
            )

        default_branch = ""
        try:
            head = (bare_path / "HEAD").read_text(encoding="utf-8").strip()
            if head.startswith("ref: refs/heads/"):
                default_branch = head.removeprefix("ref: refs/heads/")
        except OSError:
            pass
        return RepoProbe(
            status="found",
            parsed=parsed,
            visibility="local",
            default_branch=default_branch,
            is_empty=_bare_repo_is_empty(bare_path),
            can_push=True,
            sase_managed=_sase_managed_in_bare_repo(bare_path, default_branch),
            repo_id=str(bare_path),
        )

    @hookimpl
    def ws_describe_repo_creation(
        self, workflow_type: str, namespace: str
    ) -> RepoCreationForm | None:
        if workflow_type != "git":
            return None
        default_bare = str(sase_subdir("repos") / "<name>.git")
        default_checkout = str(Path.home() / "projects" / "git" / "<name>") + "/"
        return RepoCreationForm(
            workflow_type="git",
            namespace=namespace,
            fields=(
                RepoCreationField(
                    name="bare_dir",
                    label="Bare repository path",
                    kind="line",
                    group="advanced",
                    placeholder=default_bare,
                    description="Defaults to the SASE bare-repository directory.",
                ),
                RepoCreationField(
                    name="checkout_dir",
                    label="Checkout path",
                    kind="line",
                    group="advanced",
                    placeholder=default_checkout,
                    description="Used when the created repository is later added.",
                ),
            ),
            can_create=True,
        )

    @hookimpl
    def ws_create_repo(
        self, workflow_type: str, ref: str, options: dict[str, str]
    ) -> RepoCreateResult | None:
        parsed = self.ws_parse_repo_ref(workflow_type, ref)
        if parsed is None:
            return None
        bare_dir = options.get("bare_dir", "").strip()
        bare_path = _absolute_path(bare_dir or parsed.identity_key.removeprefix("git:"))
        checkout_dir = options.get("checkout_dir", "").strip()
        checkout_path = (
            str(_absolute_path(checkout_dir)) + "/"
            if checkout_dir
            else parsed.checkout_dir
        )
        parsed = ParsedRepoRef(
            workflow_type=parsed.workflow_type,
            ref=str(bare_path) if bare_dir else parsed.ref,
            identity_key=f"git:{bare_path}",
            display=parsed.display,
            name=parsed.name,
            project_key_base=parsed.project_key_base,
            project_name_base=parsed.project_name_base,
            checkout_dir=checkout_path,
            normalized_from=parsed.normalized_from,
        )
        if bare_path.exists():
            if not _is_bare_git_directory(bare_path):
                return RepoCreateResult(
                    status="failed",
                    parsed=parsed,
                    repo_id=str(bare_path),
                    visibility="local",
                    message=f"Path already exists and is not a bare git repository: {bare_path}",
                )
            is_empty = _bare_repo_is_empty(bare_path)
            if is_empty is None:
                return RepoCreateResult(
                    status="failed",
                    parsed=parsed,
                    repo_id=str(bare_path),
                    visibility="local",
                    message=f"Could not inspect refs in bare repository: {bare_path}",
                )
            if not is_empty:
                return RepoCreateResult(
                    status="exists",
                    parsed=parsed,
                    repo_id=str(bare_path),
                    visibility="local",
                    message="Bare repository already exists and contains refs.",
                )
            return RepoCreateResult(
                status="created",
                parsed=parsed,
                repo_id=str(bare_path),
                visibility="local",
                message="Bare repository already exists and is empty.",
            )

        try:
            bare_path.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ["git", "init", "--bare", str(bare_path)],
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
                timeout=10,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return RepoCreateResult(
                status="failed",
                parsed=parsed,
                repo_id=str(bare_path),
                visibility="local",
                message=str(exc),
            )
        if result.returncode != 0 or not _is_bare_git_directory(bare_path):
            return RepoCreateResult(
                status="failed",
                parsed=parsed,
                repo_id=str(bare_path),
                visibility="local",
                message=(
                    result.stderr.strip() or "git init did not create a bare repository"
                ),
            )
        return RepoCreateResult(
            status="created",
            parsed=parsed,
            repo_id=str(bare_path),
            visibility="local",
            message="Created an empty bare repository.",
        )

    @hookimpl
    def ws_submit(
        self,
        # Legacy hook argument name frozen for out-of-tree plugin compatibility.
        changespec_file: str,
        changespec_name: str,
        project_basename: str,
        console: object | None,
    ) -> tuple[bool, str | None] | None:
        patch_file = changespec_file  # legacy hook argument name
        if not self._is_bare_git_project(patch_file):
            return None
        return submit_bare_git(patch_file, changespec_name, project_basename, console)

    @hookimpl
    def ws_setup_workflow(
        self,
        ref: str,
        workflow_type: str,
        n: int,
        release: bool,
    ) -> dict[str, str] | None:
        if workflow_type != "git":
            return None
        # Setup logic will be expanded in later phases
        return None

    @hookimpl
    def ws_get_workspace_directory(
        self,
        workflow_type: str,
        workspace_num: int,
        project_name: str,
        primary_workspace_dir: str,
    ) -> str | None:
        if workflow_type != "git":
            return None
        from sase.workspace_provider.utils import ensure_workspace_checkout
        from sase.sdd.files import ensure_bare_git_sdd_initialized

        ensure_bare_git_sdd_initialized(
            primary_workspace_dir,
            commit=True,
            push=True,
            raise_on_error=True,
        )

        return ensure_workspace_checkout(primary_workspace_dir, workspace_num)

    @hookimpl
    def ws_prepare_mail(
        self,
        changespec_name: str,
        # Legacy hook argument name frozen for out-of-tree plugin compatibility.
        changespec_parent: str | None,
        project_basename: str,
        project_file: str,
        target_dir: str,
        console: object | None,
    ) -> object | None:
        if not self._is_bare_git_project(project_file):
            return None
        return prepare_mail_git(changespec_name, project_basename, target_dir, console)

    @hookimpl
    def ws_get_workspace_name(self, cwd: str) -> str | None:
        cwd = os.path.abspath(cwd)
        # Try git remote origin URL first
        try:
            result = _run_git(
                ["config", "--get", "remote.origin.url"],
                cwd=cwd,
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                if url:
                    name = os.path.basename(url)
                    if name.endswith(".git"):
                        name = name[:-4]
                    if name:
                        project_name = _valid_project_name_from_git_name(name)
                        if project_name is not None:
                            return project_name
        except Exception:
            pass

        # Fall back to repo root basename
        try:
            result = _run_git(
                ["rev-parse", "--show-toplevel"],
                cwd=cwd,
            )
            if result.returncode == 0:
                name = os.path.basename(result.stdout.strip())
                if name:
                    return _valid_project_name_from_git_name(name)
        except Exception:
            pass

        return None

    @hookimpl
    def ws_format_commit_description(
        self,
        file_path: str,
        project: str,
        workflow_type: str,
        bug: str | None,
        fixed_bug: str | None,
    ) -> bool | None:
        if workflow_type != "git":
            return None
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"[{project}] {content}\n")
        return True
