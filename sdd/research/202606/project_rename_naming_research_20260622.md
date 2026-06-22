# Project Rename — Naming Research

Date: 2026-06-22

## Question

`sase` (pronounced "sassy") is being considered for a rename. What should it be renamed to? This document
researches *why* a rename is justified, what a rename actually costs, the criteria a good name must meet, a wide
candidate sweep with live availability checks, and ends with **five concrete recommendations**.

## TL;DR (Bottom Line)

- **The strongest reason to rename is a hard namespace collision.** "SASE" is already a multi-billion-dollar
  cybersecurity category — **Secure Access Service Edge** (coined by Gartner in 2019) — and it is *also* pronounced
  "sassy." The project shares both the spelling and the pronunciation of an established enterprise term. For a
  developer tool that wants to be searchable and ownable, this is close to a worst-case collision.
- **A coined/short real word beats a literal acronym** for a CLI you type dozens of times a day. Best practice for CLI
  tools is "short, memorable, and consistent," and "thoughtful meaninglessness" (a coined or loosely-evocative word) is
  explicitly fine.
- **The agent-orchestration namespace is crowded and moving fast.** Several otherwise-great names are *already* taken by
  directly adjacent tools — `weft` ("durable task substrate for agent systems"), `regatta` ("tmux-backed mission
  control for parallel AI coding agents"), `tutti` ("multi-agent orchestration CLI"), `marl` (multi-agent RL). These
  must be avoided.
- **My five recommendations, in order:** **Corral**, **Bosun**, **Coxswain** (command `cox`), **Gantry**, **Muster**.
  See the final section for full rationale, availability tier, and caveats for each.

## Why rename at all

### 1. The fatal collision: SASE = Secure Access Service Edge

"SASE" was defined by Gartner in 2019 ("The Future of Network Security is in the Cloud") and is now a saturated
enterprise-security category marketed by Cisco, Palo Alto, Zscaler, Cloudflare, Netskope, IBM, and others. It bundles
SD-WAN, SWG, CASB, FWaaS, and ZTNA. Crucially, **the industry pronounces it "sassy" — identical to this project.**

Consequences for a developer tool sharing the exact spelling *and* pronunciation:

- **Search is unwinnable.** "sase", "sase docs", "what is sase", "sase tutorial" all return networking/security
  results. A new dev tool cannot out-rank a Gartner category backed by the biggest security vendors.
- **Verbal ambiguity.** Saying "I use sassy" to another engineer evokes the security category, not a coding-agent
  orchestrator.
- **No category ownership.** A good tool name lets you *define* a category; this one inherits someone else's.

### 2. Secondary issues with the current name

- **Acronym rigidity.** "Structured Agentic Software Engineering" is a fine *descriptor*, but binding the brand to a
  4-word backronym makes positioning brittle. The product is broader than any one expansion (workspaces, ChangeSpecs,
  XPrompt, ACE/AXE, beads, memory, commit flow, a Rust core, plugins).
- **Spelling vs. pronunciation gap.** "sase" → "sassy" is not obvious to a newcomer reading it cold.
- **Sub-brand sprawl already exists.** ACE, AXE, XPrompt, Beads, SDD are strong internal names; the umbrella name is the
  weak link, and it is the one prefixing every repo (`sase-core`, `sase-github`, `sase-telegram`, `sase-nvim`) and
  every command.

### What renaming does *not* fix

The internal sub-brands (ACE, AXE, XPrompt) are good and should be kept. Note also the **Beads** name already collides
with `gastownhall/beads` (a popular issue-graph tool) — that is a separate, pre-existing decision and out of scope here.

## What a rename actually touches (cost picture)

This informs the criteria (favor a short command + a backward-compatible alias window). A rename ripples through:

| Surface | Current | Notes |
| --- | --- | --- |
| CLI command | `sase ...` | Highest-friction change; typed constantly. Ship a `sase` → `<new>` alias for a deprecation window. |
| PyPI package | `sase` | New project; redirect/yank-with-notice strategy. |
| Docs domain | `sase.sh` | New domain; keep redirect. |
| GitHub org + repos | `sase-org`, `sase-core`, `sase-github`, `sase-telegram`, `sase-nvim` | Org rename + repo renames (GitHub keeps redirects). |
| Rust binding/crate | `sase_core_rs`, `sase_core` | crates.io name must be checked/claimed. |
| Config + state paths | `~/.sase/`, `~/.config/sase/sase.yml`, `~/.sase/projects/<project>/`, `.gp`/`.sase` files | Migration shim that reads old paths. |
| Methodology label | "Structured Agentic Software Engineering" / SDD | Can be **kept** as the descriptor under a new brand (see strategy). |

**Strategic fork to decide first:** rename the *brand only* (keep "structured agentic software engineering" as the
lowercase category descriptor under a new product name) **or** rebrand the methodology too. All five recommendations
below work either way — they sit cleanly on top of an unchanged "structured agentic software engineering" descriptor,
so you are not forced to throw away the positioning language.

## Naming criteria (for this project specifically)

1. **Short & typeable** — it is a CLI typed many times daily. Target 1–2 syllables, ≤ ~6 characters for the command.
2. **Unambiguous spelling & pronunciation** — read-it-once-and-type-it. (This is where `sase`/"sassy" and, below,
   `coxswain` are weakest.)
3. **No major existing-term collision** — the whole point. Avoid loaded acronyms and saturated brands.
4. **No adjacent dev/AI-tool collision** — the agent-orchestration space is crowded; verified live (see Avoid list).
5. **Namespace availability** — PyPI, crates.io, npm, a usable GitHub org, and a buyable domain (`.sh`/`.dev`/`.io`).
6. **Prefix-friendly** — must read well as `<name>-core`, `<name>-github`, `<name>-nvim`.
7. **Meaning that fits the product** — "orchestrate a crew of agents into tracked, repeatable workflows / a durable
   operating layer." Metaphor families that fit: **conducting an ensemble**, **steering/running a ship's crew**,
   **wrangling a herd/fleet**, **the supporting structure that holds & positions work**.
8. **Personality** — `sase`/"sassy" had charm. Don't trade all the way down to a sterile infra word unless desired.

## Candidate sweep (with live availability)

PyPI checked via the JSON API on 2026-06-22 (404 = AVAILABLE). GitHub bare-handle checked via profile fetch — note the
project already uses an *org* (`sase-org`), so a taken bare handle is not disqualifying (use `<name>hq`, `use<name>`, or
`<name>-dev`). crates.io / npm / domains / trademark still need a final pass for the chosen name.

### AVOID — taken by directly adjacent AI/agent tools

| Name | Collision |
| --- | --- |
| `weft` | PyPI: "The durable task substrate for agent systems." Direct adjacency. |
| `regatta` | PyPI: "tmux-backed mission control for parallel AI coding agents" (v0.1.0, Jun 2026). Direct competitor. |
| `tutti` | "A multi-agent orchestration CLI with config-driven workflows, git worktree isolation, typed artifact flow." Direct competitor. |
| `marl` | PyPI: "Multi-Agent Reinforcement Learning." Confusing adjacency. |
| `skein` | PyPI: Apache YARN deploy tool (also a famous hash function). Taken + noisy. |
| Conductor, Kiro, Tessl, Archon, Optio, Gas Town, Beads | Existing named products in/around this exact space. |

### Family A — Steering / running a ship's crew (orchestration + control)

| Name | PyPI | Fit | Notes |
| --- | --- | --- | --- |
| **Coxswain** (`cox`) | **AVAILABLE** | ★★★★★ steers the boat *and* directs the rowing crew | Best meaning. Spelling is the catch → lean on `cox` as the binary. |
| **Bosun** (boatswain) | Dormant squat (v1.0.3, 2014, "UNKNOWN") | ★★★★ directs the working crew, runs day-to-day ops = "operating layer" | Short, punchy, easy. Acquire via PEP 541 or use `bosun-cli` pkg. |
| Purser | **AVAILABLE** | ★★★ keeps the ship's books/records = durable state, "tracked" | Clean but sleepy as a brand. |
| Helmsman | Tiny pkg (Helm test fw, 2022) | ★★★ steers | "Helm" itself is owned by Kubernetes; long word. |
| Tiller | Trivial squat | ★★ steering lever | "Tiller" was Helm v2's server — bad association. |
| Quartermaster | Trivial squat (2017) | ★★ provisions the crew | Long. |

### Family B — Wrangling a herd / fleet (isolation + many agents)

| Name | PyPI | Fit | Notes |
| --- | --- | --- | --- |
| **Corral** | **AVAILABLE** | ★★★★★ round up & pen a herd of agents into isolated workspaces under your control | Friendly, keeps "sassy"-style charm; great CLI verb (`corral run`). Watch corral/coral spelling. |
| **Muster** | Trivial squat (v0.0.1, 2017) | ★★★★ assemble/call together a force | Excellent imperative ("muster the agents"); easy spelling. |
| Drover | Taken (Lambda deploy tool) | ★★★ drives a herd to market | Adjacent-ish (deploy) noise. |
| Rookery | **AVAILABLE** | ★★ a managed colony | A bit obscure; "rook" = chess noise. |
| Flotilla | Dormant (single-cell bio, 2016) | ★★★ a small fleet | Long; mild squat. |

### Family C — Conducting an ensemble (orchestration)

| Name | PyPI | Fit | Notes |
| --- | --- | --- | --- |
| Rostrum | **AVAILABLE** | ★★★ the conductor's/speaker's platform; "roster" connotation | Clean; slightly formal/obscure. |
| Baton / Tutti / Maestro / Score | Taken (and `tutti` is a competitor) | — | Avoid. |

### Family D — Supporting structure that holds & positions work (ties to "Structured")

| Name | PyPI | Fit | Notes |
| --- | --- | --- | --- |
| **Gantry** | Dormant ML-ops lib (last 2023) | ★★★★ the frame that positions & services the work (rocket/crane/CI gantry) = "operating layer / control plane" | Serious infra tone; ties to "Structured." Mild squat. |
| Trellis | Taken (old event lib) + Roots "Trellis" | ★★★ structure growth climbs on | Crowded. |
| Lattice / Keystone | Taken (Lattice data fw; OpenStack Keystone) | — | Avoid. |

## Shortlist evaluation

Weighing meaning, spelling/typeability, availability, prefix-fit, and personality, five rise to the top. Two are
**cleanly available on PyPI today** (Corral, Coxswain); three carry only a **dormant/trivial** PyPI squat that is either
acquirable (PEP 541) or sidesteppable with a `-cli`/distinct package name while keeping the command short (Bosun,
Gantry, Muster). None collide with a known AI/agent tool (verified via search).

---

## Five recommendations

> Ranked. Each shows pronunciation, why it fits, availability tier, the CLI feel, the repo-family prefix, and caveats.
> All five layer cleanly on top of an unchanged "structured agentic software engineering" descriptor, so the
> methodology language can survive the brand change.

### 1. Corral  ⭐ top pick
- **Say:** kuh-RAL.
- **Why it fits:** You *corral* a herd — round it up, pen it into separate enclosures, and keep it under control. That
  is exactly the product: many agents, isolated workspaces, brought into tracked, repeatable order. It keeps the
  friendly, slightly-cheeky personality that "sassy" had, without any of the baggage.
- **Availability:** **PyPI clean** (404). No AI/agent-tool collision found. GitHub bare handle `corral` is an active
  user → use an org (`corralhq`, `usecorral`, `corral-dev`).
- **CLI feel:** `corral run "..."`, `corral ace`, `corral doctor` — reads naturally; "corral your agents" is a tagline
  on its own.
- **Family:** `corral-core`, `corral-github`, `corral-nvim` all read well.
- **Caveats:** corral/coral homophone-ish spelling; confirm domain (`corral.sh`/`.dev`) and crates.io/npm.

### 2. Bosun
- **Say:** BOH-sun (phonetic spelling of "boatswain").
- **Why it fits:** The bosun is the officer who **directs the working crew and runs the ship's day-to-day operations** —
  a near-perfect gloss for a "durable operating layer" that coordinates a crew of agents. Short, punchy, memorable,
  unambiguous to say and spell.
- **Availability:** PyPI taken only by a **dormant 2014 squat** (v1.0.3, summary "UNKNOWN") — a strong PEP 541
  name-reclaim candidate; fallback package `bosun` org / `bosun-cli` while keeping the command `bosun`. No AI-tool
  collision found. (Note: Stack Exchange has an internal monitoring tool historically called "bosun" — low overlap, but
  verify trademark.)
- **CLI feel:** `bosun run`, `bosun ace` — crisp.
- **Family:** `bosun-core`, `bosun-github`, `bosun-nvim`.
- **Caveats:** reclaim/secure the PyPI name; check the legacy Stack Exchange "bosun" for any trademark concern.

### 3. Coxswain  (command: `cox`)
- **Say:** KOK-sun.
- **Why it fits:** The **most semantically precise** option — the coxswain steers the boat *and* directs the rhythm and
  effort of the entire crew. That is orchestration + control in one word. Clean namespace.
- **Availability:** **PyPI clean** (404). GitHub bare handle exists but is inactive (0 repos) → use an org. No AI-tool
  collision.
- **CLI feel:** the full word is hard to spell, so **ship the binary as `cox`** (`cox run`, `cox ace`) and keep
  "Coxswain" as the proper brand. `cox` is short and fast; minor brand-noise (Cox Communications) but fine for a CLI.
- **Family:** `coxswain-core` (or `cox-core`), etc.
- **Caveats:** spelling friction is the whole reason for the `cox` alias; decide brand-vs-binary split deliberately.

### 4. Gantry
- **Say:** GAN-tree.
- **Why it fits:** A gantry is the **supporting frame that positions, holds, and services work** — rocket gantry, crane
  gantry, CI gantry. It maps directly to "operating layer / control plane" and nods to the "**Structured**" in the
  current name. The most *serious-infrastructure* of the five.
- **Availability:** PyPI taken by a **dormant ML-ops library** (last release 2023) — mild squat; either coexist with a
  distinct package name or pursue reclaim. No AI-coding-agent tool collision found. (There is/was a "Gantry" ML
  observability startup and a "Gantry 5" web template framework — verify trademark before committing.)
- **CLI feel:** `gantry run`, `gantry ace` — clean, professional.
- **Family:** `gantry-core`, `gantry-github`, `gantry-nvim`.
- **Caveats:** more crowded than the others (ML startup + web framework); strongest pick if you want enterprise/infra
  tone over personality.

### 5. Muster
- **Say:** MUH-ster.
- **Why it fits:** To **muster** is to assemble and bring a force into order — "muster the agents," "muster a run." A
  great imperative verb, trivially easy to spell and say, with the same call-to-action energy as a CLI should have.
- **Availability:** PyPI taken only by a **trivial 2017 squat** (v0.0.1) — strong reclaim candidate; fallback
  `muster-cli`. No AI-tool collision found.
- **CLI feel:** `muster run`, `muster ace` — the verb *is* the action.
- **Family:** `muster-core`, `muster-github`, `muster-nvim`.
- **Caveats:** secure the PyPI name; "muster" has common-English ubiquity (mild SEO dilution, but nothing like the SASE
  collision).

### Honorable mentions (clean PyPI, didn't make the five)
**Purser** (records/state keeper — clean but sleepy), **Rostrum** (conductor's platform — clean but formal),
**Rookery** (agent colony — clean but obscure).

### Alternative strategy: coin a word
Every short *real* word is contested somewhere. If a guaranteed-clean namespace matters more than built-in meaning,
coin a brandable token in the spirit of `sase`/`uv`/`ruff`/`bun` (short, soft, ownable). This trades instant meaning for
total namespace control and effortless trademarking. Worth a dedicated brainstorm if none of the five clear the final
checks below.

## Final verification checklist (run for the chosen name before committing)

- [ ] PyPI (confirmed clean today for Corral, Coxswain; reclaim/alias plan for Bosun, Gantry, Muster)
- [ ] crates.io (for `<name>-core` Rust crate / `<name>_core_rs` binding) — **not yet checked**
- [ ] npm (repo uses `package.json`/wrangler) — **not yet checked**
- [ ] GitHub org handle (`<name>hq` / `use<name>` / `<name>-dev` fallbacks) — **not yet checked**
- [ ] Domain: `<name>.sh` / `.dev` / `.io` — **not yet checked**
- [ ] Trademark / existing-product sweep (esp. Gantry, Bosun)
- [ ] Decide: brand-only rename vs. methodology rebrand
- [ ] Plan `sase` → `<new>` command alias + config-path migration shim + doc redirects

## Sources

Project (local):
- `README.md`, `pyproject.toml`, `AGENTS.md`, `memory/sase.md`, `memory/glossary.md`
- `sdd/research/202606/open_source_sase_competitors_consolidated.md` (adjacent-tool landscape)

External (fetched 2026-06-22):
- SASE = Secure Access Service Edge, "sassy": [Zscaler](https://www.zscaler.com/resources/security-terms-glossary/what-is-sase),
  [IBM](https://www.ibm.com/think/topics/sase),
  [TechTarget](https://www.techtarget.com/searchnetworking/definition/Secure-Access-Service-Edge-SASE),
  [Netskope](https://www.netskope.com/security-defined/what-is-sase),
  [Cisco Umbrella](https://umbrella.cisco.com/secure-access-service-edge-sase/what-is-sase)
- CLI naming best practice: [The Poetics of CLI Command Names](https://smallstep.com/blog/the-poetics-of-cli-command-names/),
  [Simon Willison — building CLI tools](https://simonwillison.net/2023/Sep/30/cli-tools-python/),
  [namecheck (PyPI name availability)](https://github.com/pixelprotest/namecheck)
- Adjacent-tool collisions: PyPI JSON API for `weft`, `regatta`, `marl`, `skein`, `tutti`;
  [awesome-agent-orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators),
  [Augment Code — open-source agent orchestrators (2026)](https://www.augmentcode.com/tools/open-source-agent-orchestrators)
- PyPI availability checks (JSON API) for: trellis, skein, gantry, tiller, weft, drover, coxswain, lattice, flotilla,
  bosun, regatta, muster, cadre, helmsman, atelier, quorum, capstan, baton, tutti, purser, belay, rostrum, keelson,
  wharf, corral, rookery, quartermaster, marl
</content>
</invoke>
