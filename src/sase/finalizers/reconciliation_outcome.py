"""Clean-outcome classification after machine-owned auto-commits."""

from __future__ import annotations


def clean_result_reason(
    *,
    done_plan_auto_committed: bool,
    sdd_prompt_qa_auto_committed: bool,
    sdd_store_auto_committed: bool,
    sdd_bead_projection_auto_committed: bool = False,
    artifact_links_auto_committed: bool = False,
) -> str:
    """Classify a clean commit outcome after machine-owned auto-commits."""

    auto_committed: list[str] = []
    if done_plan_auto_committed:
        auto_committed.append("done_plan_status")
    if sdd_prompt_qa_auto_committed:
        auto_committed.append("sdd_prompt_qa")
    if sdd_bead_projection_auto_committed:
        auto_committed.append("sdd_bead_projection")
    if sdd_store_auto_committed:
        auto_committed.append("sdd_store")
    if artifact_links_auto_committed:
        auto_committed.append("artifact_links")
    if not auto_committed:
        return "no_changes"
    return "auto_committed_" + "_and_".join(auto_committed)
