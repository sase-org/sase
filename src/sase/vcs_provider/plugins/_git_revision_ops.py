"""Git branch naming and revision resolution operations."""

from sase.core.git_query_facade import parse_git_branch_name
from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import hookimpl


class GitRevisionOpsMixin(CommandRunner):
    """Git branch naming and revision resolution operations."""

    def _revision_candidates(
        self, changespec_name: str, project_basename: str
    ) -> tuple[list[str], str, str]:
        from sase.core.branch_map import read_branch_map
        from sase.core.changespec import (
            changespec_name_to_branch,
            changespec_name_to_branch_with_suffix,
        )

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
        for candidate in [
            mapped_branch,
            changespec_name,
            derived_with_suffix,
            derived_without_suffix,
            old_branch_with_suffix,
            old_branch_without_suffix,
            prefix_stripped,
        ]:
            if candidate and candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)

        return candidates, old_branch_without_suffix, old_branch_with_suffix

    # --- Branch name derivation ---

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
    def vcs_existing_branch_suffixes(self, base_name: str, cwd: str) -> set[int]:
        """Return ``_<N>`` suffix numbers already taken by remote branches.

        Queries the remote for branches named ``<base_name>_<N>`` (exact
        numeric suffix only) so PR-branch suffix allocation can avoid names
        whose branch already exists on the remote. Returns an empty set when
        there is no ``origin`` remote or the query fails.
        """
        import re

        remote_check = self._run(["git", "remote", "get-url", "origin"], cwd)
        if not remote_check.success:
            return set()

        out = self._run(
            ["git", "ls-remote", "--heads", "origin", f"{base_name}_*"],
            cwd,
            timeout=60,
        )
        if not out.success:
            return set()

        suffix_re = re.compile(re.escape(base_name) + r"_(\d+)$")
        suffixes: set[int] = set()
        for line in out.stdout.splitlines():
            # Each line is "<sha>\trefs/heads/<branch>".
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            branch = parts[1].strip().removeprefix("refs/heads/")
            match = suffix_re.match(branch)
            if match:
                suffixes.add(int(match.group(1)))
        return suffixes

    # --- Revision resolution ---

    @hookimpl
    def vcs_resolve_revision(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str:
        candidates, old_branch_without_suffix, old_branch_with_suffix = (
            self._revision_candidates(changespec_name, project_basename)
        )

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
        # look for a unique suffixed remote branch. This handles the case
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
                    ref
                    for ref in ref_out.stdout.strip().splitlines()
                    if suffix_re.match(ref)
                ]
                if len(matches) == 1:
                    return matches[0]

        # Fall back to derived name without suffix (may fail at checkout)
        return self.vcs_derive_branch_name(changespec_name, project_basename)

    @hookimpl
    def vcs_resolve_current_changespec_head_ref(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str:
        """Resolve DELTAS head with current-PR semantics.

        If the workspace is already on the target branch, use that checked-out
        branch because it may contain local commits that have just been created.
        Otherwise fetch and prefer origin/<branch> so background DELTAS refreshes
        do not read a stale local branch tip.
        """
        from sase.vcs_provider._errors import VCSOperationError

        candidates, old_branch_without_suffix, old_branch_with_suffix = (
            self._revision_candidates(changespec_name, project_basename)
        )

        branch_out = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
        if branch_out.success:
            current_branch = parse_git_branch_name(branch_out.stdout)
            if current_branch in candidates:
                return current_branch

        fetch_out = self._run(["git", "fetch", "origin"], cwd, timeout=600)
        if not fetch_out.success:
            raise VCSOperationError(
                "resolve_current_changespec_head_ref",
                fetch_out.stderr.strip() or "git fetch origin failed",
            )

        for candidate in candidates:
            remote_ref = f"origin/{candidate}"
            out = self._run(
                ["git", "rev-parse", "--verify", "--quiet", remote_ref], cwd
            )
            if out.success:
                return remote_ref

        for candidate in candidates:
            out = self._run(["git", "rev-parse", "--verify", "--quiet", candidate], cwd)
            if out.success:
                return candidate

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
                    ref
                    for ref in ref_out.stdout.strip().splitlines()
                    if suffix_re.match(ref)
                ]
                if len(matches) == 1:
                    return matches[0]

        return self.vcs_derive_branch_name(changespec_name, project_basename)
