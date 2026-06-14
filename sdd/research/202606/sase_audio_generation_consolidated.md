# SASE Audio Generation and PDF-to-Podcast Research

Research date: 2026-06-14

Consolidated from:

- `sdd/research/202606/audio_podcast_generation_for_sase.md`
- `sdd/research/202606/sase_audio_generation_research.md`

## Question

Can SASE generate audio from user-provided content, such as turning a PDF into a NotebookLM-style fake podcast? What are
the realistic alternatives, and which should SASE build first?

## Short Answer

Yes. The feature is feasible and fits SASE well, but it should be treated as a pipeline rather than a single TTS call:

1. ingest the source document;
2. extract and normalize source text;
3. generate a grounded outline and two-speaker transcript;
4. validate the transcript, length, voices, and safety defaults;
5. synthesize speech;
6. assemble or export the audio;
7. save the audio, transcript, source map, and generation manifest as SASE artifacts.

The differentiated part is step 3. NotebookLM-style quality comes mostly from scriptwriting: outline, critique, revision,
host dynamics, disfluencies, source grounding, and useful framing. That is SASE's strong area: agent orchestration,
xprompt workflows, multi-agent critique loops, and existing LLM provider selection. The genuinely new capability is TTS
plus some audio assembly and artifact UX.

## SASE Fit

The existing repo already has most of the product shape needed for an MVP:

- xprompt workflows can chain `bash`, `python`, and `prompt_part` steps with typed inputs and JSON outputs.
- `sase_llm`, `sase_vcs`, and `sase_workspace` entry point groups show an established provider/plugin pattern.
- Explicit artifacts already support `chat`, `plan`, `image`, `markdown`, `pdf`, and generic `file`; audio can start as
  `file`.
- `sase artifact create` requires an agent context and stores files under the current run's `SASE_ARTIFACTS_DIR`.
- The core runtime has no general audio/TTS stack today. `pypdf` exists only in the optional `docs-pdf` extra, so a v1
  feature should keep runtime PDF/audio dependencies narrow.

This should start in Python and xprompt workflow code, not the Rust core. The Rust boundary matters when shared domain
behavior must match across the TUI, CLI, web app, and other frontends. For v1, PDF extraction, provider HTTP calls, audio
file IO, and artifact creation are workflow glue. Move provider/job state into `sase-core` only if a second frontend
needs the same behavior.

Likely first interface:

```bash
sase run '#!audio_overview(source=paper.pdf, style=deep_dive, provider=gemini-tts, length=short)'
```

Likely later interface if the workflow proves useful:

```bash
sase audio generate paper.pdf --style deep-dive --provider gemini --out overview.mp3
```

## Current Landscape

| Alternative | What it solves | SASE fit | Main limitation |
| --- | --- | --- | --- |
| NotebookLM / Drive Audio Overviews | Best immediate PDF-to-podcast product benchmark | Manual workaround and quality target | Not a SASE-controlled artifact pipeline |
| Deprecated NotebookLM Enterprise Podcast API | Batch source-to-MP3 API shape | Do not target | Deprecated; Google is not allowlisting new customers |
| Podcastfy / open NotebookLM projects | Fastest prototype | Good spike/reference | Duplicates SASE orchestration and provider layers |
| SASE-native workflow + Gemini TTS | Best MVP for podcast-style output | Strongest default | Gemini TTS is Preview and long output needs chunking |
| SASE-native workflow + OpenAI TTS | Simple fallback and likely existing credentials | Good fallback | Single-voice request path; long transcripts need chunking/stitching |
| SASE-native workflow + ElevenLabs | Premium dialogue/studio quality | Premium opt-in | Cost, account policy, and voice-safety surface |
| AWS Polly / Azure Speech | Enterprise TTS primitives | Enterprise fallback | More narration/SSML than NotebookLM-style banter |
| Local TTS: Dia2, Kokoro, Piper, Riva | Privacy/offline generation | Later optional provider tier | GPU/runtime/dependency burden and less turnkey quality |

## Option A: Hosted NotebookLM or Google Drive

