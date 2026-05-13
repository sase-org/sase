---
create_time: 2026-04-28 23:12:34
status: done
prompt: sdd/prompts/202604/multi_agent_xprompts.md
---
# Multi-Agent XPrompts: Implementation Plan

## Overview

Add support for **multi-agent xprompts**: xprompt files (or config-defined xprompts) whose body contains `---` segment
separators are expanded into multiple agent prompts and dispatched through the existing `launch_multi_prompt_agents()`
path. Every spawned agent receives the same xprompt input arguments, substituted into its segment.

Today the two systems are orthogonal:

- `parse_multi_prompt()` (`src/sase/agent/multi_prompt.py:39`) splits the **user-submitted prompt** on `---` at dispatch
  time.
- xprompt expansion (`src/sase/xprompt/processor.py:202`) inline-substitutes `#name(args)` with the xprompt body. The
  body is treated as a single string; any `---` inside it survives only as literal text.

So `sase run "#multi_agent_xp(arg)"` where `multi_agent_xp` has `---` in its body produces **one** agent that sees the
joined text with literal `---` markers, not N agents.

## Goal

Define and ship a single, simple semantic: when a top-level xprompt reference in a user prompt resolves to an xprompt
whose body contains segment separators, dispatch each segment as its own agent. Args are substituted before splitting,
so every segment has access to all of the xprompt's input arguments.

## Worked Example

`xprompts/three_phase.md`:

```
---
input:
  - name: feature
    type: line
---
%name:plan
Plan changes for {{ feature }}.

---

%wait
Implement {{ feature }} based on the plan.

---

%wait
Write tests for {{ feature }}.
```

User runs `sase run "#three_phase(login bug fix)"`. Today: 1 agent with literal `---` markers in its prompt. After this
change: 3 agents (`plan`, then two waiting agents), each receiving the body for one phase with `feature` substituted.

---

## Design Decisions

### D1. Where the split happens

**At dispatch time, immediately after `parse_multi_prompt()`** — in a new helper `expand_multi_agent_xprompts()` that
walks each user-prompt segment, detects whether the segment is "a top-level reference to a multi-agent xprompt", expands
the xprompt body with its args, and replaces the single segment with the resulting N sub-segments.

Why here, not elsewhere:

- **Not in the loader**: a multi-agent xprompt is a property of a _call site_ — it only matters when it's about to be
  dispatched. The XPrompt object stays a uniform `content: str`.
- **Not inside `process_xprompt_references()`**: that function returns a single string and is used in many contexts
  (workflow steps, directive extraction, embedded expansion). Changing its return type would ripple. Multi-agent
  semantics are a dispatch concern.
- **Not at agent runtime (`run_agent_phases.py`)**: by then we've already committed to one process per agent. Splitting
  there means spawning extra processes from inside an agent — the wrong direction.

The dispatch site already calls `parse_multi_prompt()` and already calls `launch_multi_prompt_agents(segments=...)`.
Inserting one transformation step between them is the minimal change.

### D2. What "top-level reference to a multi-agent xprompt" means

A segment qualifies for re-splitting iff **all** of these hold:

1. After stripping leading/trailing whitespace and any leading directive lines (`%name:...`, `%model:...`, `%wait`,
   etc.), the segment consists of exactly one xprompt reference (`#name`, `#name(args)`, `#name:arg`, or `#name+`) and
   nothing else.
2. The referenced xprompt is known and its body contains at least one `---` separator (outside fenced blocks).

If a segment contains a multi-agent xprompt reference mixed with other prose, that's an error: raise
`MultiAgentXPromptUsageError` with a clear message ("multi-agent xprompt #foo must be the only content in its segment").
This keeps semantics unambiguous; the user can split their prompt manually if they want surrounding text.

Directive preservation: leading directives on the calling segment (e.g. `%name:custom`) attach to the **first**
sub-segment only. The xprompt body is responsible for any per-segment directives it wants inside its own segments.

### D3. Argument propagation

