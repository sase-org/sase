# Episode V2 Phase 9 Pilot

Date: 2026-05-29

Scope: read-only Phase 9 pilot against the local `sase` May 2026 episode corpus.

Commands:

```bash
.venv/bin/sase memory episodes list -s 2026-05-01 -u 2026-05-29 -o importance -l 10 -j
.venv/bin/sase memory episodes export -s 2026-05-01 -u 2026-05-29 -o importance -l 5 -j
.venv/bin/sase memory episodes recall -q "retry feedback" -l 5 -j
.venv/bin/sase memory episodes build -s 2026-05-28 -u 2026-05-29 --split -l 30 -D -j
```

Results:

- Stored inventory for May 2026 currently contains one legacy aggregate episode:
  `ep-6dcdf1e3f2e4d8665029f093`.
- Legacy recall still returns lesson cards with evidence links for `retry feedback`.
- Event-readiness export is bounded and read-only: it returned `writes_events: false`, a top-level `limit`, per-episode
  source/factor/safety limits, compact source refs, safety fields, and no `sdd/events/` writes.
- Dry-run split build for May 28 produced 27 v2 component episodes from 30 project-scan seeds and did not write episode
  files (`wrote: false`).
- The dry-run split output demonstrated component separation that the stored legacy aggregate lacks. Components carried
  stable v2 IDs, component keys, strong graph edges, weak ChangeSpec/family/path refs, source refs, safety flags, and
  zero lesson records.
- Importance in the bounded May 28 sample was non-uniform (`low` and `medium` were present). The sample did not include
  a high-importance component.
- Weak refs remained metadata in the sample. Repeated `changespec=sase` weak refs did not collapse the bounded project
  scan into one component.
- One connected multi-agent component (`ep-6735dd21a81e574eb8b19a77`) merged related plan/code evidence and surfaced
  missing source warnings without blocking the dry run.

Handoff notes:

- The local stored corpus should be rebuilt with split v2 storage before relying on inventory/export for real event
  selection; today the durable May corpus is still a v1 aggregate.
- Phase 9 export is suitable as the read-only input shape for future event review, but event promotion remains a
  separate non-goal.
