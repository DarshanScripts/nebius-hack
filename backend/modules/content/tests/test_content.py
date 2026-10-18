"""Run: PYTHONPATH="$PWD/.bootstrap:$PWD" .venv/bin/python -m pytest backend/modules/content/tests -q"""
import asyncio
import io
import json

import httpx
import pytest
from PIL import Image

from contracts.models import (
    DialogueRequest, ImageRequest, ResearchNotes, ResearchRequest, StageFailure,
)
from backend.modules.content import checks, images, service, tavily
from backend.modules.content.demo import CHARACTERS, DemoRuntime

PID = "demo-whatsapp-001"
TOPIC = "How does WhatsApp voice calling infrastructure work?"
SETTINGS = {"TAVILY_API_KEY": "test", "TAVILY_POLL_INTERVAL_SECONDS": "0", "TAVILY_RESEARCH_TIMEOUT_SECONDS": "5"}


def runtime(tmp_path, mock=True, replies=None):
    rt = DemoRuntime(tmp_path, True, dict(SETTINGS))
    rt.mock_mode = mock
    calls = []

    async def structured(*, messages, schema):
        calls.append(messages)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return schema.model_validate(reply)
    rt.structured = structured
    rt.calls = calls
    return rt


def mock_tavily(monkeypatch, handler):
    log = []

    def wrapped(request):
        log.append((request.method, request.url.path))
        return handler(request)
    monkeypatch.setattr(tavily, "make_client", lambda key: httpx.AsyncClient(
        base_url=tavily.BASE_URL, transport=httpx.MockTransport(wrapped)))
    return log


def mock_bundle(tmp_path):
    rt = runtime(tmp_path)
    research = asyncio.run(service.run_research(ResearchRequest(project_id=PID, topic=TOPIC), rt))
    script = asyncio.run(service.generate_dialogue(
        DialogueRequest(project_id=PID, research=research, characters=CHARACTERS), rt))
    return rt, research, script


def test_mock_pipeline_is_valid_and_marked(tmp_path):
    rt, research, script = mock_bundle(tmp_path)
    assert research.is_mock and all(s.title.startswith("Mock") for s in research.sources)
    assert [c.claim_id for c in research.claims] == [f"c{i:03d}" for i in range(1, 7)]
    assert checks.script_problems(script, research) == []
    assert [t.claim_ids for t in script.turns if t.speaker_id == "jensen"] == [[f"c{i:03d}"] for i in range(1, 7)]
    imgs = asyncio.run(service.find_images(ImageRequest(project_id=PID, research=research, script=script), rt))
    assert [s.status for s in imgs.selections].count("unavailable") == 1
    for s in imgs.selections:
        if s.asset:
            assert images.decode(rt.path(s.asset.key).read_bytes())
    assert rt.calls == []  # mock never calls the LLM


def research_handler(statuses):
    seq = list(statuses)

    def handler(req):
        if req.method == "POST":
            return httpx.Response(201, json={"request_id": "rq1", "status": "pending"})
        status = seq.pop(0)
        if status != "completed":
            return httpx.Response(200, json={"request_id": "rq1", "status": status})
        return httpx.Response(200, json={
            "request_id": "rq1", "status": "completed", "content": {"Overview": "Calls use signaling.", "Media": ["SRTP"]},
            "sources": [{"title": "A", "url": "https://a.example/x"}, {"url": "https://b.example/y"},
                        {"url": "https://a.example/x"}, {"title": "bad", "url": "file:///etc/passwd"}]})
    return handler


GOOD_CLAIMS = [{"claim_id": f"k{i}", "text": f"claim {i}", "source_ids": ["src001"],
                "evidence_type": "general_industry_practice"} for i in range(3)]


