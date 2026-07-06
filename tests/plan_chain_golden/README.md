# Plan Chain Golden Harness

Run this harness with:

```bash
pytest -m plan_chain_golden
```

It pins the current plan/questions lifecycle before the Dynamic Agent Families v2 state-machine work restructures that
path. Later phases should run it before and after any refactor that touches approval choices, marker handling, handoff
events, or prompt reconstruction.

Pinned invariants:

- Plan approval choices still serialize to the legacy runner protocol. Phase 2 relies on this while replacing hard-coded
  choice tables with a registry.
- The live `run` choice remains a shared-writer path that runs the coder but does not archive the plan yet. Phase 2
  deliberately changes that archive behavior.
- Modal fallback mappings without `result.choice` still infer protocol fields, status overrides, and persisted action
  labels. Phase 2 centralizes those mappings.
- Marker handling is consume-once, rejects stale markers, and lets explicit user kill win. Phase 3 routes this through
  typed events.
- A plan poll returning `None` after a fresh kill yields a killed outcome. Phase 3 must preserve that user-kill
  boundary.
- A normally completing follow-up agent breaks the exec loop; there is no post-coder lifecycle seam today. Phase 4
  deliberately relaxes this through `role_completed`.
- Feedback-replan and Q&A follow-up prompts stay byte-identical at the shared helper boundary. Phases 3-5 preserve these
  prompt bodies while changing the dispatcher.
- Auto plan approval remains limited to `approve`, `tale`, and `epic`. Later custom-role auto behavior must be explicit
  rather than accidentally enabled.
