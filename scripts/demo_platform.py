"""No provider calls. Demonstrate creation, persisted artifacts and a locked timeline."""
import argparse
import asyncio
import json
from pathlib import Path

from backend.core.config import Settings
from backend.core.fixtures import SERVICES
from backend.core.pipeline import Coordinator
from contracts.models import ProjectCreate


async def demo(output):
    coordinator = Coordinator(Settings(_env_file=None, mock_mode=True, artifact_root=output), services=SERVICES)
    snapshot = coordinator.create(ProjectCreate(topic="Mock demo: how does voice calling work?"))
    print(f"Created {snapshot.project_id} with {len(snapshot.scenes)} pending slots")
    while coordinator._tasks:
        await asyncio.gather(*list(coordinator._tasks), return_exceptions=True)
    snapshot = coordinator.repo.get(snapshot.project_id)
    assert snapshot.timeline is not None
    boundaries = [snapshot.timeline.scenes[0].start_frame] + [s.end_frame for s in snapshot.timeline.scenes]
    print(json.dumps({"status": snapshot.status, "boundaries": boundaries,
        "last_speech_frame": snapshot.timeline.utterances[-1].end_frame,
        "events": coordinator.repo.events(snapshot.project_id).next_after,
        "scene_errors": [s.error.code if s.error else None for s in snapshot.scenes]}, indent=2))
    print("Content/audio are explicit fixtures. Scene previews require Member 4's renderer module.")
    await coordinator.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/demos/platform"))
    asyncio.run(demo(parser.parse_args().output))
