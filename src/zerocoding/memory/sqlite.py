
import sqlite3
from pathlib import Path


class SQLiteMemory:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self._ensure_tables()

    def _ensure_tables(self):
        cursor = self.connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.commit()

    def add_message(self, role, content):
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO messages (role, content) VALUES (?, ?)",
            (role, content),
        )
        self.connection.commit()

    def get_history(self, limit=20):
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = cursor.fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    def clear(self):
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM messages")
        self.connection.commit()

    def close(self):
        self.connection.close()

