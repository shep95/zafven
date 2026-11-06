"""Durable message archive, known-member directory, and batch delivery queue."""
from __future__ import annotations

import asyncio
from contextlib import closing
import hashlib
import json
import sqlite3
from pathlib import Path

import config


class CommunityDB:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(config.BOT_DATA_DIR) / "community.sqlite3"

    def _run(self, operation):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=30)) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY, guild_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
                    mirrored INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS messages_pending ON messages(mirrored, id);
                CREATE TABLE IF NOT EXISTS members (
                    guild_id TEXT NOT NULL, user_id TEXT NOT NULL, name TEXT NOT NULL,
                    present INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL,
                    PRIMARY KEY(guild_id, user_id));
                CREATE TABLE IF NOT EXISTS deliveries (
                    guild_id TEXT NOT NULL, campaign TEXT NOT NULL, user_id TEXT NOT NULL,
                    body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', error TEXT,
                    PRIMARY KEY(guild_id, campaign, user_id));
                CREATE TABLE IF NOT EXISTS user_memory (
                    guild_id TEXT NOT NULL, user_id TEXT NOT NULL, payload TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1, mirrored_revision INTEGER NOT NULL DEFAULT 0,
                    channel_id TEXT, message_id TEXT, PRIMARY KEY(guild_id, user_id));
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS promotion_consent (
                    user_id TEXT PRIMARY KEY, allowed INTEGER NOT NULL DEFAULT 0);
            """)
            return operation(conn)

    async def _call(self, operation):
        return await asyncio.to_thread(self._run, operation)

    async def remember(self, guild_id: int, user_id: int, name: str, *,
                       present: bool, source: str) -> None:
        await self._call(lambda c: c.execute(
            "INSERT INTO members VALUES (?, ?, ?, ?, ?) ON CONFLICT(guild_id,user_id) "
            "DO UPDATE SET name=excluded.name,present=excluded.present,source=excluded.source",
            (str(guild_id), str(user_id), name, int(present), source)))

    async def members(self, guild_id: int) -> list[dict]:
        return await self._call(lambda c: [dict(r) for r in c.execute(
            "SELECT * FROM members WHERE guild_id=?", (str(guild_id),))])

    async def archive(self, payload: dict) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
        await self._call(lambda c: c.execute(
            "INSERT OR IGNORE INTO messages(guild_id,fingerprint,payload) VALUES (?,?,?)",
            (str(payload["guild_id"]), fingerprint, serialized)))

    async def pending_messages(self, limit: int = 50, guild_id: int | None = None) -> list[dict]:
        query = "SELECT * FROM messages WHERE mirrored=0"
        params = []
        if guild_id is not None:
            query += " AND guild_id=?"
            params.append(str(guild_id))
        params.append(limit)
        return await self._call(lambda c: [dict(r) for r in c.execute(query + " ORDER BY id LIMIT ?", params)])

    async def mark_mirrored(self, ids: list[int]) -> None:
        await self._call(lambda c: c.executemany(
            "UPDATE messages SET mirrored=1 WHERE id=?", [(i,) for i in ids]))

    async def enqueue(self, guild_id: int, campaign: str, user_ids: list[int], body: str) -> int:
        def write(c):
            before = c.total_changes
            c.executemany("INSERT OR IGNORE INTO deliveries(guild_id,campaign,user_id,body) "
                          "VALUES (?,?,?,?)", [(str(guild_id), campaign, str(uid), body) for uid in user_ids])
            return c.total_changes - before
        return await self._call(write)

    async def pending_delivery(self) -> dict | None:
        def read(c):
            row = c.execute("SELECT * FROM deliveries WHERE status='pending' ORDER BY rowid LIMIT 1").fetchone()
            return dict(row) if row else None
        return await self._call(read)

    async def delivery_status(self, row: dict, status: str, error: str = "") -> None:
        await self._call(lambda c: c.execute(
            "UPDATE deliveries SET status=?,error=? WHERE guild_id=? AND campaign=? AND user_id=?",
            (status, error[:500], row["guild_id"], row["campaign"], row["user_id"])))

    async def claim_delivery(self, row: dict) -> bool:
        return await self._call(lambda c: c.execute(
            "UPDATE deliveries SET status='sending' WHERE guild_id=? AND campaign=? "
            "AND user_id=? AND status='pending'",
            (row["guild_id"], row["campaign"], row["user_id"])).rowcount == 1)

    async def campaign_status(self, guild_id: int, campaign: str) -> dict[str, int]:
        return await self._call(lambda c: {r["status"]: r["n"] for r in c.execute(
            "SELECT status,COUNT(*) n FROM deliveries WHERE guild_id=? AND campaign=? GROUP BY status",
            (str(guild_id), campaign))})

    async def cancel_campaign(self, guild_id: int, campaign: str) -> None:
        await self._call(lambda c: c.execute(
            "UPDATE deliveries SET status='cancelled' WHERE guild_id=? AND campaign=? AND status='pending'",
            (str(guild_id), campaign)))


database = CommunityDB()
