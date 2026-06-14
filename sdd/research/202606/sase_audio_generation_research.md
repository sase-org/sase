# SASE Audio Generation and PDF-to-Podcast Research

Research date: 2026-06-14

## Question

Can SASE generate audio from user-provided content, such as turning a PDF into a NotebookLM-style podcast, and what
alternatives solve this problem?

## Short Answer

Yes. The problem is very feasible, but it is not one feature. It is a pipeline:

1. ingest a source document;
2. extract and normalize text;
3. generate a grounded outline or two-speaker transcript;
4. synthesize speech with one or more voices;
5. stitch and encode audio;
6. save the audio, transcript, source map, and generation manifest as SASE artifacts.

SASE already has enough shape for an MVP: xprompt workflows can combine agent, Python, and shell steps, and
`sase artifact create` can attach generated files to an agent run as explicit artifacts. The first implementation does
not need a new agent runtime. It should be an artifact-producing workflow or optional command backed by provider
adapters.

The main product choice is whether SASE should:

- delegate to a hosted product like NotebookLM or Gemini in Drive;
- wrap an open-source NotebookLM-like project such as Podcastfy;
- build a small SASE-native document-to-audio pipeline over TTS APIs;
- support local/private TTS engines for offline or sensitive content.

## SASE Fit

Audio generation should be treated like generated PDFs and images: a durable output artifact attached to a run.

Useful existing SASE surfaces:

- XPrompt workflows already support typed inputs, Python/bash steps, agent steps, and output passing.
- Agent finalization already persists explicit artifacts.
- The artifact kind model currently supports `chat`, `plan`, `image`, `markdown`, `pdf`, and generic `file`; audio can
  start as `file`.
- ACE can list and open explicit artifacts even if it does not yet have first-class audio playback.

Likely first user experience:

```bash
sase run '#!audio_overview(source=paper.pdf, style=deep_dive, provider=gemini-tts, length=short)'
```

Likely later user experience if this graduates from workflow to CLI:

```bash
sase audio generate paper.pdf --style deep-dive --provider gemini-tts --out overview.mp3
```

The CLI form is nicer, but the workflow form is the right first cut because it exercises the product without committing
to a permanent command surface too early.

## Option Matrix

| Option | What it solves | SASE fit | Main limitation |
| --- | --- | --- | --- |
| NotebookLM / Gemini in Drive | Best immediate user-facing PDF-to-podcast experience | Manual benchmark or external workflow | Not SASE-controlled; limited automation/API story |
| Podcastfy / Open NotebookLM | Fastest open-source prototype | Good spike dependency or reference implementation | Adds third-party orchestration and provider abstractions |
| SASE-native pipeline + Gemini TTS | Best SASE-controlled podcast-style output | Best default implementation path | Gemini TTS is still preview in current docs |
| SASE-native pipeline + OpenAI TTS | Simple, reliable text-to-speech path | Good fallback and users may already have OpenAI credentials | Needs per-speaker segment stitching; input size limits |
| SASE-native pipeline + ElevenLabs | Highest-end creative voice/dialogue production | Premium provider option | Cost, credits, voice-safety policy surface |
| AWS Polly / Azure Speech | Enterprise TTS, SSML, compliance, stable cloud primitives | Good enterprise fallback | More narration/SSML than NotebookLM-style dialogue |
| Local TTS: Piper, Kokoro, Riva | Private/offline/cheap speech synthesis | Good optional privacy mode | Requires separate script generation and more UX tuning |

## Option A: Hosted NotebookLM or Gemini Audio Overviews

This is the closest thing to the desired end-user behavior today. NotebookLM supports PDFs and other source types, with
limits such as 500,000 words per source, 200 MB local uploads, and 50 sources for free users. Its Audio Overviews are
deep-dive discussions between AI hosts based on uploaded sources, can be downloaded, support interactive mode in
English, and support 80+ output languages.

Google Drive also gained one-click audio overviews for text-heavy PDFs, saving a conversational podcast-style audio
summary directly to Drive. This is powered by the same underlying technology as NotebookLM's Audio Overview feature.

Fit for SASE:

- Use it as the quality benchmark and the fastest manual workaround.
- Do not make it the SASE integration target. It is a product UI/workspace feature, not a controllable local artifact
  pipeline.
- Do not plan around the old NotebookLM Enterprise Podcast API. Google's current docs say that API is deprecated and
  Google is not allowlisting new customers.

Best use:

- "I have one PDF and want the result now."
- Demos and comparison tests for SASE-generated output quality.

Not good for:

- agent-run artifacts;
- provider-neutral workflows;
- local/private processing;
- deterministic transcript review before audio generation.

## Option B: Wrap Podcastfy or Open NotebookLM

