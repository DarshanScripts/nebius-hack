# Project context: grounded research to an editable educational reel

Read this file and `plan.md` before coding. The team will tell you your member number, 1–5. Implement only that member's assigned files and interfaces. `plan.md` contains the contracts, ownership rules, branch names, and acceptance criteria.

## What we are building

A hackathon application turns a topic into a one-minute educational Instagram reel. Example: **“How does WhatsApp voice calling infrastructure work?”** A Python backend researches the topic with Tavily Deep Research, then NVIDIA Nemotron generates a grounded conversation between two characters. A voice adapter produces their audio and aligned transcripts. Independent Nemotron agents generate animated Remotion scenes. The user previews scenes, requests changes to an individual scene through a message, and presses **Stitch** to render the final video on Nebius Cloud.

The speakers are **Sundar Pichai** and **Jensen Huang**. These are scripted characters in a generated discussion, not quotations from an actual conversation. One asks skeptical or adversarial questions, and the other answers or challenges the premise. Both can counterargue. Ground factual statements in the research and preserve uncertainty about proprietary infrastructure.

We have **five people, five coding agents, and an original five-hour build window**. Member 1 is the project owner and maintains `main`. Members develop on five separate branches and submit their changes for merging into `main`. Planning/configuration files exist; application modules are still to be implemented. The owner has created the Nebius VM; it is awaiting Running status and IP assignment. Everyone can begin against fixtures immediately.

## Product flow

1. A collapsible left sidebar lists projects/reels and has a **New** button.
2. New opens a topic input in the center workspace. Submitting starts the pipeline.
3. The center conversation/activity pane first shows a collapsible research result and sources.
4. It then displays dialogue turns, followed by audio, transcription, and timestamp information as those become available.
5. The right pane has six ordered scene slots immediately. Each preview appears as soon as it is ready, even if scenes finish out of order.
6. A message such as “Please correct scene six: make the packet diagram clearer” updates only that scene. It keeps its audio, duration, boundary states, and position in the reel.
7. **Stitch** composes the latest ready scenes, audio, captions, and animated character images into one MP4. Show rendering progress. The final file is saved under `output/`; a download link is sufficient. An embedded final-video player is optional.

The uploaded sketches illustrate this workspace and these stages. They are workflow guidance, not a pixel-perfect frontend design specification.

## Fixed visual and timing choices

- Video: **1080 × 1920**, **9:16**, **30 fps**, **1800 frames / 60 seconds**.
- Six scenes for the hackathon version, with durations allocated after audio is generated. Scene length is not fixed at ten seconds.
- White background with a subtle **dot grid**, not ruled or connected grid lines.
- Top 70%: animated workboard, title, and captions. Bottom 30%: transparent character PNGs that slide in/out according to the speaking turns.
- One shared theme, layout, animation vocabulary, and persistent character layer across the whole video.
- Use React + Vite + TypeScript and ordinary CSS for the editor. Use FastAPI/Python for the backend. Remotion requires a small Node/TypeScript rendering service.
- Use Remotion frame-based animations. GSAP is unnecessary for this version.

## Pipeline and independence

```text
Topic
  → Tavily research
  → Nemotron structured dialogue
  → Nemotron image-query planning + Tavily image search
  → Voice synthesis/voice clone adapter + measured word alignment
  → Deterministic global timeline and scene boundaries
  → Independent Nemotron scene agents, running concurrently
  → Individual scene previews, published progressively
  → Targeted scene revisions
  → Final Remotion composition/render on Nebius Cloud
```

Runtime stages have real data dependencies. **Team implementation does not need to wait for those stages:** everyone builds against the frozen schemas and deterministic mock fixtures in `plan.md`. Scene agents share an immutable context, theme, and boundary contract. They do not exchange messages or edit each other's files. A small Python scheduler calls stages and publishes state; there is no supervisor LLM or additional orchestration agent.

Use LangChain structured output for dialogue, image-query planning, and edit routing. Use LangChain `create_agent` for each scene's tool-using generation/repair loop. Do not add a second LangGraph workflow merely to connect the stages. The selected text endpoint is **`https://integrate.api.nvidia.com/v1`**, model **`nvidia/nemotron-3.5-super-vl-120b-a12b`**. Member 1 checks actual tool/schema capabilities before enabling that strategy. Read `NEMOTRON_*` configuration; do not hardcode another provider/model in a module.

## Assets the owner will add

```text
assets/characters/sundar.png
assets/characters/jensen.png
assets/voices/sundar/reference.wav
assets/voices/sundar/reference.txt
assets/voices/jensen/reference.wav
assets/voices/jensen/reference.txt
```

Character images should have transparent backgrounds. Voice reference text is the exact transcript of its matching reference WAV when the chosen model needs it. A provider voice ID can replace reference audio if supported. Member 3 owns that mapping. Do not change character IDs `sundar` and `jensen`.

**Selected voice stack: Chatterbox Turbo + WhisperX, self-hosted on a Nebius GPU VM.** Existing Sundar Pichai and Jensen Huang audio samples condition Chatterbox directly; separate voice-model training and hosted voice IDs are unnecessary for this version. Member 3 provides a Chatterbox FastAPI container on port 8002 and a separate WhisperX container on port 8003. These are our application endpoints, not Nebius Token Factory speech routes.

**Word timestamps are mandatory.** Chatterbox generates each WAV; normalize/finalize the audio, then WhisperX forced-aligns the known dialogue transcript to that exact WAV. Return every alignable spoken word with `word_id`, `text`, clip-local `start_ms`, and `end_ms`. Validate coverage and fail/retry if meaningful words cannot be aligned. Full Whisper transcription is optional for quality checking; speaker diarization is unnecessary because we already know the speaker per clip. Scene animation and captions use these measured word times, not estimates from text length.

