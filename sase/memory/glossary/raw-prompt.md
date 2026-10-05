---
keyword: Raw Prompt
---

The raw prompt is an agent's launch prompt after project tags and macro aliases are
canonicalized (`+sase` becomes a `#gh:` workspace reference and `#c` becomes `#commit`)
and before any macro invocation expands. It is saved as `raw_prompt.md`, shown on the
RAW PROMPT tab, and reused by restarts. It follows the submitted prompt
(`submitted_prompt.md`, the launch-boundary text before canonicalization) and precedes
the expanded prompt the model receives, from which directives are stripped. It is
unrelated to `sase prompt show -f raw` and to raw `<label>` placeholders.
