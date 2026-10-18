from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.api.routes import router
from backend.core.config import Settings
from backend.core.pipeline import Coordinator, RequestError
from contracts.models import PipelineError, StageFailure


def error_response(status: int, error: PipelineError):
    return JSONResponse(status_code=status, content={"error": error.model_dump(mode="json")})


def create_app(settings: Settings | None = None, services: dict | None = None) -> FastAPI:
    settings = settings or Settings()
    coordinator = Coordinator(settings, services)

    @asynccontextmanager
    async def lifespan(app):
        coordinator.recover()
        yield
        await coordinator.close()

    app = FastAPI(title="Grounded Reel API", version="0.1.0", lifespan=lifespan)
    app.state.coordinator = coordinator
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Range"],
                       expose_headers=["Accept-Ranges", "Content-Range", "Content-Length"])

    @app.exception_handler(RequestError)
    async def request_error(request: Request, exc: RequestError):
        return error_response(exc.status, exc.error)

    @app.exception_handler(StageFailure)
    async def stage_error(request: Request, exc: StageFailure):
        return error_response(503, exc.error)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Validation inputs may contain user data; do not echo whole payloads.
        fields = ", ".join(".".join(str(p) for p in error["loc"]) for error in exc.errors())
        return error_response(422, PipelineError(code="VALIDATION_ERROR", stage="api",
                                               message=f"Invalid request fields: {fields}"))

    @app.exception_handler(KeyError)
    async def missing_project(request: Request, exc: KeyError):
        return error_response(404, PipelineError(code="PROJECT_NOT_FOUND", stage="api", message="Project not found"))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(exc.status_code, PipelineError(code="HTTP_ERROR", stage="api", message=str(exc.detail)))

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        return error_response(500, PipelineError(code="INTERNAL_ERROR", stage="api",
                                               message="Unexpected server error; completed outputs preserved"))

    app.include_router(router)
    return app


app = create_app()
