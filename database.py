import os
import re
import asyncio
import logging
from typing import Optional, Dict

import aiosqlite

logger = logging.getLogger(__name__)

# Constants
DB_PATH = "/app/data/mafia.db"

def get_database_url() -> Optional[str]:
    """Dynamically fetches the DATABASE_URL environment variable at runtime."""
    return os.getenv("DATABASE_URL")

# Lazy-loaded PostgreSQL pool
_pg_pool = None

# Agar PostgreSQL ulanishi muvaffaqiyatsiz bo'lsa — SQLite ga o'tamiz
_pg_failed = False

# Optional import asyncpg
try:
    import asyncpg
except ImportError:
    asyncpg = None


async def get_pg_pool():
    """Lazily creates and returns the PostgreSQL connection pool.
    
    Agar ulanish muvaffaqiyatsiz bo'lsa — None qaytaradi (xato chiqarmaydi).
    Bot SQLite bilan ishlashda davom etadi.
    """
    global _pg_pool, _pg_failed
    
    # Avval muvaffaqiyatsiz ulanish bo'lgan bo'lsa — qayta urinmaymiz
    if _pg_failed:
        return None
    
    db_url = get_database_url()
    if not db_url:
        return None
    
    if asyncpg is None:
        logger.warning("⚠️ asyncpg o'rnatilmagan. SQLite ishlatiladi.")
        return None
    
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if _pg_pool is not None:
        # Pool boshqa event loop ga tegishli bo'lsa — qayta ishga tushiramiz
        try:
            if loop is not None and (_pg_pool._loop != loop or _pg_pool._closed):
                logger.info("Re-initializing PostgreSQL connection pool for new event loop...")
                _pg_pool = None
        except Exception:
            _pg_pool = None

    if _pg_pool is None:
        url = db_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        try:
            logger.info("🔗 PostgreSQL ulanish pool yaratilyapti...")
            _pg_pool = await asyncpg.create_pool(url, min_size=1, max_size=10)
            logger.info("✅ PostgreSQL ulanish muvaffaqiyatli!")
        except Exception as e:
            logger.error(f"❌ PostgreSQL ulanishda xatolik: {e}")
            logger.warning("⚠️ SQLite zaxira rejimine o'tildi. Bot ishlashda davom etadi.")
            _pg_failed = True
            _pg_pool = None
            return None
    
    return _pg_pool


def convert_placeholders(query: str) -> str:
    """Converts PostgreSQL $1, $2 style placeholders to SQLite ? style."""
    return re.sub(r'\$\d+', '?', query)


# --- Basic Executions ---

def _use_postgres() -> bool:
    """PostgreSQL ishlatish kerakmi? (ulanish muvaffaqiyatli bo'lsa)"""
    return bool(get_database_url()) and not _pg_failed


async def execute_query(query: str, *args):
    """Executes a non-returning SQL query."""
    if _use_postgres():
        pool = await get_pg_pool()
        if pool is not None:
            async with pool.acquire() as conn:
                return await conn.execute(query, *args)
    # SQLite fallback
    sqlite_query = convert_placeholders(query)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(sqlite_query, args)
        await db.commit()


async def execute_insert(query: str, *args) -> int:
    """Executes an INSERT query and returns the last inserted primary key row ID."""
    if _use_postgres():
        pool = await get_pg_pool()
        if pool is not None:
            async with pool.acquire() as conn:
                return await conn.fetchval(query, *args)
    # SQLite fallback
    sqlite_query = convert_placeholders(query)
    clean_query = re.sub(r'(?i)\s+RETURNING\s+\w+', '', sqlite_query)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(clean_query, args)
        last_id = cursor.lastrowid
        await db.commit()
        return last_id