Podcastfy is an open-source Python package and CLI that transforms websites, PDFs, images, YouTube videos, text, and
topics into multilingual audio conversations. It supports short and long-form podcasts, transcript/audio customization,
100+ LLMs for transcript generation, local LLMs, and TTS providers including OpenAI, Google, ElevenLabs, and Microsoft
Edge. PyPI shows `podcastfy` 0.4.3 released on 2025-12-09, Apache-2.0 licensed, Python 3.11+.

Open NotebookLM is a smaller reference app that explicitly converts a PDF into natural dialogue and outputs an MP3,
using an LLM plus open-source TTS models.

Fit for SASE:

- Good spike path. A SASE workflow could call Podcastfy in a Python step, then attach the generated audio and transcript
  with `sase artifact create`.
- Good source of product ideas: transcript schema, multi-speaker prompt shape, long-form chunking, provider routing.
- Risky as the permanent core abstraction. SASE already has its own workflow, agent, artifact, provider, and config
  layers. Importing Podcastfy wholesale would duplicate orchestration and make debugging harder.

Best use:

- Prototype in one or two days.
- Validate whether users actually want this feature.
- Compare providers quickly.

Not good for:

- polished SASE-native UX;
- strict source-grounding controls;
- minimal dependency surface.

## Option C: SASE-Native Pipeline with Gemini TTS

Gemini TTS is the strongest default provider candidate for the podcast-specific use case. Google's current Gemini API
docs say the TTS API can generate single-speaker and multi-speaker audio, is controllable with natural-language
direction, and is tailored for exact text recitation in structured workflows such as podcast or audiobook generation.
The models page lists Gemini 3.1 Flash TTS Preview, Gemini 2.5 Flash Preview TTS, and Gemini 2.5 Pro Preview TTS as
supporting both single-speaker and multi-speaker generation. The prompting guide also supports inline audio tags such as
tone, pace, whispering, laughter, and other delivery controls.

Why this maps well to SASE:

- Native multi-speaker TTS means SASE can render a dialogue transcript without splitting every utterance into separate
  provider calls.
- Gemini's promptable style controls map naturally to SASE xprompt profiles: `brief`, `deep_dive`, `debate`,
  `executive_summary`, `explainer`, `critique`.
- Google also has SynthID watermarking for NotebookLM podcast audio and broader Google AI-generated audio, which is a
  useful safety/provenance story.

Risks:

- The Gemini TTS docs currently label the feature as Preview.
- Google billing/project setup is a new auth surface unless the user already uses Gemini.
- Native multi-speaker output is convenient, but SASE should still store the generated transcript before synthesis so
  users can inspect what will be spoken.

Best use:

- Default SASE PDF-to-podcast provider.
- Multi-speaker summaries, debates, guided explainers, and source-grounded "deep dive" output.

## Option D: SASE-Native Pipeline with OpenAI TTS

OpenAI's current TTS guide exposes a speech endpoint based on `gpt-4o-mini-tts`, with built-in voices, streaming, and
speech steering for accent, emotion, intonation, speed, tone, whispering, and related delivery traits. The model page
lists text input and audio output, with a maximum input size of 2,000 tokens for `gpt-4o-mini-tts`; the TTS guide lists
13 built-in voices and recommends `marin` or `cedar` for best quality. OpenAI's realtime docs distinguish request-based
audio APIs as the right path for files and bounded generated speech, while realtime sessions are better for live
low-latency voice agents.

Fit for SASE:

- Good first fallback because many SASE users may already have OpenAI credentials.
- Simpler integration than a full realtime voice stack.
- Works well for narration, executive summaries, and short podcast segments.

Tradeoffs:

- For two-host podcasts, SASE should synthesize each utterance or speaker block separately, choose two voices, then
  stitch the audio. That gives control but adds latency and ffmpeg/pydub work.
- The 2,000-token input limit makes chunking mandatory for long transcripts.
- OpenAI's public usage policies prohibit using someone's likeness or voice without consent in ways that could confuse
  authenticity; SASE should keep defaults to generic synthetic voices and disclose generated audio.

Best use:

- Narrated summaries;
- provider fallback;
- users already configured for OpenAI;
- short generated artifacts where segment stitching is acceptable.

## Option E: ElevenLabs for Premium Dialogue and Studio Workflows

ElevenLabs has a mature audio product surface. Its TTS API emphasizes lifelike audio, nuanced intonation, pacing,
emotional awareness, streaming, and 32-language support in its developer docs. Its model docs describe Eleven v3 and a
Text to Dialogue API for natural dialogue with multiple characters. The Studio API even has a "create podcast" endpoint
that creates and auto-converts a podcast project, with separate audio generation charges.

Fit for SASE:

- Best premium option for polished voices and creator workflows.
- Useful when the user explicitly values production quality more than cost or provider simplicity.
- Studio projects may be useful later if SASE wants a human-in-the-loop editor before final export.

