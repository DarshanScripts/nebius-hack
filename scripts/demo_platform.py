"""No provider calls. Demonstrate creation, persisted artifacts and a locked timeline."""
import argparse
import asyncio
import json
import secrets
import subprocess
from pathlib import Path

from backend.core.config import Settings
from backend.core.fixtures import SERVICES
from backend.core.pipeline import Coordinator
from contracts.models import EditRequest, ProjectCreate


async def drain(coordinator):
    while coordinator._tasks:
        await asyncio.gather(*list(coordinator._tasks))


async def check_render(coordinator, project_id):
    from backend.modules.scenes.demo import ffprobe

    before = coordinator.repo.get(project_id)
    assert before.status == "ready", before.model_dump_json()
    context = coordinator.context(project_id)
    await coordinator.edit(project_id, EditRequest(
        message="Please correct scene six: make the packet diagram clearer",
        scene_id="s06", expected_scene_revision=1))
    await drain(coordinator)
    after = coordinator.repo.get(project_id)
    assert after.status == "ready", after.model_dump_json()
    assert after.scenes[-1].current_revision == 2
    assert after.scenes[-1].build.source.sha256 != before.scenes[-1].build.source.sha256
    assert after.scenes[:5] == before.scenes[:5]
    assert after.audio == before.audio and after.timeline == before.timeline
    assert coordinator.context(project_id) == context
    await coordinator.stitch(project_id)
    await drain(coordinator)
    final = coordinator.repo.get(project_id)
    assert final.status == "completed", final.model_dump_json()
    assert final.final_project_revision == 2 and not final.final_is_stale
    probe = ffprobe(coordinator.runtime.path(final.final.video.key))
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"], video["r_frame_rate"],
            video["pix_fmt"], int(video["nb_read_packets"])) == (
                1080, 1920, "30/1", "yuv420p", 1800), probe
    assert video["codec_name"] == "h264" and audio["codec_name"] == "aac", probe
    assert abs(float(probe["format"]["duration"]) - 60) < 0.1, probe
    coordinator.recover()
    assert coordinator.repo.get(project_id) == final
    report = {
        "mode": "mock", "audio": "silent fixture; not cloned speech",
        "project_id": project_id, "status": final.status,
        "scene_6_revision": 2, "sibling_scenes_unchanged": True,
        "audio_and_timeline_unchanged": True, "persistence_restored": True,
        "video": final.final.video.key, "ffprobe": probe,
    }
    ref = await coordinator.runtime.write_json(f"projects/{project_id}/acceptance.json", report)
    print(json.dumps(report, indent=2), flush=True)
    print(f"Acceptance report: {coordinator.runtime.path(ref.key)}", flush=True)


async def demo(output, render=False, port=8012):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    worker = None
    token = secrets.token_hex(24)
    render_settings = {
        "render_worker_url": f"http://127.0.0.1:{port}",
        "render_worker_token": token, "render_job_timeout_seconds": 1800,
    } if render else {}
    coordinator = Coordinator(Settings(
        _env_file=None, mock_mode=True, artifact_root=output, **render_settings), services=SERVICES)
    try:
        if render:
            from backend.modules.scenes.demo import start_worker, wait_health

            worker = start_worker(output, port, token)
            await wait_health(coordinator.settings.render_worker_url)
        await run_demo(coordinator, render)
    finally:
        await coordinator.close()
        if worker is not None:
            worker.terminate()
            try:
                await asyncio.to_thread(worker.wait, 10)
            except subprocess.TimeoutExpired:
                worker.kill()
                await asyncio.to_thread(worker.wait)


async def run_demo(coordinator, render):
    snapshot = coordinator.create(ProjectCreate(topic="Mock demo: how does voice calling work?"))
    print(f"Created {snapshot.project_id} with {len(snapshot.scenes)} pending slots", flush=True)
    await drain(coordinator)
    snapshot = coordinator.repo.get(snapshot.project_id)
    assert snapshot.timeline is not None
    boundaries = [snapshot.timeline.scenes[0].start_frame] + [s.end_frame for s in snapshot.timeline.scenes]
    print(json.dumps({"status": snapshot.status, "boundaries": boundaries,
        "last_speech_frame": snapshot.timeline.utterances[-1].end_frame,
        "events": coordinator.repo.events(snapshot.project_id).next_after,
        "scene_errors": [s.error.code if s.error else None for s in snapshot.scenes]}, indent=2))
    print("Content/audio are explicit fixtures, not live research or cloned speech.", flush=True)
    if render:
        await check_render(coordinator, snapshot.project_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/demos/platform"))
    parser.add_argument("--render", action="store_true",
                        help="start the local renderer, verify six previews, edit and final MP4")
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()
    asyncio.run(demo(args.output, args.render, args.port))
