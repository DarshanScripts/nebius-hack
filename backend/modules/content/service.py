"""Member 2: grounded research, two-character dialogue and per-scene images.

Public callables: run_research, generate_dialogue, find_images. Each returns a validated
contract model or raises StageFailure. Mock mode uses fixtures/ only and never calls a provider.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from contracts.models import (
    ArtifactRef, DialogueRequest, DialogueScript, DialogueTurn, ImageBundle, ImageQuery, ImageQueryPlan,
    ImageRequest, ImageSelection, PipelineError, ResearchBundle, ResearchNotes, ResearchRequest,
    Runtime, Source, SpeakerId, StageFailure,
)

from . import checks, images, tavily

FIXTURES = Path(__file__).parent / "fixtures"
REPAIR_ROUNDS = 2
MIN_CLAIMS = 3
MAX_REPORT_CHARS = 60_000
SEARCH_CONCURRENCY = 3
CANDIDATES_PER_SCENE = 5
DOWNLOAD_DEADLINE_S = 20.0

T = TypeVar("T", bound=BaseModel)


def _fail(stage: str, code: str, message: str, retryable: bool = False) -> StageFailure:
    return StageFailure(PipelineError(code=code, stage=stage, message=message, retryable=retryable))


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _setting(runtime: Runtime, name: str, default: Any = None) -> Any:
    for key in (name, name.lower()):
        value = runtime.settings.get(key)
        if value not in (None, ""):
            return value
    return default


def _tavily_key(runtime: Runtime, stage: str) -> str:
    key = _setting(runtime, "TAVILY_API_KEY")
    if not key:
        raise _fail(stage, "TAVILY_NOT_CONFIGURED", "TAVILY_API_KEY is not set and mock mode is off")
    return str(key)


def _read_json(runtime: Runtime, key: str) -> Any | None:
    path = runtime.path(key)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


async def _structured_checked(
    runtime: Runtime, messages: list[dict[str, str]], schema: type[T], check: Callable[[T], list[str]]
) -> tuple[T, list[str]]:
    """Schema validity is Runtime.structured's job; this adds bounded repair for semantic rules."""
    result = await runtime.structured(messages=messages, schema=schema)
    for _ in range(REPAIR_ROUNDS):
        problems = check(result)
        if not problems:
            return result, []
        messages = [
            *messages,
            {"role": "assistant", "content": result.model_dump_json()},
            {"role": "user", "content": "Your JSON has these problems:\n- " + "\n- ".join(problems)
             + "\nReturn the complete corrected JSON object only."},
        ]
        result = await runtime.structured(messages=messages, schema=schema)
    return result, check(result)


# ---------------------------------------------------------------- research

def _index_sources(raw_sources: Any) -> list[Source]:
    sources: list[Source] = []
    seen: set[str] = set()
    for item in raw_sources if isinstance(raw_sources, list) else []:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        title = item.get("title") if isinstance(item.get("title"), str) and item["title"].strip() else url
        favicon = item.get("favicon") if isinstance(item.get("favicon"), str) else None
        sources.append(Source(source_id=f"src{len(sources) + 1:03d}", title=title, url=url, favicon=favicon))
    return sources


def _url_key(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}" + (f"?{parts.query}" if parts.query else "")


REFERENCE_LINE = re.compile(r"^\s*\[(\d{1,3})\]\s*[:.-]?\s*.*?(https?://\S+)", re.M)


def _report_citations(report: str, sources: list[Source]) -> dict[str, list[int]]:
    """source_id -> the report's own [n]. Tavily's sources array is NOT in the report's reference order
    (seen live: report [12] was sources[15]), so match the report's reference list by URL."""
    by_url = {_url_key(s.url): s.source_id for s in sources}
    found: dict[str, list[int]] = {}
    for n, url in REFERENCE_LINE.findall(report):
        sid = by_url.get(_url_key(url.rstrip(").,>]")))
        if sid and int(n) not in found.setdefault(sid, []):
            found[sid].append(int(n))  # the same URL can carry several reference numbers
    return found


