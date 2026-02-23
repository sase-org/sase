"""Mercurial/Fig VCS plugin implementation.

This is the pluggy-based equivalent of :class:`_HgProvider`.  Every public
method carries an ``@hookimpl`` decorator and uses the ``vcs_`` prefix
required by :class:`VCSHookSpec`.
"""

import os

from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import hookimpl


class HgPlugin(CommandRunner):
    """Pluggy plugin for Mercurial workspaces."""

    # --- Core operations ---

    @hookimpl
    def vcs_checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["sase_hg_update", revision], cwd)
        return self._to_result(out, "sase_hg_update")

    @hookimpl
    def vcs_diff(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["hg", "diff"], cwd)
        if not out.success:
            return (False, f"hg diff failed: {out.stderr.strip()}")
        text = out.stdout.strip()
        return (True, text if text else None)

    @hookimpl
    def vcs_diff_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["hg", "diff", "-c", revision], cwd)
        if not out.success:
            return (False, f"hg diff failed: {out.stderr.strip()}")
        return (True, out.stdout)

    @hookimpl
    def vcs_apply_patch(self, patch_path: str, cwd: str) -> tuple[bool, str | None]:
        expanded = os.path.expanduser(patch_path)
        if not os.path.exists(expanded):
            return (False, f"Diff file not found: {patch_path}")
        out = self._run(["hg", "import", "--no-commit", expanded], cwd)
        if not out.success:
            return (False, out.stderr.strip() or "hg import failed")
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
        out = self._run(["hg", "import", "--no-commit"] + expanded, cwd)
        if not out.success:
            return (False, out.stderr.strip() or "hg import failed")
        return (True, None)

    @hookimpl
    def vcs_add_remove(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["hg", "addremove"], cwd)
        return self._to_result(out, "hg addremove")

    @hookimpl
    def vcs_clean_workspace(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["hg", "update", "--clean", "."], cwd)
        if not out.success:
            return (False, f"hg update --clean failed: {out.stderr.strip()}")
        out = self._run(["hg", "clean"], cwd)
        if not out.success:
            return (False, f"hg clean failed: {out.stderr.strip()}")
        return (True, None)

    @hookimpl
    def vcs_commit(self, name: str, logfile: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run_shell(f'hg commit --name "{name}" --logfile "{logfile}"', cwd)
        return self._to_result(out, "hg commit")

    @hookimpl
    def vcs_amend(
        self, note: str, cwd: str, no_upload: bool
    ) -> tuple[bool, str | None]:
        cmd = ["sase_hg_amend"]
        if no_upload:
            cmd.append("--no-upload")
        cmd.append(note)
        out = self._run(cmd, cwd)
        return self._to_result(out, "sase_hg_amend")

    @hookimpl
    def vcs_rename_branch(self, new_name: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["sase_hg_rename", new_name], cwd)
        return self._to_result(out, "sase_hg_rename")

    @hookimpl
    def vcs_rebase(
        self, branch_name: str, new_parent: str, cwd: str
    ) -> tuple[bool, str | None]:
        out = self._run(["sase_hg_rebase", branch_name, new_parent], cwd, timeout=600)
        return self._to_result(out, "sase_hg_rebase")

    @hookimpl
    def vcs_archive(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["sase_hg_archive", revision], cwd)
        return self._to_result(out, "sase_hg_archive")

    @hookimpl
    def vcs_prune(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["sase_hg_prune", revision], cwd)
        return self._to_result(out, "sase_hg_prune")

    @hookimpl
    def vcs_stash_and_clean(
        self, diff_name: str, cwd: str, timeout: int
    ) -> tuple[bool, str | None]:
        out = self._run(["sase_hg_clean", diff_name], cwd, timeout=timeout)
        if not out.success:
            error_msg = out.stderr.strip() or out.stdout.strip() or "no error output"
            return (False, error_msg)
        return (True, None)

    # --- Optional core operations ---

    @hookimpl
    def vcs_get_default_parent_revision(self, cwd: str) -> str:
        return "p4head"

    @hookimpl
    def vcs_sync_workspace(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run_streaming(["sase_hg_sync"], cwd, timeout=600)
        return self._to_result(out, "sase_hg_sync")

    @hookimpl
    def vcs_is_sync_in_progress(self, cwd: str) -> bool:
        out = self._run(["hg", "resolve", "--list"], cwd)
        if not out.success:
            return False
        return any(line.startswith("U ") for line in out.stdout.split("\n"))

    @hookimpl
    def vcs_get_conflicted_files(self, cwd: str) -> list[str]:
        out = self._run(["hg", "resolve", "--list"], cwd)
        if not out.success:
            return []
        return [line[2:] for line in out.stdout.split("\n") if line.startswith("U ")]

    @hookimpl
    def vcs_continue_sync(self, cwd: str) -> tuple[bool, str | None]:
        if self.vcs_is_sync_in_progress(cwd):
            return (False, "Unresolved conflicts remain")
        out = self._run(["hg", "rebase", "--continue"], cwd, timeout=600)
        return self._to_result(out, "hg rebase --continue")

    @hookimpl
    def vcs_abort_sync(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["hg", "rebase", "--abort"], cwd)
        if not out.success:
            out = self._run(["hg", "update", "--clean", "."], cwd)
            return self._to_result(out, "hg update --clean")
        return (True, None)

    # --- VCS-agnostic operations ---

    @hookimpl
    def vcs_prepare_description_for_reword(self, description: str) -> str:
        return (
            description.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace("\r", "\\r")
        )

    @hookimpl
    def vcs_get_change_url(self, cwd: str) -> tuple[bool, str | None]:
        success, number = self.vcs_get_cl_number(cwd)
        if not success:
            return (False, None)
        if number:
            return (True, f"http://cl/{number}")
        return (True, None)

    # --- Google-internal operations ---

    @hookimpl
    def vcs_reword(self, description: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["sase_hg_reword", description], cwd)
        return self._to_result(out, "sase_hg_reword")

    @hookimpl
    def vcs_reword_add_tag(
        self, tag_name: str, tag_value: str, cwd: str
    ) -> tuple[bool, str | None]:
        out = self._run(["sase_hg_reword", "--add-tag", tag_name, tag_value], cwd)
        return self._to_result(out, "sase_hg_reword")

    @hookimpl
    def vcs_get_description(
        self, revision: str, cwd: str, short: bool
    ) -> tuple[bool, str | None]:
        cmd = ["cl_desc"]
        if short:
            cmd.append("-s")
        else:
            cmd.extend(["-r", revision])
        out = self._run(cmd, cwd)
        if not out.success:
            return (False, out.stderr.strip() or "cl_desc failed")
        return (True, out.stdout)

    @hookimpl
    def vcs_get_branch_name(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run_shell("branch_name", cwd)
        if not out.success:
            return (False, "branch_name command failed")
        name = out.stdout.strip()
        return (True, name) if name else (True, None)

    @hookimpl
    def vcs_get_cl_number(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run_shell("branch_number", cwd)
        if not out.success:
            return (False, "branch_number command failed")
        number = out.stdout.strip()
        if number and number.isdigit():
            return (True, number)
        return (True, None)

    @hookimpl
    def vcs_get_workspace_name(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run_shell("workspace_name", cwd)
        if not out.success:
            return (False, "workspace_name command failed")
        name = out.stdout.strip()
        return (True, name) if name else (True, None)

    @hookimpl
    def vcs_has_local_changes(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run_shell("branch_local_changes", cwd)
        text = out.stdout.strip()
        return (True, text if text else None)

    @hookimpl
    def vcs_get_bug_number(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run_shell("sase_hg_branch_bug", cwd)
        if not out.success:
            return (False, "sase_hg_branch_bug command failed")
        return (True, out.stdout.strip())

    @hookimpl
    def vcs_mail(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["hg", "mail", "-r", revision], cwd)
        return self._to_result(out, "hg mail")

    @hookimpl
    def vcs_fix(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run_shell("hg fix", cwd)
        return self._to_result(out, "hg fix")

    @hookimpl
    def vcs_upload(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run_shell("hg upload tree", cwd)
        return self._to_result(out, "hg upload tree")

    @hookimpl
    def vcs_find_reviewers(self, cl_number: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["p4", "findreviewers", "-c", cl_number], cwd)
        if not out.success:
            return (False, out.stderr.strip() or "p4 findreviewers failed")
        return (True, out.stdout)

    @hookimpl
    def vcs_rewind(self, diff_paths: list[str], cwd: str) -> tuple[bool, str | None]:
        out = self._run(["sase_hg_rewind"] + diff_paths, cwd, timeout=600)
        return self._to_result(out, "sase_hg_rewind")
