"""Alembic environment for Creative Ops.

We keep it deliberately minimal:
  - No autogenerate; every migration wraps a hand-written .sql file so the
    schema history matches exactly what was applied by hand pre-Alembic.
  - No MetaData target — we don't ship SQLAlchemy models.
  - DB URL comes from the same settings the app uses.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure /app is on sys.path so we can import config
_APP = str(Path(__file__).resolve().parent.parent)
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from config import settings  # noqa: E402

alembic_config = context.config

# Interpret the config file for logging
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

# psycopg3 driver URL — settings.supabase_db_url is postgresql:// which
# SQLAlchemy will happily hand to psycopg2 if installed. We ship psycopg[binary],
# not psycopg2, so force the psycopg (v3) driver explicitly.
_db_url = os.environ.get("SUPABASE_DB_URL") or settings.supabase_db_url
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://", 1)
alembic_config.set_main_option("sqlalchemy.url", _db_url)

# No autogenerate — every migration wraps raw SQL.
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=alembic_config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
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