def _to_markdown(content: Any, depth: int = 2) -> str:
    """Report is normally a string; structured content is converted explicitly (raw stays in raw.json)."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return "\n\n".join(f"{'#' * min(depth, 6)} {k}\n\n{_to_markdown(v, depth + 1)}" for k, v in content.items())
    if isinstance(content, list):
        return "\n".join(f"- {_to_markdown(v, depth + 1)}" for v in content)
    return "" if content is None else str(content)


RESEARCH_GUIDANCE = (
    "Explain how this works for ordinary end users of the product; use developer or business-API documentation "
    "only as supporting evidence unless the question is about it. "
    "Prioritize official engineering blogs, security whitepapers and relevant standards (IETF/RFCs). "
    "Clearly separate documented product behavior, general industry practice and inference. "
    "Do not state undocumented specifics (exact codecs, topology, regions, vendors) as fact; say they are unknown."
)

NOTES_SYSTEM = (
    "You turn a research report into citable claims for a 60-second educational video. "
    "Use only the sources given; every claim cites at least one of their source_ids. A report citation [n] "
    "refers to the source listed as 'report [n]'; never guess a source from list position. "
    "Write claims in plain words a curious non-engineer understands; name a technical term only when needed. "
    "evidence_type: 'documented' only when a cited source states it about this product; "
    "'general_industry_practice' for how such systems usually work; 'inference' otherwise, always with a caveat. "
    "Never present an undocumented proprietary detail (exact codec, topology, region, vendor) as documented. "
    "Write 6-12 short, concrete claims with ids c001, c002, ... and list open uncertainties. "
    "Return JSON only."
)


async def _research_notes(runtime: Runtime, topic: str, report: str, sources: list[Source]) -> ResearchNotes:
    source_ids = {s.source_id for s in sources}
    cites = _report_citations(report, sources)
    listing = "\n".join(f"{s.source_id}" + (" = report " + ", ".join(f"[{n}]" for n in cites[s.source_id]) if s.source_id in cites else "")
                        + f" | {s.title} | {s.url}" for s in sources)
    messages = [
        {"role": "system", "content": NOTES_SYSTEM},
        {"role": "user", "content": f"Topic: {topic}\n\nSources:\n{listing}\n\nReport:\n{report[:MAX_REPORT_CHARS]}"},
    ]

    def check(n: ResearchNotes) -> list[str]:
        problems = checks.claim_problems(n.claims, source_ids)
        if len(n.claims) < MIN_CLAIMS:
            problems.append(f"need at least {MIN_CLAIMS} claims")
        if not n.summary.strip():
            problems.append("summary is empty")
        return problems

    notes, _ = await _structured_checked(runtime, messages, ResearchNotes, check)
    # After bounded repair, drop any claim that still breaks grounding rules rather than publish it.
    seen: set[str] = set()
    kept = []
    for c in notes.claims:
        if c.claim_id not in seen and not checks.claim_problems([c], source_ids):
            kept.append(c)
        seen.add(c.claim_id)
    if len(kept) < MIN_CLAIMS or not notes.summary.strip():
        raise _fail("research", "RESEARCH_UNGROUNDED", f"Only {len(kept)} claims passed grounding checks", True)
    claims = [c.model_copy(update={"claim_id": f"c{i:03d}"}) for i, c in enumerate(kept, start=1)]
    return notes.model_copy(update={"claims": claims})


def _attempt_dir(runtime: Runtime, base: str) -> str:
    """Attempt 1 lives in research/, later attempts in research/attemptN/ once an earlier one failed."""
    n = 1
    while runtime.path(f"{base if n == 1 else f'{base}/attempt{n}'}/failed.json").exists():
        n += 1
    return base if n == 1 else f"{base}/attempt{n}"


async def _tavily_raw(request: ResearchRequest, runtime: Runtime, d: str) -> dict:
    """Completed raw JSON for this attempt: reuse it, resume a saved request ID, or create one."""
    raw = _read_json(runtime, f"{d}/raw.json")
    if raw is not None:
        return raw
    async with tavily.make_client(_tavily_key(runtime, "research")) as client:
        initial = _read_json(runtime, f"{d}/initial.json")
        if initial is None:
            initial = await tavily.create_research(
                client, f"{request.topic}\n\n{RESEARCH_GUIDANCE}", str(_setting(runtime, "TAVILY_RESEARCH_MODEL", "pro")))
            await runtime.write_json(f"{d}/initial.json", initial)
        try:
            raw = await tavily.poll_research(
                client, initial["request_id"],
                interval=float(_setting(runtime, "TAVILY_POLL_INTERVAL_SECONDS", 3)),
                deadline_s=float(_setting(runtime, "TAVILY_RESEARCH_TIMEOUT_SECONDS", 600)),
            )
        except StageFailure as exc:
            # Permanent failure of this request: the next retry starts a new attempt. A bad key is not the request's fault.
            if not exc.error.retryable and exc.error.code != "TAVILY_AUTH":
                await runtime.write_json(f"{d}/failed.json", {"request_id": initial["request_id"],
                                                              "error": exc.error.model_dump(mode="json")})
            raise
    await runtime.write_json(f"{d}/raw.json", raw)
    return raw


async def run_research(request: ResearchRequest, runtime: Runtime) -> ResearchBundle:
    base = f"projects/{request.project_id}/research"
    if runtime.mock_mode:
        d = base
        raw = _fixture("research_raw.json")
        await runtime.write_json(f"{d}/raw.json", raw)
    else:
        d = _attempt_dir(runtime, base)
        raw = await _tavily_raw(request, runtime, d)

    sources = _index_sources(raw.get("sources"))
    report = _to_markdown(raw.get("content")).strip()
    if not sources or not report:
        error = _fail("research", "RESEARCH_NO_SOURCES" if not sources else "RESEARCH_EMPTY",
                      "Tavily research returned no usable source URLs" if not sources else
                      "Tavily research returned an empty report", True)
        if not runtime.mock_mode:  # reusing this raw.json would fail forever; retry with a new request
            await runtime.write_json(f"{d}/failed.json", {"request_id": raw.get("request_id"),
                                                          "error": error.error.model_dump(mode="json")})
        raise error

    if runtime.mock_mode:
        notes = ResearchNotes.model_validate(_fixture("research_notes.json"))
    else:
        notes = await _research_notes(runtime, request.topic, report, sources)

    raw_ref = _ref_for(runtime, f"{d}/raw.json")
    bundle = ResearchBundle(
        project_id=request.project_id, topic=request.topic, tavily_request_id=str(
            raw.get("request_id") or (_read_json(runtime, f"{d}/initial.json") or {}).get("request_id", "")),
        summary=notes.summary, report_markdown=report, sources=sources, claims=notes.claims,
        uncertainties=notes.uncertainties, raw_response=raw_ref, is_mock=runtime.mock_mode,
    )
    problems = checks.claim_problems(bundle.claims, {s.source_id for s in sources})
    if problems:
        raise _fail("research", "RESEARCH_INVALID", "; ".join(problems))
    return bundle  # core writes research/bundle.json after its own validation


def _ref_for(runtime: Runtime, key: str) -> ArtifactRef:
    """ArtifactRef for an already-written artifact (raw.json may come from an earlier poll)."""
    data = runtime.path(key).read_bytes()
    return ArtifactRef(key=key, media_type="application/json", sha256=hashlib.sha256(data).hexdigest(),
                       size_bytes=len(data))


# ---------------------------------------------------------------- dialogue

class _TurnDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speaker_id: SpeakerId
    intent: Literal["hook", "question", "answer", "challenge", "takeaway"]
    text: str = Field(min_length=1, pattern=r"\S")
    claim_ids: list[str] = Field(default_factory=list)


class _DialogueDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    turns: list[_TurnDraft] = Field(min_length=12, max_length=12)


DIALOGUE_SYSTEM = """You write a 60-second educational dialogue for an Instagram reel.
Characters (scripted characters, not real quotations): {sundar} (speaker_id "sundar") asks skeptical,
adversarial questions; {jensen} (speaker_id "jensen") explains or challenges the premise. Both may counterargue.
Rules:
- Exactly 12 turns alternating sundar, jensen, sundar, ... (sundar first). Turns 1-2 form scene 1, 3-4 scene 2, ... 11-12 scene 6.
- 120 to 135 spoken words in total. Short hook first, then skeptical questions, concise explanations,
  at least one challenge/correction, and a closing takeaway (intent "takeaway") in turn 12.