def test_live_research_polls_normalizes_and_repairs(tmp_path, monkeypatch):
    log = mock_tavily(monkeypatch, research_handler(["in_progress", "processing", "completed"]))
    bad = {"summary": "s", "claims": GOOD_CLAIMS[:2] + [
        {"claim_id": "x", "text": "t", "source_ids": ["src099"], "evidence_type": "documented"},
        {"claim_id": "y", "text": "t", "source_ids": ["src002"], "evidence_type": "inference"}]}
    good = {"summary": "s", "claims": GOOD_CLAIMS + [
        {"claim_id": "y", "text": "t", "source_ids": ["src002"], "evidence_type": "inference", "caveat": "guess"}]}
    rt = runtime(tmp_path, mock=False, replies=[bad, good])
    b = asyncio.run(service.run_research(ResearchRequest(project_id=PID, topic=TOPIC), rt))
    assert [m for m, _ in log] == ["POST", "GET", "GET", "GET"]
    assert [s.url for s in b.sources] == ["https://a.example/x", "https://b.example/y"]
    assert [c.claim_id for c in b.claims] == ["c001", "c002", "c003", "c004"]
    assert "## Overview" in b.report_markdown and not b.is_mock
    assert "src099" in rt.calls[1][-1]["content"]  # repair prompt names the problem
    assert json.loads(rt.path(b.raw_response.key).read_text())["status"] == "completed"
    assert rt.path(f"projects/{PID}/research/initial.json").exists()


def test_research_resumes_saved_request_without_new_post(tmp_path, monkeypatch):
    log = mock_tavily(monkeypatch, research_handler(["processing", "completed"]))
    rt = runtime(tmp_path, mock=False, replies=[{"summary": "s", "claims": GOOD_CLAIMS}])
    asyncio.run(rt.write_json(f"projects/{PID}/research/initial.json", {"request_id": "rq1", "status": "pending"}))
    b = asyncio.run(service.run_research(ResearchRequest(project_id=PID, topic=TOPIC), rt))
    assert [m for m, _ in log] == ["GET", "GET"] and b.tavily_request_id == "rq1"


def test_research_timeout_is_retryable_and_resumable(tmp_path, monkeypatch):
    mock_tavily(monkeypatch, research_handler(["pending"] * 100))
    rt = runtime(tmp_path, mock=False)
    rt.settings["TAVILY_RESEARCH_TIMEOUT_SECONDS"] = "0"
    with pytest.raises(StageFailure) as e:
        asyncio.run(service.run_research(ResearchRequest(project_id=PID, topic=TOPIC), rt))
    assert e.value.error.code == "TAVILY_RESEARCH_TIMEOUT" and e.value.error.retryable
    assert rt.path(f"projects/{PID}/research/initial.json").exists()


def test_failed_research_starts_new_attempt_dir(tmp_path, monkeypatch):
    mock_tavily(monkeypatch, research_handler(["failed"]))
    rt = runtime(tmp_path, mock=False)
    with pytest.raises(StageFailure):
        asyncio.run(service.run_research(ResearchRequest(project_id=PID, topic=TOPIC), rt))
    assert service._attempt_dir(rt, f"projects/{PID}/research") == f"projects/{PID}/research/attempt2"


@pytest.mark.parametrize("resp,code,calls", [
    (httpx.Response(200, json={"request_id": "rq1", "status": "weird"}), "TAVILY_BAD_RESPONSE", 2),
    (httpx.Response(401, json={}), "TAVILY_AUTH", 1),
])
def test_tavily_errors(tmp_path, monkeypatch, resp, code, calls):
    def handler(req):
        if req.method == "POST" and code != "TAVILY_AUTH":
            return httpx.Response(201, json={"request_id": "rq1"})
        return resp
    log = mock_tavily(monkeypatch, handler)
    with pytest.raises(StageFailure) as e:
        asyncio.run(service.run_research(ResearchRequest(project_id=PID, topic=TOPIC), runtime(tmp_path, mock=False)))
    assert e.value.error.code == code and len(log) == calls


