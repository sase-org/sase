"""PR-related operations: prefix, tags, body, and parent detection."""

from __future__ import annotations

import json
import os

from sase.output import print_status
from sase.vcs_provider import get_vcs_provider
from sase.workflows.commit.runtime_tags import (
    filter_runtime_owned_tags,
    update_trailing_commit_tags,
)


def apply_project_pr_prefix(payload: dict) -> None:
    """Set ``_pr_title_prefix`` if ``use_project_pr_prefix`` is enabled."""
    from sase.vcs_provider.config import (
        get_use_project_pr_prefix,
        strip_project_pr_prefix,
    )

    if not get_use_project_pr_prefix():
        return
    try:
        from sase.workflows.utils import get_project_from_workspace

        project_name = get_project_from_workspace()
    except Exception:
        project_name = None
    if project_name:
        payload["_pr_title_prefix"] = f"[{project_name}] "
        # Strip any existing prefix from the message to prevent
        # duplication when the agent already included one.
        message = payload.get("message", "")
        if message:
            payload["message"] = strip_project_pr_prefix(message)


def _fetch_parent_pr_tags(parent_cl_name: str | None) -> dict[str, object]:
    """Fetch PR tags from the parent PR's body (best-effort).

    Returns an empty dict if there is no parent, the parent has no PR URL,
    or the fetch fails for any reason.
    """
    if not parent_cl_name:
        return {}

    try:
        from sase.vcs_provider.config import extract_pr_tags
        from sase.workflows.utils import (
            get_patch_from_file,
            get_project_file_path,
            get_project_from_workspace,
        )

        project_name = get_project_from_workspace()
        if not project_name:
            return {}

        project_file = get_project_file_path(project_name)
        parent_cs = get_patch_from_file(project_file, parent_cl_name)
        if parent_cs is None or not parent_cs.pr_url:
            return {}

        cwd = os.getcwd()
        provider = get_vcs_provider(cwd)
        ok, body = provider.get_change_body(parent_cs.pr_url, cwd)
        if not ok or not body:
            return {}

        return extract_pr_tags(body)
    except Exception as exc:
        print_status(f"Parent PR tag fetch failed: {exc}", "warning")
        return {}


def append_pr_tags(payload: dict, parent_cl_name: str | None) -> None:
    """Append configured pr_tags to the commit message.

    When there is a parent PR, its tags are inherited and used as the
    base layer.  Config tags override parent tags, and the BUG tag
    (from payload or env) overrides everything.
    """
    from sase.vcs_provider.config import get_pr_tags

    parent_tags = filter_runtime_owned_tags(_fetch_parent_pr_tags(parent_cl_name))
    config_tags = filter_runtime_owned_tags(get_pr_tags())

    # Merge: parent (lowest) → config → BUG (highest)
    tags = {**parent_tags, **config_tags}

    patch_name = str(payload.get("name") or "").strip()
    if patch_name:
        tags = {
            "PATCH": patch_name,
            **{k: v for k, v in tags.items() if k not in {"PATCH", "SASE_PATCH"}},
        }

    bug_id = payload.get("bug_id", "") or os.environ.get("SASE_BUG_ID", "")
    if bug_id and bug_id != "0":
        tags = {"BUG": bug_id, **{k: v for k, v in tags.items() if k != "BUG"}}

    if not tags:
        return

    message = payload.get("message", "")
    from sase.workflows.commit.runtime_tags import parse_trailing_commit_tag_values

    if "BEAD" in parse_trailing_commit_tag_values(str(message or "")):
        tags = {
            key: value
            for key, value in tags.items()
            if key not in {"BEAD", "SASE_BEAD"}
        }
    payload["message"] = update_trailing_commit_tags(message, tags)


def build_pr_body(payload: dict) -> None:
    """Append agent info footer to PR body via _pr_body payload field."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return

    lines: list[str] = []
    provider = meta.get("llm_provider")
    model = meta.get("model")
    if provider and model:
        lines.append(f"**Model:** `{provider}/{model}`")
    from sase.core.commit_footer_facade import LinkedCommitTagValue
    from sase.workflows.commit.runtime_tags import parse_trailing_commit_tag_values

    agent_value = parse_trailing_commit_tag_values(
        str(payload.get("message") or "")
    ).get("AGENT")
    if isinstance(agent_value, LinkedCommitTagValue):
        lines.append(f"**Agent:** [{agent_value.label}]({agent_value.destination})")
    elif agent_value:
        lines.append(f"**Agent:** `{agent_value}`")
    elif name := meta.get("name"):
        # The footer names a sase agent, so the metadata fallback -- which
        # records the concrete agent shell -- is projected to its sase agent
        # too.
        from sase.sase_agent import sase_agent_name

        lines.append(f"**Agent:** `{sase_agent_name(str(name))}`")

    if lines:
        from sase.core.commit_footer_facade import append_body_suffix_before_footer

        message = payload.get("message", "")
        footer = "\n".join(lines)
        payload["_pr_body"] = append_body_suffix_before_footer(
            message,
            f"---\n{footer}",
        )


def detect_parent_patch(base_cl_name: str | None, payload: dict) -> str | None:
    """Detect the parent Patch from the current branch.

    Returns the Patch name if the current branch corresponds to an
    existing Patch, None otherwise.
    """
    from sase.workflows.utils import (
        get_patch_from_file,
        get_cl_name_from_branch,
        get_project_file_path,
        get_project_from_workspace,
    )

    try:
        branch_cl = get_cl_name_from_branch()
    except Exception as exc:
        print_status(f"Parent auto-detect: failed to get branch name: {exc}", "warning")
        return None
    if not branch_cl:
        return None

    # Don't set parent to self
    new_cl = base_cl_name or payload.get("name")
    if branch_cl == new_cl:
        return None

    try:
        project_name = get_project_from_workspace()
    except Exception as exc:
        print_status(f"Parent auto-detect: failed to get project: {exc}", "warning")
        return None
    if not project_name:
        return None

    try:
        project_file = get_project_file_path(project_name)
        cs = get_patch_from_file(project_file, branch_cl)
    except Exception as exc:
        print_status(f"Parent auto-detect: failed to read Patch: {exc}", "warning")
        return None
    return branch_cl if cs is not None else None
