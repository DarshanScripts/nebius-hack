"""Standalone member-4 demo / acceptance run.

    python -m backend.modules.scenes.demo --mock --output output/demos/scenes

Builds the section-12 fixture context, generates six scenes, renders previews
(submitted s03,s01,s06,s02,s05,s04), routes and applies "correct scene six",
exercises the agent repair loop into the deterministic fallback with a canned
model, renders the 60-second master, and checks stream metadata. Starts its own
render worker (renderer/) unless --worker-url is given. Writes a timestamped
report under the output directory, also when the run fails.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from contracts.models import EditRoutingRequest, FinalRenderRequest, PreviewRequest, SceneDraft, SceneTask

from . import service
from .fixtures.context import build_fixture_context
from .fixtures.runtime import FixtureRuntime, live_llm_from_env

REPO = Path(__file__).resolve().parents[3]
RENDERER = REPO / "renderer"
PREVIEW_ORDER = ["s03", "s01", "s06", "s02", "s05", "s04"]
EDIT_MESSAGE = "Please correct scene six: make the packet diagram clearer"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def start_worker(artifact_root: Path, port: int, token: str) -> subprocess.Popen[bytes]:
    if not (RENDERER / "node_modules").exists():
        raise SystemExit("renderer/node_modules missing: run `npm ci --prefix renderer` first")
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env.update({"ARTIFACT_ROOT": str(artifact_root), "RENDER_WORKER_PORT": str(port), "RENDER_WORKER_HOST": "127.0.0.1", "RENDER_WORKER_TOKEN": token})
    logf = open(artifact_root / f"worker-{port}.log", "ab")
    return subprocess.Popen([str(RENDERER / "node_modules" / ".bin" / "tsx"), "src/worker.ts"], cwd=RENDERER, env=env, stdout=logf, stderr=subprocess.STDOUT)


async def wait_health(url: str, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                if (await c.get(f"{url}/health")).status_code == 200:
                    return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.5)
    raise SystemExit(f"render worker at {url} did not become healthy")


def ffprobe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_packets", "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,nb_read_packets,sample_rate:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def broken_model(messages: list[dict[str, str]], schema: type) -> Any:
    """Canned 'model' that always returns code violating the policy: drives repair -> fallback offline."""
    return SceneDraft(source_code="import React from 'react';\nexport default function Scene() { setTimeout(() => {}, 1); return <div>{Date.now()}</div>; }\n", summary="deliberately broken canned draft", cues=[])


async def run(args: argparse.Namespace, report: dict[str, Any]) -> None:
    out = Path(args.output).resolve()
    run_id = report["run_id"]
    token = secrets.token_hex(16)
    worker = None
    url = args.worker_url
    if url is None:
        url = f"http://127.0.0.1:{args.port}"
        worker = start_worker(out, args.port, token)
        report["worker"] = {"url": url, "started_by_demo": True, "log": f"worker-{args.port}.log"}
    else:
        token = os.environ.get("RENDER_WORKER_TOKEN", "")
        report["worker"] = {"url": url, "started_by_demo": False}
    settings = {"RENDER_WORKER_URL": url, "RENDER_WORKER_TOKEN": token, "RENDER_JOB_TIMEOUT_SECONDS": args.timeout, "NEMOTRON_STRUCTURED_MODE": os.environ.get("NEMOTRON_STRUCTURED_MODE", "json_prompt")}
    try:
        await wait_health(url)
        rt = FixtureRuntime(out, mock_mode=args.mock, settings=settings, llm=None if args.mock else live_llm_from_env())
        ctx = await build_fixture_context(rt, character_pngs=args.character_pngs)
        report["context"] = {"context_hash": ctx.context_hash, "timeline_hash": ctx.timeline_hash, "boundaries": [s.start_frame for s in ctx.timeline.scenes] + [1800]}
        log(f"fixture context ready: boundaries {report['context']['boundaries']}")

        # 1. six independent scene generations (3 concurrent)
        sem = asyncio.Semaphore(3)

        targets = [s for s in ctx.timeline.scenes if not args.only or s.scene_id in args.only]

        async def gen(slot: Any) -> Any:
            async with sem:
                return await service.generate_scene(SceneTask(project_id=ctx.project_id, job_id=f"gen-{slot.scene_id}-{run_id}", context=ctx, slot=slot, revision=1), rt)

        builds = {b.scene_id: b for b in await asyncio.gather(*(gen(s) for s in targets))}
        report["builds_v1"] = {sid: {"mode": b.generation_mode, "source": b.source.key, "sha256": b.source.sha256} for sid, b in sorted(builds.items())}
        report["builds_v1"].update({sid: {**report["builds_v1"][sid], "repair_attempts": b.repair_attempts, "warnings": b.warnings, "summary": b.summary} for sid, b in builds.items()})
        log(f"generated {len(builds)} scenes: {[(sid, b.generation_mode, b.repair_attempts) for sid, b in sorted(builds.items())]}")

        # 2. previews submitted out of order; record completion order
        slots = {s.scene_id: s for s in ctx.timeline.scenes}
        completion: list[str] = []
        previews: dict[str, Any] = {}

        async def preview(sid: str, delay: float) -> None:
            await asyncio.sleep(delay)
            outcome = await service.render_preview(PreviewRequest(project_id=ctx.project_id, job_id=f"gen-{sid}-{run_id}", context=ctx, slot=slots[sid], build=builds[sid]), rt)
            completion.append(sid)
            previews[sid] = outcome
            log(f"preview {sid} ready: {outcome.render.duration_frames} frames -> {outcome.render.video.key}")

        if not args.skip_previews:
            t0 = time.monotonic()
            log(f"rendering {len(builds)} preview(s) (worker concurrency 1; ~10-60 s each on a laptop)")
            await asyncio.gather(*(preview(sid, i * 0.3) for i, sid in enumerate(o for o in PREVIEW_ORDER if o in builds)))
            report["previews"] = {"completion_order": completion, "seconds": round(time.monotonic() - t0, 1),
                                  "results": {sid: {"video": o.render.video.key, "frames": o.render.duration_frames, "worker_job_id": o.render.job_id} for sid, o in sorted(previews.items())}}

        if args.only:
            report["status"] = "completed"
            log(f"--only {args.only}: skipping edit, fallback and final")
            return

        # 3. targeted edit of scene six
        intent = await service.route_edit(EditRoutingRequest(project_id=ctx.project_id, message=EDIT_MESSAGE, scene_ids=list(slots)), rt)
        report["edit_intent"] = intent.model_dump(mode="json")
        assert intent.action == "edit_scene" and intent.scene_id == "s06", intent
        edit_op = f"edit-s06-{run_id}"
        b2 = await service.generate_scene(SceneTask(project_id=ctx.project_id, job_id=edit_op, context=ctx, slot=slots["s06"], revision=2, previous_build=builds["s06"], edit_instruction=intent.instruction), rt)
        edit_outcome = await service.render_preview(PreviewRequest(project_id=ctx.project_id, job_id=edit_op, context=ctx, slot=slots["s06"], build=b2), rt)
        before = {sid: b.source.sha256 for sid, b in builds.items()}
        builds["s06"] = edit_outcome.build
        after = {sid: b.source.sha256 for sid, b in builds.items()}
        report["edit"] = {
            "revision_before": 1, "revision_after": edit_outcome.build.revision,
            "s06_source_changed": before["s06"] != after["s06"],
            "s01_s05_unchanged": all(before[s] == after[s] for s in ["s01", "s02", "s03", "s04", "s05"]),
            "slot_unchanged": edit_outcome.build.timeline_hash == ctx.timeline_hash,
            "preview": edit_outcome.render.video.key, "frames": edit_outcome.render.duration_frames,
        }
        log(f"edit applied: {report['edit']}")

        # 4. repair loop exhausted -> deterministic fallback (canned broken model, no network)
        if not args.skip_fallback:
            frt = FixtureRuntime(out, mock_mode=False, settings={**settings, "NEMOTRON_STRUCTURED_MODE": "json_prompt"}, structured_handler=broken_model)
            fb = await service.generate_scene(SceneTask(project_id=ctx.project_id, job_id=f"fallback-s05-{run_id}", context=ctx, slot=slots["s05"], revision=1), frt)
            fbo = await service.render_preview(PreviewRequest(project_id=ctx.project_id, job_id=f"fallback-s05-{run_id}", context=ctx, slot=slots["s05"], build=fb), frt)
            report["fallback"] = {"generation_mode": fb.generation_mode, "repair_attempts": fb.repair_attempts, "warnings": fb.warnings, "preview": fbo.render.video.key}
            log(f"fallback scene: mode={fb.generation_mode} repairs={fb.repair_attempts}")

        # 5. final master composition
        if not args.skip_final:
            log("rendering final 1800-frame master (several minutes on a laptop)")
            t0 = time.monotonic()
            final = await service.render_final(FinalRenderRequest(project_id=ctx.project_id, job_id=f"final-{run_id}", project_revision=2, context=ctx, builds=[builds[s] for s in sorted(builds)]), rt)
            reel = rt.path(final.video.key)
            probe = ffprobe(reel)
            report["final"] = {"video": final.video.key, "poster": final.poster.key if final.poster else None, "frames": final.duration_frames, "seconds": round(time.monotonic() - t0, 1), "ffprobe": probe}
            if shutil.which("ffmpeg"):
                shots = []
                for gf in (1340, 1353, 1365, 1380):  # s05 exit fade, cut, s06 first speech, s06 interior
                    png = reel.parent / f"boundary-{gf}.png"
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(reel), "-vf", f"select=eq(n\\,{gf})", "-vframes", "1", str(png)], check=True)
                    shots.append(str(png.relative_to(out)))
                report["final"]["boundary_frames"] = shots
            log(f"final ready: {final.video.key} ({final.duration_frames} frames)")
        report["progress_events"] = len(rt.progress_events)
        report["status"] = "completed"
    finally:
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(10)
            except subprocess.TimeoutExpired:
                worker.kill()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mock", action="store_true", help="fixture content, no model calls (Remotion still renders real MP4s)")
    p.add_argument("--output", default="output/demos/scenes", help="artifact root for this demo")
    p.add_argument("--worker-url", default=None, help="use a running worker (its ARTIFACT_ROOT must equal --output)")
    p.add_argument("--port", type=int, default=8011, help="port for the worker the demo starts")
    p.add_argument("--timeout", type=int, default=1800, help="per render job deadline in seconds")
    p.add_argument("--character-pngs", action="store_true", help="use MOCK transparent character PNGs instead of silhouette placeholders")
    p.add_argument("--only", nargs="+", choices=["s01", "s02", "s03", "s04", "s05", "s06"], help="generate/preview only these scenes (e.g. one live scene); skips edit/fallback/final")
    p.add_argument("--skip-previews", action="store_true")
    p.add_argument("--skip-fallback", action="store_true")
    p.add_argument("--skip-final", action="store_true")
    args = p.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M")
    report: dict[str, Any] = {"run_id": run_id, "mode": "mock" if args.mock else "live", "status": "failed", "started_at": datetime.now().isoformat(timespec="seconds")}
    try:
        asyncio.run(run(args, report))
    except BaseException as e:
        report["error"] = f"{type(e).__name__}: {e}"
        report["traceback"] = traceback.format_exc()[-6000:]
        raise
    finally:
        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        path = out / f"demo-report-{run_id}.json"
        path.write_text(json.dumps(report, indent=2, default=str))
        log(f"report: {path} (status={report['status']})")
    sys.exit(0 if report["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
