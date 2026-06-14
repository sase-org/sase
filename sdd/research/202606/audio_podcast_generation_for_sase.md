# Audio / Podcast Generation for SASE (NotebookLM-style)

Date: 2026-06-14

## Question

Can `sase` generate audio — specifically NotebookLM-style "fake podcasts" (a two-host
conversation) from user-provided content such as a PDF? Is it feasible, what are the realistic
alternatives, and which one should we build?

**Bottom line up front:** Yes, it is feasible, and it is a surprisingly good fit for SASE. The
hardest and most differentiated part of a NotebookLM clone — turning a document into a lively,
critiqued, multi-host *script* — is exactly what SASE's agent + xprompt orchestration already does
well. The only genuinely new capability is text-to-speech (TTS) and audio assembly, and that is a
solved, commoditized problem with both cloud APIs and open-weight models. Recommendation is at the
end: **build a native xprompt-driven MVP on a cloud multi-speaker TTS API first, then graduate to a
provider-plugin abstraction** mirroring the existing `sase_llm` / `sase_vcs` pattern.

## The Anatomy of a NotebookLM-style Podcast

Every system in this space — Google's NotebookLM, Podcastfy, open-notebooklm — is the same
four-stage pipeline. Understanding the stages is the key to scoping SASE's work, because SASE
already owns two of them.

1. **Ingest** — Extract text from the source (PDF, URL, image, YouTube transcript). For PDFs this
   is `pdftotext` / `pypdf` / `pdfplumber`. Cheap, well-understood.
2. **Scriptwriting** — An LLM turns raw content into a structured, natural-sounding two-host
   dialogue. This is the part that makes NotebookLM feel magical, and it is *not* a single prompt.
   Per teardowns of NotebookLM, the real pipeline is: generate an outline → revise the outline →
   write a detailed script → **critique** the script → revise from critique → inject "disfluencies"
   (um, breaths, interruptions, affirmations) so the speech sounds human rather than read-aloud.
3. **Synthesis (TTS)** — Convert the script to audio with distinct voices per host. Either a
   multi-speaker model that does it in one call, or a single-voice model called per line and
   stitched.
4. **Assembly** — Concatenate/normalize the per-utterance audio into one file (mp3/wav),
   typically via `ffmpeg` / `pydub`.

**Why this matters for SASE:** Stage 2 is a multi-step, self-critiquing, multi-role agent workflow —
literally SASE's core competency (multi-agent xprompts, `research_swarm`-style fan-out/critique,
the LLM provider abstraction). Stage 1 is trivial. Stages 3–4 are the only new dependencies. So the
question is not "can SASE do this" but "how thin can we make the TTS/assembly layer."

## How SASE's Architecture Fits

From a read of the codebase, the relevant seams are already in place:

- **LLM abstraction already exists.** `src/sase/llm_provider/registry.py` loads providers from the
  `sase_llm` entry-point group; `claude`, `codex`, `gemini`, `opencode`, `qwen` are registered in
  `pyproject.toml`. Scriptwriting (stage 2) reuses this directly — no new model client needed.
- **xprompt workflows are the natural pipeline container.** `.yml` xprompts
  (`src/sase/xprompt/workflow_loader.py`, `workflow_executor.py`) chain `bash`, `python`, and
  `prompt_part` steps with typed inputs and JSON outputs. The whole podcast pipeline (extract →
  script → synthesize → assemble) maps onto one workflow file. Example shape exists at
  `src/sase/xprompts/file.yml`.
- **Multi-agent xprompts give us the critique loop for free.** `---` segment separators plus
  `%wait:` join directives (`src/sase/default_xprompts/research_swarm.md`,
  `src/sase/agent/multi_prompt_launcher.py`) are exactly the primitive for an
  outline → draft → critic → reviser script pipeline.
- **CLI extension is a known pattern.** New subcommands register via `parser_*.py` +
  `*_handler.py` (`src/sase/main/parser.py`, `entry.py`). A `sase audio` / `sase podcast`
  subcommand is a small, conventional addition.
- **Plugin/provider pattern is well established.** VCS (`sase_vcs`), LLM (`sase_llm`), workspace
  (`sase_workspace`) are all entry-point plugin groups discovered via
  `src/sase/main/plugin_discovery.py`. A `sase_tts` group would be idiomatic.
- **Artifact storage exists.** Generated audio belongs in the agent artifact dir
  (`SASE_ARTIFACTS_DIR`, `store_explicit_agent_artifact()` in `artifact_handler.py`) — the audio
  file becomes a first-class run artifact.