NotebookLM is the current product benchmark. Google's help docs describe Audio Overviews as deep-dive discussions
between AI hosts based on uploaded sources. NotebookLM supports PDFs and many other source types, with source limits
such as 500,000 words per source and 200 MB local uploads. Google Drive also added one-click PDF audio overviews that
turn long, text-heavy PDFs into conversational summaries saved back to Drive; at launch, that Drive feature supported
English-language PDFs.

This solves the user's immediate "I have a PDF and want an audio summary" need, but it is not the right SASE
integration target. It is a hosted UI/workspace product, not a controllable local SASE artifact pipeline with
transcript review, provider choice, source maps, or SASE run metadata.

The older NotebookLM Enterprise Podcast API is not a good escape hatch. Google now labels it deprecated and says it is
not allowlisting new customers.

Use NotebookLM and Drive as:

- quality benchmarks;
- manual workarounds;
- comparison targets for the SASE workflow output.

Do not use them as:

- the default SASE backend;
- the long-term automation API;
- the place where SASE stores provenance, transcripts, or artifacts.

## Option B: Wrap Podcastfy or Similar Open-Source Pipelines

Podcastfy is an Apache-licensed Python package that converts websites, PDFs, images, YouTube videos, text, and topics
into multilingual audio conversations. PyPI currently lists `podcastfy` 0.4.3, released 2025-12-09, requiring Python
3.11+. Its docs list `ffmpeg`, API keys, CLI/Python usage, short/long-form podcast generation, 100+ LLMs for transcript
generation, local LLM support, and TTS providers such as OpenAI, Google, ElevenLabs, and Microsoft Edge.

This is the fastest path to a demo:

```bash
python -m podcastfy.client --url <source>
```

A hidden or experimental SASE workflow could shell out to Podcastfy and attach the generated MP3/transcript with
`sase artifact create -k file`.

The problem is product ownership. Podcastfy brings its own orchestration, LLM/provider abstraction, transcript
formatting, and dependencies. That overlaps with SASE's xprompt, agent, artifact, and provider model. It is useful as a
spike and reference implementation, but it should not become the shipped core dependency.

## Option C: SASE-Native Workflow with Gemini TTS

This is the best MVP path.

Google's Gemini API TTS docs say it can transform text into single-speaker or multi-speaker audio, is controllable with
natural-language instructions, and is intended for exact text recitation workflows such as podcasts and audiobooks. The
docs currently use `gemini-3.1-flash-tts-preview` for multi-speaker examples, list 30 voice options, and list Gemini
3.1 Flash TTS Preview plus Gemini 2.5 Flash/Pro Preview TTS as supporting both single-speaker and multi-speaker output.

Why this fits SASE:

- SASE can use its existing LLM provider layer to write a reviewed, source-grounded transcript first.
- Gemini can render the two-speaker transcript in one provider call, avoiding per-line stitching for v1.
- Gemini's speaker names, voice configs, and inline audio tags map naturally to SASE style profiles such as `brief`,
  `deep_dive`, `debate`, `executive_summary`, and `critique`.

Risks and guardrails:

- Gemini TTS is still Preview.
- The docs say TTS has a 32k-token context window, does not support streaming, and longer outputs can drift in quality.
  SASE should chunk anything beyond a few minutes.
- The docs also recommend retries for occasional server-side failures and clear prompts so style instructions are not
  read aloud.
- SASE should always save the transcript before synthesis so the user can inspect and regenerate cheaply.

## Option D: SASE-Native Workflow with OpenAI TTS

OpenAI is a strong fallback because SASE users may already have OpenAI credentials. The current speech endpoint uses
`gpt-4o-mini-tts`, supports instructions for delivery style, returns MP3 by default, supports streaming, and exposes 13
built-in voices. The model page lists a 2,000-token maximum input size for `gpt-4o-mini-tts`, so long podcast scripts
must be chunked.

OpenAI fits best for:

- narrated summaries;
- short podcast segments;
- provider fallback;
- users who already have OpenAI API setup.

It is less convenient than Gemini for a two-host podcast because SASE should synthesize speaker blocks separately,
choose two voices, and stitch/normalize output. That is manageable, but it adds latency, ffmpeg/pydub work, and more
failure modes. OpenAI's TTS docs also require clear disclosure that the voice is AI-generated.