- intent is one of hook, question, answer, challenge, takeaway. Sundar (odd turns) asks or challenges; Jensen (even turns)
  never asks a question: each Jensen turn directly answers or corrects the Sundar turn just before it.
- Only state facts found in the claims below and put their claim_ids on that turn. Every turn that is not a question
  (hook, answer, challenge, takeaway) cites at least one claim unless its text ends with "?". Keep caveats: never present an inference or unknown proprietary detail as fact.
- Audience: curious non-engineers scrolling Instagram. Plain, natural spoken sentences, never lists of terms.
  At most one technical term or acronym per turn, explained in everyday words in the same turn. 6 to 18 words per turn.
- Spoken words only: no stage directions, brackets, parentheses, emojis, speaker labels or markdown.
  Write numbers and acronyms the way they should be spoken.
- title: a short reel title (max 8 words).
Return JSON only."""


def _to_script(draft: _DialogueDraft, request: DialogueRequest) -> DialogueScript:
    return DialogueScript(
        project_id=request.project_id, script_revision=request.script_revision, title=draft.title.strip(),
        turns=[DialogueTurn(dialogue_id=f"d{i:03d}", order=i, scene_index=(i - 1) // 2 + 1,
                            speaker_id=t.speaker_id, text=t.text.strip(), intent=t.intent, claim_ids=t.claim_ids)
               for i, t in enumerate(draft.turns, start=1)],
    )


def _dialogue_messages(request: DialogueRequest) -> list[dict[str, str]]:
    names = {c.character_id: c.display_name for c in request.characters}
    r = request.research
    claims = "\n".join(f"{c.claim_id} [{c.evidence_type}] {c.text}" + (f" (caveat: {c.caveat})" if c.caveat else "")
                       for c in r.claims)
    user = (f"Topic: {r.topic}\n\nResearch summary:\n{r.summary}\n\nClaims:\n{claims}\n\n"
            f"Uncertainties:\n" + "\n".join(f"- {u}" for u in r.uncertainties))
    if request.previous_script:
        user += ("\n\nPrevious script (revise it, keep what works):\n"
                 + "\n".join(f"{t.dialogue_id} {t.speaker_id}: {t.text}" for t in request.previous_script.turns))
    if request.revision_instruction:
        user += f"\n\nRevision instruction: {request.revision_instruction}"
    system = DIALOGUE_SYSTEM.format(sundar=names.get("sundar", "Sundar Pichai"), jensen=names.get("jensen", "Jensen Huang"))
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def generate_dialogue(request: DialogueRequest, runtime: Runtime) -> DialogueScript:
    if sorted(c.character_id for c in request.characters) != ["jensen", "sundar"]:
        raise _fail("dialogue", "INVALID_CHARACTERS", "characters must be exactly sundar and jensen")
    if request.previous_script and request.script_revision <= request.previous_script.script_revision:
        raise _fail("dialogue", "INVALID_REVISION", "script_revision must be greater than previous_script's")

    if runtime.mock_mode:
        script = _to_script(_DialogueDraft.model_validate(_fixture("dialogue.json")), request)
        problems = checks.script_problems(script, request.research)
    else:
        def check(d: _DialogueDraft) -> list[str]:
            return checks.script_problems(_to_script(d, request), request.research)
        draft, problems = await _structured_checked(runtime, _dialogue_messages(request), _DialogueDraft, check)
        script = _to_script(draft, request)
    if problems:
        raise _fail("dialogue", "DIALOGUE_INVALID", "; ".join(problems[:8]), True)
    return script  # core writes script/v<rev>/script.json after its own validation


# ---------------------------------------------------------------- images

IMAGE_PLAN_SYSTEM = """You plan one web image search per scene of a 6-scene educational reel.
For each scene_index 1-6 write one specific query (4-10 words) for a clear, relevant photo or diagram that
illustrates that scene's two dialogue turns, plus a one-sentence reason. Use plain concept words, not protocol
acronyms, and always include the product or topic name so the query cannot match another meaning of a word
(write "WhatsApp call relay server diagram", not "relay diagram"). Prefer diagrams, devices and infrastructure over people or logos. dialogue_ids are that scene's two turn ids. Return JSON only."""


