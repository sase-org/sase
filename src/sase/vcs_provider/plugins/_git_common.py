"""Shared git methods for git-based VCS plugins.

Common git operations (checkout, diff, commit, rebase, etc.) are
identical across different git-based plugins.  This mixin centralises
them so plugin classes only override the handful of methods that differ.
"""

import os

from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import hookimpl


class GitCommon(CommandRunner):
    """Mixin with shared ``@hookimpl`` methods for git-based plugins."""

    # --- Core operations ---

    @hookimpl
    def vcs_checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        # When asked to checkout a remote-tracking ref like origin/master,
        # always use the local branch name to leverage git's DWIM behavior.
        # If the local branch exists, git uses it directly; if not, git
        # auto-creates a local tracking branch from the remote-tracking ref.
        if revision.startswith("origin/"):
            revision = revision[len("origin/") :]
        out = self._run(["git", "checkout", revision], cwd)
        return self._to_result(out, "git checkout")

    @hookimpl
    def vcs_diff(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "diff", "HEAD"], cwd)
        if not out.success:
            out = self._run(["git", "diff"], cwd)
            if not out.success:
                return (False, f"git diff failed: {out.stderr.strip()}")
        text = out.stdout.strip()
        return (True, text if text else None)

    @hookimpl
    def vcs_diff_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "diff", f"{revision}~1", revision], cwd)
        if not out.success:
            out = self._run(["git", "show", "--format=", "--patch", revision], cwd)
            if not out.success:
                return (False, f"git diff failed: {out.stderr.strip()}")
        return (True, out.stdout)

    @hookimpl
    def vcs_apply_patch(self, patch_path: str, cwd: str) -> tuple[bool, str | None]:
        expanded = os.path.expanduser(patch_path)
        if not os.path.exists(expanded):
            return (False, f"Diff file not found: {patch_path}")
        out = self._run(["git", "apply", expanded], cwd)
        if not out.success:
            return (False, out.stderr.strip() or "git apply failed")
        return (True, None)

    @hookimpl
    def vcs_apply_patches(
        self, patch_paths: list[str], cwd: str
    ) -> tuple[bool, str | None]:
        if not patch_paths:
            return (True, None)
        expanded: list[str] = []
        for p in patch_paths:
            ep = os.path.expanduser(p)
            if not os.path.exists(ep):
                return (False, f"Diff file not found: {p}")
            expanded.append(ep)
        out = self._run(["git", "apply"] + expanded, cwd)
        if not out.success:
            return (False, out.stderr.strip() or "git apply failed")
        return (True, None)

    @hookimpl
    def vcs_add_remove(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "add", "-A"], cwd)
        return self._to_result(out, "git add -A")

    @hookimpl
    def vcs_clean_workspace(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "reset", "--hard", "HEAD"], cwd)
        if not out.success:
            return (False, f"git reset --hard failed: {out.stderr.strip()}")
        out = self._run(["git", "clean", "-fd"], cwd)
        if not out.success:
            return (False, f"git clean -fd failed: {out.stderr.strip()}")
        return (True, None)

    @hookimpl
    def vcs_commit(self, name: str, logfile: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "commit", "-F", logfile], cwd)
        return self._to_result(out, "git commit")

    @hookimpl
    def vcs_amend(
        self, note: str, cwd: str, no_upload: bool
    ) -> tuple[bool, str | None]:
        out = self._run(["git", "commit", "--amend", "-m", note], cwd)
        return self._to_result(out, "git commit --amend")

    @hookimpl
    def vcs_rename_branch(self, new_name: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "branch", "-m", new_name], cwd)
        return self._to_result(out, "git branch -m")

    @hookimpl
    def vcs_rebase(
        self, branch_name: str, new_parent: str, cwd: str
    ) -> tuple[bool, str | None]:
        out = self._run(
            ["git", "rebase", "--onto", new_parent, branch_name], cwd, timeout=600
        )
        return self._to_result(out, "git rebase")

    @hookimpl
    def vcs_archive(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        tag_out = self._run(["git", "tag", f"archive/{revision}", revision], cwd)
        if not tag_out.success:
            return self._to_result(tag_out, "git tag")
        delete_out = self._run(["git", "branch", "-D", revision], cwd)
        if not delete_out.success:
            return self._to_result(delete_out, "git branch -D")
        return (True, None)

    @hookimpl
    def vcs_prune(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        # resolve_revision may return a remote-tracking ref (e.g.
        # "origin/branch") when no local branch exists.  git branch -D only
        # deletes local branches, so strip the remote prefix first.
        local_branch = revision.removeprefix("origin/")
        out = self._run(["git", "branch", "-D", local_branch], cwd)
        if not out.success and "not found" in out.stderr:
            # No local branch to delete — nothing to prune.
            return (True, None)
        return self._to_result(out, "git branch -D")

    @hookimpl
    def vcs_stash_and_clean(
        self, diff_name: str, cwd: str, timeout: int
    ) -> tuple[bool, str | None]:
        status_out = self._run(["git", "status", "--porcelain"], cwd, timeout=timeout)
        if not status_out.success:
            return (False, f"git status failed: {status_out.stderr.strip()}")
        if not status_out.stdout.strip():
            return (True, None)
        out = self._run(
            ["git", "stash", "push", "--include-untracked", "-m", diff_name],
            cwd,
            timeout=timeout,
        )
        if not out.success:
            return (False, f"git stash push failed: {out.stderr.strip()}")
        return (True, None)

    # --- Optional core operations ---

    @hookimpl
    def vcs_derive_branch_name(
        self, changespec_name: str, project_basename: str
    ) -> str:
        from sase.core.changespec import strip_reverted_suffix

        return strip_reverted_suffix(changespec_name)

    @hookimpl
    def vcs_derive_branch_name_with_suffix(
        self, changespec_name: str, project_basename: str
    ) -> str:
        return changespec_name

    @hookimpl
    def vcs_can_rename_branch(self, cwd: str) -> bool:
        return True

    @hookimpl
    def vcs_resolve_revision(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str:
        from sase.core.branch_map import read_branch_map
        from sase.core.changespec import (
            changespec_name_to_branch,
            changespec_name_to_branch_with_suffix,
        )

        # --- Build candidate list ---
        # 1. Branch map alias (highest priority for immutable-branch providers)
        branch_map = read_branch_map(project_basename)
        mapped_branch = branch_map.get(changespec_name)

        # 2. New naming: derive_branch_name_with_suffix / derive_branch_name
        derived_with_suffix = self.vcs_derive_branch_name_with_suffix(
            changespec_name, project_basename
        )
        derived_without_suffix = self.vcs_derive_branch_name(
            changespec_name, project_basename
        )

        # 3. Old naming (backward compat): changespec_name_to_branch*
        old_branch_with_suffix = changespec_name_to_branch_with_suffix(
            changespec_name, project_basename
        )
        old_branch_without_suffix = changespec_name_to_branch(
            changespec_name, project_basename
        )

        # 4. Prefix-stripped with underscores preserved
        prefix = f"{project_basename}_"
        prefix_stripped = (
            changespec_name[len(prefix) :]
            if changespec_name.startswith(prefix)
            else None
        )

        # Deduplicate while preserving priority order
        seen: set[str] = set()
        candidates: list[str] = []
        for c in [
            mapped_branch,
            changespec_name,
            derived_with_suffix,
            derived_without_suffix,
            old_branch_with_suffix,
            old_branch_without_suffix,
            prefix_stripped,
        ]:
            if c and c not in seen:
                seen.add(c)
                candidates.append(c)

        # Try each candidate against local refs
        for candidate in candidates:
            out = self._run(["git", "rev-parse", "--verify", "--quiet", candidate], cwd)
            if out.success:
                return candidate

        # No local match — fetch from remote and retry against both local
        # and remote-tracking refs (rev-parse only finds local refs, but
        # git checkout can DWIM-create from origin/<branch>).
        self._run(["git", "fetch", "origin"], cwd, timeout=600)
        for candidate in candidates:
            out = self._run(["git", "rev-parse", "--verify", "--quiet", candidate], cwd)
            if out.success:
                return candidate
            # Check remote-tracking ref — vcs_checkout strips "origin/" and
            # git's DWIM creates a local tracking branch automatically.
            remote_ref = f"origin/{candidate}"
            out = self._run(
                ["git", "rev-parse", "--verify", "--quiet", remote_ref], cwd
            )
            if out.success:
                return remote_ref

        # Last resort: if the changespec is a base name (no __N suffix),
        # look for a unique suffixed remote branch.  This handles the case
        # where a Ready changespec's branch was previously renamed with a
        # suffix (e.g. "feature-1") but the changespec name lost the suffix.
        if old_branch_without_suffix == old_branch_with_suffix:
            pattern = f"refs/remotes/origin/{old_branch_without_suffix}-*"
            ref_out = self._run(
                ["git", "for-each-ref", "--format=%(refname:short)", pattern], cwd
            )
            if ref_out.success and ref_out.stdout.strip():
                import re

                suffix_re = re.compile(
                    re.escape(f"origin/{old_branch_without_suffix}") + r"-\d+$"
                )
                matches = [
                    r for r in ref_out.stdout.strip().splitlines() if suffix_re.match(r)
                ]
                if len(matches) == 1:
                    return matches[0]

        # Fall back to derived name without suffix (may fail at checkout)
        return derived_without_suffix

    @hookimpl
    def vcs_show_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "show", "--format=", "--patch", revision], cwd)
        if not out.success:
            return (False, f"git show failed: {out.stderr.strip()}")
        return (True, out.stdout)

    @hookimpl
    def vcs_diff_with_untracked(
        self, cwd: str, timeout: int
    ) -> tuple[bool, str | None]:
        tracked = self._run(["git", "diff", "HEAD"], cwd, timeout=timeout)
        tracked_diff = tracked.stdout if tracked.success else ""

        ls_out = self._run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd,
            timeout=timeout,
        )
        untracked_diff = ""
        if ls_out.success and ls_out.stdout:
            files = [f for f in ls_out.stdout.split("\0") if f]
            for f in files[:100]:
                # git diff --no-index exits 1 when files differ (expected)
                result = self._run(
                    ["git", "diff", "--no-index", "/dev/null", f],
                    cwd,
                    timeout=timeout,
                )
                if result.stdout:
                    untracked_diff += result.stdout

        combined = tracked_diff + untracked_diff
        return (True, combined if combined.strip() else None)

    @hookimpl
    def vcs_committed_diff(self, cwd: str, timeout: int) -> tuple[bool, str | None]:
        out = self._run(["git", "diff", "HEAD~1..HEAD"], cwd, timeout=timeout)
        if not out.success:
            return (True, None)
        text = out.stdout.strip()
        return (True, text if text else None)

    def _get_default_branch(self, cwd: str) -> str:
        """Detect the default branch name (e.g. ``main`` or ``master``)."""
        branch_out = self._run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd)
        default_branch = "main"
        if branch_out.success:
            ref = branch_out.stdout.strip()
            if ref:
                default_branch = ref.rsplit("/", 1)[-1]
        return default_branch

    @hookimpl
    def vcs_get_default_parent_revision(self, cwd: str) -> str:
        return f"origin/{self._get_default_branch(cwd)}"

    @hookimpl
    def vcs_file_at_revision(
        self, revision: str, file_path: str, cwd: str
    ) -> tuple[bool, str | None]:
        out = self._run(["git", "show", f"{revision}:{file_path}"], cwd)
        if not out.success:
            return (False, f"git show failed: {out.stderr.strip()}")
        return (True, out.stdout)

    @hookimpl
    def vcs_sync_workspace(self, cwd: str) -> tuple[bool, str | None]:
        fetch_out = self._run(["git", "fetch", "origin"], cwd, timeout=600)
        if not fetch_out.success:
            return self._to_result(fetch_out, "git fetch origin")
        default_branch = self._get_default_branch(cwd)
        rebase_out = self._run(
            ["git", "rebase", f"origin/{default_branch}"], cwd, timeout=600
        )
        return self._to_result(rebase_out, "git rebase")

    @hookimpl
    def vcs_is_sync_in_progress(self, cwd: str) -> bool:
        out = self._run(["git", "rev-parse", "--git-dir"], cwd)
        if not out.success:
            return False
        git_dir = out.stdout.strip()
        if not os.path.isabs(git_dir):
            git_dir = os.path.join(cwd, git_dir)
        return os.path.isdir(os.path.join(git_dir, "rebase-merge")) or os.path.isdir(
            os.path.join(git_dir, "rebase-apply")
        )

    @hookimpl
    def vcs_get_conflicted_files(self, cwd: str) -> list[str]:
        out = self._run(["git", "diff", "--name-only", "--diff-filter=U"], cwd)
        if not out.success:
            return []
        return [line for line in out.stdout.split("\n") if line.strip()]

    @hookimpl
    def vcs_continue_sync(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(
            ["git", "-c", "core.editor=true", "rebase", "--continue"],
            cwd,
            timeout=600,
        )
        return self._to_result(out, "git rebase --continue")

    @hookimpl
    def vcs_abort_sync(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "rebase", "--abort"], cwd)
        return self._to_result(out, "git rebase --abort")

    # --- VCS-agnostic / Google-internal operations ---

    @hookimpl
    def vcs_reword(self, description: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "commit", "--amend", "-m", description], cwd)
        return self._to_result(out, "git commit --amend")

    @hookimpl
    def vcs_reword_add_tag(
        self, tag_name: str, tag_value: str, cwd: str
    ) -> tuple[bool, str | None]:
        out = self._run(["git", "log", "--format=%B", "-n1", "HEAD"], cwd)
        if not out.success:
            return (False, out.stderr.strip() or "git log failed")
        current_msg = out.stdout.rstrip("\n")
        new_msg = f"{current_msg}\n{tag_name}={tag_value}"
        amend_out = self._run(["git", "commit", "--amend", "-m", new_msg], cwd)
        return self._to_result(amend_out, "git commit --amend")

    @hookimpl
    def vcs_get_description(
        self, revision: str, cwd: str, short: bool
    ) -> tuple[bool, str | None]:
        fmt = "%s" if short else "%B"
        out = self._run(["git", "log", f"--format={fmt}", "-n1", revision], cwd)
        if not out.success:
            return (False, out.stderr.strip() or "git log failed")
        return (True, out.stdout)

    @hookimpl
    def vcs_get_branch_name(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
        if not out.success:
            return (False, "git rev-parse --abbrev-ref HEAD failed")
        name = out.stdout.strip()
        if not name or name == "HEAD":
            return (True, None)
        return (True, name)

    @hookimpl
    def vcs_get_workspace_name(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "config", "--get", "remote.origin.url"], cwd)
        if out.success and out.stdout.strip():
            url = out.stdout.strip()
            name = os.path.basename(url)
            if name.endswith(".git"):
                name = name[:-4]
            return (True, name) if name else (True, None)
        root_out = self._run(["git", "rev-parse", "--show-toplevel"], cwd)
        if root_out.success and root_out.stdout.strip():
            name = os.path.basename(root_out.stdout.strip())
            return (True, name) if name else (True, None)
        return (False, "Could not determine workspace name")

    @hookimpl
    def vcs_has_local_changes(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "status", "--porcelain"], cwd)
        if not out.success:
            return (False, out.stderr.strip() or "git status failed")
        text = out.stdout.strip()
        return (True, text if text else None)

    @hookimpl
    def vcs_get_bug_number(self, cwd: str) -> tuple[bool, str | None]:
        return (True, "")

    @hookimpl
    def vcs_fix(self, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    @hookimpl
    def vcs_upload(self, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    # --- Commit dispatch helpers ---

    def _stage_bead_dirs(self, cwd: str) -> None:
        """Stage ``.sase_beads/`` if the directory has uncommitted changes."""
        bead_dir = os.path.join(cwd, ".sase_beads")
        if os.path.isdir(bead_dir):
            status = self._run(["git", "status", "--porcelain", ".sase_beads/"], cwd)
            if status.stdout.strip():
                self._run(["git", "add", ".sase_beads/"], cwd)

    def _stage_extra_paths(self, payload: dict, cwd: str) -> None:
        """Stage extra paths recorded in the payload (e.g. plan file)."""
        plan_path = payload.get("_plan_path", "")
        if plan_path:
            self._run(["git", "add", "--", plan_path], cwd)

    def _validate_staged(self, cwd: str) -> tuple[bool, str | None]:
        """Return failure when the index contains no staged changes."""
        check = self._run(["git", "diff", "--cached", "--quiet"], cwd)
        if check.success:  # exit 0 ⇒ nothing staged
            return (False, "No staged changes to commit")
        return (True, None)

    def _merge_with_master(self, cwd: str) -> tuple[bool, str | None]:
        """Fetch and merge ``origin/<default>`` to keep the branch current."""
        # Skip for detached HEAD
        branch_out = self._run(["git", "symbolic-ref", "--short", "HEAD"], cwd)
        if not branch_out.success:
            return (True, None)

        # Detect default branch (master or main)
        default_branch = ""
        for candidate in ("master", "main"):
            check = self._run(
                [
                    "git",
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/remotes/origin/{candidate}",
                ],
                cwd,
            )
            if check.success:
                default_branch = candidate
                break
        if not default_branch:
            return (True, None)

        self._run(
            ["git", "fetch", "origin", default_branch, "--quiet"], cwd, timeout=600
        )

        # Stash staged changes (--keep-index preserves the index)
        stash_out = self._run(["git", "stash", "--quiet", "--keep-index"], cwd)
        stashed = stash_out.success

        merge_out = self._run(
            ["git", "merge", f"origin/{default_branch}", "--no-edit", "--quiet"], cwd
        )
        if not merge_out.success:
            self._run(["git", "merge", "--abort"], cwd)
            if stashed:
                self._run(["git", "stash", "pop", "--quiet"], cwd)
            return (
                False,
                f"Merge conflict syncing with origin/{default_branch}. "
                "Resolve manually and retry.",
            )

        if stashed:
            pop = self._run(["git", "stash", "pop", "--quiet"], cwd)
            if not pop.success:
                return (
                    False,
                    "Failed to restore staged changes after merge. "
                    "Run 'git stash pop' to recover.",
                )

        return (True, None)

    def _push_with_retry(
        self, cwd: str, push_args: list[str] | None = None
    ) -> tuple[bool, str | None]:
        """Push to origin; on failure pull-and-retry once."""
        remote_check = self._run(["git", "remote", "get-url", "origin"], cwd)
        if not remote_check.success:
            return (True, None)  # no remote — skip

        if push_args is None:
            branch_out = self._run(["git", "symbolic-ref", "--short", "HEAD"], cwd)
            if not branch_out.success:
                return (True, None)  # detached HEAD — skip
            push_args = ["origin", branch_out.stdout.strip()]

        push_out = self._run(["git", "push"] + push_args, cwd)
        if push_out.success:
            return (True, None)

        # Pull and retry
        pull_out = self._run(["git", "pull", "--no-edit"], cwd)
        if not pull_out.success:
            self._run(["git", "merge", "--abort"], cwd)
            err = pull_out.stderr.strip() or pull_out.stdout.strip()
            return (False, f"git push failed and pull could not resolve it: {err}")

        push2 = self._run(["git", "push"] + push_args, cwd)
        if not push2.success:
            err = push2.stderr.strip() or push2.stdout.strip()
            return (False, f"git push failed after pull: {err}")
        return (True, None)

    def _post_commit_bead_amend(self, payload: dict, cwd: str) -> None:
        """Add a COMMIT note to the bead and amend ``.sase_beads/`` into the commit."""
        bead_id = payload.get("bead_id")
        if not bead_id:
            return

        rev = self._run(["git", "rev-parse", "--short", "HEAD"], cwd)
        commit_hash = rev.stdout.strip() if rev.success else "unknown"

        self._run(
            ["sase", "bead", "update", bead_id, "--notes", f"COMMIT: {commit_hash}"],
            cwd,
        )

        # Fold bead tracking changes into the commit via amend
        bead_dir = os.path.join(cwd, ".sase_beads")
        if os.path.isdir(bead_dir):
            status = self._run(["git", "status", "--porcelain", ".sase_beads/"], cwd)
            if status.stdout.strip():
                self._run(["git", "add", ".sase_beads/"], cwd)
                self._run(["git", "commit", "--amend", "--no-edit", "--quiet"], cwd)

    # --- Commit dispatch ---

    @hookimpl
    def vcs_create_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        message = payload.get("message", "")
        files = payload.get("files", [])

        # Stage user files
        if files:
            out = self._run(["git", "add", "--"] + files, cwd)
        else:
            out = self._run(["git", "add", "-A"], cwd)
        if not out.success:
            return self._to_result(out, "git add")

        # Stage .sase_beads/ and extra paths (plan file)
        self._stage_bead_dirs(cwd)
        self._stage_extra_paths(payload, cwd)

        # Validate staged changes exist
        ok, err = self._validate_staged(cwd)
        if not ok:
            return (False, err)

        # Merge with origin/master to keep branch current
        ok, err = self._merge_with_master(cwd)
        if not ok:
            return (False, err)

        # Re-stage .sase_beads/ after merge (merge may modify tracked files)
        self._stage_bead_dirs(cwd)

        out = self._run(["git", "commit", "-m", message], cwd)
        if not out.success:
            return self._to_result(out, "git commit")

        # Post-commit bead note + amend (skip for create_proposal delegation)
        if not payload.get("_skip_bead_amend"):
            self._post_commit_bead_amend(payload, cwd)

        ok, err = self._push_with_retry(cwd)
        if not ok:
            return (False, err)

        rev = self._run(["git", "rev-parse", "--short", "HEAD"], cwd)
        commit_hash = rev.stdout.strip() if rev.success else None
        return (True, commit_hash)

    @hookimpl
    def vcs_create_proposal(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        """Save diff and clean workspace - proposals don't commit."""
        from sase.workflows.commit_utils.workspace import clean_workspace, save_diff

        cl_name = payload.get("name", "") or payload.get("_cl_name", "")
        diff_path = save_diff(cl_name, target_dir=cwd)
        if not diff_path:
            return (False, "No changes to save as proposal diff")

        clean_workspace(cwd)
        return (True, diff_path)

    @hookimpl
    def vcs_create_pull_request(
        self, payload: dict, cwd: str
    ) -> tuple[bool, str | None]:
        name = payload.get("name", "")
        message = payload.get("message", "")
        files = payload.get("files", [])

        out = self._run(["git", "checkout", "-b", name], cwd)
        if not out.success:
            return self._to_result(out, "git checkout -b")

        if files:
            out = self._run(["git", "add", "--"] + files, cwd)
        else:
            out = self._run(["git", "add", "-A"], cwd)
        if not out.success:
            return self._to_result(out, "git add")

        # Stage .sase_beads/ and extra paths
        self._stage_bead_dirs(cwd)
        self._stage_extra_paths(payload, cwd)

        # Validate staged changes
        ok, err = self._validate_staged(cwd)
        if not ok:
            return (False, err)

        out = self._run(["git", "commit", "-m", message], cwd)
        if not out.success:
            return self._to_result(out, "git commit")

        ok, err = self._push_with_retry(cwd, ["-u", "origin", name])
        if not ok:
            return (False, err)
        return (True, None)