Args are substituted into the **whole xprompt body** by the existing `_expand_single_xprompt()` /
`substitute_placeholders()` pipeline, then the substituted body is split on `---`. Every resulting segment naturally
references the same substituted values; nothing extra is needed.

For Jinja2 templates (`{{ feature }}`): rendering happens once over the full body, so loops and conditionals see
consistent state. For legacy `{1}`, `{2}`: same — substitution is a string-level pass over the full body.

Local xprompts defined in the user's frontmatter (`xprompts: { _foo: ... }`) remain available to every segment because
the existing per-segment dispatch already serializes `local_xprompts_for_segment(segment)` per agent. After
re-splitting, the new segments go through that same code path, so their references to `_foo` still resolve.

### D4. Detection: lazy, not stored on `XPrompt`

We do NOT add `is_multi_agent: bool` to the `XPrompt` dataclass. Detection is cheap (one regex over the body, with
fenced blocks protected) and only runs at dispatch when the segment is a candidate (rule D2.1). Keeping XPrompt simple
avoids breaking callers that construct `XPrompt` objects (config, plugins, frontmatter, env-delivered local xprompts).

A helper `xprompt_has_segment_separators(xp: XPrompt) -> bool` lives next to the new dispatch helper.

### D5. Nested multi-agent xprompts

If a multi-agent xprompt's body itself references another multi-agent xprompt as the sole content of one of its
segments, do we re-expand transitively?

**Decision: yes, recursively at dispatch time** — but only at the top level of each segment, with a depth cap (e.g. 8)
to prevent runaway. This matches the existing `_MAX_EXPANSION_ITERATIONS` philosophy and lets `multi_agent_a` compose
`multi_agent_b`. If `#b` appears inline inside `#a`'s body (not as a standalone segment), it expands inline as today
(joined with literal `---`).

If the user wants the inline form, they can compose with workflows or write the segments by hand. The clean rule is:
**only standalone-reference segments re-split**.

### D6. Escape syntax for literal `---`

Already handled by the existing `protect_fenced_blocks()` helper — `---` inside triple-backtick code fences is not
treated as a separator. We reuse it. No new escape syntax is needed.

### D7. Backwards compatibility

