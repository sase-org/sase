"""VCS plugin manager that delegates to pluggy hooks."""

import pluggy

from ._base import VCSProvider


class VCSPluginManager(VCSProvider):
    """Wraps a :class:`pluggy.PluginManager` while implementing the
    :class:`VCSProvider` interface.

    Each ``VCSProvider`` method delegates to the corresponding
    ``self._pm.hook.vcs_*()`` call.  When pluggy returns ``None``
    (no plugin handled the hook), a :class:`NotImplementedError` is raised,
    matching the behaviour of the ABC default methods.
    """

    def __init__(self, pm: pluggy.PluginManager) -> None:
        self._pm = pm

    # --- helpers ---

    def _call_or_raise(
        self, hook_name: str, **kwargs: object
    ) -> tuple[bool, str | None]:
        """Call a hook and raise ``NotImplementedError`` if no plugin handles it."""
        result = getattr(self._pm.hook, hook_name)(**kwargs)
        if result is None:
            op = hook_name.removeprefix("vcs_")
            raise NotImplementedError(f"{op} is not supported by this VCS provider")
        return result  # type: ignore[return-value]

    # --- Core abstract methods ---

    def checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_checkout", revision=revision, cwd=cwd)

    def diff(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_diff", cwd=cwd)

    def diff_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_diff_revision", revision=revision, cwd=cwd)

    def apply_patch(self, patch_path: str, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_apply_patch", patch_path=patch_path, cwd=cwd)

    def apply_patches(
        self, patch_paths: list[str], cwd: str
    ) -> tuple[bool, str | None]:
        return self._call_or_raise(
            "vcs_apply_patches", patch_paths=patch_paths, cwd=cwd
        )

    def add_remove(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_add_remove", cwd=cwd)

    def clean_workspace(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_clean_workspace", cwd=cwd)

    def commit(self, name: str, logfile: str, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_commit", name=name, logfile=logfile, cwd=cwd)

    def amend(
        self, note: str, cwd: str, *, no_upload: bool = False
    ) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_amend", note=note, cwd=cwd, no_upload=no_upload)

    def rename_branch(self, new_name: str, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_rename_branch", new_name=new_name, cwd=cwd)

    def rebase(
        self, branch_name: str, new_parent: str, cwd: str
    ) -> tuple[bool, str | None]:
        return self._call_or_raise(
            "vcs_rebase", branch_name=branch_name, new_parent=new_parent, cwd=cwd
        )

    def archive(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_archive", revision=revision, cwd=cwd)

    def prune(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_prune", revision=revision, cwd=cwd)

    def stash_and_clean(
        self, diff_name: str, cwd: str, *, timeout: int = 300
    ) -> tuple[bool, str | None]:
        return self._call_or_raise(
            "vcs_stash_and_clean", diff_name=diff_name, cwd=cwd, timeout=timeout
        )

    # --- Optional core methods (with non-trivial defaults) ---

    def derive_branch_name(self, changespec_name: str, project_basename: str) -> str:
        result = self._pm.hook.vcs_derive_branch_name(
            changespec_name=changespec_name, project_basename=project_basename
        )
        if result is None:
            from sase.core.changespec import changespec_name_to_branch

            return changespec_name_to_branch(changespec_name, project_basename)
        return result  # type: ignore[return-value]

    def derive_branch_name_with_suffix(
        self, changespec_name: str, project_basename: str
    ) -> str:
        result = self._pm.hook.vcs_derive_branch_name_with_suffix(
            changespec_name=changespec_name, project_basename=project_basename
        )
        if result is None:
            from sase.core.changespec import changespec_name_to_branch_with_suffix

            return changespec_name_to_branch_with_suffix(
                changespec_name, project_basename
            )
        return result  # type: ignore[return-value]

    def can_rename_branch(self, cwd: str) -> bool:
        result = self._pm.hook.vcs_can_rename_branch(cwd=cwd)
        if result is None:
            return True
        return result  # type: ignore[return-value]

    def resolve_revision(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str:
        result = self._pm.hook.vcs_resolve_revision(
            changespec_name=changespec_name,
            project_basename=project_basename,
            cwd=cwd,
        )
        if result is None:
            return changespec_name
        return result  # type: ignore[return-value]

    def show_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_show_revision", revision=revision, cwd=cwd)

    def diff_with_untracked(
        self, cwd: str, *, timeout: int = 10
    ) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_diff_with_untracked", cwd=cwd, timeout=timeout)

    def committed_diff(self, cwd: str, *, timeout: int = 10) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_committed_diff", cwd=cwd, timeout=timeout)

    def get_default_parent_revision(self, cwd: str) -> str:
        result = self._pm.hook.vcs_get_default_parent_revision(cwd=cwd)
        if result is None:
            raise NotImplementedError(
                "get_default_parent_revision is not supported by this VCS provider"
            )
        return result  # type: ignore[return-value]

    def file_at_revision(
        self, revision: str, file_path: str, cwd: str
    ) -> tuple[bool, str | None]:
        return self._call_or_raise(
            "vcs_file_at_revision", revision=revision, file_path=file_path, cwd=cwd
        )

    def sync_workspace(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_sync_workspace", cwd=cwd)

    def is_sync_in_progress(self, cwd: str) -> bool:
        result = self._pm.hook.vcs_is_sync_in_progress(cwd=cwd)
        if result is None:
            raise NotImplementedError(
                "is_sync_in_progress is not supported by this VCS provider"
            )
        return result  # type: ignore[return-value]

    def get_conflicted_files(self, cwd: str) -> list[str]:
        result = self._pm.hook.vcs_get_conflicted_files(cwd=cwd)
        if result is None:
            raise NotImplementedError(
                "get_conflicted_files is not supported by this VCS provider"
            )
        return result  # type: ignore[return-value]

    def continue_sync(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_continue_sync", cwd=cwd)

    def abort_sync(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_abort_sync", cwd=cwd)

    # --- Google-internal methods ---

    def reword(self, description: str, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_reword", description=description, cwd=cwd)

    def reword_add_tag(
        self, tag_name: str, tag_value: str, cwd: str
    ) -> tuple[bool, str | None]:
        return self._call_or_raise(
            "vcs_reword_add_tag", tag_name=tag_name, tag_value=tag_value, cwd=cwd
        )

    def get_description(
        self, revision: str, cwd: str, *, short: bool = False
    ) -> tuple[bool, str | None]:
        return self._call_or_raise(
            "vcs_get_description", revision=revision, cwd=cwd, short=short
        )

    def get_branch_name(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_get_branch_name", cwd=cwd)

    def get_cl_number(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_get_cl_number", cwd=cwd)

    def get_workspace_name(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_get_workspace_name", cwd=cwd)

    def has_local_changes(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_has_local_changes", cwd=cwd)

    def get_bug_number(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_get_bug_number", cwd=cwd)

    def mail(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_mail", revision=revision, cwd=cwd)

    def fix(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_fix", cwd=cwd)

    def upload(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_upload", cwd=cwd)

    def find_reviewers(self, cl_number: str, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_find_reviewers", cl_number=cl_number, cwd=cwd)

    def rewind(self, diff_paths: list[str], cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_rewind", diff_paths=diff_paths, cwd=cwd)

    # --- Commit dispatch ---

    def create_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_create_commit", payload=payload, cwd=cwd)

    def create_proposal(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_create_proposal", payload=payload, cwd=cwd)

    def create_pull_request(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_create_pull_request", payload=payload, cwd=cwd)

    def finalize_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_finalize_commit", payload=payload, cwd=cwd)

    # --- VCS-agnostic methods ---

    def abandon_change(
        self, cl: str, revision: str, cwd: str
    ) -> tuple[bool, str | None]:
        result = self._pm.hook.vcs_abandon_change(cl=cl, revision=revision, cwd=cwd)
        if result is None:
            return (True, None)
        return result  # type: ignore[return-value]

    def prepare_description_for_reword(self, description: str) -> str:
        result = self._pm.hook.vcs_prepare_description_for_reword(
            description=description
        )
        if result is None:
            return description
        return result  # type: ignore[return-value]

    def normalize_bug_value(self, tag_value: str) -> str:
        result = self._pm.hook.vcs_normalize_bug_value(tag_value=tag_value)
        if result is None:
            return tag_value
        return result  # type: ignore[return-value]

    def get_change_url(self, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise("vcs_get_change_url", cwd=cwd)

    def get_change_body(self, change_ref: str, cwd: str) -> tuple[bool, str | None]:
        return self._call_or_raise(
            "vcs_get_change_body", change_ref=change_ref, cwd=cwd
        )