def test_tavily_retries_429_with_retry_after(monkeypatch):
    seq = [httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(201, json={"request_id": "r"})]
    mock_tavily(monkeypatch, lambda req: seq.pop(0))

    async def go():
        async with tavily.make_client("k") as c:
            return await tavily.create_research(c, "q", "pro")
    assert asyncio.run(go())["request_id"] == "r"


def test_live_dialogue_repairs_then_validates(tmp_path):
    _, research, mock_script = mock_bundle(tmp_path)
    good = {"title": "T", "turns": [{"speaker_id": t.speaker_id, "intent": t.intent, "text": t.text,
                                     "claim_ids": t.claim_ids} for t in mock_script.turns]}
    bad = json.loads(json.dumps(good))
    bad["turns"][0]["speaker_id"] = "jensen"
    bad["turns"][1]["claim_ids"] = ["c999"]
    bad["turns"][2]["text"] = "[laughs] Really?"
    rt = runtime(tmp_path, mock=False, replies=[bad, good])
    script = asyncio.run(service.generate_dialogue(
        DialogueRequest(project_id=PID, research=research, characters=CHARACTERS, script_revision=2,
                        previous_script=mock_script, revision_instruction="Shorter please"), rt))
    assert script.script_revision == 2 and len(rt.calls) == 2
    assert "Shorter please" in rt.calls[0][1]["content"]
    assert not rt.path(f"projects/{PID}/script/v2/script.json").exists()  # core owns this file

    rt = runtime(tmp_path, mock=False, replies=[bad, bad, bad])
    with pytest.raises(StageFailure) as e:
        asyncio.run(service.generate_dialogue(DialogueRequest(project_id=PID, research=research, characters=CHARACTERS), rt))
    assert e.value.error.code == "DIALOGUE_INVALID"


def png(size=(400, 300)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, format="PNG")
    return buf.getvalue()


def test_image_safety_and_decoding():
    assert images.decode(png()) and not images.decode(b"<svg/>") and not images.decode(png((50, 50)))
    assert [c.image_url for c in images.candidates({"images": [
        "https://x.example/a.png", {"url": "https://x.example/b.jpg", "description": "d"}, {"url": "ftp://bad"}, 3]})] \
        == ["https://x.example/a.png", "https://x.example/b.jpg"]

    async def go(url):
        async with images.make_client() as c:
            return await images.download(c, url)
    for url in ["http://127.0.0.1/a.png", "http://10.0.0.5/a.png", "http://169.254.169.254/latest", "file:///etc/passwd"]:
        img, why = asyncio.run(go(url))
        assert img is None and "refused" in why