- **No audio deps today.** `pyproject.toml` (Python 3.12+) has no audio/TTS/PDF libraries. HTTP is
  done with stdlib `urllib`. So every option below adds *some* new dependency surface; minimizing
  that surface is a design goal.

### Where does this live — Rust core or Python?

The boundary note (`memory/short/rust_core_backend_boundary.md`) litmus test is:

> "If a web app, CLI, editor integration, or another frontend would need the behavior to match the
> TUI, treat it as core backend logic."

Applying it:
- **Script-generation orchestration and provider/config selection** *could* be argued into the Rust
  core if a future web frontend must produce byte-identical podcasts to the TUI. For an MVP this is
  over-engineering.
- **TTS API calls, PDF extraction, ffmpeg assembly, file IO** are presentation-adjacent glue /
  IO — Python-side by the same test. There is no shared-domain invariant a second frontend must
  match here.

**Verdict:** Build in Python. Revisit moving the *job/provider registry and script-state model* into
`sase-core` only if/when a non-TUI frontend (web) needs parity.

## Prior Art (don't reinvent the wheel)

- **Google NotebookLM "Audio Overview"** — the reference product. Closed. Built on Gemini for the
  script and Google's own dialogue-grade TTS lineage (AudioLM / SoundStorm — models that generate
  "acoustic tokens" capturing *how* something is said, trained on real dialogue so they insert
  breaths/pauses naturally). Not an API we can use directly, but the *workflow* (outline → critique →
  disfluencies) is the thing to copy.
- **Podcastfy** (`github.com/souzatharsis/podcastfy`, Apache-2.0, `pip install podcastfy`) — the
  leading open-source NotebookLM alternative. Ingests URL/PDF/image/YouTube/topic; generates the
  transcript via 100+ LLMs (OpenAI/Anthropic/Google or local HuggingFace models); synthesizes with
  OpenAI / Google / ElevenLabs / Microsoft Edge TTS; shorts (2–5 min) or longform (30+ min);
  multilingual. Needs Python 3.11+ and `ffmpeg`. It internally uses its own LLM stack
  (litellm/langchain-style), which **overlaps and competes** with SASE's `sase_llm` abstraction.
- **open-notebooklm** (`github.com/gabrielchua/open-notebooklm`) and **knowsuchagency/pdf-to-podcast**
  — smaller, single-purpose "PDF → episode" demos; good reference implementations, not libraries to
  depend on.

## TTS Landscape (the only genuinely new capability)

### Cloud multi-speaker (best quality, lowest build effort)

- **Gemini 2.5 Flash/Pro TTS** — *the standout for this use case.* Generates a **complete
  multi-speaker conversation in a single inference call** from a `Speaker: dialogue` script —
  collapsing stages 3 *and* 4 into one API call (no per-line stitching). 30+ voices, 24 languages;
  Flash is the cheaper/faster tier, Pro higher quality. This is the closest public API to how
  NotebookLM itself works.
- **ElevenLabs** — highest perceived voice quality (MOS ~4.3 vs Google ~4.1, OpenAI ~3.9), low
  latency (Flash v2.5 ~75ms). Per-voice synthesis; you stitch. ~$0.06 / 1K chars (premium pricing).
  The choice when voice realism is the differentiator.
- **OpenAI `gpt-4o-mini-tts`** — solid default, token-based pricing (~$0.60/M input + ~$12/M audio
  output). Single-voice; stitch per host.
- **Azure / Amazon Polly / Deepgram Aura-2** — cheapest neural options and lowest latency
  (Aura-2 ~90ms); single-voice, stitch. Good "cost is the only constraint" fallbacks.

### Open-weight / self-hosted (privacy, zero per-use cost, needs a GPU)

- **Dia2** (Nari Labs, 1.6B, ~5 GB VRAM) — *purpose-built for dialogue.* Tag speakers `[S1]`/`[S2]`,
  drop in `(laughs)`/`(sighs)`, get natural turn-taking. This is the open analog of the NotebookLM
  voice experience.
- **Kokoro** (82M, Apache-2.0, ~300MB, ~210× real-time on a 4090) — the only open TTS that runs
  comfortably on consumer hardware; single-voice, fast, cheap. Stitch per host.
- **Chatterbox** (ElevenLabs-tier quality, voice cloning from ~10s) and **Orpheus** (Llama-based
  speech-LLM) — higher quality, heavier to deploy.