async def fetch_all(query: str, *args) -> list[dict]:
    """Fetches all rows for a query and returns them as a list of dicts."""
    if _use_postgres():
        pool = await get_pg_pool()
        if pool is not None:
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
                return [dict(r) for r in rows]
    # SQLite fallback
    sqlite_query = convert_placeholders(query)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sqlite_query, args) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def fetch_row(query: str, *args) -> dict | None:
    """Fetches a single row and returns it as a dict or None."""
    if _use_postgres():
        pool = await get_pg_pool()
        if pool is not None:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, *args)
                return dict(row) if row else None
    # SQLite fallback
    sqlite_query = convert_placeholders(query)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sqlite_query, args) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def fetch_val(query: str, *args):
    """Fetches a single scalar value (e.g. COUNT(*))."""
    if _use_postgres():
        pool = await get_pg_pool()
        if pool is not None:
            async with pool.acquire() as conn:
                return await conn.fetchval(query, *args)
    # SQLite fallback
    sqlite_query = convert_placeholders(query)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(sqlite_query, args) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


# --- Init & Migrate ---

async def migrate_sqlite_to_postgres():
    """SQLite data migration to PostgreSQL."""
    db_url = get_database_url()
    if not os.path.exists(DB_PATH) or not db_url:
        return

    logger.info("🔄 SQLite-dan PostgreSQL-ga ma'lumotlarni nusxalash (migratsiya) boshlandi...")
    pool = await get_pg_pool()
    async with pool.acquire() as pg_conn:
        tables = [
            "users", "admins", "game_assets", "bans", "warns", 
            "tournaments", "tournament_participants"
        ]

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            sqlite_tables = [r[0] for r in await cursor.fetchall()]
            
            for table in tables:
                if table not in sqlite_tables:
                    continue
                    
                try:
                    pg_count = await pg_conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                    if pg_count > 0:
                        logger.info(f"ℹ️ '{table}' jadvalida allaqachon ma'lumot bor. Nusxalash o'tkazib yuborildi.")
                        continue
                        
                    logger.info(f"📦 '{table}' jadvalidan ma'lumotlar ko'chirilmoqda...")
                    
                    db.row_factory = aiosqlite.Row
                    async with db.execute(f"SELECT * FROM {table}") as sqlite_cursor:
                        rows = await sqlite_cursor.fetchall()
                        if not rows:
                            continue
                            
                        cols = [d[0] for d in sqlite_cursor.description]
                        cols_quoted = [f'"{c}"' for c in cols]
                        col_str = ", ".join(cols_quoted)
                        val_str = ", ".join([f"${i+1}" for i in range(len(cols))])
                        
                        insert_query = f"INSERT INTO {table} ({col_str}) VALUES ({val_str}) ON CONFLICT DO NOTHING"
                        
                        count = 0
                        for row in rows:
                            vals = tuple(row)
                            await pg_conn.execute(insert_query, *vals)
                            count += 1
                            
                    logger.info(f"✅ '{table}' jadvalidan {count} ta qator muvaffaqiyatli nusxalandi.")
                except Exception as e:
                    logger.warning(f"⚠️ '{table}' jadvalini nusxalashda xatolik yuz berdi: {e}")
                    
    logger.info("🎉 SQLite-dan PostgreSQL-ga ma'lumotlar migratsiyasi yakunlandi.")


