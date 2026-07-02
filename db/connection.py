"""DB connection + settings.

Uses psycopg 3. Connection params come from environment (see .env.example).
Nothing here is imported by the pure feature/score modules, so tests that don't
touch the DB never need psycopg installed at runtime.
"""

from __future__ import annotations

import os
from contextlib import contextmanager


def dsn() -> str:
    user = os.getenv("POSTGRES_USER", "trees")
    pwd = os.getenv("POSTGRES_PASSWORD", "trees")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "trees")
    return f"host={host} port={port} dbname={db} user={user} password={pwd}"


@contextmanager
def get_conn():
    """Yield a psycopg connection (imported lazily to keep it optional)."""
    import psycopg

    conn = psycopg.connect(dsn())
    try:
        yield conn
    finally:
        conn.close()
