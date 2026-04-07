import sys
from pathlib import Path
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Make sibling top-level packages (e.g. database) importable when running this file directly.
SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from database.database import create_db_and_tables
from routers import modules, events, courses, ical

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Almaweb API",
    summary="Parsed data from almaweb API",
    description="API for accessing parsed data from almaweb API, which includes modules, courses, and events.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api")
api_router.include_router(modules.router)
api_router.include_router(courses.router)
api_router.include_router(events.router)
api_router.include_router(ical.router)
app.include_router(api_router)