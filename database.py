import os
import sqlite3
import json
import logging
from contextlib import contextmanager
from typing import Dict, List, Optional
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.is_pg = self.db_url is not None and self.db_url.startswith("postgres")
        # In-memory cache: {uid: dict}
        self._cache: Dict[int, dict] = {}
        self._init_db()

    def _get_conn(self):
        if self.is_pg:
            if not psycopg2:
                raise ImportError("psycopg2 is not installed but DATABASE_URL starts with postgres")
            return psycopg2.connect(self.db_url)
        else:
            conn = sqlite3.connect("mafia.db", check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn

    @contextmanager
    def _cursor(self, commit: bool = False):
        """
        Xavfsiz connection va cursor boshqaruvi uchun Context Manager.
        Avtomatik ravishda xatolik bo'lsa rollback qiladi va oxirida close qiladi.
        """
        conn = self._get_conn()
        try:
            if self.is_pg:
                cur = conn.cursor(cursor_factory=RealDictCursor)
            else:
                cur = conn.cursor()
            yield cur
            if commit:
                conn.commit()
        except Exception as e:
            if commit:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            cur.close()
            conn.close()

    def _invalidate(self, uid: int):
        self._cache.pop(uid, None)

    def _init_db(self):
        conn = self._get_conn()
        cur = conn.cursor()

        try:
            if self.is_pg:
                # ── STEP 1: Create parent tables ──
                cur.execute("""
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
                        photo BYTEA,
                        lang TEXT DEFAULT 'uz',
                        premium INT DEFAULT 0
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS admins (
                        uid BIGINT PRIMARY KEY
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS game_assets (
                        key TEXT PRIMARY KEY,
                        url TEXT NOT NULL
                    );
                """)
                conn.commit()

                # ── STEP 2: Migrations (BEFORE dependent tables!) ──
                # Migration: rename 'id' -> 'uid' in users table (legacy schema)
                try:
                    cur.execute("SELECT uid FROM users LIMIT 0;")
                except psycopg2.Error:
                    conn.rollback()
                    try:
                        cur.execute("SELECT id FROM users LIMIT 0;")
                        conn.rollback()
                        cur.execute("ALTER TABLE users RENAME COLUMN id TO uid;")
                        conn.commit()
                    except psycopg2.Error:
                        conn.rollback()

                # Migration: rename 'id' -> 'uid' in admins table (legacy schema)
                try:
                    cur.execute("SELECT uid FROM admins LIMIT 0;")
                except psycopg2.Error:
                    conn.rollback()
                    try:
                        cur.execute("SELECT id FROM admins LIMIT 0;")
                        conn.rollback()
                        cur.execute("ALTER TABLE admins RENAME COLUMN id TO uid;")
                        conn.commit()
                    except psycopg2.Error:
                        conn.rollback()

                # Migration: add 'premium' column if missing
                try:
                    cur.execute("SELECT premium FROM users LIMIT 0;")
                except psycopg2.Error:
                    conn.rollback()
                    try:
                        cur.execute("ALTER TABLE users ADD COLUMN premium INT DEFAULT 0;")
                        conn.commit()
                    except psycopg2.Error:
                        conn.rollback()

                # ── STEP 3: Create dependent tables (AFTER uid migration!) ──
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS bans (
                        uid BIGINT PRIMARY KEY,
                        reason TEXT,
                        banned_by BIGINT,
                        banned_at TEXT
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS warns (
                        id SERIAL PRIMARY KEY,
                        uid BIGINT,
                        reason TEXT,
                        warned_by BIGINT,
                        warned_at TEXT
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tournaments (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        prize_amount INT DEFAULT 0,
                        status TEXT DEFAULT 'open',
                        winner_uid BIGINT,
                        created_at TEXT
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tournament_participants (
                        tournament_id INT REFERENCES tournaments(id) ON DELETE CASCADE,
                        uid BIGINT REFERENCES users(uid),
                        points INT DEFAULT 0,
                        wins INT DEFAULT 0,
                        PRIMARY KEY (tournament_id, uid)
                    );
                """)
                conn.commit()

            else:
                # ── SQLite: Create all tables ──
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        uid INTEGER PRIMARY KEY,
                        username TEXT,
                        name TEXT,
                        money INTEGER DEFAULT 100,
                        shield INTEGER DEFAULT 0,
                        documents INTEGER DEFAULT 0,
                        active_role INTEGER DEFAULT 0,
                        immortality INTEGER DEFAULT 0,
                        games_played INTEGER DEFAULT 0,
                        games_won INTEGER DEFAULT 0,
                        last_played TEXT,
                        photo BLOB,
                        lang TEXT DEFAULT 'uz',
                        premium INTEGER DEFAULT 0
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS admins (
                        uid INTEGER PRIMARY KEY
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS game_assets (
                        key TEXT PRIMARY KEY,
                        url TEXT NOT NULL
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS bans (
                        uid INTEGER PRIMARY KEY,
                        reason TEXT,
                        banned_by INTEGER,
                        banned_at TEXT
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS warns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        uid INTEGER,
                        reason TEXT,
                        warned_by INTEGER,
                        warned_at TEXT
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tournaments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        prize_amount INTEGER DEFAULT 0,
                        status TEXT DEFAULT 'open',
                        winner_uid INTEGER,
                        created_at TEXT
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tournament_participants (
                        tournament_id INTEGER,
                        uid INTEGER,
                        points INTEGER DEFAULT 0,
                        wins INTEGER DEFAULT 0,
                        PRIMARY KEY (tournament_id, uid),
                        FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE,
                        FOREIGN KEY (uid) REFERENCES users(uid)
                    );
                """)
                conn.commit()

                # SQLite Migration: add 'premium' column if missing
                try:
                    cur.execute("SELECT premium FROM users LIMIT 0;")
                except sqlite3.OperationalError:
                    try:
                        cur.execute("ALTER TABLE users ADD COLUMN premium INTEGER DEFAULT 0;")
                        conn.commit()
                    except sqlite3.OperationalError:
                        pass
        finally:
            conn.close()

    def ban_user(self, uid: int, reason: str, banned_by: int):
        from datetime import datetime
        q = "INSERT INTO bans (uid, reason, banned_by, banned_at) VALUES (%s,%s,%s,%s) ON CONFLICT (uid) DO UPDATE SET reason=%s, banned_by=%s, banned_at=%s" if self.is_pg else \
            "INSERT OR REPLACE INTO bans (uid, reason, banned_by, banned_at) VALUES (?,?,?,?)"
        now = datetime.now().isoformat()
        with self._cursor(commit=True) as cur:
            if self.is_pg:
                cur.execute(q, (uid, reason, banned_by, now, reason, banned_by, now))
            else:
                cur.execute(q, (uid, reason, banned_by, now))

    def unban_user(self, uid: int):
        with self._cursor(commit=True) as cur:
            cur.execute("DELETE FROM bans WHERE uid = %s" if self.is_pg else "DELETE FROM bans WHERE uid = ?", (uid,))

    def is_banned(self, uid: int) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM bans WHERE uid = %s" if self.is_pg else "SELECT * FROM bans WHERE uid = ?", (uid,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_total_users(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            return cur.fetchone()[0]

    def get_top_players(self, limit: int = 10) -> list:
        with self._cursor() as cur:
            cur.execute(
                "SELECT uid, name, username, games_played, games_won, money FROM users ORDER BY games_won DESC LIMIT %s" if self.is_pg else
                "SELECT uid, name, username, games_played, games_won, money FROM users ORDER BY games_won DESC LIMIT ?",
                (limit,)
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def get_user(self, uid: int) -> Optional[dict]:
        if uid in self._cache:
            return self._cache[uid].copy()
        with self._cursor() as cur:
            cur.execute("SELECT * FROM users WHERE uid = %s" if self.is_pg else "SELECT * FROM users WHERE uid = ?", (uid,))
            row = cur.fetchone()
            if row:
                data = dict(row)
                self._cache[uid] = data.copy()
                return data
            return None

    def create_user(self, uid: int, name: str = None, username: str = None):
        query = """
            INSERT INTO users (uid, name, username) 
            VALUES (%s, %s, %s)
            ON CONFLICT (uid) DO NOTHING
        """ if self.is_pg else """
            INSERT OR IGNORE INTO users (uid, name, username)
            VALUES (?, ?, ?)
        """
        with self._cursor(commit=True) as cur:
            cur.execute(query, (uid, name, username))
        self._invalidate(uid)

    def update_user(self, uid: int, **kwargs):
        if not kwargs: return
        cols = ", ".join([f"{k} = %s" if self.is_pg else f"{k} = ?" for k in kwargs.keys()])
        vals = list(kwargs.values()) + [uid]
        query = f"UPDATE users SET {cols} WHERE uid = %s" if self.is_pg else f"UPDATE users SET {cols} WHERE uid = ?"
        with self._cursor(commit=True) as cur:
            cur.execute(query, vals)
        self._invalidate(uid)

    def get_admins(self) -> set:
        with self._cursor() as cur:
            cur.execute("SELECT uid FROM admins")
            rows = cur.fetchall()
            return {row[0] for row in rows}

    def add_admin(self, uid: int):
        query = "INSERT INTO admins (uid) VALUES (%s) ON CONFLICT DO NOTHING" if self.is_pg else "INSERT OR IGNORE INTO admins (uid) VALUES (?)"
        with self._cursor(commit=True) as cur:
            cur.execute(query, (uid,))

    def remove_admin(self, uid: int):
        with self._cursor(commit=True) as cur:
            cur.execute("DELETE FROM admins WHERE uid = %s" if self.is_pg else "DELETE FROM admins WHERE uid = ?", (uid,))

    # ── TOURNAMENTS ──
    def create_tournament(self, name: str, prize: int = 0):
        from datetime import datetime
        now = datetime.now().isoformat()
        with self._cursor(commit=True) as cur:
            cur.execute("INSERT INTO tournaments (name, prize_amount, created_at) VALUES (%s, %s, %s)" if self.is_pg else
                        "INSERT INTO tournaments (name, prize_amount, created_at) VALUES (?, ?, ?)", (name, prize, now))

    def get_tournaments(self):
        with self._cursor() as cur:
            cur.execute("SELECT * FROM tournaments ORDER BY created_at DESC")
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def join_tournament(self, tournament_id: int, uid: int):
        query = "INSERT INTO tournament_participants (tournament_id, uid) VALUES (%s, %s) ON CONFLICT DO NOTHING" if self.is_pg else \
                "INSERT OR IGNORE INTO tournament_participants (tournament_id, uid) VALUES (?, ?)"
        with self._cursor(commit=True) as cur:
            cur.execute(query, (tournament_id, uid))

    def get_tournament_leaderboard(self, tournament_id: int):
        with self._cursor() as cur:
            cur.execute("""
                SELECT tp.*, u.name, u.username 
                FROM tournament_participants tp
                JOIN users u ON tp.uid = u.uid
                WHERE tp.tournament_id = %s
                ORDER BY tp.points DESC, tp.wins DESC
            """ if self.is_pg else """
                SELECT tp.*, u.name, u.username 
                FROM tournament_participants tp
                JOIN users u ON tp.uid = u.uid
                WHERE tp.tournament_id = ?
                ORDER BY tp.points DESC, tp.wins DESC
            """, (tournament_id,))
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def update_tournament_status(self, tournament_id: int, status: str):
        with self._cursor(commit=True) as cur:
            cur.execute("UPDATE tournaments SET status = %s WHERE id = %s" if self.is_pg else
                        "UPDATE tournaments SET status = ? WHERE id = ?", (status, tournament_id))

    def finish_tournament(self, tournament_id: int):
        """Turnirni yakunlash va g'olibga sovg'ani berish"""
        with self._cursor(commit=True) as cur:
            # Turnir info olish
            cur.execute("SELECT * FROM tournaments WHERE id = %s" if self.is_pg else "SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
            t = cur.fetchone()
            if not t or t['status'] == 'finished':
                return None
            
            # G'olibni aniqlash (leaderboard top 1)
            cur.execute("""
                SELECT uid FROM tournament_participants 
                WHERE tournament_id = %s 
                ORDER BY points DESC, wins DESC LIMIT 1
            """ if self.is_pg else """
                SELECT uid FROM tournament_participants 
                WHERE tournament_id = ? 
                ORDER BY points DESC, wins DESC LIMIT 1
            """, (tournament_id,))
            winner_row = cur.fetchone()
            
            if winner_row:
                winner_uid = winner_row['uid']
                prize = t['prize_amount']
                
                # 1. Turnir statusini yangilash
                cur.execute("UPDATE tournaments SET status = 'finished', winner_uid = %s WHERE id = %s" if self.is_pg else
                            "UPDATE tournaments SET status = 'finished', winner_uid = ? WHERE id = ?", (winner_uid, tournament_id))
                
                # 2. G'olibning balansiga pul qo'shish (botda avtomatik)
                # Pulni users table-da yangilash
                cur.execute("UPDATE users SET money = money + %s WHERE uid = %s" if self.is_pg else
                            "UPDATE users SET money = money + ? WHERE uid = ?", (prize, winner_uid))
                
                self._invalidate(winner_uid)
                return {"uid": winner_uid, "prize": prize}
            
            return None

    def get_asset_url(self, key: str, default: str) -> str:
        try:
            with self._cursor() as cur:
                cur.execute("SELECT url FROM game_assets WHERE key = %s" if self.is_pg else "SELECT url FROM game_assets WHERE key = ?", (key,))
                row = cur.fetchone()
                return row['url'] if row and 'url' in row else (row[0] if row else default)
        except Exception as e:
            logger.error(f"Error getting asset url for {key}: {e}")
            return default

    def set_asset_url(self, key: str, url: str):
        try:
            with self._cursor(commit=True) as cur:
                if self.is_pg:
                    cur.execute("INSERT INTO game_assets (key, url) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET url = %s", (key, url, url))
                else:
                    cur.execute("INSERT OR REPLACE INTO game_assets (key, url) VALUES (?, ?)", (key, url))
        except Exception as e:
            logger.error(f"Error setting asset url for {key}: {e}")


DB = DatabaseManager()

def get_uid_data(uid: int) -> dict:
    if uid == 0:
        return {"lang": "uz", "money": 0, "shield": 0, "documents": 0,
                "active_role": 0, "immortality": 0, "games_played": 0, "games_won": 0}
    data = DB.get_user(uid)
    if not data:
        DB.create_user(uid)
        data = DB.get_user(uid)
    if not data:
        return {"uid": uid, "lang": "uz", "money": 100, "shield": 0, "documents": 0,
                "active_role": 0, "immortality": 0, "games_played": 0, "games_won": 0}
    return data
