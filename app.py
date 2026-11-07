#!/usr/bin/env python3
"""Launch Florida Plate Finder at http://127.0.0.1:8000."""

from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routes import router, run_manager
from app.settings import PROJECT_ROOT


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    run_manager.recover_interrupted_runs()
    yield
    run_manager.shutdown()


app = FastAPI(
    title="Florida Plate Finder",
    description="Local, responsible Florida personalized plate discovery and checking app.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")
app.include_router(router)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
