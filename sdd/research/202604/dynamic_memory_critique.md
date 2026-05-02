# Dynamic Memory (Tier 2) Critique & Improvement Ideas

## Feature Summary

Dynamic memory matches keyword-tagged xprompts against the user's prompt before an agent session starts. Matched content
is resolved via `$(cat ...)`, written to a temp file, and injected into the prompt as `DYNAMIC MEMORY: @<path>`. The
agent runtime then inlines the file content during its `@`-reference resolution pass.

**Key files:**

- `src/sase/memory/dynamic.py` — keyword matching and temp file generation
- `src/sase/xprompt/loader.py:455-507` — auto-discovery of `memory/long/*.md` files with `keywords` frontmatter
- `src/sase/axe/run_agent_runner.py:219-247` — integration point (generation + prompt injection)
- `src/sase/llm_provider/preprocessing.py:30-52` — Prettier protection for `DYNAMIC MEMORY` lines

**Current memory pool:** 2 files (`external_repos.md`, `generated_skills.md`), ~16 keywords total.

---

## Critique

### 1. Substring matching causes false positives

The matching logic (`kw.lower() in prompt_lower`) does plain substring containment. This means:

- Keyword `"skill"` matches "unskilled", "reskilling", "skill" inside a URL path
- Keyword `"plugin"` matches "unplugging"
- Keyword `"cross-repo"` matches "across-repository" (hyphen alignment)
- Multi-word keywords like `"commit workflow"` only match that exact phrase, but single-word keywords are overly broad

With only 2 memory files and ~60 lines of content, false positives are cheap today. But as the pool grows, unnecessary
context injection becomes a real cost — both in tokens and in diluting the agent's focus.

**Suggestion:** Switch to word-boundary matching using `re.search(rf'\b{re.escape(kw)}\b', prompt, re.I)`. This
eliminates most spurious substring matches while keeping the implementation simple. The original research doc
(`sdd/research/202604/dynamic_memory_implementation.md`) noted this as an open question and chose substring for simplicity — now
that the feature is stable, the tradeoff has shifted.

### 2. No relevance scoring or threshold

Every keyword hit is binary: match or no match. A memory file that matches on a single low-signal keyword (e.g.,
"plugin" appearing in passing) is included with the same weight as one matching 5 highly specific keywords. There's no
way to express "only include this if the prompt is clearly about this topic."

**Suggestion:** Track the number of keyword hits per memory file and consider a minimum-hits threshold or a scoring
mechanism. For example, a memory file with 8 keywords that matches on 1 might be a weaker signal than one with 3
keywords matching on 2. A simple `min_hits: 2` frontmatter field per memory file would be a lightweight first step.

### 3. No negative keywords or exclusion patterns

There's no way to say "match on keyword X unless keyword Y is also present." As more memory files are added with
overlapping domains, disambiguation becomes important. For example, if a future memory file covers "skill testing" vs
"skill generation", the keyword "skill" alone can't distinguish them.

**Suggestion:** Support a `exclude_keywords` frontmatter field, or allow `!keyword` syntax within the keywords list to
express exclusion. Low priority until the memory pool grows, but worth designing for.

### 4. Full xprompt loading for a narrow filter

`generate_dynamic_memory()` calls `get_all_prompts()`, which loads every xprompt from all 9 priority-ordered sources
(CWD dirs, home dirs, config, plugins, internal). It then filters to just the handful with `XPromptTag.memory`. This is
a lot of I/O and parsing for a narrow filter.

Today this is fine (the xprompt pool is small enough that loading is fast). But it's worth noting as a scaling concern.
If the xprompt library grows significantly, a targeted loader that only discovers memory-tagged entries would be more
efficient.

**Suggestion:** No action needed now, but if profiling ever shows `generate_dynamic_memory` as a bottleneck, consider a
`get_memory_xprompts()` fast path that skips non-memory sources.

### 5. Temp files accumulate without cleanup

Temp files are created with `tempfile.NamedTemporaryFile(delete=False)` in `$SASE_TMPDIR` and are never explicitly
deleted. Each agent session creates a new temp file. Over time, these accumulate.

The impact is minimal (each file is tiny, and `$SASE_TMPDIR` is presumably cleaned periodically or on reboot), but
explicit cleanup at the end of an agent run would be more hygienic.

**Suggestion:** Either clean up the temp file at the end of the agent run in `run_agent_runner.py`, or document the
assumption that `$SASE_TMPDIR` is ephemeral. A simple `atexit.register(os.unlink, path)` in the runner would suffice.

### 6. Prompt injection placement

Dynamic memory is appended to the very end of the user's prompt:

```python
prompt = prompt + f"\n\nDYNAMIC MEMORY: @{dynamic_result.path}"
```

