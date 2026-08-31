from unittest.mock import MagicMock, patch

from app.hosted_demo import bootstrap_hosted_demo, ensure_demo_seeded


def _database_cursor(existing_observations: int) -> tuple[MagicMock, MagicMock]:
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = (existing_observations,)
    return connection, cursor


def test_demo_seed_runs_when_observations_are_empty() -> None:
    connection, cursor = _database_cursor(0)

    with (
        patch("app.hosted_demo.psycopg.connect") as connect,
        patch("app.hosted_demo.run_demo") as run_demo,
    ):
        connect.return_value.__enter__.return_value = connection

        assert ensure_demo_seeded("postgresql://demo") is True

    run_demo.assert_called_once_with("postgresql://demo")
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert "SELECT pg_advisory_lock(%s)" in statements
    assert "SELECT pg_advisory_unlock(%s)" in statements


def test_demo_seed_is_skipped_when_observations_exist() -> None:
    connection, _ = _database_cursor(4)

    with (
        patch("app.hosted_demo.psycopg.connect") as connect,
        patch("app.hosted_demo.run_demo") as run_demo,
    ):
        connect.return_value.__enter__.return_value = connection

        assert ensure_demo_seeded("postgresql://demo") is False

    run_demo.assert_not_called()


def test_bootstrap_reuses_migration_runner_before_seed() -> None:
    with (
        patch(
            "app.hosted_demo.migrate_database", return_value=["005_network_observations"]
        ) as migrate,
        patch("app.hosted_demo.ensure_demo_seeded", return_value=True) as seed,
    ):
        applied, seeded = bootstrap_hosted_demo("postgresql://demo")

    migrate.assert_called_once_with("postgresql://demo")
    seed.assert_called_once_with("postgresql://demo")
    assert applied == ["005_network_observations"]
    assert seeded is True
