"""BRSR Reporting Portal — FastAPI application entrypoint."""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.errors import register_exception_handlers
from app.api.users import router as users_router
from app.auth.router import router as auth_router
from app.config import get_settings
from app.calculation.router import router as calculation_router
from app.collection.router import router as collection_router
from app.consolidation.router import router as consolidation_router
from app.workflow.periods_router import router as periods_router
from app.entities.router import router as entities_router
from app.evidence.router import router as evidence_router
from app.framework.router import router as framework_router
from app.logging import configure_logging, request_id_var
from app.reporting.router import router as reporting_periods_router
from app.validation.router import router as validation_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("starting", extra={"endpoint": "lifespan", "status": 0, "duration_ms": 0})
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/openapi.json",
        docs_url="/docs",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_var.set(request_id)
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "unhandled error",
                extra={"endpoint": request.url.path, "status": 500, "duration_ms": 0},
            )
            raise
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "request",
            extra={
                "endpoint": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(health.router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(entities_router)
    app.include_router(framework_router)
    app.include_router(collection_router)
    app.include_router(validation_router)
    app.include_router(calculation_router)
    app.include_router(consolidation_router)
    app.include_router(periods_router)
    app.include_router(evidence_router)
    app.include_router(reporting_periods_router)

    register_exception_handlers(app)
    return app


app = create_app()
