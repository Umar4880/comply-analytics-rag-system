import sqlite3
from app.database.sql import Database


def test_database_connection_and_schema(tmp_path):
    db_file = tmp_path / "test_sql.db"
    db = Database(db_path=str(db_file))

    with db._connect_db() as conn:
        value = conn.execute("SELECT 1").fetchone()[0]
        assert value == 1

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "document_metadata" in tables
    assert "chunk_metadata" in tables
    assert "chat_sessions" in tables
    assert "chat_messages" in tables