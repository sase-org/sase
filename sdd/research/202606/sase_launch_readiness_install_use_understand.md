# SASE Launch Readiness: Install, Use, and Understand Friction

Date: 2026-06-07

## Question

I am getting ready to post a blog post about SASE to gain traction. Which parts of the project most need work so that a
stranger arriving from the post can **install**, **use**, and **understand** SASE without bouncing?

## Scope and Relationship to Prior Research

This is the **product-readiness** companion to the existing **launch-strategy** notes. Those cover *how* to distribute
the post and sequence channels; this note covers *what about the product itself* will make or break the first 30
minutes of a stranger's experience. Read the strategy notes first; do not duplicate them:

- [`making_sase_popular_hn_launch_research.md`](./making_sase_popular_hn_launch_research.md) — HN mechanics, positioning,
  growth loops.
- [`sase_blog_launch_strategy_consolidated.md`](./sase_blog_launch_strategy_consolidated.md) — channel sequencing,
  preflight, cross-post mechanics. Note it already recommends "make the quickstart impossible to miss" — this note shows
  the quickstart is currently *not* reachable from the published site (Finding U-1).
- [`../202605/public_release_process_and_install_research.md`](../202605/public_release_process_and_install_research.md)
  — the 2026-05-07 release/install deep dive. Several of its blockers are **re-confirmed as still live below**; some of
  its UX claims are now **stale** and corrected here.
- [`../202605/sase_init_onboarding.md`](../202605/sase_init_onboarding.md) — prior onboarding spec.

**What is new here:** a same-day (2026-06-07) re-verification of the single biggest launch blocker against live PyPI,
plus a consolidated, severity-ranked punch-list across install/use/understand with file:line evidence, and explicit
corrections to assumptions that no longer hold.

## How These Findings Were Produced

Three parallel read-only investigations (install, first-use, understandability) over the repo, then **direct
verification** of the highest-stakes and most surprising claims against live state. Claims are tagged:

- **[VERIFIED]** — I confirmed it directly this session (live PyPI query, grep of source, config inspection).
- **[READ]** — surfaced by a sub-agent reading docs/source; high-confidence but not independently re-run.
- **[CORRECTED]** — a prior-research or sub-agent claim that is now wrong; the corrected fact is given.

---

## TL;DR — The One Thing That Must Be Fixed Before Launch

**[VERIFIED] `pip install sase` / `uv tool install sase` fail right now.** As of 2026-06-07:

| Package | PyPI status |
| --- | --- |
| `sase` | HTTP **200**, latest = **0.1.0** (only release) |
| `sase-core-rs` | HTTP **404** (also `sase_core_rs` → 404) |

`sase` 0.1.0 hard-depends on `sase-core-rs>=0.1.1,<0.2.0` (`pyproject.toml:22`), and there is **no pure-Python fallback**
for the Rust core (`README.md:231`, `docs/development.md`). So any stranger who copy-pastes a PyPI install line from the
blog post hits an unresolvable dependency on the first command. The README already advertises the happy path —
"Normal installs pull a prebuilt wheel" (`README.md:230`) — but that path is **currently aspirational**, because the
wheel's package does not exist on the index.

This single fact gates everything else. If the post ships before it is fixed, the install funnel is ~0% for anyone not
cloning the repo. The 2026-05 release research flagged this; it is **still true today**.

**Minimum fix:** publish `sase-core-rs` wheels to PyPI, bump `sase` to `0.2.0` (PyPI forbids re-uploading `0.1.0`), and
smoke-test `pip install sase` in a clean venv on Linux + macOS. Until that is green, the blog CTA should say
`git clone … && just install`, not `pip install sase`.

---

## INSTALL — friction ranked

### I-1 [VERIFIED] PyPI install is broken (see TL;DR). Severity: **blocker**.
- Evidence: live PyPI 404 for `sase-core-rs`; `pyproject.toml:22`; `README.md:230-231`.
- Fix: publish core wheels, bump `sase` to 0.2.0, test the real install path. This is P0.