## Cloud and configuration

**Use the single created Nebius GPU VM for all five containers:** `web`, `api`, `renderer`, `chatterbox`, and `whisperx`. The API/renderer use CPU resources and share an artifact volume; only the two speech containers need GPU access. Nemotron inference uses the selected NVIDIA hosted API. Speech WAVs move over authenticated internal HTTP calls, keeping module contracts decoupled. Serialize speech pipelines initially. Browser preview playback remains in the frontend. The Stitch button triggers real Remotion rendering/encoding on this VM.

### Created VM and deployment handoff

| Setting | Owner-provided value |
| --- | --- |
| Final review VM name | `cyan-ape-instance-8` |
| Project | `group08-project` / `project-e05mfttbln00ypf4h123rz` |
| Region | `uk-south2` |
| Platform / preset | `gpu-rtx6000-a` / `1gpu-24vcpu-218gb` |
| GPU | NVIDIA RTX PRO 6000, 96 GB GPU memory |
| Host CPU / RAM | 24 vCPUs / 218 GiB RAM |
| Boot image | `ubuntu24.04-cuda13.0` |
| Boot disk | 1.25 TiB SSD, encrypted |
| SSH username | **`orange_whisky`**, not `ubuntu` |
| Subnet | `vpcsubnet-e05xggeet8sf02btby` |
| Security group | `vpcsecuritygroup-e05s1hk66ypwqtswpn` |
| Attached service account | `group08-sa` |
| IP addresses | Pending; no public/private IP has been supplied yet |

An earlier Terraform preview used `maroon-carp-instance-6`; the final review used `cyan-ape-instance-8`. Member 1 verifies the existing VM's name/ID in the console when it becomes ready. **Do not run that old Terraform snippet to create a second VM.** The generated owner-only SSH key is `.ssh/nebius_reel_ed25519`; its path is in the owner's ignored `.env`. No credentials/private key belong in the files shared with teammates.

The RTX PRO 6000 is Blackwell: member 3 must choose PyTorch/CUDA binaries that support this GPU and lock compatible dependencies independently for Chatterbox and WhisperX. Host CUDA 13 does not automatically make an old package's bundled CUDA kernels compatible. Verify actual GPU inference inside each container before serving it. Member 1 owns host setup/deployment; teammates do not need VM access or real API keys to start fixture-based implementation.

Use root `.env.example` as the configuration reference. Root `.env` is a local, ignored template with empty credentials and mock mode enabled. No keys have been supplied. The frontend receives only the public API URL. There is no requirement to provision Kubernetes, queues, or object storage for the five-hour version.

## Team map

| Member | Branch | Responsibility |
| --- | --- | --- |
| 1, owner | `feat/m1-platform` | Shared contracts/runtime, FastAPI, persistence, scheduler, timeline, Nebius deployment, main integration |
| 2 | `feat/m2-research-dialogue` | Tavily research, Nemotron dialogue, image queries/search, grounded content bundle |
| 3 | `feat/m3-voice-alignment` | Voice adapter, normalized WAVs, transcripts, real timestamps |
| 4 | `feat/m4-scenes-renderer` | Scene agents, edit router, Remotion components/worker, preview and final rendering |
| 5 | `feat/m5-editor-ui` | Frontend editor, project list, activity/dialogue pane, ordered progressive previews and edit/Stitch UX |

Each member owns a disjoint directory. Only member 1 edits shared contracts and root manifests. See `plan.md` for the exact file map and callable interfaces. Do not create five different backends or five different contract definitions.

## Existing repository context and references

The repository initially contains `README.md`, plus the earlier `req.md` and `reqc.md` research notes. `reqc.md` shows illustrative Tavily initial/completed JSON, not a live response. Use `plan.md` as the application contract; raw provider JSON is stored separately and normalized before use.

- [Reference project: infra_peter](https://github.com/aditya-ladawa/infra_peter): inspiration for research-to-reel flow. Its README describes a Python/LangGraph reel pipeline. Reuse specific ideas only after checking the actual file; do not import its whole architecture or assume its provider integrations match ours.
- [Tavily research](https://docs.tavily.com/documentation/api-reference/endpoint/research), [result polling](https://docs.tavily.com/documentation/api-reference/endpoint/research-get), [image search options](https://docs.tavily.com/documentation/api-reference/endpoint/search).
- [LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output), [agents](https://docs.langchain.com/oss/python/langchain/agents).
- [Nebius Token Factory quickstart](https://docs.tokenfactory.nebius.com/quickstart), [inference API](https://api.tokenfactory.nebius.com/docs).
- [Chatterbox Turbo](https://github.com/resemble-ai/chatterbox), [WhisperX](https://github.com/m-bain/whisperX), [known-transcript alignment](https://github.com/m-bain/whisperX/issues/939).
- [Remotion Docker rendering](https://www.remotion.dev/docs/docker), [deterministic animations](https://www.remotion.dev/docs/flickering).

## Scope boundary

The demo must cover topic → grounded research → dialogue → audio/timing → concurrent editable scenes → final one-minute MP4. Prioritize this complete path. Authentication, billing, publishing to Instagram, arbitrary video lengths, lip sync, music, adaptive themes, collaborative editing, and production infrastructure are outside the five-hour scope.

When a live provider is unavailable, return a clear stage error and preserve completed work. Mock mode is explicit and must never silently impersonate a live research or voice result.
