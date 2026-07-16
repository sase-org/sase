# Plan Chain Golden Harness

Run this harness with:

```bash
pytest -m plan_chain_golden
```

It pins the current plan/questions lifecycle. Run it around changes to approval choices, marker handling, or prompt
reconstruction.

Pinned invariants:

- Plan approval choices still serialize to the legacy runner protocol. Phase 2 relies on this while replacing hard-coded
  choice tables with a registry.
- The live `run` choice remains a shared-writer path that runs the coder and participates in the same plan-archive side
  effect as approve. Phase 2 made that side effect deliberate.
- Modal fallback mappings without `result.choice` still infer protocol fields, status overrides, and persisted action
  labels. Phase 2 centralizes those mappings.
- Marker handling is consume-once, rejects stale markers, and lets explicit user kill win.
- A plan poll returning `None` after a fresh kill yields a killed outcome.
- A normally completing follow-up agent breaks the execution loop.
- Feedback-replan and Q&A follow-up prompts stay byte-identical at the shared helper boundary.
- Auto plan approval remains limited to `approve`, `tale`, and `epic`.
