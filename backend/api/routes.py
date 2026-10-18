import mimetypes
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from backend.core.pipeline import RequestError
from contracts.models import EditRequest, Model, ProjectCreate
from contracts.validation import artifact_path

router = APIRouter(prefix="/api")


class RetryRequest(Model):
    stage: Literal["research", "dialogue", "images", "voice", "scenes", "final"]
    scene_id: str | None = None


@router.get("/health")
async def health(request: Request):
    coordinator = request.app.state.coordinator
    return {"status": "ok", "mode": "mock" if coordinator.settings.mock_mode else "live",
            "structured_mode": coordinator.settings.nemotron_structured_mode}


@router.post("/projects", status_code=202)
async def create_project(body: ProjectCreate, request: Request):
    return request.app.state.coordinator.create(body)


@router.get("/projects")
async def list_projects(request: Request):
    return {"projects": request.app.state.coordinator.repo.list()}


@router.get("/projects/{project_id}")
async def get_project(project_id: str, request: Request):
    return request.app.state.coordinator.repo.get(project_id)


@router.get("/projects/{project_id}/events")
async def events(project_id: str, request: Request, after: int = Query(default=0, ge=0)):
    return request.app.state.coordinator.repo.events(project_id, after)


@router.post("/projects/{project_id}/edits", status_code=202)
async def edit(project_id: str, body: EditRequest, request: Request):
    return await request.app.state.coordinator.edit(project_id, body)


@router.post("/projects/{project_id}/retry", status_code=202)
async def retry(project_id: str, body: RetryRequest, request: Request):
    return await request.app.state.coordinator.retry(project_id, body.stage, body.scene_id)


@router.post("/projects/{project_id}/stitch", status_code=202)
async def stitch(project_id: str, request: Request):
    return await request.app.state.coordinator.stitch(project_id)


@router.get("/artifacts/{key:path}")
async def artifact(key: str, request: Request):
    try:
        path = artifact_path(request.app.state.coordinator.runtime.artifact_root, key)
    except ValueError as exc:
        raise RequestError(404, "ARTIFACT_NOT_FOUND", "Artifact not found") from exc
    if not key.startswith("projects/") or not path.is_file() or path.name.startswith("."):
        raise RequestError(404, "ARTIFACT_NOT_FOUND", "Artifact not found")
    # Starlette's FileResponse implements byte ranges, ETag and Last-Modified.
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                        filename=path.name, content_disposition_type="inline")