Tradeoffs:

- More expensive in common usage than basic cloud TTS.
- Heavier account/credit/commercial-license surface.
- Stronger voice-cloning and impersonation policy considerations. ElevenLabs' prohibited-use policy forbids
  intentionally replicating another person's voice without consent or legal right, or doing so deceptively.

Best use:

- Paid/professional podcast output;
- high-quality multi-speaker creative content;
- users who already use ElevenLabs.

## Option F: AWS Polly or Azure Speech

AWS Polly and Azure Speech are strong enterprise TTS primitives. Polly converts text into lifelike speech, supports
many languages and multiple voice classes, and allows caching/replay of generated speech. Polly also supports SSML for
controlling pronunciation, volume, speech rate, pauses, and related speech details; its Long-form voices are intended
for longer content such as news articles, training materials, and marketing videos. Azure Speech exposes REST and SDK
text-to-speech APIs with neural voices in many locales, and Azure's HD voices can detect emotion from input text and
adjust tone while maintaining consistent voice personas.

Fit for SASE:

- Good enterprise option where AWS/Azure accounts, compliance posture, and regional controls matter.
- SSML is useful for deterministic narration and pronunciation fixes.
- Less ideal for a NotebookLM-like "AI hosts bantering" feel unless SASE does more transcript and segment-direction
  work itself.

Best use:

- corporate deployments;
- compliance-driven environments;
- multilingual narration;
- deterministic SSML-heavy audio, not necessarily creative podcasts.

## Option G: Local and Private TTS

Local TTS is credible for privacy and offline use, but it is not the best first default for a polished NotebookLM-like
feature.

Relevant options:

- Piper is a fast local neural TTS engine with CLI, web server, Python API, C/C++ API, and voice support.
- Kokoro-82M is an Apache-licensed open-weight TTS model with 82 million parameters that can be deployed locally or in
  production.
- NVIDIA Riva provides a GPU-accelerated TTS stack with offline and streaming inference modes.

Fit for SASE:

- Good optional provider tier for sensitive PDFs, disconnected machines, and users who want no source text sent to a
  TTS provider.
- Pairs naturally with local LLM transcript generation if SASE later supports fully local "private audio overview"
  workflows.

Tradeoffs:

- SASE still needs a separate LLM step to produce the script.
- Voice quality and emotional dialogue usually require more tuning than Gemini/OpenAI/ElevenLabs.
- Packaging can be heavy, especially for GPU-backed Riva.

Best use:

- privacy-first local mode;
- inexpensive batch narration;
- research or internal-only artifacts.

## Implementation Shape

An MVP can be built as a SASE xprompt workflow with one helper module rather than a new CLI command.

### MVP workflow

1. `extract_source`: Python step reads PDF/text/Markdown input, extracts text, stores `source_text.md` and
   `source_manifest.json`.
2. `write_transcript`: agent step generates structured JSON:
   - `title`
   - `summary`
   - `speakers`
   - `segments[]` with `speaker`, `text`, `tone`, `source_refs`, and optional `ssml_or_tags`
   - `disclosure`
3. `validate_transcript`: Python step checks length, empty segments, unsupported voices, banned impersonation patterns,
   and source-reference coverage.
4. `synthesize_audio`: Python step calls the selected TTS provider, caches segment/provider responses by hash, and
   writes WAV segments.
5. `assemble_audio`: Python/bash step uses ffmpeg to normalize, concatenate, add short pauses, and emit MP3/WAV.
6. `save_artifacts`: stores:
   - `overview.mp3`
   - `transcript.md`
   - `transcript.json`
   - `generation_manifest.json`
   - optionally `source_excerpt_map.md`

For the first version, store audio with `sase artifact create -k file`. If users like the feature, add an `audio`
artifact kind later and teach ACE/notifications to play or upload audio more intelligently.

### Provider adapter sketch

Keep provider code small and boring:

```python
class TtsProvider(Protocol):
    name: str

    def synthesize(self, request: TtsRequest) -> TtsResult:
        ...
```

`TtsRequest` should include:

- `segments`
- `voices`
- `language`
- `format`
- `style_profile`
- `provider_model`
- `safety_disclosure`

SASE should store the exact request and provider response metadata in `generation_manifest.json`, without storing API
keys or secrets.

### Safety and UX rules

- Default to generic synthetic voices. Do not offer "sound like $person" presets.
- Include a short audible or written disclosure in the transcript/manifest, and optionally at the start/end of the
  audio for shared artifacts.
- Require explicit user opt-in before voice cloning or custom uploaded voices.
- Preserve a transcript before audio generation so the user can inspect and regenerate cheaply.
- Keep source citations in the transcript, even though the MP3 cannot carry useful citations by itself.
- Do not treat generated audio as a replacement for reading the source on legal, medical, financial, or safety-critical
  material.

