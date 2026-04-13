# Research: Codified Context Paper Insights for Dynamic Memory

## Paper Summary

**"Codified Context: Infrastructure for AI Agents in a Complex Codebase"** (Vasilopoulos, arXiv:2602.20478v1, Feb 2026)
describes a three-tier context architecture developed during construction of a 108K-line C# distributed system across
283 agent sessions over 70 days:

- **Tier 1 (Hot Memory / Constitution):** ~660-line Markdown file, always loaded. Conventions, build commands,
  orchestration protocols, trigger tables for routing tasks to specialist agents.
- **Tier 2 (Specialist Agents):** 19 domain-expert agent specifications (~9,300 lines total, 115-1,233 lines each). Over
  half of each spec is embedded domain knowledge, not behavioral instructions.
- **Tier 3 (Cold Memory / Knowledge Base):** 34 Markdown specification documents (~16,250 lines). Single-subsystem
  scope. Retrieved on demand via an MCP server with keyword search.

Total context infrastructure: ~26,200 lines (24.2% of total codebase). The paper validates four mechanisms by which
codified context improves outcomes: inter-session coordination, captured experience, gap detection, and domain-expert
diagnosis.

## Mapping to SASE's Memory Tiers

| Paper Tier             | SASE Equivalent         | Status            |
| ---------------------- | ----------------------- | ----------------- |
| T1: Constitution       | `memory/short/*.md`     | Implemented       |
| T2: Specialist Agents  | xprompts / skills       | Implemented       |
| T3: Knowledge Base     | `memory/long/*.md`      | 7 files, ~250 LOC |
| MCP Retrieval Service  | Dynamic memory (tier 2) | Implemented       |
| Trigger Tables         | Dynamic memory keywords | Implemented       |
| Context Drift Detector | (no equivalent)         | Missing           |

The paper's MCP retrieval service (keyword search over Tier 3 specs) maps directly to our dynamic memory's keyword
matching. The key difference: the paper's retrieval is agent-initiated (the agent calls `find_relevant_context(task)`),
while ours is pre-session (sase matches keywords before the agent starts). Both approaches have tradeoffs worth
understanding.

---

## Insights and Improvement Ideas

### 1. Knowledge Embedding in Specialists (Brevity Bias Problem)

**Paper insight:** Over half of each specialist agent specification is project-domain knowledge, not behavioral
instructions. The networking agent (915 lines) embeds the full determinism theory because "partial knowledge risks
desynchronization bugs." The paper calls this intentional overlap with Tier 3 and links it to the "brevity bias"
phenomenon from the ACE research (Zhang et al., 2026) -- iterative optimization collapses toward short, generic prompts
that perform worse.

**Relevance to SASE:** Our dynamic memory files are short summaries (25-35 lines each). The paper suggests this may be
insufficient for complex domains. When a memory file is injected, it should provide enough context that the agent can
act correctly without needing to read additional files. The paper's "symptom-cause-fix tables" pattern is a concrete
format worth adopting.

**Potential improvement:** For high-complexity domains (e.g., the axe agent runner, TUI development), consider whether
the dynamic memory content is rich enough to be actionable, or whether it merely points the agent in the right direction
and hopes it reads more. The paper's heuristic: "if debugging a particular domain consumed an extended session without
resolution, the knowledge is insufficient."

### 2. Trigger Tables and Automatic Routing

**Paper insight:** The constitution embeds trigger tables that route tasks to specialist agents based on observable
signals (primarily which files are being modified). "Automatic routing removes the burden of the developer remembering
which agent to invoke." Routing compliance is reinforced by redundant encoding.

**Relevance to SASE:** Our dynamic memory already implements a version of this -- keywords act as triggers that route
context to the agent. But the paper's triggers are richer: they include pre-change vs post-change timing, file-pattern
signals (not just keyword matches), and explicit agent routing (not just context injection).

**Potential improvements:**

- **File-pattern triggers:** Add support for matching against the files mentioned in the user's prompt or the files in
  the current git diff, not just keyword text. A user working on `src/sase/ace/` files should automatically get TUI
  development context even if they never say "TUI" in their prompt. This would complement keyword matching with
  path-based matching.
- **Pre-change vs post-change context:** Some context is most useful before the agent starts (domain knowledge), while
  other context is most useful after changes are made (review checklists). Our current system only supports pre-change
  injection. Consider whether post-change context injection (e.g., as part of `just check`) would be valuable.

