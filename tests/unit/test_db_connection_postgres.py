from utils import db_connection


def test_postgres_placeholder_translation_adds_returning_for_id_table():
    sql, auto_returning = db_connection._sqlite_to_psycopg_sql(
        "INSERT INTO leads (organization_id, email) VALUES (?, ?)"
    )

    assert sql == "INSERT INTO leads (organization_id, email) VALUES (%s, %s) RETURNING id"
    assert auto_returning is True


def test_postgres_placeholder_translation_preserves_explicit_returning():
    sql, auto_returning = db_connection._sqlite_to_psycopg_sql(
        "INSERT INTO campaigns (name) VALUES (?) RETURNING id, name"
    )

    assert sql == "INSERT INTO campaigns (name) VALUES (%s) RETURNING id, name"
    assert auto_returning is False


def test_postgres_placeholder_translation_skips_composite_key_tables():
    sql, auto_returning = db_connection._sqlite_to_psycopg_sql(
        "INSERT INTO campaign_leads (campaign_id, lead_id) VALUES (?, ?)"
    )

    assert sql == "INSERT INTO campaign_leads (campaign_id, lead_id) VALUES (%s, %s)"
    assert auto_returning is False


def test_postgres_sql_helpers_switch_on_postgres_url(monkeypatch):
    monkeypatch.setattr(db_connection, "_database_url", lambda: "postgresql://user:pass@db/sdr")

    assert db_connection.using_postgres() is True
    assert db_connection.sql_random_order() == "random()"
    assert db_connection.sql_order_by_datetime("created_at") == "created_at"
    assert "string_agg" in db_connection.sql_group_concat_distinct("provider")


def test_stale_postgres_connection_error_detection():
    assert db_connection._is_stale_postgres_connection_error(
        RuntimeError("consuming input failed: SSL connection has been closed unexpectedly")
    )
    assert db_connection._is_stale_postgres_connection_error(
        RuntimeError("server closed the connection unexpectedly")
    )
    assert not db_connection._is_stale_postgres_connection_error(
        RuntimeError("relation app_users does not exist")
    )


def test_sql_helpers_keep_sqlite_defaults(monkeypatch):
    monkeypatch.setattr(db_connection, "_database_url", lambda: "sqlite:///./db/sdr.sqlite3")

    assert db_connection.using_postgres() is False
    assert db_connection.sql_random_order() == "RANDOM()"
    assert db_connection.sql_order_by_datetime("created_at") == "datetime(created_at)"
    assert "GROUP_CONCAT" in db_connection.sql_group_concat_distinct("provider")


def test_split_sql_script_ignores_comment_lines_without_dropping_statement():
    statements = db_connection._split_sql_script(
        """
        -- schema heading
        CREATE TABLE demo (id INTEGER);

        -- seed heading
        INSERT INTO demo (id) VALUES (1);
        """
    )

    assert statements == [
        "CREATE TABLE demo (id INTEGER)",
        "INSERT INTO demo (id) VALUES (1)",
    ]
