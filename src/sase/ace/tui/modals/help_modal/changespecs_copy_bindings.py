"""Copy-mode keybinding sections for the ChangeSpecs help tab."""

from ...keymaps import KeymapRegistry, key_display_name
from .binding_common import Sections, key_sequence_display


def copy_mode_sections(km: KeymapRegistry) -> Sections:
    """Build ChangeSpec and artifact copy-mode help sections."""
    d = key_display_name
    cm = km.copy_mode

    cs_copy = cm.keys["changespecs"]
    commits_copy = cm.keys["artifacts_commits"]
    beads_copy = cm.keys["artifacts_beads"]
    plans_copy = cm.keys["artifacts_plans"]
    chats_copy = cm.keys["artifacts_chats"]
    files_copy = cm.keys["artifacts_other"]
    bugs_copy = cm.keys["artifacts_bugs"]
    assert isinstance(cs_copy, dict)
    assert isinstance(commits_copy, dict)
    assert isinstance(beads_copy, dict)
    assert isinstance(plans_copy, dict)
    assert isinstance(chats_copy, dict)
    assert isinstance(files_copy, dict)
    assert isinstance(bugs_copy, dict)
    pr_copy_key = cs_copy.get("pr_number", cs_copy.get("cl_number"))
    assert isinstance(pr_copy_key, str)

    return [
        (
            f"Copy Mode · Commits ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (
                    key_sequence_display(cm.prefix, commits_copy["reference"]),
                    "Copy @commit reference",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["link"]),
                    "Copy Markdown link",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["handoff"]),
                    "Reference in new agent prompt",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["sha"]),
                    "Copy full SHA",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["message"]),
                    "Copy commit message",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["repo_sha"]),
                    "Copy repo@SHA",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["plan"]),
                    "Copy linked plan reference",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["json"]),
                    "Copy metadata JSON",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["snapshot"]),
                    "Copy sase ace snapshot",
                ),
            ],
        ),
        (
            f"Copy Mode · Beads ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (
                    key_sequence_display(cm.prefix, beads_copy["id"]),
                    "Copy bead id",
                ),
                (
                    key_sequence_display(cm.prefix, beads_copy["reference"]),
                    "Copy @bead reference",
                ),
                (
                    key_sequence_display(cm.prefix, beads_copy["link"]),
                    "Copy Markdown link",
                ),
                (
                    key_sequence_display(cm.prefix, beads_copy["handoff"]),
                    "Reference in new agent prompt",
                ),
                (
                    key_sequence_display(cm.prefix, beads_copy["title"]),
                    "Copy bead title",
                ),
                (
                    key_sequence_display(cm.prefix, beads_copy["body"]),
                    "Copy description and notes",
                ),
                (
                    key_sequence_display(cm.prefix, beads_copy["design"]),
                    "Copy design reference",
                ),
                (
                    key_sequence_display(cm.prefix, beads_copy["json"]),
                    "Copy metadata JSON",
                ),
                (
                    key_sequence_display(cm.prefix, beads_copy["snapshot"]),
                    "Copy sase ace snapshot",
                ),
            ],
        ),
        (
            f"Copy Mode · Plans ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (
                    key_sequence_display(cm.prefix, plans_copy["bead_id"]),
                    "Copy owning bead id",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["reference"]),
                    "Copy @document reference",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["link"]),
                    "Copy Markdown link",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["handoff"]),
                    "Reference in new agent prompt",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["design"]),
                    "Copy owning bead design",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["path"]),
                    "Copy plan path",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["title"]),
                    "Copy plan title",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["body"]),
                    "Copy plan body",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["json"]),
                    "Copy metadata JSON",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["snapshot"]),
                    "Copy sase ace snapshot",
                ),
            ],
        ),
        (
            f"Copy Mode · Chats ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (
                    key_sequence_display(cm.prefix, chats_copy["reference"]),
                    "Copy @chat reference",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["link"]),
                    "Copy Markdown link",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["handoff"]),
                    "Reference in new agent prompt",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["path"]),
                    "Copy transcript path",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["agent"]),
                    "Copy agent name",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["transcript"]),
                    "Copy transcript contents",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["json"]),
                    "Copy metadata JSON",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["snapshot"]),
                    "Copy sase ace snapshot",
                ),
            ],
        ),
        (
            f"Copy Mode · Other ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (
                    key_sequence_display(cm.prefix, files_copy["contents"]),
                    "Copy text contents",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["reference"]),
                    "Copy @file reference",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["link"]),
                    "Copy Markdown link",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["handoff"]),
                    "Reference in new agent prompt",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["path"]),
                    "Copy anchored stored path",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["source"]),
                    "Copy anchored source path",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["label"]),
                    "Copy artifact-file label",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["json"]),
                    "Copy metadata JSON",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["snapshot"]),
                    "Copy sase ace snapshot",
                ),
            ],
        ),
        (
            f"Copy Mode · Bugs ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (
                    key_sequence_display(cm.prefix, bugs_copy["reference"]),
                    "Copy @bug reference",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["link"]),
                    "Copy Markdown link",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["handoff"]),
                    "Reference in new agent prompt",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["number"]),
                    "Copy issue number",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["url"]),
                    "Copy issue URL",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["title"]),
                    "Copy issue title",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["prompt"]),
                    "Copy agent-ready prompt",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["json"]),
                    "Copy metadata JSON",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["snapshot"]),
                    "Copy sase ace snapshot",
                ),
            ],
        ),
        (
            f"Copy Mode ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (f"{d(cm.prefix)}{d(cs_copy['raw'])}", "Copy ChangeSpec"),
                (
                    f"{d(cm.prefix)}{d(cs_copy['with_snapshot'])}",
                    "Copy ChangeSpec + snapshot",
                ),
                (f"{d(cm.prefix)}{d(cs_copy['bug'])}", "Copy bug number"),
                (f"{d(cm.prefix)}{d(pr_copy_key)}", "Copy PR number"),
                (f"{d(cm.prefix)}{d(cs_copy['name'])}", "Copy ChangeSpec name"),
                (f"{d(cm.prefix)}{d(cs_copy['link'])}", "Copy Markdown link"),
                (f"{d(cm.prefix)}{d(cs_copy['spec'])}", "Copy project spec file"),
                (f"{d(cm.prefix)}{d(cs_copy['snapshot'])}", "Copy sase ace snapshot"),
            ],
        ),
    ]
