---
create_time: 2026-05-30
status: research
revised: 2026-05-30
---

# Consolidated SASE Episode Lessons For Long-Term Memory

## Question

Review the existing SASE project episodes and identify lessons future agents could learn from. End with a recommendation
for which lessons should be added as long-term memories in `memory/long/`.

This file consolidates and verifies the two research-swarm drafts:

- `sdd/research/202605/sase_episode_lessons_memory_recommendations.md`
- `sdd/research/202605/sase_episode_lessons_review.md`

It also folds in the strongest non-duplicative context from the pre-existing same-topic research note. The final
recommendations below do not modify `memory/long/`; memory changes need explicit approval and should go through
`sase memory write` plus `sase memory review`.

## Verification

I verified the drafts against the current generated episode store, current code/docs, and the older in-repo SDD corpus
that predates generated episodes:

- `sase memory episodes status -p sase -j`
- `sase memory episodes list -p sase -j -o time`
- `sase memory episodes list -p sase -j -o importance`
- `sase memory episodes show -p sase <episode-id> --format overview`
- `sase memory episodes verify -p sase --all`
- `sase memory episodes doctor -p sase -j`
- `docs/episodes.md`
- `src/sase/memory/episodes/*`
- `src/sase/default_config.yml`
- `src/sase/config/core.py`
- `src/sase/axe/config.py`
- `src/sase/default_xprompts/research_swarm.md`
- related SDD tales, prompts, epics, legends, and research files under `sdd/`

Existing long-term memories were read with audited `sase memory read` commands:

- `memory/long/generated_skills.md`
- `memory/long/tui_jk_baseline.md`

Neither existing long memory covers the episode-system or AXE/chop lessons recommended here.

## Inventory

The current project episode store has 83 stored SASE episodes under `~/.sase/projects/sase/episodes`.

| Metric | Count |
| --- | ---: |
| Stored episodes | 83 |
| Source refs | 620 |
| Agent roots | 64 |
| Chat refs | 112 |
| Medium-importance episodes | 6 |
| Low-importance episodes | 77 |
| Episodes with safety warnings | 7 |
| Alias rows | 2 |

Verification checked all 83 episodes: 68 are clean and 15 are drifted, with 123 missing source refs and 6 changed source
refs. That drift matters: episodes are durable evidence indexes, but their source refs can age or disappear, so future
agents should reread and verify cited sources before promoting a lesson.

The six medium-signal episodes are:

| Episode | Agents | Main lesson area |
| --- | --- | --- |
| `ep-c2f1302a907fd2416145ffcb` | `bn7`, `bn7-code` | Artifact path display/copy should use workspace metadata. |
| `ep-dbf0db9652514f21e736506e` | `bn8`, `bn8-code`, `bn8.f1`, `bn8.f1-code` | Notification modal tabs are top-level taxonomy. |
| `ep-decdbb3262ba2afee38eda4a` | `boc`, `boc-code` | Notification footer bracket bindings need Rich/Textual markup-safe hints. |
| `ep-4073e6ba115b2988964c3fc5` | `bod`, `bod.f1`, `bod.f1-code` | Episode v2 visualization and component gotchas. |
| `ep-c1d2a252147001e9f0eeccd9` | `bof`, `bof-code` | `memory_episodes` AXE chop configuration. |
| `ep-c70b902cbab33f08deec31ee` | `boj`, `boj-code` | Agent root status overrides must reconcile with freshly loaded state. |

Several low-scored episodes are still important: the research-swarm cluster around `sdd/events/` versus episodes, the
bulk episode-generation episode `ep-6b9619e5a9228eefaa7e94a5`, and repeated scheduled-chop episodes.

The older in-repo SDD corpus is not the same as the generated episode store, but it is useful context for this request
because it is the repo's durable record of SASE project work from before generated episodes were available. I treated
that corpus as a cross-check, not as equal-weight evidence for the final episode-specific recommendations.

## Durable Lessons

### 1. Episodes Are Evidence, Not Instructions

`docs/episodes.md` is explicit: episodes are deterministic, source-linked evidence records. They do not write
`memory/short` or `memory/long`. If an episode contains a reusable project rule, propose it with `sase memory write` and
approve it with `sase memory review`.

The research-swarm cluster adds the governance context:

- Raw chats and artifacts are source evidence.
- Private episodes are generated evidence indexes.
- Curated `sdd/events/` records can be reviewed, repo-safe project history.
- `memory/long` remains the small reviewed semantic/procedural memory layer.

Episode export is read-only and reports `writes_events: false`; it should feed reviewable proposals, not directly write
events or long memory. This is the strongest lesson in the corpus because it protects the trust boundary between
untrusted generated evidence and durable agent instructions.

