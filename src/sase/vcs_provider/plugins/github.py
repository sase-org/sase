"""GitHub VCS plugin implementation.

Handles git repositories hosted on GitHub (or similar hosted services).
Inherits shared git operations from :class:`GitCommon` and adds
GitHub-specific methods (``mail`` with PR creation, ``get_cl_number``
and ``get_change_url`` via ``gh`` CLI).
"""

from sase.vcs_provider._hookspec import hookimpl

from ._git_common import GitCommon


class GitHubPlugin(GitCommon):
    """Pluggy plugin for GitHub-hosted git repositories."""

    @hookimpl
    def vcs_get_change_url(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["gh", "pr", "view", "--json", "url", "-q", ".url"], cwd)
        if out.success:
            url = out.stdout.strip()
            return (True, url) if url else (True, None)
        return (True, None)

    @hookimpl
    def vcs_get_cl_number(self, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["gh", "pr", "view", "--json", "number", "-q", ".number"], cwd)
        if out.success:
            number = out.stdout.strip()
            return (True, number) if number else (True, None)
        return (True, None)

    @hookimpl
    def vcs_mail(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        out = self._run(["git", "push", "-u", "origin", revision], cwd)
        if not out.success:
            return self._to_result(out, "git push")
        pr_check = self._run(
            ["gh", "pr", "view", "--json", "number", "-q", ".number"], cwd
        )
        if not pr_check.success:
            pr_create = self._run(["gh", "pr", "create", "--fill"], cwd)
            if not pr_create.success:
                return self._to_result(pr_create, "gh pr create")
        return (True, None)