def _scene_ids(script: DialogueScript, index: int) -> list[str]:
    return [t.dialogue_id for t in script.turns if t.scene_index == index]


def _normalize_plan(plan: ImageQueryPlan, script: DialogueScript) -> list[ImageQuery]:
    return [q.model_copy(update={"dialogue_ids": _scene_ids(script, q.scene_index)})
            for q in sorted(plan.queries, key=lambda q: q.scene_index)]


async def _plan_queries(request: ImageRequest, runtime: Runtime) -> list[ImageQuery]:
    script = request.script
    scenes = "\n".join(f"scene {i}: " + " / ".join(f"{t.dialogue_id} {t.speaker_id}: {t.text}"
                                                    for t in script.turns if t.scene_index == i) for i in range(1, 7))
    user = f"Topic: {request.research.topic}\nSummary: {request.research.summary}\n\nScenes:\n{scenes}"
    messages = [{"role": "system", "content": IMAGE_PLAN_SYSTEM}, {"role": "user", "content": user}]

    def check(p: ImageQueryPlan) -> list[str]:
        return [] if sorted(q.scene_index for q in p.queries) == [1, 2, 3, 4, 5, 6] else \
            ["queries must cover scene_index 1-6 exactly once"]
    try:
        plan, problems = await _structured_checked(runtime, messages, ImageQueryPlan, check)
        if not problems:
            return _normalize_plan(plan, script)
        why = "; ".join(problems)
    except StageFailure as exc:
        why = f"{exc.error.code}: {exc.error.message}"
    # Planning is a nicety; fall back to queries built from the scene text instead of failing images.
    # The reason lands in plan.json via ImageQuery.reason so a weak image run can be explained afterwards.
    topic = request.research.topic.rstrip("?. ")
    return [ImageQuery(scene_index=i, dialogue_ids=_scene_ids(script, i),
                       query=f"{topic} {next(t.text for t in script.turns if t.scene_index == i and t.speaker_id == 'jensen')}"[:300],
                       reason=f"Deterministic fallback query; planning failed: {why}"[:500])
            for i in range(1, 7)]