### 2. Episode Builds Need Narrow Selectors And Strong-Lineage Boundaries

Project-scan date filters select seed records, not arbitrary hard component boundaries. Strong lineage can still pull in
related retry, fork, parent, response-chat, and workflow-step records. Weak refs such as ChangeSpec, bead, family,
touched path, and generic file evidence should remain metadata/search signal rather than component-join criteria.

The historical project-scan hang episode is a useful warning: a May 26 build expanded 255 date-window seed records into
5,672 ChangeSpec-linked records before the boundary fix. The current docs and code now describe bounded project-scan
behavior and recommend choosing the narrowest selector available:

- `--agent`
- `--artifact-dir`
- `--changespec`
- `--chat`
- project scan with `--split` only when the date window is the real seed set

Human-mode build progress now goes to stderr and `--json` stays clean on stdout. Do not mistake a slow build for a hung
one without checking progress, selectors, and `doctor`/`status`.

### 3. Safety Warnings And Drift Are Review Signals, Not Failure

Episode rows can show `warnings=N safety flag(s)` while remaining `active` and queryable. Current warning derivation
includes:

- `hidden-source:*`
- `private-source:*`
- `missing-source:*`
- prompt-injection phrase hits
- credential/redaction pattern hits

The observed medium episodes with warnings were still successful episodes. Treat warnings and verification drift as
"verify before reuse", especially before promotion to memory, not as "the episode is broken".

### 4. Episode V2 Views Should Separate Lineage From Evidence Noise

The episode v2 implementation episodes produced reusable view/component gotchas:

- Timeline grouping should prefer actor/conversation labels (`agent_run`, then `chat`, then `workflow_step`) over
  marker-file labels such as `episode_trace.json`.
- Strong graph mode should show lineage structure; evidence/file edges such as `source`, `artifact`, `output`, `diff`,
  `plan`, `feedback`, `question`, and `memory_context` belong in weak/all mode.
- Related-timestamp expansion must skip the current artifact record to avoid retry self-loop edges.
- Bulk/day builds can miss standalone chats with no artifacts; coverage audits may need a chat-seeding pass that folds
  records into existing canonical episodes instead of creating duplicates.

These are narrow implementation facts, but together they are the practical rule future agents need: v2 episodes are
connected components over strong historical lineage, with weak metadata and evidence kept inspectable but not allowed to
distort the default graph.

### 5. Scheduled Chops Use Two Cadences And Atomic Markers

AXE lumberjacks have an `interval` wake frequency and optional `chop_timeout`; individual chops can also have
`run_every`. A typical `memory_episodes` opt-in config uses:

```yaml
axe:
  lumberjacks:
    memory:
      interval: 300
      chop_timeout: "10m"
      chops:
        - name: memory_episodes
          run_every: "15m"
```

`interval: 300` means the lumberjack wakes every five minutes; `run_every: "15m"` means that chop runs at most every
fifteen minutes. The configured chop name resolves to the `sase_chop_memory_episodes` script entry point.

The repeated audit/pylimit/refresh-docs episodes also expose a reusable automation pattern: persist a marker under
`~/.sase/projects/<project>/`, count commits since that marker, launch only past a threshold, and update the marker only
after a successful launch. This gives periodic automation batching, idempotence, and first-run/corrupt-marker recovery.

When editing user config, dicts merge recursively but user-base lists replace default lists. Add a new lumberjack rather
than appending to an existing default lumberjack's `chops` list unless replacing that list is intentional.

### 6. Research Swarms Are Useful But Need Cleanup Discipline

`src/sase/default_xprompts/research_swarm.md` records a reusable workflow shape:

1. Launch independent Codex and Claude research agents.
2. Wait for both.
3. Have a final agent read both transcripts, consolidate findings, and delete intermediate drafts.
4. Fork the final result to an image agent when a visual artifact is useful.

The workflow is valuable for open-ended research because it creates model diversity without keeping duplicate drafts.
This current consolidation follows that pattern.

### 7. TUI Findings Are Real But Mostly Secondary Memory Candidates

The TUI episodes contain valid lessons, but most are narrower than the episode-system and chop/orchestration findings:

- Keep display formatting separate from stored data and CLI contracts. Examples: repo-relative artifact display/copy and
  notification tag label capitalization.
- Notification modal tabs are top-level taxonomy. `Muted` has precedence over `HITL`, `Errors`, stored tags, and
  `General`; mute/snooze can move a row out of the active tab.
- `[` and `]` notification-tab bindings are modal-local `BINDINGS`; footer discoverability does not require default
  keymap config changes. Hint strings need Rich/Textual markup-safety tests.
