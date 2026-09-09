import os
from pathlib import Path
from dotenv import load_dotenv

# Explicit path, not just load_dotenv() — this file lives in app/, one
# directory below the project root where .env actually is. Auto-detection
# walks up from the caller's location and behaves inconsistently depending
# on how the process was launched — this was the actual cause of the
# JWT_SECRET warning: load_dotenv() was silently failing to find .env,
# not a problem with .env itself.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import auth, drivers, trips, payments, uploads, admin_ui
from app.routers.trips import retry_unmatched_trips
from app.core.database import SessionLocal  # ASSUMPTION — confirm this exists;
                                              # if get_db() in database.py uses a
                                              # differently-named session factory,
                                              # swap the name below to match.

# --- Periodic re-matching sweep ---
# Trip matching in trips.py only runs once, synchronously, at the moment a
# rider calls /trips/request. If no verified+available+nearby driver exists
# at that exact instant, the trip is stuck in 'requested' forever — nothing
# else retries it. This loop is that retry: every REMATCH_INTERVAL_SECONDS,
# sweep any trip that's been stuck long enough and try matching it again.
REMATCH_INTERVAL_SECONDS = 15

_rematch_task = None


async def _rematch_loop():
    while True:
        try:
            db = SessionLocal()
            try:
                matched = retry_unmatched_trips(db)
                if matched:
                    print(f"[rematch] matched {matched} previously-stuck trip(s)")
            finally:
                db.close()
        except Exception as e:
            # A bad sweep should never kill the loop — log and keep going,
            # the next tick tries again.
            print(f"[rematch] sweep failed: {e}")
        await asyncio.sleep(REMATCH_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _rematch_task
    _rematch_task = asyncio.create_task(_rematch_loop())
    try:
        yield
    finally:
        if _rematch_task:
            _rematch_task.cancel()
            try:
                await _rematch_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="itrola Ride API", lifespan=lifespan)
from fastapi.middleware.cors import CORSMiddleware

# ALLOWED_ORIGINS: comma-separated list in .env, e.g.
#   ALLOWED_ORIGINS=https://itrolaride.app,https://admin.itrolaride.app
# Falls back to "*" only when unset, so local dev keeps working without
# extra setup — but production MUST set this explicitly. A wildcard origin
# combined with allow_credentials=True is a real vulnerability: it lets any
# website read authenticated responses from a logged-in user's browser.
_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",")] if _origins_env != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Schema is now owned by Alembic migrations (see /migrations), not this
# call — create_all() only ever creates missing tables and never alters
# existing ones, which is exactly why every schema change up to this point
# needed a manual ALTER TABLE. Run `alembic upgrade head` after pulling
# changes instead of relying on this to keep the DB in sync.
# Base.metadata.create_all(bind=engine)

app.include_router(auth.router)
app.include_router(drivers.router)
app.include_router(trips.router)
app.include_router(payments.router)
app.include_router(uploads.router)
app.include_router(admin_ui.router)

# Serves files saved by uploads.py (e.g. /static/driver_photos/<uuid>.jpg)
app.mount("/static", StaticFiles(directory="static"), name="static")


# --- Periodic re-matching sweep ---
# Trip matching in trips.py only runs once, synchronously, at the moment a
# rider calls /trips/request. If no verified+available+nearby driver exists
# at that exact instant, the trip is stuck in 'requested' forever — nothing
# else retries it. This loop is that retry: every REMATCH_INTERVAL_SECONDS,
# sweep any trip that's been stuck long enough and try matching it again.
REMATCH_INTERVAL_SECONDS = 15

_rematch_task = None


async def _rematch_loop():
    while True:
        try:
            db = SessionLocal()
            try:
                matched = retry_unmatched_trips(db)
                if matched:
                    print(f"[rematch] matched {matched} previously-stuck trip(s)")
            finally:
                db.close()
        except Exception as e:
            # A bad sweep should never kill the loop — log and keep going,
            # the next tick tries again.
            print(f"[rematch] sweep failed: {e}")
        await asyncio.sleep(REMATCH_INTERVAL_SECONDS)


@app.on_event("startup")
async def start_rematch_loop():
    global _rematch_task
    _rematch_task = asyncio.create_task(_rematch_loop())


@app.on_event("shutdown")
async def stop_rematch_loop():
    if _rematch_task:
        _rematch_task.cancel()


@app.get("/")
def root():
    """
    Required if deploying to Cloud Run — the startup probe hits '/' and
    will loop-restart the container on 404 if this route is missing.
    """
    return {"status": "ok", "service": "itrola-ride-api"}
