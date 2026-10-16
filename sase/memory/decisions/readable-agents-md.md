---
keyword: The Committed AGENTS.md Stays A Readable Projection
aliases:
  - readable-agents-md
  - readable AGENTS.md
  - C1 readable projection
summary:
  The repo commits the full runtime AGENTS.md projection plus a CLAUDE.md copy, checked
  by CI; SASE runs still get per-invocation bundles, and agy, Qwen, and OpenCode stay on
  native AGENTS.md discovery.
metadata:
  status: accepted
  decided: 2026-10-16
---

**Claim.** The repo commits the full runtime projection (`AGENTS.md` plus a
byte-identical `CLAUDE.md` copy), checked by CI. It is the readable standing
instructions and the per-invocation fallback. SASE runs still get
[[decisions/instructions-per-invocation]] bundles. Antigravity (agy), Qwen, and OpenCode
stay on native `AGENTS.md` discovery.

**Why.** People, GitHub readers, and non-SASE tools get full transparency, and
`AGENTS.md` is a cross-vendor convention. 28 of the 29 bundle benefits do not need the
file untracked. Churn is small: 89 of 3,699 commits in 60 days. The Codex "can't
suppress" premise was false — `project_doc_max_bytes=0` suppresses native project
documents per invocation. The full file keeps every fallback complete, since no fallback
reads a retired provider copy.

Rejected alternatives: **the export stub with `sync` and a last-known-good store** (the
roadmap's E4) — there is nothing to sync, because the committed file is already
readable; **C2, committing the export render** — it would weaken the Grok and Muse
fallbacks; **prefix delivery for agy** — agy reads `AGENTS.md` natively with no
suppression switch, so a prefix bundle would load the contract twice.

**Cost.** Two artifacts to keep aligned; the CI drift gate and the parity test mitigate
this. Generated-file churn continues. agy loads the contract without the home layer.

**Reopens when.** Merge conflicts on generated files measurably slow landings. E7
audiences ship and a single file becomes misleading. Outside contributors need a
purpose-built stub. A legacy CLI gains a suppression switch or a system-prompt channel,
or Qwen or OpenCode gain real usage.
