---
keyword: Rosters Load On Demand
aliases: [rosters-load-on-demand, on-demand memory web rosters]
summary:
  A web descriptor can replace its generated roster with an audited read pointer and
  declare when agents must read that roster.
metadata:
  status: accepted
  decided: 2026-11-25
---

**Claim.** A memory web may set `roster_loading: on_demand` to replace its generated
roster with a pointer to `sase memory read roster:<web> -r "<why>"`. The web declares
the situations that require the roster in `roster_read_when:`. The on-disk descriptor
still carries its complete roster, and the authored descriptor body still renders in the
Memory Webs section. A roster read is audited and can be batched with strand reads.

**Why.** At `df9ce4ef55` the sase decisions section was 8,408 B, 38% of the root bundle,
and the bob-cli section was 25,641 B, 69% of its bundle; bob-cli's Codex bundle was 4.5
KB over its 32,768 B cap, so compaction ran every turn. Researchers make 78% of decision
reads, and a bare `sase memory read decisions` printed every body by accident (about 69
KB in sase). After adoption sase's AGENTS.md went from 21,076 B to 13,868 B; bob-cli's
decisions section went from 19,095 B to 1,775 B, and its Codex bundle from 30,954 B
(compacted) to 14,031 B (uncompacted). Per-invocation bundles are frozen at spawn, so
the host cannot know whether an agent will plan, and the pointer must be standing text.
Rejected alternatives: relying on the compaction ladder; a titles-only roster; reviving
`type:` on descriptors; `when:` audience-scoped bundles; a flat reference note as the
index; semantic search.

**Cost.** Ambient discovery is lost for unplanned work; compliance is social in v1
because nothing enforces the read; `roster` becomes a reserved web slug; there is one
more divergence between the on-disk descriptor and its projection.

**Reopens when.** Planner compliance measured from `memory_reads.jsonl` stays poor. The
fix then is the deferred `sase plan validate` roster check or a titles-only
`roster_loading: compact` mode. It also reopens if the host gains a reliable spawn-time
fact that an agent will plan.

**Evidence.** Research `research:202611/on_demand_web_rosters/on_demand_web_rosters.md`;
see [[decisions/webs-render-in-their-own-section]].
