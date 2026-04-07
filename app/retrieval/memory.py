from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "database" / "db" / "sql_db.db"


class ConversationMemory:
    def __init__(self) -> None:
        self._db_path = os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))

    def load_history(self, thread_id: str, exchanges: int = 10) -> list[dict[str, Any]]:
        if not thread_id or not os.path.exists(self._db_path):
            return []

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT role, content FROM chat_messages WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?",
                (thread_id, exchanges * 2),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        messages = [{"role": row["role"], "content": row["content"]} for row in rows]
        messages.reverse()
        return messages
