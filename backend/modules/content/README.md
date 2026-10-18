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
| `run_research` | `POST /research` (`input`, `TAVILY_RESEARCH_MODEL`, `stream:false`), saves `initial.json` with the `request_id`, polls `GET /research/{id}` (`pending`/`in_progress`/`processing` = running; unknown status = error). Indexes source URLs as `src001…`, then Nemotron turns the report into `ResearchNotes` claims against those IDs. | `projects/<id>/research/{initial,raw,bundle}.json` |
| `generate_dialogue` | Nemotron writes 12 turns; ids/order/scene are assigned in code. Checked: alternating Sundar-first speakers, valid claim IDs, every `answer` cites a claim, no stage directions, 120–135 words (110–145 accepted). Up to 2 repair rounds with the exact problems. Supports `previous_script` + `revision_instruction`. | `projects/<id>/script/v<rev>/script.json` |
| `find_images` | Nemotron `ImageQueryPlan` (one query per scene; `dialogue_ids` overwritten from the script; deterministic fallback queries if planning fails). Tavily `/search` with `include_images` + `include_image_descriptions`, all six queries, ≤3 concurrent. Downloads the first usable candidate. | `projects/<id>/images/v<rev>/{plan.json,search/sNN.json,sNN.<png\|jpg\|webp>,bundle.json}` |

### Grounding and safety rules implemented
- Claims citing unknown sources or `inference` without a caveat are sent back for repair, and dropped if still invalid; fewer than 3 valid claims → `RESEARCH_UNGROUNDED`. Claim IDs are renumbered `c001…`.
- Research prompt asks for official engineering/security docs and standards, separates documented / industry practice / inference, and forbids stating undocumented codec/topology/region/vendor as fact.
- Tavily: network/429/5xx retried 4× with backoff, `Retry-After` honoured (capped 60 s); 401/403 → `TAVILY_AUTH`, other 4xx → `TAVILY_BAD_REQUEST`, both immediate.
- **Resume:** a retry with `initial.json` but no `raw.json` resumes polling that `request_id` (no new paid request). Poll deadline → retryable `TAVILY_RESEARCH_TIMEOUT`. Completed `raw.json` is reused. A permanent failure (Tavily `failed`, unknown status, no sources or empty report; not a 401) writes `failed.json`, so the next retry uses `research/attempt2/`.
- Images: http(s) only; every hop (redirects followed manually, max 3) must resolve to public IPs only; 8 MB cap, 20 s total per download; must decode with Pillow as PNG/JPEG/WebP ≥200 px (SVG/GIF rejected). `source_page_url` is only set if Tavily returned one — never invented. Failed scenes are `status:"unavailable"` with a reason; one scene's failure never affects the others.

### Mock mode (`runtime.mock_mode`)
Fixtures in `fixtures/` only, no provider or LLM calls: `src001/src002` "Mock…" sources on example.com, claims `c001…c006` marked as demonstration data, 12 turns (133 words, answers cite `c001…c006`), `is_mock: true`, and image selections for scenes 1,2,3,5,6 (generated, labelled "MOCK" PNGs) with scene 4 `unavailable` to exercise the vector fallback.

## Commands

```bash
uv venv .venv --python 3.11 && uv pip install --python .venv/bin/python pydantic httpx pillow pytest langchain-openai
export PYTHONPATH="$PWD/.bootstrap:$PWD"     # drop .bootstrap once contracts/models.py is on main

python -m backend.modules.content.demo --mock --output output/demos/content     # fixtures only
python -m pytest backend/modules/content/tests -q                                # 17 tests
python -m backend.modules.content.demo --output output/demos/content --topic "How does WhatsApp voice calling infrastructure work?"   # live
```

The live demo reads root `.env` (`TAVILY_*`, `NEMOTRON_BASE_URL`, `NEMOTRON_API_KEY`, `NEMOTRON_MODEL`) and uses a small local `DemoRuntime` (json_prompt + `model_validate_json`, 2 corrective attempts). Rerunning after an interruption resumes the saved Tavily request ID.

## Results (2026-10-18)
- Mock demo: 2 sources, 6 claims, 12 alternating turns / 133 words in six scenes, 5 selected images + 1 unavailable; artifacts written under `output/demos/content/projects/demo-whatsapp-001/`.
- `pytest`: 17 passed — redirect-to-metadata-IP refusal; permanent failures (no sources, unknown status) start a new attempt while a 401 keeps the request for resume; mock pipeline; live research polling (`in_progress`→`processing`→`completed`), structured-content conversion, source dedupe, claim repair; resume without new POST; retryable timeout; failed-attempt directory; unknown status / 401; 429 + `Retry-After`; dialogue repair + revision + failure; SSRF refusals (loopback, RFC1918, metadata IP, file://) and decode checks; live image selection with a search error and an undecodable candidate.

## Notes for member 1 (integration)
- Settings are read from `runtime.settings` by env name (`TAVILY_API_KEY`, `TAVILY_RESEARCH_MODEL`, `TAVILY_POLL_INTERVAL_SECONDS`, `TAVILY_RESEARCH_TIMEOUT_SECONDS`); lowercase keys also work.
- `runtime.path(key)` is used to check/read existing artifacts (resume), so it must work for keys that do not exist yet.
- `runtime.structured` is never called in mock mode.
- Not a contract change, just a suggestion: `ResearchRequest` has no `job_id`, so research polling does not call `report_progress`.
- No shared-contract changes were needed.

## Blockers / not verified
- **No live run yet**: there are no Tavily/NVIDIA keys in this checkout. The live HTTP paths are tested only against mocked transports. The real Nemotron structured output and Tavily response shapes still need one live run (the command above).
- Image relevance is Tavily's ranking order (first usable candidate). There is no vision re-ranking.
