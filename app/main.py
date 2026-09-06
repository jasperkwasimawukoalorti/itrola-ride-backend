import os
import dotenv as _dotenv


class dotenv:
    """Compatibility facade for loading dotenv files."""

    @staticmethod
    def load_dotenv(*args, **kwargs):
        """Load dotenv values into ``os.environ`` and report success."""
        return _dotenv.load_dotenv(*args, **kwargs)

dotenv.load_dotenv()  # without this, os.getenv() silently falls back to defaults —
                # e.g. ADMIN_API_KEY would use the insecure "change-this-admin-key"
                # fallback in deps.py rather than your real .env value, unless
                # something exports it manually in the shell first.

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import auth, drivers, trips, payments, uploads, admin_ui

app = FastAPI(title="itrola Ride API")
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


@app.get("/")
def root():
    """
    Required if deploying to Cloud Run — the startup probe hits '/' and
    will loop-restart the container on 404 if this route is missing.
    """
    return {"status": "ok", "service": "itrola-ride-api"}
