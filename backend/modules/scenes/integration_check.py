"""Integration check: Member 1's real Coordinator driving this module end to end.

    python -m backend.modules.scenes.integration_check --worker-url http://127.0.0.1:8021 \
        --output output/demos/scenes-core

Content/voice come from core's explicit fixtures (backend/core/fixtures.py); scene
generation, previews, the routed edit and Stitch go through backend.modules.scenes
exactly as the API imports it. Needs a render worker whose ARTIFACT_ROOT is --output and
RENDER_WORKER_TOKEN in the environment (if the worker requires it). Writes a timestamped
report, also on failure.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.core.config import Settings
from backend.core.fixtures import SERVICES
from backend.core.pipeline import Coordinator
from contracts.models import EditRequest, ProjectCreate

SCENE_CALLS = {"generate_scene", "render_preview", "route_edit", "render_final"}


async def drain(coordinator: Coordinator, deadline_s: float) -> None:
    end = time.monotonic() + deadline_s
    while coordinator._tasks:
        if time.monotonic() > end:
            raise TimeoutError(f"coordinator tasks still running after {deadline_s}s")
        await asyncio.sleep(1)


async def check(args: argparse.Namespace, report: dict[str, Any]) -> None:
    settings = Settings(_env_file=None, mock_mode=True, artifact_root=Path(args.output).resolve(),
                        render_worker_url=args.worker_url, render_worker_token=os.environ.get("RENDER_WORKER_TOKEN", ""),
                        render_job_timeout_seconds=args.timeout)
    services = {k: v for k, v in SERVICES.items() if k not in SCENE_CALLS}  # real member-4 module for scenes
    coordinator = Coordinator(settings, services=services)
    try:
        snap = coordinator.create(ProjectCreate(topic="Mock integration: how does voice calling work?"))
        pid = snap.project_id
        report["project_id"] = pid
        await drain(coordinator, args.timeout)
        snap = coordinator.repo.get(pid)
        events = coordinator.repo.events(pid).events
        report["after_generation"] = {
            "status": snap.status,
            "scenes": {s.scene_id: {"status": s.status, "revision": s.current_revision, "mode": s.build.generation_mode if s.build else None,
                                    "preview": s.preview.video.key if s.preview and s.preview.video else None,
                                    "worker_job": s.preview.job_id if s.preview else None, "error": s.error.code if s.error else None}
                       for s in snap.scenes},
            "ready_event_order": [e.scene_id for e in events if e.type == "scene.ready"],
            "progress_events": sum(1 for e in events if e.type == "render.progress"),
        }
        assert snap.status == "ready", f"project status {snap.status}: {[s.error for s in snap.scenes if s.error]}"
        before = {s.scene_id: s.build.source.sha256 for s in snap.scenes}

        await coordinator.edit(pid, EditRequest(message="Please correct scene six: make the packet diagram clearer", expected_scene_revision=1))
        await drain(coordinator, args.timeout)
        snap = coordinator.repo.get(pid)
        after = {s.scene_id: s.build.source.sha256 for s in snap.scenes}
        s06 = next(s for s in snap.scenes if s.scene_id == "s06")
        report["edit"] = {"s06_revision": s06.current_revision, "s06_changed": before["s06"] != after["s06"],
                          "others_unchanged": all(before[k] == after[k] for k in before if k != "s06"),
                          "project_revision": snap.project_revision, "s06_preview": s06.preview.video.key}
        assert s06.current_revision == 2 and report["edit"]["others_unchanged"], report["edit"]

        await coordinator.stitch(pid)
        await drain(coordinator, args.timeout)
        snap = coordinator.repo.get(pid)
        assert snap.status == "completed" and snap.final and snap.final.status == "completed", (snap.status, snap.final)
        reel = coordinator.runtime.path(snap.final.video.key)
        probe = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-show_entries",
                                "stream=codec_name,width,height,r_frame_rate,pix_fmt,nb_read_packets", "-of", "json", str(reel)],
                               capture_output=True, text=True, check=True)
        report["final"] = {"video": snap.final.video.key, "frames": snap.final.duration_frames, "final_is_stale": snap.final_is_stale,
                           "manifest_exists": coordinator.runtime.path(f"projects/{pid}/final/{snap.final.job_id}/manifest.json").exists(),
                           "ffprobe": json.loads(probe.stdout)}
        report["status"] = "completed"
    finally:
        await coordinator.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--worker-url", default="http://127.0.0.1:8001")
    p.add_argument("--output", default="output/demos/scenes-core")
    p.add_argument("--timeout", type=float, default=1800)
    args = p.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M")
    report: dict[str, Any] = {"run_id": run_id, "status": "failed", "started_at": datetime.now().isoformat(timespec="seconds")}
    try:
        asyncio.run(check(args, report))
    except BaseException as e:
        report["error"] = f"{type(e).__name__}: {e}"
        report["traceback"] = traceback.format_exc()[-6000:]
        raise
    finally:
        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        path = out / f"integration-report-{run_id}.json"
        path.write_text(json.dumps(report, indent=2, default=str))
        print(f"report: {path} (status={report['status']})", flush=True)


if __name__ == "__main__":
    main()
