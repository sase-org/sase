---
keyword: Instruction Bundle
aliases:
  - instruction bundle
---

An instruction bundle is the frozen per-invocation render of the project, home, and SASE
instructions for one agent invocation, built from `sase/memory/` plus the operator's
home memory layer and a provider directive. Each SASE root invocation gets one bundle,
delivered exactly once through an adapter-owned explicit channel; preview it with
`sase instructions render` and inspect what an agent received with
`sase instructions show NAME`. Successful preparation records the bundle bytes beside
its [[glossary:instruction-manifest]] under `instructions/`. It never contains the
committed `AGENTS.md` projection header.
