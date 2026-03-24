"""Bare-git VCS plugin implementation.

Handles git repositories backed by a local bare remote (i.e. the origin
URL is a filesystem path rather than a hosted service like GitHub).
Inherits shared git operations from :class:`GitCommon` and overrides the
methods that differ from the GitHub workflow.
"""

from sase.vcs_provider._hookspec import hookimpl

from ._git_common import GitCommon


class BareGitPlugin(GitCommon):
    """Pluggy plugin for bare-git (local remote) repositories."""

    @hookimpl
    def vcs_get_change_url(self, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    @hookimpl
    def vcs_get_cl_number(self, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    @hookimpl
    def vcs_mail(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "push", "-u", "origin", revision], cwd)
        if not out.success:
            return self._to_result(out, "git push")
        return (True, None)

    # --- Commit dispatch ---

    @hookimpl
    def vcs_create_commit(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        message = payload.get("message", "")
        files = payload.get("files", [])
        if files:
            out = self._run(["git", "add"] + files, cwd)
        else:
            out = self._run(["git", "add", "-A"], cwd)
        if not out.success:
            return self._to_result(out, "git add")
        out = self._run(["git", "commit", "-m", message], cwd)
        if not out.success:
            return self._to_result(out, "git commit")
        out = self._run(["git", "push"], cwd)
        if not out.success:
            return self._to_result(out, "git push")
        return (True, None)

    @hookimpl
    def vcs_create_proposal(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
        return self.vcs_create_commit(payload, cwd)

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
            out = self._run(["git", "add"] + files, cwd)
        else:
            out = self._run(["git", "add", "-A"], cwd)
        if not out.success:
            return self._to_result(out, "git add")
        out = self._run(["git", "commit", "-m", message], cwd)
        if not out.success:
            return self._to_result(out, "git commit")
        out = self._run(["git", "push", "-u", "origin", name], cwd)
        if not out.success:
            return self._to_result(out, "git push")
        return (True, None)