- Notification-derived agent status overrides are presentation hints. Fresh loader/family aggregation should clear stale
  `QUESTION` overrides when a root has advanced to active statuses such as `RUNNING` or `PLAN APPROVED`. Stale tokens
  for worker plans must include override values, not only row identity.
- Artifact path copying should rely on explicit workspace metadata and `source_path` fallback, not the process cwd.

These are worth keeping in this research note and in their SDD tales. They should become long memory only if future work
continues to hit the same UI surfaces.

### 8. Older SDD Corpus Adds Adjacent Candidates

The older in-repo SDD corpus confirms several durable lessons outside the current generated episode set. These are
strong findings, but they come from broader project records rather than the 83 generated episodes, so they should not
displace the primary recommendations above:

- Workspace and sibling repository contracts: numbered workspace plus resolved sibling map/env are the contract; do not
  infer sibling paths from local checkout layout, and do not use `workspace.strategy: none` for ordinary code siblings
  unless shared-checkout edits are acceptable.
- Long-memory governance and context budgeting: memory files should be proposed/reviewed, not hand-edited; always-loaded
  context is a scarce token budget; broad rules belong in Tier 3 unless they must be always loaded.
- Dynamic memory authoring: keyword-gated Tier 2 memory needs narrow multi-word triggers and collision checks; a
  `long-` dynamic memory file already mirrors its Tier 3 source, so agents should not read the canonical long file too.
- Test isolation: tests touching `~/.sase`, VCS providers, subprocesses, or hooks must redirect every home-path API and
  give mocks explicit return values; bare `MagicMock()` truthiness has caused real workflow side effects.
- XPrompt workflow authoring: workflows are configuration code; long inline Python belongs in modules, shared step logic
  should not be copy-pasted, and standalone agent workflows differ from embedded prompt wrappers.
- Rust core boundary specifics: `sase_core_rs` is a hard dependency for ported operations, Python owns host orchestration
  and mutating I/O, and not every "core" operation belongs in Rust when PyO3 boundary costs dominate.

The first four adjacent lessons are plausible future long-memory candidates. The XPrompt and Rust findings are useful,
but Rust is partly covered by existing short memory and XPrompt guidance needs a separate focused review before
promotion.

## Do Not Promote

Do not promote raw episode IDs, current counts, or drift totals. They are evidence for this review, but they will age.

Do not promote repeated scheduled-chop no-op episodes as separate memories. Their value is the automation pattern, not
the individual no-op outcomes.

Do not promote unrelated low-signal prompt fragments or non-SASE Obsidian styling work.

Do not promote the Athena-specific `memory_episodes` chop deployment as a project-wide rule. Keep the reusable AXE
configuration model, not machine-specific config.

Do not add separate long memories for notification tabs, agent status override reconciliation, artifact relative-path
copying, or individual episode visualization bugs yet. They are real lessons, but their current evidence is narrower and
already preserved in the relevant tales and code history.

## Recommendation

Add two long-term memories first:

1. `memory/long/memory_episodes_system.md`

   Capture the episode trust boundary and operational gotchas: episodes are private source-linked evidence, not active
   instructions; reusable rules go through `sase memory write`/`review`; `sdd/events/` can be reviewed repo-safe history;
   export is read-only; project-scan date filters select seeds; explicit selectors are preferred; build progress goes to
   stderr while JSON stays clean; warnings and drift are review signals; source drift requires rereading evidence; and
   v2 components should be strong-lineage-first with weak refs/evidence kept out of default component identity and graph
   noise.

2. `memory/long/axe_chops_and_swarms.md`

   Capture scheduled automation and research orchestration: lumberjack `interval`, `chop_timeout`, and per-chop
   `run_every`; script-chop name resolution; dict-merge/list-replace config behavior; marker-based lazy audits that
   update markers only after successful launch; narrow-scope audit prompts; and the research-swarm fan-out -> wait ->
   consolidate -> cleanup -> optional image pattern.

After approval, create both with `sase memory write`, review them with `sase memory review`, and add them to the
`AGENTS.md` Tier 3 index.

Optional short-memory additions:

- Add a one-line `memory/short/gotchas.md` reminder to keep display formatting separate from stored data and CLI
  contracts.
- Add a one-line `memory/short/gotchas.md` reminder to test Rich/Textual markup safety for footer and hint strings that
  contain bracket characters.

Consider separate long-memory proposals from the older SDD cross-check only if the user wants a broader project-memory
audit beyond generated episodes:

- `memory/long/workspace_sibling_contracts.md`
- `memory/long/prompt_context_budget.md`
- `memory/long/dynamic_memory_authoring.md`
- `memory/long/test_isolation_contracts.md`

Those are strong candidates, but they should not be bundled into the episode review landing change because their evidence
base is broader than the current episode store.
