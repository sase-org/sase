"""Shared git methods for git-based VCS plugins.

Common git operations (checkout, diff, commit, rebase, etc.) are
identical across different git-based plugins.  This module composes
the operation mixins so plugin classes only need to inherit from
:class:`GitCommon`.
"""

from sase.vcs_provider.plugins._git_commit_dispatch import GitCommitDispatchMixin
from sase.vcs_provider.plugins._git_core_ops import GitCoreOpsMixin
from sase.vcs_provider.plugins._git_query_ops import GitQueryOpsMixin


class GitCommon(GitCoreOpsMixin, GitQueryOpsMixin, GitCommitDispatchMixin):
    """Mixin with shared ``@hookimpl`` methods for git-based plugins."""

    _provider_name: str = "git"