class DatabaseManager:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        self._cache: Dict[int, dict] = {}

    async def init_db(self):
        """Initializes tables for PostgreSQL or SQLite.
        
        PostgreSQL ulanishi muvaffaqiyatsiz bo'lsa, SQLite ga o'tadi.
        """
        queries = [
            """
            CREATE TABLE IF NOT EXISTS users (
                uid BIGINT PRIMARY KEY,
                username TEXT,
                name TEXT,
                money INT DEFAULT 100,
                shield INT DEFAULT 0,
                documents INT DEFAULT 0,
                active_role INT DEFAULT 0,
                immortality INT DEFAULT 0,
                games_played INT DEFAULT 0,
                games_won INT DEFAULT 0,
                last_played TEXT,
                photo TEXT,
                lang TEXT DEFAULT 'uz',
                premium INT DEFAULT 0
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS admins (
                uid BIGINT PRIMARY KEY
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS game_assets (
                key TEXT PRIMARY KEY,
                url TEXT NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS bans (
                uid BIGINT PRIMARY KEY,
                reason TEXT,
                banned_by BIGINT,
                banned_at TEXT
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS warns (
                id SERIAL PRIMARY KEY,
                uid BIGINT,
                reason TEXT,
                warned_by BIGINT,
                warned_at TEXT
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS tournaments (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                prize_amount INT DEFAULT 0,
                status TEXT DEFAULT 'open',
                winner_uid BIGINT,
                created_at TEXT
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS tournament_participants (
                tournament_id INT,
                uid BIGINT,
                points INT DEFAULT 0,
                wins INT DEFAULT 0,
                PRIMARY KEY (tournament_id, uid)
            );
            """
        ]

        # Avval PostgreSQL ulanishini tekshiramiz
        # _use_postgres() — ulanish muvaffaqiyatli bo'lsa True
        if _use_postgres():
            try:
                # Jadvallarni PostgreSQL da yaratamiz
                for q in queries:
                    await execute_query(q)

                # PostgreSQL specific migrations
                try:
                    await execute_query("SELECT premium FROM users LIMIT 0")
                except Exception:
                    try:
                        await execute_query("ALTER TABLE users ADD COLUMN premium INT DEFAULT 0")
                    except Exception:
                        pass

                # SQLite -> PostgreSQL migratsiya
                await migrate_sqlite_to_postgres()
                logger.info("✅ PostgreSQL jadvallari tayyor.")
                return
            except Exception as e:
                logger.error(f"❌ PostgreSQL init_db xatolik: {e}")
                logger.warning("⚠️ SQLite ga o'tilmoqda...")

        # SQLite fallback — SERIAL -> AUTOINCREMENT, BIGINT -> INTEGER
        sqlite_queries = []
        for q in queries:
            q = q.replace("BIGINT", "INTEGER").replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            sqlite_queries.append(q)
        for q in sqlite_queries:
            await execute_query(q)

        # SQLite specific migrations
        try:
            await execute_query("SELECT premium FROM users LIMIT 0")
        except Exception:
            try:
                await execute_query("ALTER TABLE users ADD COLUMN premium INTEGER DEFAULT 0")
            except Exception:
                pass
        logger.info("✅ SQLite jadvallari tayyor.")

    def _invalidate(self, uid: int):
        self._cache.pop(uid, None)

    async def ban_user(self, uid: int, reason: str, banned_by: int):
        from datetime import datetime
        now = datetime.now().isoformat()
        if _use_postgres():
            q = "INSERT INTO bans (uid, reason, banned_by, banned_at) VALUES ($1,$2,$3,$4) ON CONFLICT (uid) DO UPDATE SET reason=$5, banned_by=$6, banned_at=$7"
            await execute_query(q, uid, reason, banned_by, now, reason, banned_by, now)
        else:
            q = "INSERT OR REPLACE INTO bans (uid, reason, banned_by, banned_at) VALUES ($1,$2,$3,$4)"
            await execute_query(q, uid, reason, banned_by, now)

    async def unban_user(self, uid: int):
        await execute_query("DELETE FROM bans WHERE uid = $1", uid)

    async def is_banned(self, uid: int) -> Optional[dict]:
        return await fetch_row("SELECT * FROM bans WHERE uid = $1", uid)

    async def get_total_users(self) -> int:
        count = await fetch_val("SELECT COUNT(*) FROM users")
        return count or 0

    async def get_top_players(self, limit: int = 10) -> list:
        return await fetch_all("SELECT uid, name, username, games_played, games_won, money FROM users ORDER BY games_won DESC LIMIT $1", limit)

    async def get_user(self, uid: int) -> Optional[dict]:
        if uid in self._cache:
            return self._cache[uid].copy()
        row = await fetch_row("SELECT * FROM users WHERE uid = $1", uid)
        if row:
            self._cache[uid] = row.copy()
            return row
        return None

    async def create_user(self, uid: int, name: str = None, username: str = None):
        if _use_postgres():
            q = "INSERT INTO users (uid, name, username) VALUES ($1, $2, $3) ON CONFLICT (uid) DO NOTHING"
        else:
            q = "INSERT OR IGNORE INTO users (uid, name, username) VALUES ($1, $2, $3)"
        await execute_query(q, uid, name, username)
        self._invalidate(uid)

    async def update_user(self, uid: int, **kwargs):
        if not kwargs: return
        cols = ", ".join([f"{k} = ${i+1}" for i, k in enumerate(kwargs.keys())])
        vals = list(kwargs.values()) + [uid]
        query = f"UPDATE users SET {cols} WHERE uid = ${len(vals)}"
        await execute_query(query, *vals)
        self._invalidate(uid)

    async def get_admins(self) -> set:
        rows = await fetch_all("SELECT uid FROM admins")
        return {row['uid'] for row in rows}

    async def add_admin(self, uid: int):
        if _use_postgres():
            q = "INSERT INTO admins (uid) VALUES ($1) ON CONFLICT DO NOTHING"
        else:
            q = "INSERT OR IGNORE INTO admins (uid) VALUES ($1)"
        await execute_query(q, uid)

    async def remove_admin(self, uid: int):
        await execute_query("DELETE FROM admins WHERE uid = $1", uid)

    async def create_tournament(self, name: str, prize: int = 0):
        from datetime import datetime
        now = datetime.now().isoformat()
        await execute_query("INSERT INTO tournaments (name, prize_amount, created_at) VALUES ($1, $2, $3)", name, prize, now)

    async def get_tournaments(self):
        return await fetch_all("SELECT * FROM tournaments ORDER BY created_at DESC")

    async def join_tournament(self, tournament_id: int, uid: int):
        if _use_postgres():
            q = "INSERT INTO tournament_participants (tournament_id, uid) VALUES ($1, $2) ON CONFLICT DO NOTHING"
        else:
            q = "INSERT OR IGNORE INTO tournament_participants (tournament_id, uid) VALUES ($1, $2)"
        await execute_query(q, tournament_id, uid)

    async def get_tournament_leaderboard(self, tournament_id: int):
        q = """
            SELECT tp.*, u.name, u.username 
            FROM tournament_participants tp
            JOIN users u ON tp.uid = u.uid
            WHERE tp.tournament_id = $1
            ORDER BY tp.points DESC, tp.wins DESC
        """
        return await fetch_all(q, tournament_id)

    async def update_tournament_status(self, tournament_id: int, status: str):
        await execute_query("UPDATE tournaments SET status = $1 WHERE id = $2", status, tournament_id)

    async def finish_tournament(self, tournament_id: int):
        t = await fetch_row("SELECT * FROM tournaments WHERE id = $1", tournament_id)
        if not t or t['status'] == 'finished':
            return None
        
        winner_row = await fetch_row("""
            SELECT uid FROM tournament_participants 
            WHERE tournament_id = $1 
            ORDER BY points DESC, wins DESC LIMIT 1
        """, tournament_id)
        
        if winner_row:
            winner_uid = winner_row['uid']
            prize = t['prize_amount']
            await execute_query("UPDATE tournaments SET status = 'finished', winner_uid = $1 WHERE id = $2", winner_uid, tournament_id)
            await execute_query("UPDATE users SET money = money + $1 WHERE uid = $2", prize, winner_uid)
            self._invalidate(winner_uid)
            return {"uid": winner_uid, "prize": prize}
        return None

    async def get_asset_url(self, key: str, default: str) -> str:
        row = await fetch_row("SELECT url FROM game_assets WHERE key = $1", key)
        return row['url'] if row and 'url' in row else default

    async def set_asset_url(self, key: str, url: str):
        if _use_postgres():
            await execute_query("INSERT INTO game_assets (key, url) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET url = $3", key, url, url)
        else:
            await execute_query("INSERT OR REPLACE INTO game_assets (key, url) VALUES ($1, $2)", key, url)

DB = DatabaseManager()

async def get_uid_data(uid: int) -> dict:
    if uid == 0:
        return {"lang": "uz", "money": 0, "shield": 0, "documents": 0,
                "active_role": 0, "immortality": 0, "games_played": 0, "games_won": 0}
    data = await DB.get_user(uid)
    if not data:
        await DB.create_user(uid)
        data = await DB.get_user(uid)
    if not data:
        return {"uid": uid, "lang": "uz", "money": 100, "shield": 0, "documents": 0,
                "active_role": 0, "immortality": 0, "games_played": 0, "games_won": 0}
    return data
