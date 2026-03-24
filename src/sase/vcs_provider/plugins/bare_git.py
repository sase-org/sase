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
