"""
Truist Model Serving (TMS) — API entry point.

Wires every router, CORS, and the background job-refresh loop. The refresh
loop is a plain asyncio task (no separate worker process) so local dev stays
a single `uvicorn` process with no additional infrastructure.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import entra
from app.config import settings
from app.routers import (
    audit,
    auth,
    dashboard,
    group_mappings,
    health,
    jobs,
    models,
    monitoring,
    pipelines,
    tenants,
)
from app.services import data_pipeline_service, data_quality_service
from app.services.job_service import background_refresh_running_jobs

logger = logging.getLogger(__name__)


async def _refresh_loop() -> None:
    """Advances running jobs (EMR mock/real status polling and the step
    cascade) every JOB_REFRESH_INTERVAL_SECONDS, so job state progresses even
    when no client is polling GET /jobs/{id}."""
    while True:
        try:
            updated = await background_refresh_running_jobs()
            if updated:
                logger.info("Background refresh advanced %d job(s)", updated)
        except Exception:
            logger.exception("Background job refresh pass failed — continuing")
        await asyncio.sleep(settings.JOB_REFRESH_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to serve with weakened token validation: in prod mode the Entra
    # settings must be complete (blank audience/issuer would silently disable
    # those checks).
    if settings.AUTH_MODE == "prod":
        entra.validate_prod_config()
    # Same fail-fast policy for the real executors: a half-configured
    # connector would otherwise surface as every run failing at runtime.
    if settings.SNOWFLAKE_MODE == "real":
        data_pipeline_service.validate_real_config()
    if settings.DQ_MODE == "real":
        data_quality_service.validate_real_config()
    task = asyncio.create_task(_refresh_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Truist Model Serving (TMS)",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(tenants.router)
app.include_router(group_mappings.router)
app.include_router(pipelines.router)
app.include_router(jobs.router)
app.include_router(models.router)
app.include_router(monitoring.router)
app.include_router(audit.router)
app.include_router(dashboard.router)