### I-2 [READ] Mandatory Rust core with no fallback narrows platform reach. Severity: **high**.
- The Rust extension is required; `sase core health` is the canonical check (`README.md:115-116, 226-231`).
- Prebuilt wheels target Linux x86_64/aarch64, macOS universal2, Windows x86_64 (`docs/rust_backend.md`). **musllinux is
  not built** → Alpine/distroless/container users fall through to sdist and need a Rust toolchain (re-confirms the
  2026-05 finding). Many curious devs try new tools inside containers; this will bite a visible slice of them.
- Fix (post-P0): add a `musllinux_1_2 x86_64` wheel to the `sase-core` release matrix.

### I-3 [READ] Source install needs a heavier toolchain than the README implies. Severity: **medium**.
- The documented path is `uv venv … && just install` (`README.md:64-70`), which pulls `uv`, `just`, and — when a sibling
  `../sase-core` checkout is present and `cargo` is on PATH — auto-builds the Rust extension (`Justfile` `_setup`
  recipe, ~lines 28-35, 78-83). A stranger cloning only `sase` (no `sase-core` sibling) relies entirely on the PyPI
  wheel for `sase-core-rs` — which 404s (I-1). So **both** the PyPI path and the naive single-clone source path are
  currently dead; only "clone both repos + have cargo" works end to end.
- Fix: document the two-repo source build explicitly, OR get the wheel published so the single-clone path works.

### I-4 [READ] No bundled agent CLI; first `sase run` fails silently-ish without one. Severity: **medium**.
- SASE orchestrates external agent CLIs (Claude Code/Codex/Gemini/Qwen/OpenCode); none ship with it. With no provider on
  PATH, `sase run "<prompt>"` errors at launch. A stranger who installs successfully but hasn't set up an agent CLI
  hits a wall that isn't obviously their config's fault.
- Fix: have `sase core health` (or a new `sase doctor`) report provider detection explicitly — "0 agent CLIs found;
  install one of …".

### I-5 [CORRECTED] `sase --version` — partial. Severity: **low**.
- Prior research said there is no standardized version output. **Correction with nuance:** there *is* a `--version`, but
  only on the **`lsp`** subcommand (`src/sase/main/parser_commands.py:287`, the xprompt LSP server). There is **no
  top-level `sase --version`**; the README steers users to `sase core health` for version info (`README.md:75`). A
  plain `sase --version` is table-stakes for a launch and is a tiny add.
- Fix: add a top-level `--version` that prints `sase`, `sase-core-rs`, Python, and platform on one line.

---

## USE — first-run friction ranked

### U-1 [VERIFIED] The 15-minute quickstart exists but is unreachable from the published site. Severity: **high**.
- `docs/blog/posts/hello-sase-your-first-15-minutes.md` exists and is good. But `mkdocs.yml` nav publishes **only one**
  blog post — `[00] Why Coding Agents Need Orchestration` — and the blog index "Start Here" points at that same essay,
  not the quickstart (`docs/blog/index.md`). So a stranger who lands on sase.sh has **no in-site path** to the
  hands-on quickstart; it's effectively a draft.
- This directly contradicts the launch-strategy note's own advice to keep the quickstart "one click away." It is the
  highest-leverage doc fix: the content is already written, it's just not wired into nav.
- Fix: add the quickstart to `mkdocs.yml` nav and link it from `index.md` + the blog "Start Here". P0-for-docs.

### U-2 [READ] `sase init` drops a fresh user into a multi-step, under-explained flow. Severity: **high**.
- `sase init` reports drift and (interactively) offers to run `memory`, `sdd`, `skills` initializers in sequence
  (`docs/init.md`; `src/sase/main/init_onboarding.py`). The sub-prompts don't explain *what each does* or *why it
  matters*, and in a non-TTY context it just prints and exits. There are ~13 init subcommands total — a new user can't
  tell which matter or in what order.
- Fix: a single summarized prompt ("Set up memory / SDD / skills? Here's what each does …") and a one-line "you're
  ready, now run `sase run \"…\"`" success message.

