---
plan: sdd/tales/202606/sharded_prompt_history.md
---
 Every time we load the prompt history from the prompt history widget and every time that we launch an agent, we have to deal with this very large prompt history file. I think we did some related research (regarding some performance issue maybe) recently that is stored in a research markdown file in this repo that you should check out.

One constraint is that I don't want to lose any user prompt, regardless of how old it is, ever. With that said we don't need to load older prompts when the user invokes the prompt history (make sure the user is aware of how many prompts are loaded and has a keymap available to them to load more). Also we should shard the prompt history JSON files by date so when we launch agents and those agent prompts get written to the prompt history, it doesn't cause us to have to write to such a large file.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Shard granularity

> How should the prompt-history JSON be sharded by date? (Current store: ~9,000 prompts / 33MB in one file. Writes touch the *current* shard, so smaller shards = faster agent-launch writes.)

- [x] **Monthly (YYMM.json)** — ~12 files/yr, current shard ~MB-scale. Fewer files; load-more steps by month. Good balance.
- [ ] **Daily (YYMMDD.json)** — One file per active day; today shard tiny (sub-ms writes). Most files; closest to literal by-date. Best write perf.
- [ ] **Yearly (YY.json)** — Very few files but current shard stays large; weakest write-perf win.

#### Q2: Impl location

> Where should the sharded storage live? Prompt history is currently 100% Python (like all sibling history files), and prior research recommended deferring a Rust/SQLite move. But the rust_core_backend_boundary memory says shared backend behavior belongs in sase-core.

- [x] **Python (this repo)** — Keep storage in src/sase/history/ as today. Matches existing all-Python history code + prior research; smallest scope.
- [ ] **Rust core (sase-core)** — Move sharded read/write into sase_core with a binding. Honors the boundary memory literally; much larger scope.

#### Q3: Lazy-load UX

> What should the prompt-history modal load initially, and what should the load-more keymap do?

- [ ] **Most-recent shard, key loads next older shard** — Open shows newest date-shard only; a keymap pulls in one older shard at a time. Count shown as prompts + shards loaded/total.
- [ ] **Up to ~N recent prompts, key loads all remaining** — Open loads recent shards until ~N (e.g. 200) prompts; one keymap loads everything older.
- [x] **Other:** "Up to the last 250 prompts. The keymap should load another 250 prompts each to the prompt history panel each time it is invoked."

%xprompts_enabled:true