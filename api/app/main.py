"""KILN API entrypoint."""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import auth, builds, dashboard, health, inventory, jobs, notifications, schedule, tickets

app = FastAPI(title="KILN API", version=settings.version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# blob storage dir (local volume dev; S3 seam in prod)
os.makedirs(settings.storage_dir, exist_ok=True)

for r in (health, auth, tickets, jobs, builds, schedule, inventory, notifications, dashboard):
    app.include_router(r.router)


@app.get("/")
def root():
    return {
        "service": settings.service_name,
        "version": settings.version,
        "docs": "/docs",
        "health": "/api/health",
    }