This change is purely additive. Existing single-segment xprompts keep working identically. Existing multi-segment user
prompts (with `---` in the user's text) are unaffected — the new logic only kicks in for segments that _qualify_ per D2.

Existing xprompts that happen to contain literal `---` in their bodies (if any) WILL change behavior. Audit: scan
`src/sase/xprompts/`, plugin xprompt repos, and `~/.xprompts/` for `---` outside fenced blocks. If any pre-existing
xprompt has incidental `---`, either fence it or rewrite. Track this in the plan's audit step (Phase 0).

---

## Phases

### Phase 0 — Audit existing xprompts

Goal: confirm no existing xprompt's body contains incidental `---` separators that would change behavior.

Steps:

1. Grep `src/sase/xprompts/**/*.md`, `plans/**/*.md` is N/A, plugin repos (`sase-github`, `retired Mercurial plugin`,
   `sase-telegram`, `sase-nvim`) for `^---$` lines outside fenced blocks.
2. For each hit, decide: (a) intentional segment break — leave and document the new behavior in the xprompt's
   snippet/description, or (b) accidental — wrap in fences or remove.
3. If any hit is in plugin repos, file a follow-up note (the plugin owner can ship the fix in their own release cycle;
   sase will not break the plugin because the user's installed plugin version still produces the old behavior unless
   they upgrade).

This phase is purely diagnostic; output a short summary of hits before writing code.

---

### Phase 1 — `expand_multi_agent_xprompts()` helper

**File**: `src/sase/agent/multi_agent_xprompt.py` (new)

Functions:

- `xprompt_has_segment_separators(xp: XPrompt) -> bool`
  - Run `protect_fenced_blocks` on `xp.content`, then look for any `^---\s*$` line in the protected text. Return bool.

- `extract_top_level_xprompt_reference(segment: str, available: set[str]) -> XPromptCall | None`
  - Strip leading directive lines (lines matching `^%[a-zA-Z]`) and trailing whitespace.
  - Use existing `extract_xprompt_calls()` from `workflow_validator_extract.py` to find references.
  - If exactly one reference is found AND it is the only non-directive content in the segment AND its name is in
    `available`, return a small dataclass `XPromptCall(name, positional_args, named_args, leading_directives)`. Else
    return `None`.
  - "Only non-directive content" check: substring of the segment after the directives equals the raw `#name(args...)`
    text (with maybe surrounding whitespace).

- `expand_multi_agent_xprompts(segments: list[str], local_xprompts: dict[str, XPrompt], *, max_depth: int = 8) -> list[str]`
  - For each segment:
    - Try `extract_top_level_xprompt_reference` against `get_all_xprompts() | local_xprompts`.
    - If hit and `xprompt_has_segment_separators(xp)`:
      - Call `_expand_single_xprompt(xp, positional_args, named_args)` to get the substituted body.
      - Split the body on `---` (with fenced-block protection — reuse the splitter from `multi_prompt.py`, factored into
        a shared helper).
      - Prepend the call site's leading directives to the **first** sub-segment.
      - Recurse into the resulting sub-segments with `max_depth - 1`.
      - Replace this segment with the resulting list.
    - Else: keep the segment as-is.
  - On `max_depth == 0` and a hit: raise `_MultiAgentXPromptDepthError`.
  - Return the new flat list.

**Exception class**: `MultiAgentXPromptUsageError` (raised when a multi-agent xprompt is referenced mid-segment;
dispatch sites surface it as a user-facing error like the existing `_LocalXPromptNameError` pattern).

**Refactor**: extract the `---` splitting routine from `multi_prompt.py` into a shared helper
`split_segments_protecting_fences(body: str) -> list[str]` so both `parse_multi_prompt` and the new helper share one
regex + one fenced-block protection round-trip.

---

### Phase 2 — Wire into dispatch sites

Three call sites currently consume `parse_multi_prompt(...).segments`:

1. **`src/sase/agent/launcher.py:266`** — `launch_agent_from_cwd()`
2. **`src/sase/main/query_handler/_query.py:121`** — `run_query()` (interactive `sase run` path)
3. **`src/sase/ace/tui/actions/agent_workflow/_agent_launch.py:164,297`** — TUI `@` keybinding

In each, after `multi = parse_multi_prompt(query)`:

```python
expanded_segments = expand_multi_agent_xprompts(
    multi.segments,
    local_xprompts=multi.local_xprompts,
)
```

Then pass `expanded_segments` (instead of `multi.segments`) to `launch_multi_prompt_agents` / downstream consumers.

A subtle detail at site 2: `run_query()` joins segments back into `query` with `\n---\n` and then treats it as a single
in-process query (no spawn). For multi-agent xprompt support there, the cleanest choice is to detect "did expansion
produce more than 1 segment?" and, if so, route through `launch_multi_prompt_agents` like sites 1 and 3. Otherwise keep
current behavior. We need to confirm this works with the in-process path; if not, document the limitation (multi-agent
xprompts only work through `sase run` daemon and TUI launch, not in-process foreground `run_query`). Phase 5 covers
this.

**Agent-runtime path** (`run_agent_phases.py:60`): does NOT need changes. By the time the prompt arrives at the agent,
it has already been split by the dispatch site, so each agent sees only its own segment (no `---` inside).

---

### Phase 3 — Tests

Create `tests/test_multi_agent_xprompt.py`:

- Single-segment xprompt → 1 agent (no change).
- 3-segment xprompt without args → 3 agents, each with the right body.
- 3-segment xprompt with positional + named args → 3 agents, all sharing substituted values.
- Jinja2 template body with `{% for %}` that emits content in two segments — args propagate.
- Multi-agent xprompt mixed with surrounding prose → `MultiAgentXPromptUsageError`.
- Multi-agent xprompt referenced inline inside another xprompt's body (NOT as standalone segment) → inline expansion (no
  re-split).
