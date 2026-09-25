---
keyword: Triage Verdict
---

A triage verdict summarizes the stored failure-item classes for one failed
[[glossary:tool-run]]: it distinguishes new failures from runs with only KNOWN or FLAKY
items, while preserving the command's original exit code. Missing evidence remains
UNKNOWN rather than being attributed to another agent.
