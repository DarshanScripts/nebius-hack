# Content module (member 2): research, dialogue, images

Owner: member 2, branch `feat/m2-research-dialogue`. Only `backend/modules/content/` is touched.

## Interfaces (`service.py`)

```python
async def run_research(request: ResearchRequest, runtime: Runtime) -> ResearchBundle
async def generate_dialogue(request: DialogueRequest, runtime: Runtime) -> DialogueScript
async def find_images(request: ImageRequest, runtime: Runtime) -> ImageBundle
```

Each returns a validated contract model or raises `StageFailure(PipelineError)`. Imports only `contracts.models`.
LLM calls go through `runtime.structured(...)` (configured Nemotron endpoint); no provider/model is hardcoded here.

| Callable | Live behaviour | Artifacts (under `ARTIFACT_ROOT`) |
| --- | --- | --- |
| `run_research` | `POST /research` (`input`, `TAVILY_RESEARCH_MODEL`, `stream:false`), saves `initial.json` with the `request_id`, polls `GET /research/{id}` (`pending`/`in_progress`/`processing` = running; unknown status = error). Indexes source URLs as `src001…`; the report's own `[n]` reference list is matched to sources **by URL** (live finding: Tavily's `sources` array is not in the report's citation order), then Nemotron turns the report into `ResearchNotes` claims against those IDs. | `projects/<id>/research/[attemptN/]{initial,raw,failed}.json` (core writes `research/bundle.json`) |
| `generate_dialogue` | Nemotron writes 12 turns; ids/order/scene are assigned in code. Checked: alternating Sundar-first speakers, Jensen never asks (each even turn answers/corrects the previous one), at most one acronym per turn, valid claim IDs, every non-question turn cites a claim unless it ends with `?` (same rule as core's `validate_script`), no stage directions, 120–135 words (110–145 accepted). Up to 2 repair rounds with the exact problems. Supports `previous_script` + `revision_instruction`. | none (core writes `script/v<rev>/script.json`) |
| `find_images` | Nemotron `ImageQueryPlan` (one query per scene; `dialogue_ids` overwritten from the script; deterministic fallback queries if planning fails). Tavily `/search` with `include_images` + `include_image_descriptions`, all six queries, ≤3 concurrent. Then **one** Nemotron call ranks all candidates per scene (1-based numbers): on-topic diagrams fit, other meanings of a word (electrical relay), stock people, logos and unrelated-app screenshots are rejected; an empty list means "no image" → member 4's vector fallback; on ranking failure Tavily order is used. If query planning fails, deterministic topic+sentence queries are used and the reason is recorded in `plan.json`. Downloads the first usable ranked candidate; decoding runs in a worker thread. Each live attempt gets a fresh `aN/` folder because artifacts are immutable. | `projects/<id>/images/v<rev>/aN/{plan.json,search/sNN.json,sNN.<png\|jpg\|webp>,bundle.json}` plus `ranking.json` (mock: `images/v<rev>/`) |

### Grounding and safety rules implemented
- Claims citing unknown sources or `inference` without a caveat are sent back for repair, and dropped if still invalid; fewer than 3 valid claims → `RESEARCH_UNGROUNDED`. Claim IDs are renumbered `c001…`.
- Research prompt asks for official engineering/security docs and standards, separates documented / industry practice / inference, and forbids stating undocumented codec/topology/region/vendor as fact.
- Tavily: network/429/5xx retried 4× with backoff, `Retry-After` honoured (capped 60 s); 401/403 → `TAVILY_AUTH`, other 4xx → `TAVILY_BAD_REQUEST`, both immediate.
- **Resume:** a retry with `initial.json` but no `raw.json` resumes polling that `request_id` (no new paid request). Poll deadline → retryable `TAVILY_RESEARCH_TIMEOUT`. Completed `raw.json` is reused. A permanent failure (Tavily `failed`, unknown status, no sources or empty report; not a 401) writes `failed.json`, so the next retry uses `research/attempt2/`.
- Images: http(s) only; every hop (redirects followed manually, max 3) must resolve to public IPs only; 8 MB cap, 20 s total per download; must decode with Pillow as PNG/JPEG/WebP ≥200 px (SVG/GIF rejected). `source_page_url` is only set if Tavily returned one — never invented. Failed scenes are `status:"unavailable"` with a reason; one scene's failure never affects the others.

### Mock mode (`runtime.mock_mode`)
Fixtures in `fixtures/` only, no provider or LLM calls: `src001/src002` "Mock…" sources on example.com, claims `c001…c006` marked as demonstration data, 12 turns (132 words, answers cite `c001…c006`), `is_mock: true`, and image selections for scenes 1,2,3,5,6 (generated, labelled "MOCK" PNGs) with scene 4 `unavailable` to exercise the vector fallback.

## Commands

```bash
uv sync --python 3.11 && uv pip install pillow            # pillow: see TODO for member 1
export PYTHONPATH="$PWD"

python -m backend.modules.content.demo --mock --output output/demos/content     # fixtures only, no keys
python -m pytest backend/modules/content/tests -q                                # 22 tests
python -m backend.modules.content.demo --output output/demos/content --project-id live-001 \
    --topic "How does WhatsApp voice calling infrastructure work?"               # live; needs TAVILY_API_KEY + NEMOTRON_API_KEY in .env
```

Rerunning the live demo with the same `--project-id` reuses the saved research bundle and script (no Tavily or Nemotron calls for those stages, exactly as core does) and only regenerates images into a fresh `aN/` folder.

The live demo reads root `.env` (`TAVILY_*`, `NEMOTRON_BASE_URL`, `NEMOTRON_API_KEY`, `NEMOTRON_MODEL`) and uses a small local `DemoRuntime` (json_prompt + `model_validate_json`, 2 corrective attempts; refuses to overwrite artifacts with different bytes, like core's `AppRuntime`). Rerunning after an interruption resumes the saved Tavily request ID.

## Results (2026-10-18)
- **Live runs (real Tavily `pro` + Nemotron `nvidia/nemotron-3.5-super-vl-120b-a12b`, 3 projects):** 10–15 real sources (WhatsApp security whitepaper, engineering.fb.com, developers.facebook.com, faq.whatsapp.com), 11–12 grounded `documented` claims each citing the correct URL, 12 turns / 129–133 words of plain-language dialogue, 5–6 relevant topic-specific images (one scene correctly marked `unavailable` by the ranker). Resume verified: run 3 reused run 2's saved `initial.json`/`raw.json`. Model listed by `/v1/models`; replies carry `reasoning_content` separately and clean JSON in `content`. One transient NVIDIA HTTP 500 was observed → SDK retries (3) added. A real Tavily response is saved as `fixtures/tavily_live_sample.json` for regression tests (report text only, no credentials).
- **Image reruns on project 3 (same script):** `a1` 5/6 selected; `a2` 2/6 after a transient planning failure fell back to crude queries and a too-strict ranker (now: reason recorded, ranker accepts on-topic general diagrams); `a3` 6/6 on-topic (end-to-end encryption, security codes, encrypted audio path, relay data centers, the "Protect IP address in calls" setting).
- **After merging seed `d3dfba6`:** no `.bootstrap` needed; 22 content tests + 10 core tests pass; core `Coordinator` with this module completes research → dialogue → images → voice → timeline `[0,273,543,813,1083,1353,1800]` and stops only at `MODULE_UNAVAILABLE` for scenes.
- **Integration with `origin/feat/m1-platform` (d3dfba6)**: module copied into that branch: my 20 tests + core's 10 pass; the mock outputs pass core's `validate_research`/`validate_script`/`validate_images`/`validate_artifacts` through `AppRuntime`; a live-mode image retry under the immutable `AppRuntime` succeeds; core's `Coordinator` with this module (voice from core fixtures) completes research → dialogue → images → voice → timeline `[0,273,543,813,1083,1353,1800]` and stops only at `MODULE_UNAVAILABLE` for scenes (member 4 not merged).
- Mock demo: 2 sources, 6 claims, 12 alternating turns / 132 words in six scenes, 5 selected images + 1 unavailable; artifacts written under `output/demos/content/projects/demo-whatsapp-001/`.
- `pytest`: 22 passed — real-Tavily citation mapping; acronym and Jensen-question repair; ranker "no relevant image" / skipped scene / failed call paths; live image retry in a fresh folder; core claim rule triggers repair; citation numbers survive source dedupe; redirect-to-metadata-IP refusal; permanent failures (no sources, unknown status) start a new attempt while a 401 keeps the request for resume; mock pipeline; live research polling (`in_progress`→`processing`→`completed`), structured-content conversion, source dedupe, claim repair; resume without new POST; retryable timeout; failed-attempt directory; unknown status / 401; 429 + `Retry-After`; dialogue repair + revision + failure; SSRF refusals (loopback, RFC1918, metadata IP, file://) and decode checks; live image selection with a search error and an undecodable candidate.

## Notes for member 1 (integration)
- Settings are read from `runtime.settings` by env name (`TAVILY_API_KEY`, `TAVILY_RESEARCH_MODEL`, `TAVILY_POLL_INTERVAL_SECONDS`, `TAVILY_RESEARCH_TIMEOUT_SECONDS`); lowercase keys also work.
- `runtime.path(key)` is used to check/read existing artifacts (resume), so it must work for keys that do not exist yet.
- `runtime.structured` is never called in mock mode.
- Not a contract change, just a suggestion: `ResearchRequest` has no `job_id`, so research polling does not call `report_progress`.
- No shared-contract changes were needed.
- **Please add `pillow>=11` to `pyproject.toml`** (listed in `dependencies.txt`). PIL is imported lazily, so research and dialogue still load without it, but image decoding needs it.
- Core owns `research/bundle.json` and `script/v<rev>/script.json`; this module no longer writes them, so retries never collide with immutable artifacts.

## TODO / blockers
- [ ] **Member 1:** add `pillow>=11` to root `pyproject.toml` (`uv add pillow`) — image decoding needs it; without it `find_images` fails with `MODULE_UNAVAILABLE`-style import error while research/dialogue still work.
- [ ] **Member 1:** merge this branch; core already writes `research/bundle.json` and `script/v<rev>/script.json`, this module does not.
- [ ] **After member 3 merges:** first real voice run decides whether 129–133 words fit 53.3 s of Chatterbox speech. If `AUDIO_DURATION_OUT_OF_RANGE` keeps triggering the one-shot shorten pass, lower the prompt target (`MIN_WORDS/MAX_WORDS` in `checks.py`, "120 to 135" in `DIALOGUE_SYSTEM`).
- [ ] **After member 4 merges:** confirm scene agents use `ImageSelection.description` + `asset`, and that `unavailable` draws the vector diagram.
- [ ] Not tested (no key/URL for it): nothing in this module needs the voice/alignment/render keys. All content-stage keys (`TAVILY_API_KEY`, `NEMOTRON_*`) are present and verified live.
- Known limits: image relevance is judged from Tavily's text descriptions, not pixels; research `pro` takes 2–5 min per topic (set `TAVILY_RESEARCH_MODEL=mini` for faster, shallower demos).
