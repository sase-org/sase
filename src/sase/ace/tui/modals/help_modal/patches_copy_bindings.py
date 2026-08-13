"""Copy-mode keybinding sections for the Patches help tab."""

from ...keymaps import KeymapRegistry, key_display_name
from .binding_common import Sections, key_sequence_display


def copy_mode_sections(km: KeymapRegistry) -> Sections:
    """Build Patch and artifact copy-mode help sections."""
    d = key_display_name
    cm = km.copy_mode

    cs_copy = cm.keys["patches"]
    commits_copy = cm.keys["artifacts_stitches"]
    beads_copy = cm.keys["artifacts_beads"]
    plans_copy = cm.keys["artifacts_plans"]
    files_copy = cm.keys["artifacts_other"]
    assert isinstance(cs_copy, dict)
    assert isinstance(commits_copy, dict)
    assert isinstance(beads_copy, dict)
    assert isinstance(plans_copy, dict)
    assert isinstance(files_copy, dict)
    pr_copy_key = cs_copy.get("pr_number", cs_copy.get("cl_number"))
    assert isinstance(pr_copy_key, str)

    return [
        (
            f"Copy Mode · Stitch ({d(cm.prefix)})",
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
            f"Copy Mode · Bead ({d(cm.prefix)})",
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
            f"Copy Mode · Plan ({d(cm.prefix)})",
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
            f"Copy Mode ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (f"{d(cm.prefix)}{d(cs_copy['raw'])}", "Copy Patch"),
                (
                    f"{d(cm.prefix)}{d(cs_copy['with_snapshot'])}",
                    "Copy Patch + snapshot",
                ),
                (f"{d(cm.prefix)}{d(cs_copy['bug'])}", "Copy bug number"),
                (f"{d(cm.prefix)}{d(pr_copy_key)}", "Copy PR number"),
                (f"{d(cm.prefix)}{d(cs_copy['name'])}", "Copy Patch name"),
                (f"{d(cm.prefix)}{d(cs_copy['link'])}", "Copy Markdown link"),
                (f"{d(cm.prefix)}{d(cs_copy['spec'])}", "Copy project spec file"),
                (f"{d(cm.prefix)}{d(cs_copy['snapshot'])}", "Copy sase ace snapshot"),
            ],
        ),
    ]