async def _search(query: ImageQuery, runtime: Runtime, base: str, client) -> list[images.Candidate] | str:
    """Candidates for one scene, or the reason there are none."""
    try:
        result = await tavily.search_images(client, query.query)
    except StageFailure as exc:
        return f"search failed: {exc.error.message}"
    await runtime.write_json(f"{base}/search/s{query.scene_index:02d}.json", result)
    return images.candidates(result)[:CANDIDATES_PER_SCENE] or "no image results"


class _SceneRank(BaseModel):
    scene_index: int = Field(ge=1, le=6)
    ranked: list[int] = Field(default_factory=list,
                              description="Fitting candidates, best first, using the 1-based [k] numbers shown; [] if none fits")


class _ImageRanking(BaseModel):
    scenes: list[_SceneRank]


RANK_SYSTEM = """You choose images for scenes of an educational reel. For each scene you get its dialogue and
numbered candidate images (descriptions from a search engine). Return, per scene_index, the fitting candidates'
1-based [k] numbers, best first. A candidate fits when it is about this topic (this product's calls, devices or
infrastructure) and does not contradict the scene; a general on-topic diagram fits when nothing more specific exists.
Reject only: other meanings of a word (an electrical relay, an office phone system), stock photos of people, logos,
and screenshots of unrelated apps. Most scenes should get at least one image; return [] only when every candidate is
off-topic. Return JSON only."""


async def _rank(runtime: Runtime, request: ImageRequest, cands: dict[int, list[images.Candidate]]) -> dict[int, list[int]]:
    """One LLM call per project re-orders each scene's candidates by relevance. On failure: Tavily's order."""
    blocks = []
    for i, cs in cands.items():
        lines = " / ".join(t.text for t in request.script.turns if t.scene_index == i)
        listing = "\n".join(f"  [{k}] {c.description or 'no description'} ({urlsplit(c.image_url).hostname})"
                            for k, c in enumerate(cs, start=1))
        blocks.append(f"scene {i}: {lines}\n{listing}")
    messages = [{"role": "system", "content": RANK_SYSTEM},
                {"role": "user", "content": f"Topic: {request.research.topic}\n\n" + "\n\n".join(blocks)}]
    try:
        ranking = await runtime.structured(messages=messages, schema=_ImageRanking)
    except StageFailure:
        return {i: list(range(len(cs))) for i, cs in cands.items()}
    given = {r.scene_index: r.ranked for r in ranking.scenes}
    order = {}
    for i, cs in cands.items():
        if i not in given:  # model skipped the scene: keep search order rather than guess "none"
            order[i] = list(range(len(cs)))
        else:
            order[i] = list(dict.fromkeys(k - 1 for k in given[i] if 1 <= k <= len(cs)))
    return order


