---
keyword: Legacy V1 Agent Transport Is Read-Only History, Not An Import Source
aliases: [v1 import retirement, v1_import_retired flag, v1 sunset]
summary:
  The legacy v1 agents-sync import leg is sunset behind v1_import_retired; v1 payloads
  stay readable as v2-adoption matcher evidence but are never materialized as new
  imported artifacts.
metadata:
  status: accepted
  decided: 2026-09-03
---

**Claim.** The v1 agents-sync import leg is gated behind the `v1_import_retired` sunset
flag (default on, bead `sase-wc`). The gate lives inside
`src/sase/agents_sync/bundles.py::integrate_foreign_bundles`, at the two points that
materialize a new or refreshed imported artifact from a foreign v1 bundle
(`_create_imported_artifact` / `_refresh_imported_artifact`). With the flag on, those
calls are replaced with a diagnostic and an `IntegrationCounts.v1_import_skipped` count;
`src/sase/agents_sync/incoming_integration.py` surfaces that as a `sunset_skipped`
`CachedIntegrationResult` disposition (cached path) or a skipped receipt write
(full-sync path), in both cases leaving the hood visibly pending rather than silently
vanishing. Capture/detection (`incoming_detection.py`) and the v1 group ownership
classification (owner-observed, self-owned-already-present) are untouched: they are
evidence reads, not imports, and the v2-adoption matcher (`v2_import_v1_adoption.py`)
still depends on already-imported v1 artifacts being readable.

**Why.** Once the v2-adoption phase (bead `sase-w2.4`) lets a v2 claim supersede
matching v1 registry state in place, no machine should ever take the dead v1 import path
again — it has no prompt, no family container, and no parent linkage. Rejected
alternatives: deleting the v1 import code outright, with no flag, was rejected because
some machines migrate to v2 asynchronously and the old branch must stay reachable for
stragglers until they do; gating the call to `integrate_foreign_bundles` itself (before
it runs, in `incoming_integration.py`) was tried first and rejected because it also
blocked the owner-observed and self-owned-already-present classifications, which are
read-only evidence recognition, not materialization — this regressed
`test_username_unknown_v1_entries_are_grouped_by_machine_and_hood` before the gate was
pushed down into the two mutating branches inside `integrate_foreign_bundles`.

**Cost.** A genuinely-foreign v1 hood with no matching v2 payload (never migrated) now
stays pending forever in `sase agent sync --check` once the flag is on, since nothing
writes an import receipt for a skipped hood. The only supported exits are the
v2-adoption matcher (if a v2 counterpart eventually publishes) or the explicit fallback
command `sase agent names forget-import --machine <machine> --transport v1` added
alongside v2-adoption.

**Reopens when.** The flag bead `sase-wc` comes due (2026-12-02 / v0.19.0): if every
project reports zero `origin: import_v1` registry entries and zero pending legacy-v1
hoods left to migrate, delete the disabled (flag-off) branch, make the gate
unconditional, and close the bead. Extend instead if machines with live v1-imported
state are still observed at that point.