**Implication:** the cloud-vs-local axis is the real decision. Cloud (Gemini) gives the best
quality and least code; local (Dia2/Kokoro) gives privacy and no marginal cost but demands GPU +
ops that don't fit SASE's lightweight `pip install` TUI distribution model.

## Alternatives

### Alternative A — Vendor Podcastfy as a thin integration

Shell out to / wrap the `podcastfy` package behind a `sase podcast` command.

- **Pros:** Fastest possible path to a working demo (it already does all four stages). Apache-2.0.
  Great for a throwaway spike to validate user appetite.
- **Cons:** Heavy, opinionated dependency tree (langchain/litellm + ffmpeg + many transitive deps).
  Its internal LLM stack **duplicates and bypasses** SASE's `sase_llm` providers, violating the
  "treat all runtimes uniformly" ethos and fragmenting model/config handling. Abandonment/version
  risk for a core feature. Hard to make it feel native.
- **Verdict:** Excellent as a reference implementation and a one-afternoon prototype; **poor as a
  shipped core dependency.**

### Alternative B — Native xprompt workflow + cloud multi-speaker TTS (MVP)

A `.yml` xprompt workflow: `bash` step extracts PDF text (`pdftotext`/`pypdf`) → `prompt_part`
step(s) drive a SASE agent (Claude/Gemini via the existing `sase_llm` abstraction) through
outline → draft → critique → revise to produce a `Speaker:`-formatted script → `python` step sends
the script to **Gemini 2.5 multi-speaker TTS** in one call → audio saved as a run artifact.

- **Pros:** Reuses SASE's two biggest strengths (agent scriptwriting + xprompt orchestration). The
  Gemini single-call multi-speaker API collapses the hardest new stages (TTS + stitch) into one HTTP
  request, so the only new code is PDF extraction + one API client + artifact write. Minimal new
  dependency surface (no ffmpeg needed for the single-call path). Ships as a normal SASE workflow,
  not a foreign tool. Config/keys via `default_config.yml` + env var (`SASE_TTS_API_KEY`).
- **Cons:** Tied to one cloud vendor at first; needs API-key/secret handling (none exists today).
  Script-quality tuning (the disfluencies/critique loop) is iterative work.
- **Verdict:** Best risk-adjusted MVP. Proves the concept end-to-end with the least new surface area.

### Alternative C — Fully local / self-hosted pipeline (privacy-first)

Same orchestration as B, but synthesize with an open-weight model (**Dia2** for true `[S1]/[S2]`
dialogue, or **Kokoro** for speed) running locally, optionally with a local LLM for the script.

- **Pros:** No per-use cost, full data privacy (PDF never leaves the machine), no vendor lock-in.
  Aligns with the "local LLM for privacy" theme already present in the ecosystem.
- **Cons:** Requires a GPU (~5 GB VRAM for Dia2) and model/runtime ops that clash with SASE's
  lightweight pip/TUI install story. Lower out-of-box polish than Gemini/ElevenLabs. Adds heavy
  optional deps (torch, model weights). Slower to a good demo.
- **Verdict:** A compelling *option* to offer later (privacy-conscious / offline users), not the
  first thing to build.

### Alternative D — First-class `sase audio` subcommand + `sase_tts` provider plugin abstraction

Do it "the SASE way": define a `sase_tts` entry-point plugin group (mirroring `sase_llm`/`sase_vcs`)
with providers `gemini`, `elevenlabs`, `openai`, `local-kokoro`/`local-dia`; a `sase audio generate`
CLI subcommand (`parser_audio.py` + `audio_handler.py`); script generation through the existing
`sase_llm` registry; audio persisted via the artifact facade. Workflow B becomes one consumer of
this abstraction.

- **Pros:** Most idiomatic and extensible — provider-agnostic, so cloud quality (Gemini/ElevenLabs)
  and local privacy (Dia/Kokoro) coexist behind one seam. Uniform-runtime philosophy preserved.
  Clean home for config, secrets, voice selection. Lets B and C be *configurations*, not rewrites.
- **Cons:** More upfront design/work; premature if user appetite is unproven; needs a secret-handling
  convention SASE doesn't have yet.
- **Verdict:** The right *destination*, slightly too much to build before validating demand.

## Recommended Solution

**Phase it: B → D, with A as a throwaway probe and C as a later configuration of D.**

1. **Spike (optional, ~hours):** Wire up **Podcastfy (A)** behind a hidden command purely to
   validate output quality and user appetite. Throw it away; do not ship it as a dependency.

