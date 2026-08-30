import hashlib
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
MIGRATION_LOCK_ID = 8_582_001_001


class MigrationDriftError(RuntimeError):
    """Raised when an already-applied migration no longer matches its recorded checksum."""


def migration_files() -> list[Path]:
    return sorted(
        path
        for path in MIGRATIONS_DIR.glob("*.sql")
        if path.is_file() and path.name[:3].isdigit()
    )


def migrate_database(dsn: str) -> list[str]:
    """Apply pending SQL migrations transactionally and return newly applied versions."""
    applied: list[str] = []

    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                checksum CHAR(64) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

        cursor.execute("SELECT version, checksum FROM schema_migrations")
        recorded = dict(cursor.fetchall())

        for path in migration_files():
            version = path.stem
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()

            previous_checksum = recorded.get(version)
            if previous_checksum is not None:
                if previous_checksum != checksum:
                    raise MigrationDriftError(
                        f"Migration {version} checksum differs from the applied version"
                    )
                continue

            cursor.execute(sql)
            cursor.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (version, checksum),
            )
            applied.append(version)

    return applied


def main() -> None:
    import os

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required to run migrations")

    applied = migrate_database(dsn)
    if applied:
        print(f"Applied migrations: {', '.join(applied)}")
    else:
        print("Database schema is up to date")


if __name__ == "__main__":
    main()
