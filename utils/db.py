import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from config import DATA_DIR, DB_PATH, DEFAULT_TIMEZONE
from utils.logger import logger


POST_RECURRENCE_COLUMNS = {
    "next_run_at": "TEXT",
    "last_run_at": "TEXT",
    "end_at": "TEXT",
    "timezone": f"TEXT DEFAULT '{DEFAULT_TIMEZONE}'",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}


async def _ensure_columns(db, table_name: str, expected_columns: dict[str, str]):
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    existing = {row[1] for row in await cursor.fetchall()}

    for column_name, column_type in expected_columns.items():
        if column_name in existing:
            continue
        await db.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )


async def init_db():
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    existed_before_init = db_path.exists()
    size_before_init = db_path.stat().st_size if existed_before_init else 0

    logger.info("Runtime DATA_DIR: %s", DATA_DIR)
    logger.info("SQLite DB_PATH: %s", DB_PATH)
    logger.info(
        "SQLite file exists before init: %s, size=%s bytes",
        existed_before_init,
        size_before_init,
    )

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                publish_time TEXT NOT NULL,
                status TEXT DEFAULT 'pending'
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                title TEXT,
                type TEXT,
                added_at TEXT
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS post_targets (
                post_id INTEGER,
                chat_id TEXT,
                PRIMARY KEY (post_id, chat_id)
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS post_buttons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER,
                row INTEGER,
                text TEXT,
                url TEXT
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS post_recurrence (
                post_id INTEGER PRIMARY KEY,
                mode TEXT NOT NULL,
                config TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
            """
        )

        await _ensure_columns(db, "post_recurrence", POST_RECURRENCE_COLUMNS)
        await db.commit()

    existed_after_init = db_path.exists()
    size_after_init = db_path.stat().st_size if existed_after_init else 0
    logger.info(
        "SQLite file exists after init: %s, size=%s bytes",
        existed_after_init,
        size_after_init,
    )


async def save_post(
    post_type: str,
    content: str,
    publish_time: str,
    status: str = "pending",
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO posts (type, content, publish_time, status)
            VALUES (?, ?, ?, ?)
            """,
            (post_type, content, publish_time, status),
        )
        await db.commit()
        return cursor.lastrowid


async def get_post(post_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_scheduled_posts(post_id: int) -> dict | None:
    return await get_post(post_id)


async def add_post_targets(post_id: int, chat_ids: list[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            """
            INSERT OR IGNORE INTO post_targets (post_id, chat_id)
            VALUES (?, ?)
            """,
            [(post_id, chat_id) for chat_id in chat_ids],
        )
        await db.commit()


async def replace_post_targets(post_id: int, chat_ids: list[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM post_targets WHERE post_id = ?", (post_id,))
        await db.executemany(
            """
            INSERT OR IGNORE INTO post_targets (post_id, chat_id)
            VALUES (?, ?)
            """,
            [(post_id, chat_id) for chat_id in chat_ids],
        )
        await db.commit()


async def get_post_targets(post_id: int) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT chat_id
            FROM post_targets
            WHERE post_id = ?
            ORDER BY chat_id
            """,
            (post_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def add_chat(chat_id: str, title: str | None, chat_type: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO chats (id, title, type, added_at)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, title, chat_type, datetime.utcnow().isoformat()),
        )
        await db.commit()


async def get_all_chats() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM chats ORDER BY title ASC, id ASC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_chat(chat_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM post_targets WHERE chat_id = ?", (chat_id,))
        await db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        await db.commit()


async def update_post(
    post_id: int,
    new_content: str | None = None,
    new_type: str | None = None,
    new_publish_time: str | None = None,
    new_status: str | None = None,
):
    assignments = []
    params = []

    if new_content is not None:
        assignments.append("content = ?")
        params.append(new_content)

    if new_type is not None:
        assignments.append("type = ?")
        params.append(new_type)

    if new_publish_time is not None:
        assignments.append("publish_time = ?")
        params.append(new_publish_time)

    if new_status is not None:
        assignments.append("status = ?")
        params.append(new_status)

    if not assignments:
        return

    params.append(post_id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE posts SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
        await db.commit()


async def mark_post_as_sent(post_id: int):
    await update_post(post_id, new_status="sent")


async def mark_post_as_pending(post_id: int):
    await update_post(post_id, new_status="pending")


async def delete_post(post_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM post_buttons WHERE post_id = ?", (post_id,))
        await db.execute("DELETE FROM post_targets WHERE post_id = ?", (post_id,))
        await db.execute("DELETE FROM post_recurrence WHERE post_id = ?", (post_id,))
        await db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        await db.commit()


async def delete_post_buttons(post_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM post_buttons WHERE post_id = ?", (post_id,))
        await db.commit()


async def save_post_buttons(post_id: int, buttons: list[dict]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            """
            INSERT INTO post_buttons (post_id, row, text, url)
            VALUES (?, ?, ?, ?)
            """,
            [
                (post_id, button["row"], button["text"], button["url"])
                for button in buttons
            ],
        )
        await db.commit()


async def get_post_buttons(post_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT row, text, url
            FROM post_buttons
            WHERE post_id = ?
            ORDER BY row ASC, id ASC
            """,
            (post_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def upsert_recurrence_rule(
    post_id: int,
    config: dict,
    next_run_at: str,
    end_at: str | None,
    timezone_name: str = DEFAULT_TIMEZONE,
):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO post_recurrence (
                post_id,
                mode,
                config,
                next_run_at,
                last_run_at,
                end_at,
                timezone,
                is_active,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
                mode = excluded.mode,
                config = excluded.config,
                next_run_at = excluded.next_run_at,
                end_at = excluded.end_at,
                timezone = excluded.timezone,
                is_active = 1,
                updated_at = excluded.updated_at
            """,
            (
                post_id,
                "rule",
                json.dumps(config, ensure_ascii=False),
                next_run_at,
                None,
                end_at,
                timezone_name,
                now,
                now,
            ),
        )
        await db.commit()


async def get_active_recurrence(post_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM post_recurrence
            WHERE post_id = ? AND is_active = 1
            """,
            (post_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        result = dict(row)
        result["config"] = json.loads(result["config"])
        return result


async def advance_recurrence_rule(
    post_id: int,
    last_run_at: str,
    next_run_at: str | None,
    is_active: bool,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE post_recurrence
            SET last_run_at = ?,
                next_run_at = ?,
                is_active = ?,
                updated_at = ?
            WHERE post_id = ?
            """,
            (
                last_run_at,
                next_run_at,
                1 if is_active else 0,
                datetime.utcnow().isoformat(),
                post_id,
            ),
        )
        await db.commit()


async def disable_recurrence(post_id: int):
    await advance_recurrence_rule(post_id, None, None, False)


async def list_scheduled_items(limit: int, offset: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                p.*,
                pr.next_run_at,
                pr.end_at,
                pr.timezone,
                pr.config AS recurrence_config,
                CASE WHEN pr.post_id IS NULL THEN 0 ELSE 1 END AS is_recurring
            FROM posts p
            LEFT JOIN post_recurrence pr
                ON pr.post_id = p.id AND pr.is_active = 1
            WHERE EXISTS (
                SELECT 1
                FROM post_targets pt
                WHERE pt.post_id = p.id
            )
            AND (p.status = 'pending' OR pr.post_id IS NOT NULL)
            ORDER BY COALESCE(pr.next_run_at, p.publish_time) ASC, p.id ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = await cursor.fetchall()

    result = []
    for row in rows:
        item = dict(row)
        if item.get("recurrence_config"):
            item["recurrence_config"] = json.loads(item["recurrence_config"])
        result.append(item)
    return result


async def get_all_pending_posts() -> list[dict]:
    return await list_schedulable_posts()


async def list_schedulable_posts() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                p.*,
                pr.next_run_at,
                pr.end_at,
                pr.timezone,
                pr.config AS recurrence_config,
                CASE WHEN pr.post_id IS NULL THEN 0 ELSE 1 END AS is_recurring
            FROM posts p
            LEFT JOIN post_recurrence pr
                ON pr.post_id = p.id AND pr.is_active = 1
            WHERE EXISTS (
                SELECT 1
                FROM post_targets pt
                WHERE pt.post_id = p.id
            )
            AND (p.status = 'pending' OR pr.post_id IS NOT NULL)
            ORDER BY COALESCE(pr.next_run_at, p.publish_time) ASC, p.id ASC
            """
        )
        rows = await cursor.fetchall()

    result = []
    for row in rows:
        item = dict(row)
        if item.get("recurrence_config"):
            item["recurrence_config"] = json.loads(item["recurrence_config"])
        result.append(item)
    return result


async def get_pending_posts_page(limit: int, offset: int) -> list[dict]:
    return await list_scheduled_items(limit, offset)


async def find_legacy_orphan_posts() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT p.*
            FROM posts p
            LEFT JOIN post_recurrence pr
                ON pr.post_id = p.id AND pr.is_active = 1
            WHERE p.status = 'pending'
            AND pr.post_id IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM post_targets pt
                WHERE pt.post_id = p.id
            )
            ORDER BY p.publish_time ASC, p.id ASC
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
