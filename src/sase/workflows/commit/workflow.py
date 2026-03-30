"""CommitWorkflow class for dispatching VCS commit operations."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import TYPE_CHECKING

from sase.config.core import load_merged_config
from sase.output import print_status
from sase.vcs_provider import get_vcs_provider
from sase.workflows.base import BaseWorkflow

if TYPE_CHECKING:
    from sase.vcs_provider._base import VCSProvider

VALID_METHODS = ("create_commit", "create_proposal", "create_pull_request")


def _extract_yyyymm_from_plan(plan_path: str) -> str | None:
    """Extract YYYYMM from a plan file's ``create_time`` frontmatter field.

    Returns ``None`` if the file has no frontmatter or no ``create_time`` field.
    """
    import re

    try:
        with open(plan_path, encoding="utf-8") as f:
            content = f.read(512)  # frontmatter is near the top
    except OSError:
        return None
    if not content.startswith("---\n"):
        return None
    end = content.find("\n---\n", 4)
    if end == -1:
        return None
    fm = content[4:end]
    m = re.search(r"^create_time:\s*(\d{4})-(\d{2})", fm, re.MULTILINE)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return None


class CommitWorkflow(BaseWorkflow):
    """A workflow that dispatches commit operations to VCS provider hooks."""

    def __init__(self, payload: dict, method: str) -> None:
        self._payload = payload
        self._method = method
        self._base_cl_name: str | None = None
        self._reserved_name: str | None = None
        self._parent_cl_name: str | None = None
        self._diff_path: str | None = None
        self._cl_name: str | None = None
        self._project_file: str | None = None

    @property
    def name(self) -> str:
        return "commit"

    @property
    def description(self) -> str:
        return "Dispatch a VCS commit operation via JSON payload"

    def run(self) -> bool:
        if self._method not in VALID_METHODS:
            print_status(
                f"Unknown commit method '{self._method}'. "
                f"Valid methods: {', '.join(VALID_METHODS)}",
                "error",
            )
            return False

        if not isinstance(self._payload, dict):
            print_status("Payload must be a JSON object.", "error")
            return False
        if "message" not in self._payload and self._method != "create_pull_request":
            print_status("Payload missing required 'message' field.", "error")
            return False
        if self._method == "create_pull_request" and not self._payload.get("name"):
            print_status(
                "Payload missing required 'name' field for create_pull_request.",
                "error",
            )
            return False

        cwd = os.getcwd()

        # Bead lifecycle and SASE_PLAN: skip for proposals.
        # Must run before precommit so plan files are in place for formatting.
        if self._method != "create_proposal":
            self._handle_beads(cwd)
            self._handle_sase_plan(cwd)

        # Run precommit command (e.g. `just fix`) after all files are staged
        if not self._run_precommit(cwd):
            return False

        # Pre-compute the _<N> suffix for create_pull_request so the CL is
        # created with the correct suffixed name (important for non-git VCS
        # where ChangeSpec creation may not be able to rename the CL later).
        # Save the base name so _create_changespec can pass it (un-suffixed)
        # to add_changespec_to_project_file, which adds its own suffix.
        self._base_cl_name = None
        if self._method == "create_pull_request":
            base_name: str = self._payload["name"]
            self._base_cl_name = base_name
            try:
                from sase.workflows.commit.changespec_operations import (
                    compute_suffixed_cl_name,
                )
                from sase.workflows.utils import get_project_from_workspace

                project_name = get_project_from_workspace()
                if project_name:
                    suffixed = compute_suffixed_cl_name(project_name, base_name)
                    if suffixed:
                        self._payload["name"] = suffixed
                        self._reserved_name = suffixed
            except Exception:
                pass  # Best-effort; fall back to unsuffixed name

        # Detect parent ChangeSpec from current branch (before VCS may change it)
        if self._method == "create_pull_request":
            self._parent_cl_name = self._detect_parent_changespec()

        if self._method == "create_pull_request":
            self._apply_project_pr_prefix()
            self._append_pr_tags()
            self._build_pr_body()

        provider = get_vcs_provider(cwd)
        dispatch = getattr(provider, self._method)

        # Resolve CL name and project file for COMMITS entries and diff
        # capture.  Cached on self so both _capture_pre_commit_diff and
        # _append_commits_entry use the same values without double resolution.
        self._cl_name = self._resolve_cl_name()
        self._project_file = self._resolve_project_file()

        # Capture diff before VCS commit so it can be recorded in the
        # COMMITS entry.  After the commit the working-tree diff is empty.
        self._capture_pre_commit_diff(provider, cwd)

        print_status(f"Dispatching {self._method} to VCS provider...", "progress")
        ok, result = dispatch(self._payload, cwd)
        if not ok:
            print_status(f"{self._method} failed: {result}", "error")
            self._cleanup_reservation()
            return False

        print_status(f"{self._method} completed successfully!", "success")

        cs_name: str | None = None
        if self._method == "create_pull_request":
            cs_name = self._create_changespec(cl_url=result)

        # Write initial result marker (needed by append_post_commit_entry)
        self._write_result_marker(result, cs_name)

        # Append COMMITS entry for commit/proposal (not PR - it uses ChangeSpec).
        entry_id: str | None = None
        if self._method in ("create_commit", "create_proposal"):
            entry_id = self._append_commits_entry()
            if entry_id:
                self._write_result_marker(result, cs_name, entry_id=entry_id)

        return True

    def _run_precommit(self, cwd: str) -> bool:
        """Run the precommit_command from config, if configured."""
        config = load_merged_config()
        cmd = config.get("precommit_command", "")
        if not cmd:
            return True
        print_status(f"Running precommit command: {cmd}", "progress")
        result = subprocess.run(
            cmd, shell=True, cwd=cwd, check=False, capture_output=True, text=True
        )
        if result.returncode != 0:
            print_status(
                f"Precommit command failed (exit {result.returncode}): {cmd}",
                "error",
            )
            return False
        return True

    def _handle_beads(self, cwd: str) -> None:
        """Close and sync beads, inject bead ID into commit message."""
        bead_id = self._payload.get("bead_id")
        has_bead_dir = os.path.isdir(os.path.join(cwd, ".sase_beads")) or os.path.isdir(
            os.path.join(cwd, ".beads")
        )

        if bead_id:
            # Close bead (best effort)
            print_status(f"Closing bead {bead_id}...", "progress")
            subprocess.run(
                ["sase", "bead", "close", bead_id],
                cwd=cwd,
                capture_output=True,
                check=False,
            )
            # Inject bead ID into commit message headline
            message = self._payload.get("message", "")
            if f"({bead_id})" not in message:
                first_line, sep, rest = message.partition("\n")
                self._payload["message"] = f"{first_line} ({bead_id}){sep}{rest}"

        if bead_id or has_bead_dir:
            # Sync beads (best effort)
            subprocess.run(
                ["sase", "bead", "sync"],
                cwd=cwd,
                capture_output=True,
                check=False,
            )

    def _handle_sase_plan(self, cwd: str) -> None:
        """Append PLAN= to commit message and mark plan as done."""
        plan_path = os.environ.get("SASE_PLAN", "")
        if not plan_path:
            return

        from sase.sdd.beads import get_sdd_config

        version_controlled = get_sdd_config()

        # Determine repo root
        repo_root = self._get_repo_root(cwd)
        in_repo = bool(repo_root) and plan_path.startswith(repo_root + "/")

        # If plan file doesn't exist at the expected path, try the ~/.sase/plans/ archive
        if not os.path.isfile(plan_path):
            archive_fallback = os.path.join(
                os.path.expanduser("~"), ".sase", "plans", os.path.basename(plan_path)
            )
            if os.path.isfile(archive_fallback):
                plan_path = archive_fallback
                in_repo = False
            else:
                return  # truly missing

        # Only copy plan into repo for version-controlled SDD projects
        if version_controlled and not in_repo:
            from sase.sdd.files import get_yyyymm

            yyyymm = _extract_yyyymm_from_plan(plan_path) or get_yyyymm()
            dest = os.path.join(cwd, "plans", yyyymm, os.path.basename(plan_path))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(plan_path, dest)
            # Format the copied plan with prettier (safety net for
            # archives created before the plan_command_handler format step)
            from sase.gemini_wrapper.file_references import format_with_prettier

            raw = open(dest, encoding="utf-8").read()
            formatted = format_with_prettier(raw)
            if formatted != raw:
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(formatted)
            plan_path = dest

        # Only add frontmatter for version-controlled plans
        if version_controlled:
            plan_content = open(plan_path, encoding="utf-8").read()
            if not plan_content.startswith("---\n"):
                from sase.llm_provider._plan_utils import add_create_time_frontmatter

                with open(plan_path, "w", encoding="utf-8") as f:
                    f.write(add_create_time_frontmatter(plan_content))

        # Compute repo-root-relative path
        if repo_root and plan_path.startswith(repo_root + "/"):
            plan_rel = plan_path[len(repo_root) + 1 :]
        else:
            plan_rel = (
                os.path.relpath(plan_path, repo_root)
                if repo_root
                else os.path.basename(plan_path)
            )

        # Append PLAN= to commit message (only for version-controlled projects)
        if version_controlled:
            message = self._payload.get("message", "")
            self._payload["message"] = f"{message}\n\nPLAN={plan_rel}"

        # Mark plan as done
        subprocess.run(
            ["sed", "-i", "s/^status: wip$/status: done/", plan_path],
            check=False,
            capture_output=True,
        )

        # Only stage plan file if version-controlled
        if version_controlled:
            self._payload["_plan_path"] = plan_path

    @staticmethod
    def _get_repo_root(cwd: str) -> str:
        """Return the repo root directory, or empty string on failure."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                cwd=cwd,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return ""

    def _apply_project_pr_prefix(self) -> None:
        """Set ``_pr_title_prefix`` if ``use_project_pr_prefix`` is enabled."""
        from sase.vcs_provider.config import get_use_project_pr_prefix

        if not get_use_project_pr_prefix():
            return
        try:
            from sase.workflows.utils import get_project_from_workspace

            project_name = get_project_from_workspace()
        except Exception:
            project_name = None
        if project_name:
            self._payload["_pr_title_prefix"] = f"[{project_name}] "

    def _append_pr_tags(self) -> None:
        """Append configured pr_tags to the commit message."""
        from sase.vcs_provider.config import get_pr_tags

        tags = get_pr_tags()

        bug_id = os.environ.get("SASE_BUG_ID", "")
        if bug_id and bug_id != "0":
            tags = {"BUG": bug_id, **{k: v for k, v in tags.items() if k != "BUG"}}

        if not tags:
            return

        tag_lines = "\n".join(f"{k}={v}" for k, v in tags.items())
        message = self._payload.get("message", "")
        self._payload["message"] = f"{message}\n\n{tag_lines}"

    def _build_pr_body(self) -> None:
        """Append agent info footer to PR body via _pr_body payload field."""
        artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
        if not artifacts_dir:
            return

        meta_path = os.path.join(artifacts_dir, "agent_meta.json")
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return

        lines: list[str] = []
        provider = meta.get("llm_provider")
        model = meta.get("model")
        if provider and model:
            lines.append(f"**Model:** `{provider}/{model}`")
        name = meta.get("name")
        if name:
            lines.append(f"**Agent:** `{name}`")

        if lines:
            message = self._payload.get("message", "")
            footer = "\n".join(lines)
            self._payload["_pr_body"] = f"{message}\n\n---\n{footer}"

    def _detect_parent_changespec(self) -> str | None:
        """Detect the parent ChangeSpec from the current branch.

        Returns the ChangeSpec name if the current branch corresponds to an
        existing ChangeSpec, None otherwise.
        """
        try:
            from sase.workflows.utils import (
                get_changespec_from_file,
                get_cl_name_from_branch,
                get_project_file_path,
                get_project_from_workspace,
            )

            branch_cl = get_cl_name_from_branch()
            if not branch_cl:
                return None

            # Don't set parent to self
            new_cl = self._base_cl_name or self._payload.get("name")
            if branch_cl == new_cl:
                return None

            project_name = get_project_from_workspace()
            if not project_name:
                return None

            project_file = get_project_file_path(project_name)
            cs = get_changespec_from_file(project_file, branch_cl)
            return branch_cl if cs is not None else None
        except Exception:
            return None

    def _create_changespec(self, cl_url: str | None) -> str | None:
        """Best-effort ChangeSpec creation after a successful PR flow."""
        try:
            from sase.workflows.utils import (
                get_project_file_path,
                get_project_from_workspace,
            )
            from sase.workspace_provider.changespec import (
                create_changespec_for_workflow,
            )

            project_name = get_project_from_workspace()
            if not project_name:
                print_status(
                    "Skipping ChangeSpec: could not detect project name.", "info"
                )
                return None

            project_file = get_project_file_path(project_name)
            branch_name = self._payload.get("name", "")
            checkout_target = self._payload.get("checkout_target", "HEAD~1")

            bug_id = os.environ.get("SASE_BUG_ID", "").strip()
            bug = f"http://b/{bug_id}" if bug_id and bug_id != "0" else None

            cs_name = create_changespec_for_workflow(
                project_name=project_name,
                project_file=project_file,
                checkout_target=checkout_target,
                branch_name=branch_name,
                prompt="",
                response="",
                workflow_name="sase_commit",
                cl_url=cl_url,
                cl_name=self._base_cl_name or self._payload.get("name"),
                commit_description=self._payload.get("message", ""),
                parent=self._parent_cl_name,
                bug=bug,
                reserved_name=self._reserved_name,
            )
            if cs_name:
                print_status(f"Created ChangeSpec: {cs_name}", "success")
            else:
                print_status("Skipping ChangeSpec: no new commits detected.", "info")
            return cs_name
        except Exception as exc:
            print_status(f"Skipping ChangeSpec: {exc}", "warning")
            return None

    def _cleanup_reservation(self) -> None:
        """Remove the reservation entry on VCS failure (best-effort)."""
        if not self._reserved_name:
            return
        try:
            from sase.workflows.commit.changespec_operations import remove_reservation
            from sase.workflows.utils import get_project_from_workspace

            project_name = get_project_from_workspace()
            if project_name:
                remove_reservation(project_name, self._reserved_name)
        except Exception:
            pass

    def _resolve_cl_name(self) -> str | None:
        """Resolve the CL name from env var or current branch."""
        cl_name = os.environ.get("SASE_AGENT_CL_NAME")
        if cl_name:
            return cl_name
        try:
            from sase.workflows.utils import get_cl_name_from_branch

            return get_cl_name_from_branch()
        except Exception:
            return None

    def _resolve_project_file(self) -> str | None:
        """Resolve the project file path from env var or workspace detection."""
        project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
        if project_file:
            return project_file
        try:
            from sase.workflows.utils import (
                get_project_file_path,
                get_project_from_workspace,
            )

            project_name = get_project_from_workspace()
            if not project_name:
                return None
            return get_project_file_path(project_name)
        except Exception:
            return None

    def _capture_pre_commit_diff(self, provider: VCSProvider, cwd: str) -> None:
        """Capture VCS diff before committing and save it for the COMMITS entry.

        After the VCS commit the working-tree diff is empty, so this must run
        beforehand.  When ``SASE_ARTIFACTS_DIR`` is set (agent context), the
        diff is saved there.  Otherwise it falls back to
        ``~/.sase/diffs/<cl_name>-<timestamp>.diff`` so human CLI commits get
        diffs too.
        """
        artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
        if artifacts_dir:
            diff_path = os.path.join(artifacts_dir, "commit_diff.diff")
        else:
            if not self._cl_name:
                return
            from sase.core.time import generate_timestamp

            diffs_dir = os.path.expanduser("~/.sase/diffs")
            os.makedirs(diffs_dir, exist_ok=True)
            diff_path = os.path.join(
                diffs_dir, f"{self._cl_name}-{generate_timestamp()}.diff"
            )

        try:
            ok, diff_text = provider.diff(cwd)  # type: ignore[union-attr]
        except Exception:
            return
        if not ok or not diff_text:
            return
        try:
            with open(diff_path, "w", encoding="utf-8") as f:
                f.write(diff_text)
            self._diff_path = diff_path
        except Exception:
            pass

    def _append_commits_entry(self) -> str | None:
        """Append a COMMITS entry after successful commit/proposal. Returns entry_id."""
        if (
            not self._project_file
            or not self._cl_name
            or not os.path.isfile(self._project_file)
        ):
            return None

        # Build note + body from the commit message.
        # The header is the first line; everything after the first blank line is
        # the body.
        message = self._payload.get("message", "")
        parts = message.split("\n\n", 1)
        note = (parts[0].split("\n")[0]) or "Manual changes"
        body: list[str] | None = None
        if len(parts) > 1 and parts[1].strip():
            body = parts[1].splitlines()

        # For proposals, prepend workflow identifier if available
        if self._method == "create_proposal":
            who = os.environ.get("SASE_AGENT_WHO")
            if who:
                note = f"[{who}] {note}"

        chat_path = os.environ.get("SASE_AGENT_CHAT_PATH")

        # Compute display path for plan (replace $HOME with ~)
        plan_display: str | None = None
        raw_plan = os.environ.get("SASE_PLAN", "")
        if raw_plan:
            home = os.path.expanduser("~")
            plan_display = (
                raw_plan.replace(home, "~") if raw_plan.startswith(home) else raw_plan
            )

        from sase.workflows.commit_utils.entries import (
            add_commit_entry_with_id,
            add_proposed_commit_entry,
        )

        if self._method == "create_proposal":
            ok, entry_id = add_proposed_commit_entry(
                project_file=self._project_file,
                cl_name=self._cl_name,
                note=note,
                diff_path=self._diff_path,
                chat_path=chat_path,
                body=body,
                plan_path=plan_display,
            )
        else:
            ok, entry_id = add_commit_entry_with_id(
                project_file=self._project_file,
                cl_name=self._cl_name,
                note=note,
                diff_path=self._diff_path,
                chat_path=chat_path,
                body=body,
                plan_path=plan_display,
            )
        return entry_id if ok else None

    def _write_result_marker(
        self,
        result: str | None,
        changespec_name: str | None,
        *,
        entry_id: str | None = None,
    ) -> None:
        """Write commit result to a marker file for xprompt post-steps."""
        artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
        if not artifacts_dir:
            return

        marker = {
            "method": self._method,
            "result": result,
            "message": self._payload.get("message", ""),
            "name": self._payload.get("name", ""),
            "bead_id": self._payload.get("bead_id", ""),
            "changespec_name": changespec_name,
            "entry_id": entry_id,
            "diff_path": self._diff_path,
        }
        marker_path = os.path.join(artifacts_dir, "commit_result.json")
        with open(marker_path, "w") as f:
            json.dump(marker, f)
