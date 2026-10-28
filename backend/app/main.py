from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.operations import router as operations_router
from app.core.config import get_settings
from app.db.connection import configured_database_backend, connect
from app.db.migrations import initialize_default_database


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_default_database()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=settings.allowed_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix=settings.api_prefix)
app.include_router(operations_router, prefix=settings.api_prefix)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness_check() -> dict[str, str]:
    with connect() as connection:
        connection.execute("SELECT 1").fetchone()
    return {
        "status": "ready",
        "database": configured_database_backend(),
    }


# On a single in-house server the API also serves the built frontend
# (`VITE_API_BASE_URL=/ npm run build`), so the whole app has one address.
# Mounted last so it never shadows the API routes above.
frontend_dist = os.getenv("FRONTEND_DIST_DIR", "").strip()
if frontend_dist and Path(frontend_dist).is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