This means the agent sees it as a trailing appendix rather than integrated context alongside the AGENTS.md tier 1
memory. Depending on the runtime's attention patterns, trailing content may receive less weight than content that
appears in the system prompt or early in the conversation.

**Suggestion:** Consider whether injecting the memory reference into AGENTS.md (or a dedicated section within the system
prompt) would be more effective than appending to the user prompt. This is runtime-dependent and may not matter in
practice, but worth testing if relevance issues arise.

### 7. Preprocessing protection is a fragile workaround

The null-byte placeholder mechanism (`_protect_memory_lines` / `_unprotect_memory_lines`) exists solely because Prettier
converts underscores in `DYNAMIC MEMORY` and file paths to emphasis markdown. This is a symptom of a deeper issue:
running a markdown formatter on prompt text that isn't actually markdown.

The protection works today, but it adds ordering constraints to the preprocessing pipeline (must protect before
Prettier, must restore after). Each new preprocessing step that needs similar protection increases fragility.

**Suggestion:** This is fine as-is for now, but if more protection patterns emerge, consider either (a) teaching
Prettier to skip non-markdown regions, or (b) restructuring the pipeline so `DYNAMIC MEMORY` lines are never present
during formatting (e.g., strip them before preprocessing, reattach after).

### 8. No feedback loop on match quality

The `dynamic_memory.json` artifact records what matched, but there's no mechanism to learn whether the injected memory
was actually useful to the agent. Did the agent reference the injected content? Did it help? Was it irrelevant noise?

This matters for keyword tuning — without feedback, keyword lists are maintained by intuition rather than data.

**Suggestion:** Long-term, consider lightweight telemetry: did the agent's response reference concepts from the injected
memory? Short-term, this is a known gap with no easy fix.

### 9. `$(cat ...)` resolution happens eagerly

The content of memory xprompts uses `$(cat path)` syntax, which `process_command_substitution` resolves at generation
time (before the prompt reaches the agent). This means the temp file contains the fully resolved content.

This is fine, but it means the content is snapshotted at prompt-generation time. If the memory file changes during a
long agent session (unlikely but possible in development), the agent sees stale content. The original design proposed
`@` references that the runtime would resolve lazily, but that was abandoned due to cross-runtime compatibility
concerns.

**Not a real problem today** — memory files don't change mid-session. Just worth understanding the tradeoff.

### 10. Only 2 memory files exist — the system is under-exercised

The most important critique: the dynamic memory system was designed to accommodate growth, but it currently manages only
2 files totaling ~60 lines. This means:

- The keyword matching hasn't been stress-tested with overlapping or ambiguous keywords
- There's no evidence yet that the complexity of the system (xprompt tags, keyword matching, temp files, preprocessing
  protection) pays for itself vs. simply always loading the 60 lines
- The "tier 2" concept is validated architecturally but not empirically

**Suggestion:** The next step for this feature should be growing the memory pool. Identify 3-5 additional domains that
would benefit from conditional loading (e.g., testing patterns, TUI development, bead workflows, VCS operations). This
exercises the system and reveals whether the matching approach holds up under real diversity.

---

## Improvement Priority

| #   | Issue                       | Effort | Impact  | Priority      |
| --- | --------------------------- | ------ | ------- | ------------- |
| 10  | Grow the memory pool        | Medium | High    | **Do first**  |
| 1   | ~~Word-boundary matching~~  | Low    | Medium  | **Resolved**  |
| 2   | Relevance scoring/threshold | Low    | Medium  | Do soon       |
| 5   | ~~Temp file cleanup~~       | Low    | Low     | **Resolved**  |
| 6   | ~~Injection placement~~     | Low    | Unknown | **Resolved**  |
| 3   | Negative keywords           | Low    | Low     | When needed   |
| 7   | ~~Preprocessing fragility~~ | Medium | Low     | **Resolved**  |
| 4   | Targeted xprompt loading    | Medium | Low     | If bottleneck |
| 8   | Feedback loop               | High   | Medium  | Long-term     |
| 9   | Eager vs lazy resolution    | N/A    | N/A     | No action     |

---

## Resolved Items

Items #5, #6, and #7 were addressed by replacing the single temp file with individual `.sase/memory/` files and a
`### DYNAMIC MEMORY` markdown section. This eliminated temp file accumulation, improved injection placement with a
structured heading, and removed the Prettier protection workaround entirely.

Item #1 was addressed by switching from plain substring containment (`kw.lower() in prompt_lower`) to word-boundary
regex matching (`re.search(rf'\b{re.escape(kw)}\b', prompt, re.IGNORECASE)`). This eliminates false positives like
"skill" matching "unskilled" while preserving correct behavior for hyphenated, underscored, and dotted keywords.
