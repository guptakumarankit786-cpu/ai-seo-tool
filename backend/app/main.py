import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from sqlalchemy import update
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import SessionLocal
from app.gsc.indexing_router import router as gsc_indexing_router
from app.gsc.router import router as gsc_router
from app.models import GscInspectionRun, GscSyncRun

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Background jobs live in this process, so anything still "running" at startup was cut off.
    with SessionLocal() as db:
        for model in (GscSyncRun, GscInspectionRun):
            db.execute(
                update(model)
                .where(model.status == "running")
                .values(status="failed", error="Interrupted by a server restart", finished_at=datetime.now(UTC))
            )
        db.commit()
    yield


app = FastAPI(title="AI SEO Tool API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(gsc_router)
app.include_router(gsc_indexing_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