- Multi-agent xprompt that itself references another multi-agent xprompt as a standalone segment → recursive split.
- `---` inside fenced code blocks in xprompt body → not split.
- Leading `%name:custom` on the call site attaches to first sub-segment only.
- Local xprompts defined in user frontmatter resolve in every spawned segment.
- Depth cap: a self-referential multi-agent xprompt → `_MultiAgentXPromptDepthError`.

Augment existing tests:

- `tests/test_multi_prompt.py`: add a smoke test that a "non-multi-agent xprompt" referenced as a segment is left
  untouched.
- `tests/test_user_frontmatter.py`: confirm frontmatter local xprompts still flow through the new expansion step.
- `tests/test_xprompt_pylimit_split.py`: ensure model-split (`%m(opus,sonnet)`) still works inside a multi-agent xprompt
  sub-segment (composition).

---

### Phase 4 — Edge cases & docs

1. **Empty sub-segment after split**: drop empty/whitespace-only segments (mirrors `parse_multi_prompt`'s existing
   behavior).
2. **Xprompt with only a frontmatter and no body separators**: not multi-agent (no separators in body → detection
   returns False).
3. **`xprompt_has_segment_separators` cache**: cache by `id(xp)` if profiling shows the regex is hot; skip optimization
   for now.
4. **Documentation**:
   - Update `src/sase/xprompts/` example or the multi-prompt section of any user-facing docs (the project keeps these in
     `memory/long/` and `xprompts/` snippet fields, not standalone .md docs — so add a snippet-level note in any
     built-in xprompt that adopts the new feature).
   - Add a short note in `glossary.md` defining "multi-agent xprompt".
   - Update `plans/202603/multi_agent_prompts.md` is closed (status: done) — leave it. Cross-reference this plan from
     there as a follow-up only if requested.

---

### Phase 5 — `run_query()` in-process path decision

`run_query()` runs the query in-process (no subprocess spawn) for the foreground `sase run` path. Two options:

- **A. Route to `launch_multi_prompt_agents` when a multi-agent xprompt expands**: matches `sase run --daemon` behavior.
  Pros: consistent. Cons: the foreground path no longer stays foreground for multi-agent runs.
- **B. Keep in-process, but execute segments sequentially in the same process**: more invasive, conflicts with
  `%wait`-based orchestration that assumes spawned subprocesses with named agents.

**Recommendation: A.** Multi-agent dispatch fundamentally needs spawned subprocesses (each agent has its own workspace,
its own artifacts dir, its own `agent_meta.json`). The in-process foreground path remains for _single-agent_ prompts.
This is consistent with how the existing user-prompt `---` splitting already works at site 1 (`launch_agent_from_cwd`).

Action: in `run_query()`, after `expand_multi_agent_xprompts()`, if `len(expanded_segments) > 1`, fall back to the same
dispatch path used in `launch_agent_from_cwd` (call `launch_multi_prompt_agents`, return its first result, mark the
foreground path as having handed off).

---

## Out of Scope

- Per-segment input arg overrides (different args for different segments). If needed later, add a syntax like
  `#xp(arg).segment(0, override=...)`. For now, all segments share the same args.
- Per-segment frontmatter inside an xprompt body. The xprompt loader consumes the file's frontmatter once; we do not
  parse mini-frontmatter at the head of each segment.
- Workflow-level multi-agent dispatch. Workflows already have a richer step model; if a workflow needs multi-agent
  dispatch it should declare multiple `agent`-type steps explicitly.

---

## Acceptance

- `sase run "#three_phase(login bug fix)"` (with the xprompt above) spawns 3 agents whose `agent_meta.json` files show
  the right `name`/`wait_for` chaining and whose `raw_xprompt.md` files contain only that segment's substituted body.
- `just check` passes (lint + mypy + tests).
- New tests in `tests/test_multi_agent_xprompt.py` cover all enumerated cases.
- No regressions in existing `tests/test_multi_prompt*.py`, `tests/test_user_frontmatter.py`,
  `tests/test_xprompt_pylimit_split.py`, `tests/test_run_workflow_visibility.py`.
