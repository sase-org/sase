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

**Why.** Large catalogs make every agent pay for an index it rarely needs, while
planning and research still need a reliable path to discover governing records. A
generated pointer keeps that path explicit and auditable, and descriptor-authored
triggers make the policy generic across webs. The mechanism follows real catalogs that
are too large for always-loaded rosters; it is not a special case for decisions.

**Cost.** Agents who need the catalog must spend an additional read. Agents planning,
researching, or changing governed behavior without a plan must follow the descriptor's
read triggers. The pointer does not dynamically tailor itself to an agent's task.

**Reopens when.** The audited read path fails to make on-demand catalogs discoverable,
or the extra read cost outweighs the instruction savings in real use.
