"""
Alembic environment config for itrola-ride-backend.

This replaces the default env.py that `alembic init migrations` generates.
Two things it needs from your project:
1. DATABASE_URL from .env (via python-dotenv, same as main.py)
2. Base.metadata from app.core.database, WITH all models actually imported
   somewhere so they're registered on it — importing app.models.models below
   is what makes autogenerate aware of Driver, Vehicle, Trip, etc. Forgetting
   this import is the most common reason autogenerate produces an empty
   migration even when your models clearly changed.
"""
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from dotenv import load_dotenv

# Make sure `app.*` imports resolve when Alembic runs from the project root.
sys.path.insert(0, os.getcwd())

# Explicit path, not just load_dotenv() — auto-detection walks up from the
# caller's stack frame, which behaves inconsistently when Alembic loads this
# file through its own exec mechanism rather than a normal import. This file
# lives at migrations/env.py, so .env is one directory up.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

from app.core.database import Base
import app.models.models  # noqa: F401 — import for side effect: registers models on Base.metadata

config = context.config

# Override whatever's in alembic.ini with the real DB URL from .env, so
# there's exactly one place (.env) that knows the connection string.
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL", ""))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
