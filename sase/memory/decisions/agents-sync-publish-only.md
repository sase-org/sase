---
keyword: Agents-Sync Is Publish-Only, The Import Leg Is Deleted
aliases: [import leg removed, agents-sync publish-only, no more agent import]
summary:
  Epic sase-ws deleted the entire agents-sync import leg (v1, v2, and the ACE
  incomplete-import UI); the module only publishes agent prompts/pages outward now, and
  one explicit purge command is the sole supported operation on leftover imported local
  state.
metadata:
  status: accepted
  decided: 2026-09-05
---

**Claim.** `src/sase/agents_sync/` no longer contains any import machinery: there is no
v1 or v2 importer, no incoming cache or detection, no registry import mutations, no
`sase agent names forget-import` / `retire-v1` command, and no ACE incomplete-import
visibility gates. The only surviving leg is publication — the prompt archive, agent and
family pages, provenance links, and Referenced By write-backs — unchanged by the epic.
Locally materialized state left over from imports that ran before the leg was deleted
(`origin: import_v1` / `import_v2` registry rows, imported artifacts, dismissed bundles,
import journals/staging, incoming cache payloads, receipts) is pure history now; the
only supported operation on it is `sase agent names purge-local-state` (dry-run by
default, `--apply` to mutate) plus the matching `check_local_import_state` doctor check
that reports what is still left.

**Why.** The import leg had accreted three overlapping special cases that all needed
matching upkeep for behavior with no remaining users going forward: the legacy v1
transport, a v2 importer layered on top, and an ACE UI surface for incomplete imports.
Epic sase-ws removed them phase by phase instead of patching each indefinitely:
sase-ws.1 deleted the ACE import UI; sase-ws.2 rescoped the CLI and sync outcome/status
types to publish-only; sase-ws.3 replaced the ad hoc v1 `forget-import` cleanup with one
general purge command covering every import origin; sase-ws.4 deleted the v1/v2 import
engine itself and closed the `v1_import_retired` flag bead (`sase-wc`); sase-ws.5
dropped the Rust core identity/wire APIs whose only callers were the deleted Python leg.
Rejected alternative: keep the v1 leg alive behind `v1_import_retired` indefinitely, as
[[decisions/v1-import-retired]] originally planned — rejected because that flag's own
reopen condition (zero pending legacy-v1 hoods across every project) had been met, and
the dead flag-gated branch was actively costing maintenance with no offsetting benefit —
sase-ws.1's removal of the ACE `agents.cached` producer site, for example, silently
broke a hardcoded inventory-count assertion in the ACE proc-producer test suite, a
maintenance tax a fully deleted leg does not keep paying.

**Cost.** A machine with agent state on disk from an import that ran before this leg was
deleted has no path to re-import it if the leg is needed again — the only way back is a
fresh v2 publish from that machine, or reading the purge command's dry-run report and
any archived artifacts by hand. There is no compatibility shim; a caller that still
invokes a deleted CLI subcommand, module, or flag fails immediately rather than
degrading.

**Reopens when.** A genuine need re-emerges to sync agent state _into_ local disk from
another machine, not just publish it out. That is a new design exercise, not a
resurrection of the deleted v1/v2/ACE code — the multi-leg special-casing this decision
rejected is exactly what a new design must avoid repeating.
