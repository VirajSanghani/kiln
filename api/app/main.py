"""KILN API entrypoint (Phase 0 skeleton)."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import health

app = FastAPI(title="KILN API", version=settings.version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(health.router)


@app.get("/")
def root():
    return {
        "service": settings.service_name,
        "version": settings.version,
        "docs": "/docs",
        "health": "/api/health",
    }
