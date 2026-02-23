"""Pluggy hook specifications for VCS provider plugins."""

import pluggy

hookspec = pluggy.HookspecMarker("sase_vcs")
hookimpl = pluggy.HookimplMarker("sase_vcs")


class VCSHookSpec:
    """Hook specifications mirroring :class:`VCSProvider` methods.

    Every method uses ``firstresult=True`` so pluggy returns the first
    non-``None`` result from the registered plugins.  Method names are
    prefixed with ``vcs_`` to namespace them within the pluggy project.
    """

    # --- Core operations ---

    @hookspec(firstresult=True)
    def vcs_checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_diff(self, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_diff_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_apply_patch(self, patch_path: str, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_apply_patches(
        self, patch_paths: list[str], cwd: str
    ) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_add_remove(self, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_clean_workspace(self, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_commit(
        self, name: str, logfile: str, cwd: str
    ) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_amend(
        self, note: str, cwd: str, no_upload: bool = False
    ) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_rename_branch(self, new_name: str, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_rebase(
        self, branch_name: str, new_parent: str, cwd: str
    ) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_archive(self, revision: str, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_prune(self, revision: str, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_stash_and_clean(
        self, diff_name: str, cwd: str, timeout: int = 300
    ) -> tuple[bool, str | None]: ...

    # --- Optional core operations ---

    @hookspec(firstresult=True)
    def vcs_resolve_revision(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str: ...

    @hookspec(firstresult=True)
    def vcs_show_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_get_default_parent_revision(self, cwd: str) -> str: ...

    @hookspec(firstresult=True)
    def vcs_sync_workspace(self, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_is_sync_in_progress(self, cwd: str) -> bool: ...

    @hookspec(firstresult=True)
    def vcs_get_conflicted_files(self, cwd: str) -> list[str]: ...

    @hookspec(firstresult=True)
    def vcs_continue_sync(self, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_abort_sync(self, cwd: str) -> tuple[bool, str | None]: ...

    # --- Google-internal operations ---

    @hookspec(firstresult=True)
    def vcs_reword(self, description: str, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_reword_add_tag(
        self, tag_name: str, tag_value: str, cwd: str
    ) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_get_description(
        self, revision: str, cwd: str, short: bool = False
    ) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_get_branch_name(self, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_get_cl_number(self, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_get_workspace_name(self, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_has_local_changes(self, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_get_bug_number(self, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_mail(self, revision: str, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_fix(self, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_upload(self, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_find_reviewers(
        self, cl_number: str, cwd: str
    ) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_rewind(
        self, diff_paths: list[str], cwd: str
    ) -> tuple[bool, str | None]: ...

    # --- VCS-agnostic operations ---

    @hookspec(firstresult=True)
    def vcs_prepare_description_for_reword(self, description: str) -> str: ...

    @hookspec(firstresult=True)
    def vcs_get_change_url(self, cwd: str) -> tuple[bool, str | None]: ...
