"""
Database connection setup.
Uses PostgreSQL with PostGIS extension for geospatial queries.
For local dev without Postgres, you can swap DATABASE_URL to sqlite,
but PostGIS features (nearest-driver queries) require real PostGIS in production.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://taxi_user:taxi_pass@localhost:5432/taxi_ghana"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency for FastAPI routes to get a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
