"""Hosted demo bootstrap for a durable AtlasPay deployment.

The bootstrap reuses the normal migration runner and seeds the deterministic
network scenarios only when the durable observation table is empty. The seed
step is protected by a PostgreSQL advisory lock so concurrent starts do not
create duplicate demo observations.
"""

from __future__ import annotations

import os

import psycopg

from app.demo_network import run_demo
from app.migrations import migrate_database

DEMO_SEED_LOCK_ID = 8_582_001_002


def ensure_demo_seeded(dsn: str) -> bool:
    """Seed deterministic network observations once and report whether work ran."""

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s)", (DEMO_SEED_LOCK_ID,))
        try:
            cursor.execute("SELECT COUNT(*) FROM network_observations")
            existing = int(cursor.fetchone()[0])
            if existing:
                return False
            run_demo(dsn)
            return True
        finally:
            cursor.execute("SELECT pg_advisory_unlock(%s)", (DEMO_SEED_LOCK_ID,))


def bootstrap_hosted_demo(dsn: str) -> tuple[list[str], bool]:
    """Apply pending migrations and ensure the deterministic demo state exists."""

    applied = migrate_database(dsn)
    seeded = ensure_demo_seeded(dsn)
    return applied, seeded


def main() -> None:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required for hosted demo bootstrap")

    applied, seeded = bootstrap_hosted_demo(dsn)
    if applied:
        print(f"Applied migrations: {', '.join(applied)}")
    else:
        print("Database schema is up to date")
    print("Seeded deterministic demo scenarios" if seeded else "Demo scenarios already present")


if __name__ == "__main__":
    main()
