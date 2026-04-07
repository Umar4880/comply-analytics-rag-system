import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
import warnings

class Database:

    def __init__(self, db_path: str = None):
        if db_path:
            self.db_path = db_path
        else:
            self.db_path = str(Path(__file__).parent / "db/sql_db.db")

        self._init_db()

    #  Connection 
    @contextmanager
    def _connect_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row          # access columns by name
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL") # safe for concurrent reads
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Schema 
    def _init_db(self):
        with self._connect_db() as conn:
            conn.executescript("""
                               
                CREATE TABLE IF NOT EXISTS execution_metadata(
                    session_id TEXT NOT NULL
                    status  TEXT NOT NULL
                    error_message TEXT NOT NULL
                    attempt_count TEXT NOT NULL
                    update_at TEXT NOT NULL
                               
                );
                               
                CREATE TABLE IF NOT EXISTS document_metadata (
                    doc_id       TEXT PRIMARY KEY,
                    doc_name     TEXT NOT NULL,
                    doc_type     TEXT NOT NULL CHECK (doc_type IN ('pdf', 'docx', 'txt')),
                    doc_path     TEXT NOT NULL,
                    total_pages  INTEGER NOT NULL,
                    ingested_at  TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    status       TEXT DEFAULT 'active' CHECK (status IN ('active', 'deleted'))
                );

                CREATE TABLE IF NOT EXISTS chunk_metadata (
                    chunk_id      TEXT PRIMARY KEY,
                    doc_id        TEXT NOT NULL REFERENCES document_metadata(doc_id) ON DELETE CASCADE,
                    chunk_type    TEXT NOT NULL CHECK (chunk_type IN ('structured', 'unstructured')),
                    starting_page INTEGER NOT NULL,
                    ending_page   INTEGER NOT NULL,
                    ingested_at   TEXT NOT NULL,
                    updated_at    TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS structured_chunks (
                    chunk_id    TEXT PRIMARY KEY,
                    doc_id      TEXT NOT NULL REFERENCES document_metadata(doc_id) ON DELETE CASCADE,
                    doc_name    TEXT NOT NULL,
                    heading_h1  TEXT,
                    heading_h2  TEXT,
                    heading_h3  TEXT,
                    content     TEXT NOT NULL,
                    page_start  INTEGER NOT NULL,
                    page_end    INTEGER NOT NULL,
                    updated_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id  TEXT PRIMARY KEY,
                    user_id     TEXT NOT NULL,
                    title       TEXT,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    status      TEXT DEFAULT 'active' CHECK (status IN ('active', 'deleted'))
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    message_id   TEXT PRIMARY KEY,
                    session_id   TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                    role         TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content      TEXT NOT NULL,
                    cited_chunks TEXT,
                    created_at   TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_chunk_doc_id
                    ON chunk_metadata(doc_id);

                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON chat_messages(session_id);

                CREATE INDEX IF NOT EXISTS idx_structured_h1
                    ON structured_chunks(doc_id, heading_h1);

                CREATE INDEX IF NOT EXISTS idx_structured_h2
                    ON structured_chunks(doc_id, heading_h2);

                CREATE INDEX IF NOT EXISTS idx_structured_h3
                    ON structured_chunks(doc_id, heading_h3);

            """)

    #============================================================
    # DOCUMENT OPERATIONS
    #============================================================

    def get_doc_metadata(self, doc_id: str):
        with self._connect_db() as conn:
            return conn.execute(
                "SELECT * FROM document_metadata WHERE doc_id = ?",
                (doc_id,)
            ).fetchone()

    def get_all_doc_metadata(self):
        with self._connect_db() as conn:
            return conn.execute(
                "SELECT * FROM document_metadata WHERE status = 'active'"
            ).fetchall()

    def upsert_doc_metadata(self, doc_id: str, doc_name: str, doc_type: str,
                             doc_path: str, total_pages: int):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect_db() as conn:
            conn.execute("""
                INSERT INTO document_metadata
                    (doc_id, doc_name, doc_type, doc_path,
                     total_pages, ingested_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    total_pages = excluded.total_pages,
                    updated_at  = excluded.updated_at
            """, (doc_id, doc_name, doc_type, doc_path,
                  total_pages, now, now))

    def delete_doc_metadata(self, doc_id: str):
        with self._connect_db() as conn:
            conn.execute(
                "UPDATE document_metadata SET status = 'deleted' WHERE doc_id = ?",
                (doc_id,)
            )

    #============================================================
    # CHUNK OPERATIONS
    #============================================================

    def get_chunk_metadata(self, chunk_id: str):
        with self._connect_db() as conn:
            return conn.execute(
                "SELECT * FROM chunk_metadata WHERE chunk_id = ?",
                (chunk_id,)
            ).fetchone()

    def get_all_chunk_metadata(self, doc_id: str):
        with self._connect_db() as conn:
            return conn.execute(
                "SELECT * FROM chunk_metadata WHERE doc_id = ?",
                (doc_id,)
            ).fetchall()

    def get_all_chunk_ids(self, doc_id: str) -> set:
        with self._connect_db() as conn:
            rows = conn.execute(
                "SELECT chunk_id FROM chunk_metadata WHERE doc_id = ?",
                (doc_id,)
            ).fetchall()
        return {row["chunk_id"] for row in rows}

    def upsert_chunk_metadata(self, chunk_id: str, doc_id: str,
                               chunk_type: str, starting_page: int,
                               ending_page: int):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect_db() as conn:
            conn.execute("""
                INSERT INTO chunk_metadata
                    (chunk_id, doc_id, chunk_type,
                     starting_page, ending_page,
                     ingested_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    starting_page = excluded.starting_page,
                    ending_page = excluded.ending_page,
                    updated_at  = excluded.updated_at
            """, (chunk_id, doc_id, chunk_type,
                  starting_page, ending_page, now, now))

    def delete_chunk_metadata(self, chunk_id: str):
        with self._connect_db() as conn:
            conn.execute(
                "DELETE FROM chunk_metadata WHERE chunk_id = ?",
                (chunk_id,)
            )

    def delete_chunk_metadata_by_doc(self, doc_id: str):
        with self._connect_db() as conn:
            conn.execute(
                "DELETE FROM chunk_metadata WHERE doc_id = ?",
                (doc_id,)
            )

    def upsert_structured_chunk(
        self,
        chunk_id: str,
        doc_id: str,
        doc_name: str,
        heading_h1: str,
        heading_h2: str,
        heading_h3: str,
        content: str,
        page_start: int,
        page_end: int,
    ):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect_db() as conn:
            conn.execute(
                """
                INSERT INTO structured_chunks
                    (chunk_id, doc_id, doc_name, heading_h1, heading_h2, heading_h3,
                     content, page_start, page_end, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    heading_h1 = excluded.heading_h1,
                    heading_h2 = excluded.heading_h2,
                    heading_h3 = excluded.heading_h3,
                    content = excluded.content,
                    page_start = excluded.page_start,
                    page_end = excluded.page_end,
                    updated_at = excluded.updated_at
                """,
                (
                    chunk_id,
                    doc_id,
                    doc_name,
                    heading_h1,
                    heading_h2,
                    heading_h3,
                    content,
                    page_start,
                    page_end,
                    now,
                ),
            )

    def delete_structured_chunks_by_doc(self, doc_id: str):
        with self._connect_db() as conn:
            conn.execute("DELETE FROM structured_chunks WHERE doc_id = ?", (doc_id,))

    def find_parent_chunk(self, doc_id: str, heading_field: str, heading_value: str):
        allowed = {"heading_h1", "heading_h2", "heading_h3"}
        if heading_field not in allowed:
            return None
        if not heading_value:
            return None

        with self._connect_db() as conn:
            row = conn.execute(
                f"""
                SELECT content, heading_h1, heading_h2, heading_h3, page_start, page_end
                FROM structured_chunks
                WHERE doc_id = ? AND {heading_field} = ?
                LIMIT 1
                """,
                (doc_id, heading_value),
            ).fetchone()
            return dict(row) if row else None

    #============================================================
    # CHAT SESSION OPERATIONS
    #============================================================

    def create_session(self, session_id: str, user_id: str,
                       title: str = "New Chat"):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect_db() as conn:
            conn.execute("""
                INSERT INTO chat_sessions
                    (session_id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, user_id, title, now, now))

    def get_session(self, session_id: str):
        with self._connect_db() as conn:
            return conn.execute(
                "SELECT * FROM chat_sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()

    def get_user_sessions(self, user_id: str):
        with self._connect_db() as conn:
            return conn.execute("""
                SELECT * FROM chat_sessions
                WHERE user_id = ? AND status = 'active'
                ORDER BY updated_at DESC
            """, (user_id,)).fetchall()

    def delete_session(self, session_id: str):
        with self._connect_db() as conn:
            conn.execute(
                "UPDATE chat_sessions SET status = 'deleted' WHERE session_id = ?",
                (session_id,)
            )

    #============================================================
    # CHAT MESSAGE OPERATIONS
    #============================================================

    def add_message(self, message_id: str, session_id: str, role: str,
                    content: str, cited_chunks: list = None):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect_db() as conn:
            conn.execute("""
                INSERT INTO chat_messages
                    (message_id, session_id, role,
                     content, cited_chunks, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (message_id, session_id, role, content,
                  json.dumps(cited_chunks or []), now))
            conn.execute("""
                UPDATE chat_sessions SET updated_at = ?
                WHERE session_id = ?
            """, (now, session_id))

    def get_session_messages(self, session_id: str):
        with self._connect_db() as conn:
            return conn.execute("""
                SELECT * FROM chat_messages
                WHERE session_id = ?
                ORDER BY created_at ASC
            """, (session_id,)).fetchall()