### U-3 [READ] First `sase ace` launch is a cold, empty multi-tab TUI. Severity: **high**.
- On a fresh project the CLs/Agents/Axe tabs are empty with no first-run banner or "press X to launch your first agent"
  hint. A stranger reasonably concludes it's broken.
- Fix: empty-state banner on the CLs/Agents tabs pointing at the first action and the `?` help key.

### U-4 [CORRECTED] ACE *does* have an in-app help overlay. Severity: **n/a (assumption corrected)**.
- A sub-agent claimed "no in-app help overlay / no `?` key." **This is wrong.** `?` (`question_mark`) is bound to
  `show_help` (`src/sase/default_config.yml:126`; `src/sase/ace/tui/bindings.py:100`) and opens a real, per-tab
  `HelpModal` (`src/sase/ace/tui/modals/help_modal/modal.py`, with `agents_bindings.py` / `changespecs_bindings.py` /
  `axe_bindings.py`). The gap is **discoverability** of `?` on first launch, not the absence of help. This is why U-3's
  fix (advertise `?` in the empty state) is the right lever, not "build a help system."

### U-5 [READ] Zero-to-first-result requires absorbing several concepts. Severity: **medium**.
- To get a satisfying first run a user brushes against workspace, ChangeSpec, provider, and (if they read further)
  xprompt/bead/mentor. The quickstart handles this *if they find it* (blocked by U-1). The concept load itself is real
  but mitigated by a good quickstart + a concept map (see UN-3).
- Fix: dependent on U-1; add a "you only need these 3 ideas to start" framing at the top of the quickstart.

### U-6 [READ] Config surface is large with no "minimal starter". Severity: **medium**.
- `default_config.yml` is 100+ lines and `docs/configuration.md` is ~128k. There's no curated 10-line starter config or
  "what must I set vs. what's optional" table. Defaults mostly work, but the docs don't *say* "you can ignore all of
  this to start."
- Fix: a short "Minimal config" section asserting sane zero-config defaults, plus a 10-line annotated example.

---

## UNDERSTAND — comprehension friction ranked

### UN-1 [READ] Jargon density is the top comprehension barrier. Severity: **high**.
- A stranger must absorb a large invented vocabulary fast: ACE, AXE, AMD, SDD, xprompt, ChangeSpec, bead/phase/tier,
  mentor, episode, chop, dream, plus the SDD fantasy tiers (tale/epic/legend/myth), agent family, workspace numbering.
  Several collide with existing meanings or each other:
  - **ACE vs AXE** — near-homographs introduced back-to-back (`README.md:41-42`); easy to conflate.
  - **bead** — used for both the tracker and an individual item; **mentor / dream / chop** — non-obvious coinages;
    **long-term memory** — overloaded vs. its ML/psych meaning (here it means "referenced, not auto-loaded").
  - `memory/short/glossary.md` exists but is partial (missing tale/epic/legend/myth, dream, chop, episode, mentor, AMD,
    AXE) and isn't published as a docs page.
- Fix: publish a complete `docs/glossary.md`, link it from README/index/every major doc, and expand each term to one
  plain-English line. Highest-ROI understandability fix.

### UN-2 [READ] Docs are deep references with a steep on-ramp. Severity: **high**.
- The "Basics" nav section opens onto very large reference pages (`ace.md` ~130k, `xprompt.md` ~80k, `configuration.md`
  ~128k, `llms.md` ~66k) that start in command/keybinding detail before any 2-minute "what is this / why" intro.
- Fix: prepend a short "Quick overview" (what problem / mental model / minimal example / link to depth) to ace, axe,
  beads, xprompt, memory. Content can be lifted from existing intros; this is mostly reorganization.

### UN-3 [READ] No big-picture concept map; the architecture doc is buried. Severity: **medium-high**.
- `docs/architecture.md` is strong but sits under "Beyond the Basics," so readers meet the TUI/command detail before the
  system overview. There is no single picture of how agents → workspaces → ChangeSpecs → SDD/beads → ACE/AXE → memory
  fit together.
- Fix: add a one-screen concept map (the `sase_overview.png` asset already exists — surface it on index + architecture)
  and move/echo a condensed architecture overview into the Basics on-ramp.