## Source Index

- NotebookLM source types and limits:
  <https://support.google.com/notebooklm/answer/16215270?co=GENIE.Platform%3DDesktop&hl=en>
- NotebookLM FAQ limits and copy-protected PDF import caveat:
  <https://support.google.com/notebooklm/answer/16269187?hl=en>
- NotebookLM Audio Overview help:
  <https://support.google.com/notebooklm/answer/16212820?hl=en>
- Google Drive audio overviews for PDFs:
  <https://workspaceupdates.googleblog.com/2025/11/ai-powered-audio-overviews-for-pdfs-google-drive.html>
- Deprecated NotebookLM Enterprise Podcast API:
  <https://docs.cloud.google.com/gemini/enterprise/notebooklm-enterprise/docs/podcast-api>
- Gemini API speech generation:
  <https://ai.google.dev/gemini-api/docs/speech-generation>
- Gemini API models:
  <https://ai.google.dev/gemini-api/docs/models>
- Google Cloud Text-to-Speech pricing:
  <https://cloud.google.com/text-to-speech/pricing>
- Google SynthID:
  <https://deepmind.google/models/synthid/>
- OpenAI text-to-speech guide:
  <https://developers.openai.com/api/docs/guides/text-to-speech>
- OpenAI `gpt-4o-mini-tts` model page:
  <https://developers.openai.com/api/docs/models/gpt-4o-mini-tts>
- OpenAI realtime/audio guide:
  <https://developers.openai.com/api/docs/guides/realtime>
- OpenAI usage policies:
  <https://openai.com/policies/usage-policies/>
- ElevenLabs TTS docs:
  <https://elevenlabs.io/docs/overview/capabilities/text-to-speech>
- ElevenLabs model docs:
  <https://elevenlabs.io/docs/overview/models>
- ElevenLabs Studio create podcast API:
  <https://elevenlabs.io/docs/api-reference/studio/create-podcast>
- ElevenLabs API pricing:
  <https://elevenlabs.io/pricing/api>
- ElevenLabs prohibited-use policy:
  <https://elevenlabs.io/use-policy>
- AWS Polly overview:
  <https://docs.aws.amazon.com/polly/latest/dg/what-is.html>
- AWS Polly SSML:
  <https://docs.aws.amazon.com/polly/latest/dg/ssml.html>
- AWS Polly long-form voices:
  <https://docs.aws.amazon.com/polly/latest/dg/long-form-voices.html>
- Azure Speech REST TTS:
  <https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech>
- Azure Speech HD voices:
  <https://learn.microsoft.com/en-us/azure/ai-services/speech-service/high-definition-voices>
- Podcastfy GitHub:
  <https://github.com/souzatharsis/podcastfy>
- Podcastfy PyPI:
  <https://pypi.org/project/podcastfy/>
- Open NotebookLM:
  <https://github.com/gabrielchua/open-notebooklm>
- Together AI PDF-to-podcast walkthrough:
  <https://docs.together.ai/docs/open-notebooklm-pdf-to-podcast>
- Piper:
  <https://github.com/OHF-Voice/piper1-gpl>
- Kokoro-82M:
  <https://huggingface.co/hexgrad/Kokoro-82M>
- NVIDIA Riva TTS:
  <https://docs.nvidia.com/deeplearning/riva/user-guide/docs/tts/tts-overview.html>

## Recommended Solution

Build a SASE-native `audio_overview` xprompt workflow first, with a small optional Python helper module and provider
adapters. Use Gemini TTS as the primary provider because it is explicitly designed for controlled single-speaker and
multi-speaker podcast/audiobook-style generation. Add OpenAI TTS as the first fallback because it is simple, current,
and likely already available to many SASE users. Treat ElevenLabs as a premium opt-in provider, not the default.

Use Podcastfy as a spike/reference implementation, not as the permanent core dependency. It can validate the workflow
quickly, but SASE should own transcript generation, source-grounding, provider requests, artifact storage, and safety
defaults.

Do not target the deprecated NotebookLM Enterprise Podcast API. Keep NotebookLM and Gemini in Drive as manual
benchmarks for quality and product feel.

First milestone:

1. `#!audio_overview(source=..., provider=gemini-tts|openai-tts, style=brief|deep_dive|debate, length=short|standard)`.
2. Generate and save `transcript.json`, `transcript.md`, `overview.mp3`, and `generation_manifest.json`.
3. Attach those outputs with `sase artifact create -k file`.
4. Default to synthetic non-impersonating voices and include an AI-generated-audio disclosure.

Second milestone, only if the MVP is useful:

1. Add an `audio` artifact kind across SASE and the Rust core boundary.
2. Add ACE artifact playback/opening behavior and notification-specific audio handling.
3. Consider a first-class `sase audio generate` command after the workflow contract has settled.