def test_live_find_images_downloads_and_handles_failures(tmp_path, monkeypatch):
    _, research, script = mock_bundle(tmp_path)

    def search(req):
        q = json.loads(req.content)["query"]
        if "scene3" in q:
            return httpx.Response(400, json={})
        if "scene4" in q:
            return httpx.Response(200, json={"images": ["https://img.example/notimage"]})
        return httpx.Response(200, json={"images": [{"url": "https://img.example/ok.png", "description": "a diagram"}]})
    mock_tavily(monkeypatch, search)
    monkeypatch.setattr(images, "make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=png() if req.url.path.endswith(".png") else b"html"))))

    async def public(url):
        return True
    monkeypatch.setattr(images, "_public_host", public)
    plan = {"queries": [{"scene_index": i, "dialogue_ids": [], "query": f"scene{i}", "reason": "r"} for i in range(6, 0, -1)]}
    # Ranking: scene 6's only candidate is judged irrelevant; scene 5 skipped by the model -> search order.
    ranking = {"scenes": [{"scene_index": i, "ranked": [1]} for i in (1, 2, 4)] + [{"scene_index": 6, "ranked": []}]}
    rt = runtime(tmp_path, mock=False, replies=[plan, ranking])
    b = asyncio.run(service.find_images(ImageRequest(project_id=PID, research=research, script=script), rt))
    assert [s.status for s in b.selections] == ["selected", "selected", "unavailable", "unavailable", "selected", "unavailable"]
    assert b.selections[5].reason == "no relevant image among search results"
    assert "candidate images" in rt.calls[1][0]["content"] and "[1] a diagram (img.example)" in rt.calls[1][1]["content"]
    assert b.selections[0].query.dialogue_ids == ["d001", "d002"] and b.selections[0].source_page_url is None
    assert "search failed" in b.selections[2].reason and "no usable image" in b.selections[3].reason
    assert rt.path(b.selections[0].asset.key).read_bytes() == png()


@pytest.mark.parametrize("handler", [
    lambda req: httpx.Response(201, json={"request_id": "rq1"}) if req.method == "POST"
    else httpx.Response(200, json={"status": "completed", "content": "report", "sources": []}),
    lambda req: httpx.Response(201, json={"request_id": "rq1"}) if req.method == "POST"
    else httpx.Response(200, json={"request_id": "rq1", "status": "cancelled"}),
])
def test_permanent_research_failure_lets_retry_start_fresh(tmp_path, monkeypatch, handler):
    mock_tavily(monkeypatch, handler)
    rt = runtime(tmp_path, mock=False)
    with pytest.raises(StageFailure):
        asyncio.run(service.run_research(ResearchRequest(project_id=PID, topic=TOPIC), rt))
    assert service._attempt_dir(rt, f"projects/{PID}/research") == f"projects/{PID}/research/attempt2"


def test_auth_error_while_polling_keeps_request_for_resume(tmp_path, monkeypatch):
    mock_tavily(monkeypatch, lambda req: httpx.Response(201, json={"request_id": "rq1"}) if req.method == "POST"
                else httpx.Response(401, json={}))
    rt = runtime(tmp_path, mock=False)
    with pytest.raises(StageFailure):
        asyncio.run(service.run_research(ResearchRequest(project_id=PID, topic=TOPIC), rt))
    assert service._attempt_dir(rt, f"projects/{PID}/research") == f"projects/{PID}/research"


def test_request_id_falls_back_to_saved_initial(tmp_path, monkeypatch):
    mock_tavily(monkeypatch, lambda req: httpx.Response(201, json={"request_id": "rq1"}) if req.method == "POST"
                else httpx.Response(200, json={"status": "completed", "content": "r", "sources": [{"url": "https://a.example"}]}))
    rt = runtime(tmp_path, mock=False, replies=[{"summary": "s", "claims": GOOD_CLAIMS}])
    assert asyncio.run(service.run_research(ResearchRequest(project_id=PID, topic=TOPIC), rt)).tavily_request_id == "rq1"


def test_blank_turn_is_schema_error_and_label_check_is_narrow():
    with pytest.raises(ValueError):
        service._TurnDraft(speaker_id="sundar", intent="hook", text="   ")
    assert checks.STAGE_DIRECTION.search("Sundar: hello") and checks.STAGE_DIRECTION.search("[laughs] ok")
    assert not checks.STAGE_DIRECTION.search("First: signaling sets up the call.")


def test_redirect_to_private_address_is_refused(monkeypatch):
    async def public(url):
        return url.startswith("https://img.example")
    monkeypatch.setattr(images, "_public_host", public)

    async def go():
        transport = httpx.MockTransport(lambda req: httpx.Response(302, headers={"Location": "http://169.254.169.254/x"})
                                        if req.url.host == "img.example" else httpx.Response(200, content=png()))
        async with httpx.AsyncClient(transport=transport) as c:
            return await images.download(c, "https://img.example/a.png")
    img, why = asyncio.run(go())
    assert img is None and "refused" in why and "169.254" in why


def test_live_dialogue_retry_and_core_rule(tmp_path):
    _, research, mock_script = mock_bundle(tmp_path)
    turns = [{"speaker_id": t.speaker_id, "intent": t.intent, "text": t.text, "claim_ids": t.claim_ids}
             for t in mock_script.turns]
    turns[6]["text"] = "Relay servers. Calls go straight from phone to phone."  # uncited statement, not a question
    fixed = [dict(t) for t in turns]
    fixed[6]["text"] = "Relay servers? Don't calls go straight from phone to phone?"
    rt = runtime(tmp_path, mock=False, replies=[{"title": "T", "turns": turns}, {"title": "T", "turns": fixed}])
    asyncio.run(service.generate_dialogue(DialogueRequest(project_id=PID, research=research, characters=CHARACTERS), rt))
    assert "d007 (challenge)" in rt.calls[1][-1]["content"]


def test_live_images_retry_uses_fresh_attempt_folder(tmp_path, monkeypatch):
    _, research, script = mock_bundle(tmp_path)
    calls = iter(range(100))
    mock_tavily(monkeypatch, lambda req: httpx.Response(200, json={"images": ["https://img.example/a.png"],
                                                                  "response_time": next(calls)}))
    monkeypatch.setattr(images, "make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=png()))))

    async def public(url):
        return True
    monkeypatch.setattr(images, "_public_host", public)
    plan = lambda tag: {"queries": [{"scene_index": i, "dialogue_ids": [], "query": f"{tag}{i}", "reason": "r"}
                                    for i in range(1, 7)]}
    from contracts.models import PipelineError
    failed = StageFailure(PipelineError(code="MODEL_REQUEST_FAILED", stage="nemotron", message="x"))
    rt = runtime(tmp_path, mock=False, replies=[plan("a"), {"scenes": []}, plan("b"), failed])
    req = ImageRequest(project_id=PID, research=research, script=script)
    first = asyncio.run(service.find_images(req, rt))
    second = asyncio.run(service.find_images(req, rt))  # immutable runtime would raise if keys were reused
    assert first.selections[0].asset.key.endswith("/v1/a1/s01.png")
    assert second.selections[0].asset.key.endswith("/v1/a2/s01.png")
    # Empty ranking (scenes skipped) and a failed ranking call both fall back to search order.
    assert all(s.status == "selected" for s in first.selections + second.selections)


def test_mock_outputs_pass_core_validators(tmp_path):
    validation = pytest.importorskip("contracts.validation")
    rt, research, script = mock_bundle(tmp_path)
    imgs = asyncio.run(service.find_images(ImageRequest(project_id=PID, research=research, script=script), rt))
    validation.validate_research(research)
    validation.validate_script(script, research)
    validation.validate_images(imgs, script)
    validation.validate_artifacts(imgs, rt.artifact_root, PID)


def test_report_citations_follow_reference_list_not_sources_order():
    # Real Tavily response (2026-10-18): its sources array is in a different order from the report's [n] list.
    raw = json.loads((service.FIXTURES / "tavily_live_sample.json").read_text())
    sources = service._index_sources(raw["sources"])
    cites = service._report_citations(raw["content"], sources)
    mlow = next(s for s in sources if "mlow" in s.url)
    assert len(cites) == len(sources) and cites[mlow.source_id] == [12] and mlow.source_id == "src015"
    twice = raw["content"] + "\n[99] " + mlow.url + "\n"
    assert service._report_citations(twice, sources)[mlow.source_id] == [12, 99]


def test_acronym_lists_are_sent_back_for_repair(tmp_path):
    _, research, script = mock_bundle(tmp_path)
    bad = script.model_copy(deep=True)
    bad.turns[3].text = "WebRTC or SDES SRTP media using OPUS PCMA or PCMU."
    assert any("acronyms" in p for p in checks.script_problems(bad, research))
    bad.turns[3].text = "But why would anyone trust that?"
    assert any("must answer" in p for p in checks.script_problems(bad, research))