### 3. Emergence Pattern: Failure-Driven Agent/Memory Creation

**Paper insight:** Agent creation was driven by observed failure patterns, not upfront design. "When a category of task
repeatedly required re-explaining the same domain knowledge, that knowledge was codified." The heuristic: "if debugging
consumed an extended session without resolution, it was faster to create a specialized agent and restart."

**Relevance to SASE:** Our 7 memory files were also created based on observed need. The paper validates this approach
but suggests being more systematic about it. The paper tracked 283 sessions and could identify patterns retrospectively
from interaction data.

**Potential improvement:** Add lightweight telemetry to track when dynamic memory is matched but the agent still
struggles, or when the agent reads a long-term memory file that isn't in the dynamic memory pool (indicating a missing
keyword or missing memory file). The `dynamic_memory.json` artifact already captures match data; extending it with
outcome data would close the feedback loop identified in the existing critique (item #8).

### 4. Knowledge Base Document Structure

**Paper insight:** Tier 3 specifications follow a consistent structure: correctness pillars (table of invariants), core
mechanisms (code patterns with file paths), and known failure modes (symptom-cause-fix tables). Documents are "written
for AI consumption" with explicit code patterns, parameter names, and expected behavior.

**Relevance to SASE:** Our `memory/long/*.md` files vary in structure. Some are well-structured (bead_system.md has
clear sections), others are more narrative. The paper suggests a more rigorous template would improve agent reliability.

**Potential improvement:** Define a recommended template for `memory/long/*.md` files:

```markdown
# {Subsystem Name}

## Key Invariants

| Invariant | Enforcement | What Breaks If Violated |
| --------- | ----------- | ----------------------- |
| ...       | ...         | ...                     |

## Core Patterns

{Code patterns with file paths and function names}

## Known Failure Modes

| Symptom | Cause | Fix |
| ------- | ----- | --- |
| ...     | ...   | ... |

## Related Files

{Key file paths in the codebase}
```

### 5. MCP Retrieval vs Pre-Session Injection

**Paper insight:** The paper uses an MCP server with five tools (`list_subsystems`, `find_relevant_context`,
`search_context_documents`, `suggest_agent`, `get_files_for_subsystem`) for agent-initiated retrieval. This is
fundamentally different from our pre-session keyword matching.

**Tradeoff analysis:**

| Dimension             | Agent-initiated (Paper)             | Pre-session (SASE)                    |
| --------------------- | ----------------------------------- | ------------------------------------- |
| Precision             | Higher (agent has task context)     | Lower (keyword heuristic)             |
| Reliability           | Depends on agent choosing to search | Guaranteed (runs before agent starts) |
| Latency               | Mid-session retrieval adds latency  | No mid-session cost                   |
| Over-inclusion        | Agent can be selective              | May inject irrelevant context         |
| Runtime compatibility | Requires MCP support                | Works with any runtime                |
| Agent autonomy        | Agent drives its own context        | System drives context for agent       |

**Key observation:** The paper reports that agents using the MCP retrieval service referenced 194 knowledge base
documents across 218 sessions, with 1,478 total retrieval calls. This high engagement suggests agents are willing and
able to self-serve when given retrieval tools. However, the paper also notes that orchestration protocols _required_
retrieval before changes -- it wasn't purely optional.

**Potential improvement:** These approaches aren't mutually exclusive. Pre-session injection handles the common case
(relevant context loaded before the agent needs it), while agent-initiated retrieval handles the long-tail case (agent
discovers mid-session that it needs context not in the pre-loaded set). SASE could support both by:

1. Keeping the current pre-session dynamic memory (guaranteed baseline)
2. Adding a retrieval mechanism (MCP tool or skill) that lets agents search the full memory pool on demand

### 6. Context Drift Detection

**Paper insight:** A "context drift detector" (Python, session-start hook) parses recent git commits against the
retrieval service's subsystem-to-file mapping and injects a warning when source files change without corresponding
specification updates. This addresses the biggest maintenance risk: stale specifications.

**Relevance to SASE:** Our `memory/long/*.md` files have no staleness detection. If the axe agent runner changes
significantly but `axe_agent_runner.md` isn't updated, agents get stale context. The paper found that stale specs caused
at least two incidents where agents generated code conflicting with recent refactors.

**Potential improvement:** Implement a lightweight drift detector as a pre-session hook:

1. Each `memory/long/*.md` file lists its "Related Files" (key source paths).
2. Before an agent session, compare the last-modified date of the memory file against git log of its related files.
3. If source files changed more recently, inject a warning: "Note: {memory_file} may be stale -- {related_files} changed
   since it was last updated on {date}."

This is low-effort (the mapping already partially exists in the memory files' descriptions) and high-value (prevents the
silent-failure mode the paper describes).

### 7. Knowledge-to-Code Ratio as Diagnostic Signal

**Paper insight:** The project's knowledge-to-code ratio of 24.2% is presented not as a target but as a signal. "A more
actionable signal is agent behavior: when an agent produces inconsistent output or seems uncertain about a domain, the
relevant specification is likely missing or stale."

**Relevance to SASE:** Our ratio is much lower (~250 lines of long-term memory across ~108K lines of code, roughly
0.2%). Even including short-term memory (~60 lines) and AGENTS.md, we're well under 1%. The paper suggests this is fine
if agent behavior is consistent, but worth monitoring as the codebase grows.

**Not an actionable improvement** -- included for calibration. The paper's project (real-time multiplayer simulation)
has unusually high documentation needs due to distributed systems complexity. SASE's needs may be different. The key
heuristic is behavioral: track where agents struggle, not where the ratio is low.

### 8. Redundant Encoding for Reliability

**Paper insight:** Routing compliance is "reinforced by redundant encoding" -- the constitution requires the
orchestrator to consult the trigger table _and_ requires use of `suggest_agent()` via MCP. Multiple paths to the same
knowledge increase the probability that agents find it.

**Relevance to SASE:** Our system has some redundancy already (tier 3 files are both listed in AGENTS.md for on-demand
reading _and_ injected via dynamic memory when keywords match). The paper validates this dual-access pattern.

**Potential improvement:** Consider adding a third access path for the most critical memory files: embedding key
invariants directly in the relevant source code as structured comments that agents encounter during code reading. This
is probably overkill for SASE today, but the principle of redundant encoding is sound.

### 9. Semantic Retrieval as Upgrade Path

**Paper insight:** The current MCP implementation uses keyword substring matching. The paper explicitly calls out
"replacing keyword matching with embedding-based retrieval" as a future direction that "would improve precision at
scale."

**Relevance to SASE:** Our dynamic memory critique (item #8) already identifies the lack of a feedback loop as a gap,
and the original implementation research (Approach A recommendation) notes "upgrade path to LLM matching" as a strength.
The paper validates this trajectory.

**Potential improvement path:**

1. **Current (keyword matching):** Sufficient for 7 memory files. Cheap, fast, deterministic.
2. **Near-term (weighted keywords + min-hits threshold):** The critique's item #2. Add relevance scoring so a single
   low-signal keyword match doesn't trigger inclusion. Also: add negative keywords (critique item #3) to disambiguate
   overlapping domains.
3. **Medium-term (LLM classification):** Use a fast model (Haiku) to classify whether the prompt is relevant to each
   memory file based on its `description` field. More expensive but handles novel phrasings.
4. **Long-term (embedding retrieval):** Index all memory files with embeddings, do similarity search against the prompt
   embedding. Handles the full long-tail of phrasing variation.

### 10. Case Study Patterns Worth Replicating

The paper's four case studies each illustrate a distinct value pattern. Mapping these to SASE's memory system:

**CS1: Coordination Document (save system spec referenced in 74 sessions)**

- Pattern: A specification becomes the "source of truth" that multiple sessions coordinate around.
- SASE equivalent: `bead_system.md` and `changespec_lifecycle.md` serve this role. Their value compounds as more
  sessions reference them.
- Implication: Invest in keeping these files authoritative. The paper's 283-session experience shows that
  well-maintained specs prevent bugs across dozens of independent sessions.

**CS2: Captured Experience (UI sync routing patterns)**

- Pattern: Hard-won debugging lessons are codified into a decision tree that prevents future agents from re-deriving
  through trial-and-error.
- SASE equivalent: The "Known Failure Modes" / "Gotchas" pattern. Our `memory/short/gotchas.md` serves this for
  always-loaded content. Long-term memory files should similarly capture debugging lessons as symptom-cause-fix tables.
- Implication: After a difficult debugging session, create or update a memory file with the lessons learned. The paper's
  heuristic: "if the developer manually diagnosed and corrected through multiple iterations, capture the final
  knowledge."

**CS3: Knowledge Gap Detection (drop system had no spec)**

- Pattern: Searching for documentation and finding _nothing_ is itself a valuable signal.
- SASE equivalent: When an agent searches for relevant context via dynamic memory and gets no matches, that may indicate
  a missing memory file rather than an irrelevant query.
- Implication: Log "no match" events alongside match events. If the same type of prompt repeatedly gets no dynamic
  memory matches but the agent struggles, that's a signal to create a new memory file.

**CS4: Domain-Expert Diagnosis (deterministic RNG debugging)**

- Pattern: A specialist agent with embedded domain knowledge identifies issues that general sessions miss.
- SASE equivalent: This maps more to specialist xprompts/skills than to dynamic memory. But the paper's observation that
  the specialist's specification was ~65% domain knowledge validates the idea of rich, content-heavy memory files for
  complex domains.

---

## Prioritized Recommendations

### High Priority (informed by paper's strongest findings)

1. **File-pattern triggers for dynamic memory** -- Complement keyword matching with path-based matching against files
   mentioned in the prompt or current git diff. The paper's trigger tables are richer than pure keyword matching, and
   file patterns are a concrete, implementable signal. This is the single most impactful gap between our system and the
   paper's.

2. **Context drift detection** -- Implement a lightweight staleness warning for memory files based on git history of
   related source files. The paper identifies stale specs as the primary failure mode and includes a drift detector in
   its companion repo. Low effort, high value.

3. **Symptom-cause-fix tables in memory files** -- Adopt the paper's structured documentation format for the "Known
   Failure Modes" section of memory files. This directly addresses the captured-experience pattern (CS2) that the paper
   shows prevents repeated debugging.

### Medium Priority (validated by paper, worth doing incrementally)

4. **Relevance scoring (min-hits threshold)** -- Already identified in the existing critique. The paper's MCP retrieval
   gives agents control over precision; our pre-session injection should compensate with better filtering.

5. **No-match logging** -- Track when prompts get zero dynamic memory matches. The paper's CS3 shows that knowledge gaps
   are diagnostic signals. Logging them creates a lightweight feedback loop.

6. **Memory file template** -- Standardize the structure of `memory/long/*.md` files based on the paper's spec format
   (invariants, patterns, failure modes, related files). Consistency improves both agent consumption and human
   maintenance.

### Low Priority (paper validates but SASE doesn't need yet)

7. **Agent-initiated retrieval (MCP/skill)** -- The paper's MCP retrieval is powerful but requires MCP support in all
   runtimes. Our pre-session injection handles the common case. Revisit when the memory pool grows beyond what keyword
   matching can handle (15+ files).

8. **Embedding-based retrieval** -- The paper calls this out as future work for their own system. SASE is even further
   from needing this given its smaller memory pool.

9. **Knowledge-to-code ratio tracking** -- The paper uses this as a diagnostic signal. Not actionable for SASE today,
   but worth being aware of as the project grows.

---

## Key Takeaways

1. **The paper validates SASE's three-tier architecture.** The tier structure (always-loaded, conditional, on-demand) is
   the same pattern, independently arrived at. The paper provides 283-session empirical evidence that this architecture
   works at scale.

2. **Pre-session injection and agent-initiated retrieval are complementary, not competing.** The paper uses
   agent-initiated retrieval; SASE uses pre-session injection. Both have strengths. The ideal system has both.

3. **The paper's biggest lesson is about maintenance, not matching.** Stale specifications are the primary failure mode,
   not imprecise retrieval. A drift detector that warns about stale memory files would address the highest- risk failure
   mode.

4. **Rich domain knowledge in memory files outperforms minimal pointers.** The paper's specialist agents embed

   > 50% domain knowledge. Our memory files should be content-rich enough to be actionable without additional file
   > reads, not just navigation aids.

5. **Failure-driven memory creation is the right approach.** Both the paper and SASE create memory files in response to
   observed agent failures. The paper adds a systematic dimension: tracking interaction patterns to identify failure
   clusters, not just individual incidents.