async def _download_first(query: ImageQuery, cands: list[images.Candidate], runtime: Runtime, base: str,
                          client) -> ImageSelection:
    tried = []
    for cand in cands:
        try:
            img, why = await asyncio.wait_for(images.download(client, cand.image_url), DOWNLOAD_DEADLINE_S)
        except asyncio.TimeoutError:
            img, why = None, "download timed out"
        if img is None:
            tried.append(why)
            continue
        asset = await runtime.write_bytes(f"{base}/s{query.scene_index:02d}.{img.ext}", img.data, img.media_type)
        return ImageSelection(query=query, status="selected", asset=asset, image_url=cand.image_url,
                              source_page_url=cand.source_page_url, description=cand.description)
    reason = "no relevant image among search results" if not tried else "no usable image: " + "; ".join(tried)
    return ImageSelection(query=query, status="unavailable", reason=reason[:500])


def _mock_png(index: int) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (800, 600), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    for x in range(12, 800, 24):
        for y in range(12, 600, 24):
            draw.point((x, y), fill="#D8DEE8")
    draw.rectangle((80, 200, 300, 400), outline="#2563EB", width=6)
    draw.rectangle((500, 200, 720, 400), outline="#16A34A", width=6)
    draw.line((300, 300, 500, 300), fill="#EA580C", width=6)
    draw.text((80, 80), f"MOCK image - scene {index} (fixture, not a search result)", fill="#111827")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def find_images(request: ImageRequest, runtime: Runtime) -> ImageBundle:
    rev = request.script.script_revision
    base = f"projects/{request.project_id}/images/v{rev}"
    if runtime.mock_mode:
        queries = _normalize_plan(ImageQueryPlan.model_validate(_fixture("image_plan.json")), request.script)
        selections = []
        for q in queries:
            if q.scene_index == 4:  # fixture: one unavailable scene exercises member 4's vector fallback
                selections.append(ImageSelection(query=q, status="unavailable", reason="MOCK: no usable image in fixture"))
                continue
            asset = await runtime.write_bytes(f"{base}/s{q.scene_index:02d}.png", _mock_png(q.scene_index), "image/png")
            selections.append(ImageSelection(
                query=q, status="selected", asset=asset, image_url=f"https://example.com/mock-image-s{q.scene_index:02d}.png",
                description="MOCK generated placeholder diagram (fixture, not a search result)"))
    else:
        key = _tavily_key(runtime, "images")
        # Artifacts are immutable and live output differs per run, so every live attempt gets a fresh folder.
        n = 1
        while runtime.path(f"{base}/a{n}/plan.json").exists():
            n += 1
        base = f"{base}/a{n}"
        queries = await _plan_queries(request, runtime)
        await runtime.write_json(f"{base}/plan.json", {"queries": [q.model_dump(mode="json") for q in queries]})
        sem = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def guarded(coro):
            async with sem:
                try:
                    return await coro
                except Exception as exc:  # one scene's failure must not sink the other five
                    return f"{type(exc).__name__}: {exc}"[:500]

        async with tavily.make_client(key) as search_client, images.make_client() as dl_client:
            found = await asyncio.gather(*(guarded(_search(q, runtime, base, search_client)) for q in queries))
            cands = {q.scene_index: c for q, c in zip(queries, found) if isinstance(c, list)}
            order = await _rank(runtime, request, cands) if cands else {}
            await runtime.write_json(f"{base}/ranking.json", {str(i): o for i, o in order.items()})
            picked = await asyncio.gather(*(
                guarded(_download_first(q, [cands[q.scene_index][k] for k in order[q.scene_index]],
                                           runtime, base, dl_client))
                for q in queries if q.scene_index in cands))
        by_scene = {s.query.scene_index: s for s in picked if isinstance(s, ImageSelection)}
        reasons = dict(zip((q.scene_index for q in queries if q.scene_index in cands), picked))
        reasons.update({q.scene_index: c for q, c in zip(queries, found) if isinstance(c, str)})
        selections = [by_scene.get(q.scene_index) or ImageSelection(query=q, status="unavailable",
                                                                    reason=str(reasons[q.scene_index]))
                      for q in queries]

    bundle = ImageBundle(project_id=request.project_id, script_revision=rev, selections=selections)
    problems = checks.image_problems(bundle, request.script)
    if problems:
        raise _fail("images", "IMAGES_INVALID", "; ".join(problems))
    await runtime.write_json(f"{base}/bundle.json", bundle.model_dump(mode="json"))
    return bundle
