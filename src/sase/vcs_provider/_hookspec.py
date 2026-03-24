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
        self, note: str, cwd: str, no_upload: bool
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
        self, diff_name: str, cwd: str, timeout: int
    ) -> tuple[bool, str | None]: ...

    # --- Optional core operations ---

    @hookspec(firstresult=True)
    def vcs_resolve_revision(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str: ...

    @hookspec(firstresult=True)
    def vcs_show_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_diff_with_untracked(
        self, cwd: str, timeout: int
    ) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_committed_diff(self, cwd: str, timeout: int) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_get_default_parent_revision(self, cwd: str) -> str: ...

    @hookspec(firstresult=True)
    def vcs_file_at_revision(
        self, revision: str, file_path: str, cwd: str
    ) -> tuple[bool, str | None]: ...

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
        self, revision: str, cwd: str, short: bool
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

    # --- Commit dispatch ---

    @hookspec(firstresult=True)
    def vcs_create_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_create_proposal(
        self, payload: dict, cwd: str
    ) -> tuple[bool, str | None]: ...

    @hookspec(firstresult=True)
    def vcs_create_pull_request(
        self, payload: dict, cwd: str
    ) -> tuple[bool, str | None]: ...

    # --- VCS-agnostic operations ---

    @hookspec(firstresult=True)
    def vcs_prepare_description_for_reword(self, description: str) -> str: ...

    @hookspec(firstresult=True)
    def vcs_get_change_url(self, cwd: str) -> tuple[bool, str | None]: ...

    # --- Classification hooks (used by registry, not by VCSProvider instances) ---

    @hookspec(firstresult=True)
    def vcs_detect_repo_type(self, directory: str) -> str | None:
        """Detect a VCS repository type by checking for markers in *directory*.

        Plugins check for their VCS marker (e.g. ``.hg/``) and return
        their VCS name, or ``None`` if the marker is not present.

        Args:
            directory: A directory to check for VCS markers.

        Returns:
            The VCS type name (e.g. ``"hg"``), or ``None`` if this
            plugin's marker is not found.
        """

    @hookspec(firstresult=True)
    def vcs_classify_repo(self, git_dir: str) -> str | None:
        """Classify a git repository by examining its remote URL.

        Plugins can claim repos matching their hosting service (e.g.
        sase-github claims repos with ``github.com`` URLs, a hypothetical
        sase-gitlab could claim ``gitlab.com`` URLs).

        Args:
            git_dir: A directory inside the git working tree.

        Returns:
            The VCS provider name (e.g. ``"github"``, ``"gitlab"``),
            or ``None`` if this plugin does not claim the repo.
        """