## Option E: ElevenLabs for Premium Dialogue

ElevenLabs is the strongest premium/provider-opt-in path. Its model docs describe Eleven v3 and a Text to Dialogue API
for multi-character dialogue across many languages. The Text to Dialogue API accepts dialogue inputs with voice IDs,
supports up to 10 unique voice IDs, and recommends keeping request text at or below 2,000 characters for reliable
generation. The Studio API also has a create-podcast endpoint, but that endpoint requires allowlisting.

Use ElevenLabs when:

- production voice quality matters more than provider simplicity;
- the user already pays for ElevenLabs;
- a human-in-the-loop studio/editor workflow becomes valuable.

Do not make it the default. Its cost model, account setup, commercial usage details, and impersonation/voice-cloning
policy surface are heavier than the Gemini MVP path. SASE defaults should use generic synthetic voices and avoid "sound
like this person" presets.

## Option F: Enterprise and Local TTS Providers

AWS Polly and Azure Speech are stable enterprise TTS options. Polly supports multiple voice classes, caching/replay of
generated speech, long-form voices, and SSML controls for pronunciation, volume, and rate. Azure Speech exposes REST and
SDK text-to-speech APIs with many locales, SSML, and newer HD voices that adapt emotion, pace, and rhythm.

These are credible enterprise fallback providers, especially where existing AWS/Azure accounts, regional controls, or
compliance posture matter. They are less compelling as the first NotebookLM-like default because they are closer to
deterministic narration/SSML than natural two-host dialogue.

Local TTS is credible for private or offline use, but it should be a later provider tier:

- Dia2 is a streaming dialogue TTS model with Apache-2.0 code/model access, but its README currently says it supports
  English generation up to two minutes and that quality/voices vary without prefixing or fine-tuning.
- Kokoro-82M is an Apache-licensed open-weight TTS model with 82 million parameters and a small deployment footprint.
- Piper remains useful as a fast local TTS engine; the original `rhasspy/piper` repo is archived and development moved
  to `OHF-Voice/piper1-gpl`, which is GPL-3.0.
- NVIDIA Riva is a GPU-oriented stack with streaming/offline TTS, SSML, pronunciation dictionaries, and beta emotion
  controls.

Local mode should be positioned as privacy/offline support, not the first polished user experience. It introduces model
download, GPU/CPU performance, native dependency, licensing, and quality-tuning work that does not match the smallest
SASE MVP.

## Implementation Shape

Build the first version as an `audio_overview` xprompt workflow plus a small helper module, not a permanent CLI command.

Suggested workflow:

1. `extract_source`: read PDF/text/Markdown input, extract text, and write `source_text.md` plus `source_manifest.json`.
2. `write_transcript`: use SASE agents to produce structured transcript JSON with title, summary, speakers, segments,
   source references, tone/style tags, and disclosure text.
3. `critique_and_revise`: run a reviewer pass for grounding, clarity, length, host dynamics, and overclaiming.
4. `validate_transcript`: enforce length caps, non-empty segments, supported voices, source-reference coverage, and
   non-impersonation defaults.
5. `synthesize_audio`: call Gemini TTS first; support OpenAI as a fallback path.
6. `save_artifacts`: attach `overview.mp3` or `overview.wav`, `transcript.md`, `transcript.json`, and
   `generation_manifest.json` with `sase artifact create -k file`.

Implementation notes:

- Cache provider requests by transcript/provider/model/voice hash so edits do not regenerate unchanged chunks.
- Store provider model, voices, source hash, prompt version, and chunk IDs in `generation_manifest.json`.
- Do not store API keys or raw credentials in manifests, output variables, or `agent_meta.json`.
- Use environment variables or config references for provider credentials until SASE has a general secret-management
  convention.
- Add an `audio` artifact kind only after users want playback/preview behavior in ACE or notifications.
- Test script generation and validation with snapshots; keep TTS synthesis as integration/manual tests because audio is
  non-deterministic.

## Safety and UX Defaults

The default product should be useful but conservative:

