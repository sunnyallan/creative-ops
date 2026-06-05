from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

import psycopg
from psycopg_pool import ConnectionPool

from config import settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(conninfo=settings.supabase_db_url, min_size=1, max_size=10, kwargs={"autocommit": False})
    return _pool


@contextmanager
def tenant_connection(tenant_id: UUID) -> Iterator[psycopg.Connection]:
    """Borrow a pooled connection with app.current_tenant_id set for the txn."""
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(tenant_id),))
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
