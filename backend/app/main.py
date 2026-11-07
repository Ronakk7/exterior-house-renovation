"""FastAPI application entry point, lifecycle, and middleware configuration."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import load_catalogue
from app.api.components import router as components_router
from app.api.catalogue import router as catalogue_router
from app.api.detection import router as detection_router
from app.api.estimation import router as estimation_router
from app.api.generations import router as generations_router
from app.api.photos import router as photos_router
from app.api.projects import router as projects_router
from app.api.reports import router as reports_router
from app.api.system import router as system_router
from app.api.variants import router as variants_router
from app.core.config import Settings
from app.core.database import get_connection, init_db, sweep_interrupted_runs
from app.core.errors import AppError
from app.core.logging_setup import (
    RequestLoggingAndSecurityMiddleware,
    get_request_id,
    setup_logging,
)

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory for FastAPI app instance."""
    app_settings = settings or Settings()

    # 1. Logging setup
    setup_logging(app_settings.LOG_LEVEL)

    # 2. Lifecycle manager
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("Initializing Exterior Renovation application...")
        # Ensure directories exist
        Path(app_settings.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(app_settings.STORAGE_ROOT).mkdir(parents=True, exist_ok=True)

        # Initialize SQLite database schema
        conn = get_connection(app_settings.DATABASE_PATH)
        try:
            init_db(conn)
            # Sweep interrupted runs from prior restarts
            sweep_interrupted_runs(
                conn,
                max(
                    app_settings.AI_DETECTION_TIMEOUT_S,
                    app_settings.AI_IMAGE_TIMEOUT_S,
                ),
            )
        finally:
            conn.close()

        # Load catalogue
        load_catalogue(app_settings.CATALOGUE_PATH)
        logger.info(
            f"Catalogue loaded successfully from {app_settings.CATALOGUE_PATH}"
        )
        logger.info(
            f"Startup complete. AI configured: {app_settings.ai_configured} (Mock: {app_settings.AI_MOCK_MODE})"
        )

        yield

        logger.info("Shutting down application...")

    docs_url = "/docs" if app_settings.APP_ENV == "development" else None
    redoc_url = "/redoc" if app_settings.APP_ENV == "development" else None

    app = FastAPI(
        title="AI-Based Exterior House Renovation API",
        version="0.1.0",
        docs_url=docs_url,
        redoc_url=redoc_url,
        lifespan=lifespan,
    )

    # 3. Middleware
    app.add_middleware(RequestLoggingAndSecurityMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )

    # 4. Exception handlers
    def _standard_headers(req_id: str) -> dict:
        return {
            "X-Request-ID": req_id,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        req_id = get_request_id()
        logger.warning(
            f"Application error: code={exc.code} status={exc.http_status} message={exc.message}"
        )
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": req_id,
                }
            },
            headers=_standard_headers(req_id),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        req_id = get_request_id()
        fields = []
        for err in exc.errors():
            loc = ".".join(str(item) for item in err.get("loc", []) if item != "body")
            fields.append({"field": loc or "body", "problem": err.get("msg", "invalid")})

        logger.warning(f"Request validation failed: {fields}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid request parameters or payload.",
                    "details": {"fields": fields},
                    "request_id": req_id,
                }
            },
            headers=_standard_headers(req_id),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        req_id = get_request_id()
        # Return standard error format for all /api routes
        if request.url.path.startswith("/api"):
            code = "NOT_FOUND" if exc.status_code == 404 else "API_ERROR"
            message = (
                f"API endpoint '{request.url.path}' not found."
                if exc.status_code == 404
                else str(exc.detail)
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error": {
                        "code": code,
                        "message": message,
                        "details": {"resource": "endpoint"} if exc.status_code == 404 else {},
                        "request_id": req_id,
                    }
                },
                headers=_standard_headers(req_id),
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=_standard_headers(req_id),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        req_id = get_request_id()
        logger.exception(f"Unhandled exception during request processing: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Something went wrong on our side. Please try again.",
                    "details": {},
                    "request_id": req_id,
                }
            },
            headers=_standard_headers(req_id),
        )

    # 5. API Routers
    app.include_router(system_router, prefix="/api")
    app.include_router(projects_router, prefix="/api")
    app.include_router(photos_router, prefix="/api")
    app.include_router(detection_router, prefix="/api")
    app.include_router(components_router, prefix="/api")
    app.include_router(catalogue_router, prefix="/api")
    app.include_router(variants_router, prefix="/api")
    app.include_router(generations_router, prefix="/api")
    app.include_router(estimation_router, prefix="/api")
    app.include_router(reports_router, prefix="/api")

    # 6. Static frontend files
    frontend_path = Path(app_settings.FRONTEND_DIR).resolve()
    if not frontend_path.is_dir():
        fallback_frontend = Path(__file__).resolve().parent.parent.parent / "frontend"
        if fallback_frontend.is_dir():
            frontend_path = fallback_frontend

    static_assets = frontend_path / "static"
    if static_assets.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_assets)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index() -> FileResponse:
        index_file = frontend_path / "index.html"
        if not index_file.is_file():
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Frontend index.html not found."},
            )
        return FileResponse(str(index_file))

    return app


# Default app instance for ASGI servers
app = create_app()