- Use generic synthetic voices, not celebrity/person presets.
- Include written disclosure in transcript and manifest; optionally include a short spoken disclosure at the end.
- Preserve a transcript before audio generation.
- Keep source references in the transcript and manifest, even though MP3 cannot carry useful citations by itself.
- Estimate cost before long synthesis jobs.
- Do not position generated audio as a substitute for the source in legal, medical, financial, or safety-critical
  contexts.
- Require explicit opt-in before any custom voice, cloned voice, or uploaded speaker reference.

## Source Index

- [NotebookLM Audio Overviews](https://support.google.com/notebooklm/answer/16212820?hl=en)
- [NotebookLM source types and limits](https://support.google.com/notebooklm/answer/16215270?co=GENIE.Platform%3DDesktop&hl=en)
- [NotebookLM FAQ and limits](https://support.google.com/notebooklm/answer/16269187?hl=en)
- [Google Drive audio overviews for PDFs](https://workspaceupdates.googleblog.com/2025/11/ai-powered-audio-overviews-for-pdfs-google-drive.html)
- [Deprecated NotebookLM Enterprise Podcast API](https://docs.cloud.google.com/gemini/enterprise/notebooklm-enterprise/docs/podcast-api)
- [Gemini API TTS docs](https://ai.google.dev/gemini-api/docs/speech-generation)
- [Gemini 3.1 Flash TTS Preview model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-tts-preview)
- [OpenAI text-to-speech guide](https://developers.openai.com/api/docs/guides/text-to-speech)
- [OpenAI audio guide](https://developers.openai.com/api/docs/guides/audio)
- [OpenAI gpt-4o-mini-tts model page](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts)
- [ElevenLabs Text to Dialogue docs](https://elevenlabs.io/docs/overview/capabilities/text-to-dialogue)
- [ElevenLabs Text to Dialogue API](https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert)
- [ElevenLabs Studio create podcast API](https://elevenlabs.io/docs/api-reference/studio/create-podcast)
- [ElevenLabs prohibited-use policy](https://elevenlabs.io/use-policy)
- [Podcastfy GitHub](https://github.com/souzatharsis/podcastfy)
- [Podcastfy PyPI](https://pypi.org/project/podcastfy/)
- [Amazon Polly overview](https://docs.aws.amazon.com/polly/latest/dg/what-is.html)
- [Amazon Polly SSML](https://docs.aws.amazon.com/polly/latest/dg/ssml.html)
- [Azure Speech REST TTS](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech)
- [Azure Speech HD voices](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/high-definition-voices)
- [Dia2 GitHub](https://github.com/nari-labs/dia2)
- [Kokoro-82M Hugging Face](https://huggingface.co/hexgrad/Kokoro-82M)
- [Piper current repo](https://github.com/OHF-Voice/piper1-gpl)
- [NVIDIA Riva TTS overview](https://docs.nvidia.com/deeplearning/riva/user-guide/docs/tts/tts-overview.html)

## Recommended Solution

Build a SASE-native `audio_overview` xprompt workflow first, using Gemini TTS as the primary provider and OpenAI TTS as
the first fallback.

The MVP should:

1. accept one PDF/text/Markdown source;
2. extract text into a source artifact;
3. use existing SASE agents and `sase_llm` providers to produce a reviewed, source-grounded two-host transcript;
4. render with Gemini `gemini-3.1-flash-tts-preview` when available, chunking long scripts and retrying preview-model
   failures;
5. fall back to OpenAI `gpt-4o-mini-tts` for shorter or already-OpenAI-configured workflows;
6. save `overview.mp3` or `overview.wav`, `transcript.md`, `transcript.json`, and `generation_manifest.json` as generic
   `file` artifacts;
7. default to generic synthetic voices and clear AI-generated-audio disclosure.

After the workflow proves useful, extract the synthesis layer into a `sase_tts` plugin group and add a first-class
`sase audio generate` command. At that point, add ElevenLabs as a premium provider and Dia2/Kokoro/Piper/Riva as
privacy/offline providers. Add an `audio` artifact kind and ACE playback behavior only when the artifact UX needs it.

Do not target NotebookLM or the deprecated NotebookLM Enterprise Podcast API as the SASE backend. Use NotebookLM/Drive
only as quality benchmarks, and use Podcastfy only as a spike/reference rather than a permanent core dependency.
