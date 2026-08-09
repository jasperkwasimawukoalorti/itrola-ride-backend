from fastapi import FastAPI
from app.core.database import Base, engine
from app.routers import auth, drivers, trips

app = FastAPI(title="itrola Ride API")

# Create tables on startup (fine for MVP; use Alembic migrations once schema stabilizes)
Base.metadata.create_all(bind=engine)

app.include_router(auth.router)
app.include_router(drivers.router)
app.include_router(trips.router)


@app.get("/")
def root():
    """
    Required if deploying to Cloud Run — the startup probe hits '/' and
    will loop-restart the container on 404 if this route is missing.
    """
    return {"status": "ok", "service": "itrola-ride-api"}
