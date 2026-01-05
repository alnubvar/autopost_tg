import aiosqlite
from config import DB_PATH
from datetime import datetime
import json

# ============================
#       INIT DATABASE
# ============================


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:

        # ---- POSTS (контент + статус) ----
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                content TEXT NOT NULL,        -- текст или JSON
                publish_time TEXT NOT NULL,   -- ISO-строка
                status TEXT DEFAULT 'pending' -- pending / sent
            )
            """
        )

        # ---- CHATS (каналы / группы) ----
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,          -- chat_id
                title TEXT,
                type TEXT,                    -- channel / group / supergroup
                added_at TEXT
            )
            """
        )

        # ---- POST → CHATS (many-to-many) ----
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS post_targets (
                post_id INTEGER,
                chat_id TEXT,
                PRIMARY KEY (post_id, chat_id)
            )
            """
        )

        # ---- POST BUTTONS (inline buttons) ----
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

        await db.commit()


# ============================
#         SAVE POST
# ============================


async def save_post(post_type: str, content: str, publish_time: str) -> int:
    """
    Сохраняем ТОЛЬКО пост (без чатов).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO posts (type, content, publish_time)
            VALUES (?, ?, ?)
            """,
            (post_type, content, publish_time),
        )
        await db.commit()

        cursor = await db.execute("SELECT last_insert_rowid()")
        row = await cursor.fetchone()
        return row[0]


# ============================
#        POST TARGETS
# ============================


async def add_post_targets(post_id: int, chat_ids: list[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        for chat_id in chat_ids:
            await db.execute(
                """
                INSERT OR IGNORE INTO post_targets (post_id, chat_id)
                VALUES (?, ?)
                """,
                (post_id, chat_id),
            )
        await db.commit()


async def get_post_targets(post_id: int) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT chat_id
            FROM post_targets
            WHERE post_id = ?
            """,
            (post_id,),
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


# ============================
#           CHATS
# ============================


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
        cursor = await db.execute("SELECT * FROM chats")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ============================
#         GET POST
# ============================


async def get_scheduled_posts(post_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


# ============================
#     GET ALL FUTURE POSTS
# ============================


async def get_all_pending_posts() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM posts WHERE status = 'pending'")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ============================
#         UPDATE POST
# ============================


async def update_post(
    post_id: int,
    new_content: str | None = None,
    new_type: str | None = None,
    new_publish_time: str | None = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        query = "UPDATE posts SET "
        params = []

        if new_content is not None:
            query += "content = ?, "
            params.append(new_content)

        if new_type is not None:
            query += "type = ?, "
            params.append(new_type)

        if new_publish_time is not None:
            query += "publish_time = ?, "
            params.append(new_publish_time)

        query = query.rstrip(", ")
        query += " WHERE id = ?"
        params.append(post_id)

        await db.execute(query, params)
        await db.commit()


# ============================
#      MARK AS SENT
# ============================


async def mark_post_as_sent(post_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE posts SET status = 'sent' WHERE id = ?",
            (post_id,),
        )
        await db.commit()


# ============================
#         DELETE POST
# ============================


async def delete_post(post_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        await db.execute("DELETE FROM post_targets WHERE post_id = ?", (post_id,))
        await db.commit()


async def delete_post_buttons(post_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM post_buttons WHERE post_id = ?",
            (post_id,),
        )
        await db.commit()


# ============================
#     PAGINATION (PENDING)
# ============================


async def get_pending_posts_page(limit: int, offset: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM posts
            WHERE status = 'pending'
            ORDER BY publish_time ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ============================
#       POST BUTTONS
# ============================


async def save_post_buttons(post_id: int, buttons: list[dict]):
    """
    buttons = [
        {"row": 0, "text": "Кнопка", "url": "https://..."},
        {"row": 0, "text": "Кнопка 2", "url": "https://..."},
        {"row": 1, "text": "Кнопка 3", "url": "https://..."},
    ]
    """
    async with aiosqlite.connect(DB_PATH) as db:
        for btn in buttons:
            await db.execute(
                """
                INSERT INTO post_buttons (post_id, row, text, url)
                VALUES (?, ?, ?, ?)
                """,
                (post_id, btn["row"], btn["text"], btn["url"]),
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
        return [dict(r) for r in rows]


# ============================
#          AUTOPOST
# ============================


async def save_recurrence(post_id: int, mode: str, config: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO post_recurrence (post_id, mode, config, is_active)
            VALUES (?, ?, ?, 1)
            """,
            (post_id, mode, json.dumps(config)),
        )
        await db.commit()


async def get_recurrence(post_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM post_recurrence WHERE post_id = ? AND is_active = 1",
            (post_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def disable_recurrence(post_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE post_recurrence SET is_active = 0 WHERE post_id = ?",
            (post_id,),
        )
        await db.commit()


async def create_scheduled_post(base_post_id: int, publish_at: datetime) -> int:
    """
    Создаёт копию поста base_post_id с новым временем публикации
    и возвращает новый post_id
    """

    # 1️⃣ получаем исходный пост
    post = await get_scheduled_posts(base_post_id)
    if not post:
        raise ValueError("Base post not found")

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO posts (
                type,
                content,
                publish_time,
                status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                post["type"],
                post["content"],
                publish_at.isoformat(),
                "pending",  # ВАЖНО
            ),
        )

        await db.commit()
        return cursor.lastrowid