### UN-4 [READ] Pitch is abstract; differentiation vs. peers is implicit. Severity: **medium**.
- README/index lead with "durable operating layer," "tracked handoffs," "reviewable changes" — true but abstract, and
  every agent tool claims "reviewable changes." There's no crisp one-liner on how SASE differs from Claude Code / Cursor
  / aider / OpenHands, even though internal positioning research exists
  (`../202605/openhands_vs_sase.md`, `../202605/manus_vs_sase_lessons.md`). Note the strategy notes argue SASE's
  orchestration framing is well-aligned to the HN audience — the raw material for a sharp pitch is there, it's just not
  on the landing page.
- Fix: one concrete "imagine you launched 3 agents and lost track of whose change was whose" scenario + a 1-row
  comparison framing. Keep it on index.md above the fold.

### UN-5 [READ] Personal-setup coupling makes it read like a single-user tool. Severity: **medium**.
- chezmoi appears in the core operational model (`README.md:142`) and throughout `docs/init.md`; Telegram/mobile and a
  personal "Bob vault" reference (`docs/development.md`) read as the author's own rig rather than a general tool.
- Fix: frame chezmoi/Telegram/mobile/Bob as **optional integrations** behind a clear "optional" label; keep the core
  path provider- and dotfile-manager-agnostic in the first docs a stranger reads.

---

## Prioritized Punch-List (mapped to the launch)

**P0 — do before the post goes live (install funnel is ~0% otherwise):**
1. Publish `sase-core-rs` wheels to PyPI; bump `sase` → `0.2.0`; **smoke-test `pip install sase` in a clean venv**
   (Linux + macOS). [I-1]
2. Wire `hello-sase-your-first-15-minutes.md` into `mkdocs.yml` nav and link it from `index.md` + blog "Start Here".
   [U-1]
3. Decide the blog CTA: only say `pip install sase` if #1 is green; otherwise ship `git clone … && just install` with
   the two-repo note. [I-1/I-3]

**P1 — within launch week (reduces bounce for those who get in):**
4. Add top-level `sase --version`. [I-5]
5. `sase core health` / `sase doctor`: report agent-CLI detection ("0 found; install one of …") and a green/red
   first-run checklist. [I-4, U-2]
6. ACE empty-state banner advertising the first action and the `?` help key. [U-3/U-4]
7. Publish a complete `docs/glossary.md`, linked everywhere. [UN-1]
8. Surface `sase_overview.png` + a condensed architecture overview on the Basics on-ramp. [UN-3]

**P2 — fast follow:**
9. `musllinux` wheels for container users. [I-2]
10. "Quick overview" headers on the big reference docs. [UN-2]
11. Minimal-config starter section. [U-6]
12. Sharpen the index pitch + 1-row differentiation. [UN-4]
13. Label chezmoi/Telegram/mobile/Bob as optional. [UN-5]

## Quick Wins (cheap, high signal)
- `sase --version` (small), ACE empty-state banner (small), nav-wire the quickstart (tiny), publish the glossary
  (content largely exists), surface the existing overview image. None require architecture changes; most are docs or
  thin CLI/TUI glue.

## Corrections to Carry Forward (so we don't relitigate)
- ACE **has** a `?` help modal (per-tab). The issue is advertising it, not building it. [U-4]
- `--version` **exists but only on `sase lsp`**; no top-level flag yet. [I-5]
- The 15-minute quickstart **exists** as content but is **not in published nav**. [U-1]
- The 2026-05 PyPI blocker is **not stale** — re-verified live on 2026-06-07. [I-1]

## Open Questions / To Verify Before Acting
- Are `sase-core-rs` wheels actually built-and-green in CI, just unpublished? (If yes, P0#1 is a publish step, not a
  build project.) Check the `sase-core` release workflow.
- Does `sase core health` already enumerate detected providers, or only the Rust core? (Determines how much of P1#5 is
  new.)
- Is the macOS wheel install path tested anywhere, or only Linux? (Determines smoke-test matrix for P0#1.)