2. **Ship the MVP (Alternative B):** Build a native podcast **xprompt workflow** that:
   - extracts PDF/URL text in a `bash`/`python` step;
   - drives a SASE agent through the **NotebookLM-style script pipeline** (outline → critique →
     disfluencies) using the existing `sase_llm` abstraction and multi-agent `---`/`%wait:`
     primitives — this is where SASE genuinely beats a one-shot prompt;
   - synthesizes via **Gemini 2.5 multi-speaker TTS** (single call → finished 2-voice mp3),
     eliminating per-line stitching and ffmpeg for v1;
   - stores the audio as a run **artifact**.

   This delivers a working NotebookLM-style feature with the smallest new dependency footprint, and
   showcases SASE's orchestration as the differentiator rather than a thin TTS wrapper.

3. **Graduate to the abstraction (Alternative D):** Once validated, extract the TTS call into a
   `sase_tts` plugin group + a `sase audio` subcommand. Add **ElevenLabs** (quality) and a **local
   Dia2/Kokoro** provider (Alternative C — privacy/offline) as additional plugins. Establish the
   secret-handling convention (env-var first, config-referenced key) here.

**Why this order:** It front-loads SASE's strengths (agentic, self-critiquing scriptwriting) and
back-loads the commodity part (TTS), reaches a credible demo with minimal new surface, and avoids
two traps — (a) taking on Podcastfy's competing LLM stack as a core dependency, and (b) building a
full provider abstraction before the feature has proven its worth. The Rust core stays untouched
until a second (web) frontend actually needs script/provider parity.

## Open Questions / Follow-ups

- **Secret management:** SASE has no built-in secret store. Decide the convention (env var
  `SASE_TTS_API_KEY` vs. config-referenced key) before D.
- **Input breadth:** PDF-only for v1, or URL/YouTube/image like Podcastfy? Ingest is cheap to widen
  later.
- **Length/format controls:** shorts vs longform, number of hosts, language, voice selection — all
  config in D.
- **Cost guardrails:** longform podcasts are many thousands of TTS characters/tokens; surface
  estimated cost before synthesis.
- **Determinism/testing:** audio output is non-deterministic — test the script stage (text) with
  snapshots; treat TTS as an integration-only path.

## Sources

- [NotebookLM's automatically generated podcasts are surprisingly effective — Simon Willison](https://simonwillison.net/2024/Sep/29/notebooklm-audio-overview/)
- [Decoding the Architecture of NotebookLM's Podcast Feature](https://vrungta.substack.com/p/decoding-the-architecture-of-notebooklm)
- [NotebookLM Audio Overviews workflow teardown — Rob Allandale](https://roballandale.com/briefs/notebooklm-audio-overviews-workflow-teardown/)
- [Build an open source NotebookLM — Together AI docs](https://docs.together.ai/docs/open-notebooklm-pdf-to-podcast)
- [Podcastfy — GitHub (souzatharsis/podcastfy)](https://github.com/souzatharsis/podcastfy)
- [open-notebooklm — GitHub (gabrielchua/open-notebooklm)](https://github.com/gabrielchua/open-notebooklm)
- [pdf-to-podcast — GitHub (knowsuchagency/pdf-to-podcast)](https://github.com/knowsuchagency/pdf-to-podcast)
- [Top 10 Text-to-Speech APIs in 2026 — Eden AI](https://www.edenai.co/post/best-text-to-speech-apis)
- [Best TTS APIs in 2026 — Speechmatics](https://www.speechmatics.com/company/articles-and-news/best-tts-apis-in-2025-top-12-text-to-speech-services-for-developers)
- [Text-to-Speech API Comparison 2026 — TokenMix](https://tokenmix.ai/blog/tts-api-comparison)
- [Gemini 2.5 Text-to-Speech model updates — Google blog](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-2-5-text-to-speech/)
- [Gemini 2.5 Pro Text to Speech (multi-speaker) — WaveSpeedAI](https://wavespeed.ai/models/google/gemini-2.5-pro/text-to-speech)
- [gemini-2-tts AI podcast generator — GitHub (agituts/gemini-2-tts)](https://github.com/agituts/gemini-2-tts)
- [The Best Open-Source Text-to-Speech Models in 2026 — BentoML](https://www.bentoml.com/blog/exploring-the-world-of-open-source-text-to-speech-models)
- [Best Open Source TTS Models 2026: Kokoro, Chatterbox, Fish Audio — Speakeasy](https://www.tryspeakeasy.io/blog/open-source-text-to-speech-2026)
- [Kokoro TTS Review 2026 — TextToLab](https://texttolab.com/blog/kokoro-tts-review)
