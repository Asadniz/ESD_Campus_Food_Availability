"""App wiring only: logging, database, routers, middleware, /metrics, background job."""
import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from . import config, db, jobs, seed
from .observability.gauges import refresh_gauges
from .observability.logs import log_event, setup_logging
from .observability.middleware import ObservabilityMiddleware
from .routers import admin, eateries, holds, items
from .errors import register_error_handlers

setup_logging()
logger = logging.getLogger("campus.app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    seed.seed_if_empty()
    refresh_gauges()
    job = asyncio.create_task(jobs.run_forever())
    log_event(logger, logging.INFO, "app_started", "campus food api started", service=config.SERVICE_NAME)
    yield
    job.cancel()
    log_event(logger, logging.INFO, "app_stopped", "campus food api stopped")


app = FastAPI(title="Campus Food Availability", lifespan=lifespan)
register_error_handlers(app)
app.add_middleware(ObservabilityMiddleware)
for module in (eateries, items, holds, admin):
    app.include_router(module.router)


@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    # log_config=None: uvicorn's own messages go through our JSON formatter too.
    # access_log=False: the middleware already logs every request with more detail.
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None, access_log=False)
