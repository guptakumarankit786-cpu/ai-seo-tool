import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.gsc.router import router as gsc_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AI SEO Tool API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(gsc_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
