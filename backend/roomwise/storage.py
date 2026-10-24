from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import os


def runtime_directory():
    return Path(os.getenv("ROOMWISE_RUNTIME_DIR", str(Path(__file__).resolve().parents[2] / "runtime"))).resolve()


class VersionConflict(Exception):
    def __init__(self, current_version):
        self.current_version = current_version
        super().__init__(f"保存版本冲突，当前版本为 {current_version}")


class SceneStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS scenes (id TEXT PRIMARY KEY, name TEXT NOT NULL, version INTEGER NOT NULL, body TEXT NOT NULL, updated_at TEXT NOT NULL)")

    def _connect(self):
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def save(self, scene: dict):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT version FROM scenes WHERE id=?", (scene["id"],)).fetchone()
            version = int(scene.get("version", 0))
            if row and row["version"] != version:
                raise VersionConflict(row["version"])
            if not row and version != 0:
                # A JSON import may have an old remote version; needs explicit new ID/version.
                raise VersionConflict(0)
            next_version = version + 1
            body = {**scene, "version": next_version}
            updated_at = datetime.now(timezone.utc).isoformat()
            connection.execute("INSERT INTO scenes (id,name,version,body,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,version=excluded.version,body=excluded.body,updated_at=excluded.updated_at", (scene["id"], scene["name"], next_version, json.dumps(body, ensure_ascii=False), updated_at))
            return {"id": scene["id"], "version": next_version, "updatedAt": updated_at}

    def list(self):
        with self._connect() as connection:
            rows = connection.execute("SELECT id,name,version,updated_at FROM scenes ORDER BY updated_at DESC").fetchall()
        return [{"id": r["id"], "name": r["name"], "version": r["version"], "updatedAt": r["updated_at"]} for r in rows]

    def get(self, scene_id):
        with self._connect() as connection:
            row = connection.execute("SELECT body FROM scenes WHERE id=?", (scene_id,)).fetchone()
        return json.loads(row["body"]) if row else None
