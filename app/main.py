import os
from contextlib import AbstractAsyncContextManager
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

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import auth, drivers, trips, payments, uploads, admin_ui
from app.routers.trips import retry_unmatched_trips
from app.core.database import SessionLocal  # ASSUMPTION — confirm this exists;
                                              # if get_db() in database.py uses a
                                              # differently-named session factory,
                                              # swap the name below to match.

class ServerLifespan(AbstractAsyncContextManager):
    """Concrete async lifespan context manager for the API.

    Implements the two abstract hooks required by
    contextlib.AbstractAsyncContextManager: __aenter__ and __aexit__.
    It starts the background rematch loop on startup and cancels it
    cleanly on shutdown.
    """

    def __init__(self, app: FastAPI):
        self.app = app
        self._rematch_task = None

    async def __aenter__(self):
        """Start the rematch worker task when the FastAPI app enters its lifespan."""
        global _rematch_task
        # Keep the task on the instance so shutdown always cancels the
        # worker that was created for the current app startup.
        self._rematch_task = asyncio.create_task(_rematch_loop())
        _rematch_task = self._rematch_task
        return self.app

    async def __aexit__(self, exc_type, exc, tb):
        """Cancel the background rematch task and allow the app to shut down cleanly."""
        task = self._rematch_task
        if task is not None and not task.done():
            task.cancel()
            try:
                # Await the cancellation with return_exceptions=True so the
                # app lifespan can exit without surfacing a noisy shutdown
                # cancellation as an application error.
                await asyncio.gather(task, return_exceptions=True)
            except asyncio.CancelledError:
                # Swallow shutdown cancellation to keep FastAPI lifespan
                # teardown clean while the event loop is winding down.
                pass
        # Returning False preserves any exception already raised in the
        # lifespan context instead of masking it.
        return False


def lifespan(app: FastAPI) -> ServerLifespan:
    """FastAPI lifespan factory returning an async context manager object.

    This replaces the generator-based @asynccontextmanager form with a
    class that explicitly implements the abstract methods required by the
    async context-manager protocol.
    """
    return ServerLifespan(app)


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


@app.get("/")
def root():
    """
    Required if deploying to Cloud Run — the startup probe hits '/' and
    will loop-restart the container on 404 if this route is missing.
    """
    return {"status": "ok", "service": "itrola-ride-api"}
