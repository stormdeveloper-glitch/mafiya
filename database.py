import os
import sqlite3
import json
import logging
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

    def _invalidate(self, uid: int):
        self._cache.pop(uid, None)

    def _init_db(self):
        conn = self._get_conn()
        cur = conn.cursor()
        if self.is_pg:
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
                    lang TEXT DEFAULT 'uz'
                );
                CREATE TABLE IF NOT EXISTS admins (
                    uid BIGINT PRIMARY KEY
                );
            """)
        else:
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
                    lang TEXT DEFAULT 'uz'
                );
                CREATE TABLE IF NOT EXISTS admins (
                    uid INTEGER PRIMARY KEY
                );
            """)
        
        if self.is_pg:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bans (
                    uid BIGINT PRIMARY KEY,
                    reason TEXT,
                    banned_by BIGINT,
                    banned_at TEXT
                );
                CREATE TABLE IF NOT EXISTS warns (
                    id SERIAL PRIMARY KEY,
                    uid BIGINT,
                    reason TEXT,
                    warned_by BIGINT,
                    warned_at TEXT
                );
                CREATE TABLE IF NOT EXISTS tournaments (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    prize_amount INT DEFAULT 0,
                    status TEXT DEFAULT 'open', -- open, active, finished
                    winner_uid BIGINT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS tournament_participants (
                    tournament_id INT REFERENCES tournaments(id) ON DELETE CASCADE,
                    uid BIGINT REFERENCES users(uid),
                    points INT DEFAULT 0,
                    wins INT DEFAULT 0,
                    PRIMARY KEY (tournament_id, uid)
                );
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bans (
                    uid INTEGER PRIMARY KEY,
                    reason TEXT,
                    banned_by INTEGER,
                    banned_at TEXT
                );
                CREATE TABLE IF NOT EXISTS warns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid INTEGER,
                    reason TEXT,
                    warned_by INTEGER,
                    warned_at TEXT
                );
                CREATE TABLE IF NOT EXISTS tournaments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    prize_amount INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'open',
                    winner_uid INTEGER,
                    created_at TEXT
                );
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
        conn.close()

    def ban_user(self, uid: int, reason: str, banned_by: int):
        from datetime import datetime
        conn = self._get_conn(); cur = conn.cursor()
        q = "INSERT INTO bans (uid, reason, banned_by, banned_at) VALUES (%s,%s,%s,%s) ON CONFLICT (uid) DO UPDATE SET reason=%s, banned_by=%s, banned_at=%s" if self.is_pg else \
            "INSERT OR REPLACE INTO bans (uid, reason, banned_by, banned_at) VALUES (?,?,?,?)"
        now = datetime.now().isoformat()
        if self.is_pg:
            cur.execute(q, (uid, reason, banned_by, now, reason, banned_by, now))
        else:
            cur.execute(q, (uid, reason, banned_by, now))
        conn.commit(); conn.close()

    def unban_user(self, uid: int):
        conn = self._get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM bans WHERE uid = %s" if self.is_pg else "DELETE FROM bans WHERE uid = ?", (uid,))
        conn.commit(); conn.close()

    def is_banned(self, uid: int) -> Optional[dict]:
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if self.is_pg else conn.cursor()
        cur.execute("SELECT * FROM bans WHERE uid = %s" if self.is_pg else "SELECT * FROM bans WHERE uid = ?", (uid,))
        row = cur.fetchone(); conn.close()
        return dict(row) if row else None

    def get_total_users(self) -> int:
        conn = self._get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        count = cur.fetchone()[0]; conn.close()
        return count

    def get_top_players(self, limit: int = 10) -> list:
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if self.is_pg else conn.cursor()
        cur.execute(
            "SELECT uid, name, username, games_played, games_won, money FROM users ORDER BY games_won DESC LIMIT %s" if self.is_pg else
            "SELECT uid, name, username, games_played, games_won, money FROM users ORDER BY games_won DESC LIMIT ?",
            (limit,)
        )
        rows = cur.fetchall(); conn.close()
        return [dict(r) for r in rows]

    def get_user(self, uid: int) -> Optional[dict]:
        if uid in self._cache:
            return self._cache[uid]
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if self.is_pg else conn.cursor()
        cur.execute("SELECT * FROM users WHERE uid = %s" if self.is_pg else "SELECT * FROM users WHERE uid = ?", (uid,))
        row = cur.fetchone(); conn.close()
        if row:
            data = dict(row)
            self._cache[uid] = data
            return data
        return None

    def create_user(self, uid: int, name: str = None, username: str = None):
        conn = self._get_conn(); cur = conn.cursor()
        query = """
            INSERT INTO users (uid, name, username) 
            VALUES (%s, %s, %s)
            ON CONFLICT (uid) DO NOTHING
        """ if self.is_pg else """
            INSERT OR IGNORE INTO users (uid, name, username)
            VALUES (?, ?, ?)
        """
        cur.execute(query, (uid, name, username))
        conn.commit(); conn.close()
        self._invalidate(uid)

    def update_user(self, uid: int, **kwargs):
        if not kwargs: return
        conn = self._get_conn(); cur = conn.cursor()
        cols = ", ".join([f"{k} = %s" if self.is_pg else f"{k} = ?" for k in kwargs.keys()])
        vals = list(kwargs.values()) + [uid]
        query = f"UPDATE users SET {cols} WHERE uid = %s" if self.is_pg else f"UPDATE users SET {cols} WHERE uid = ?"
        cur.execute(query, vals)
        conn.commit(); conn.close()
        self._invalidate(uid)

    def get_admins(self) -> set:
        conn = self._get_conn(); cur = conn.cursor()
        cur.execute("SELECT uid FROM admins")
        rows = cur.fetchall(); conn.close()
        return {row[0] for row in rows}

    def add_admin(self, uid: int):
        conn = self._get_conn(); cur = conn.cursor()
        query = "INSERT INTO admins (uid) VALUES (%s) ON CONFLICT DO NOTHING" if self.is_pg else "INSERT OR IGNORE INTO admins (uid) VALUES (?)"
        cur.execute(query, (uid,))
        conn.commit(); conn.close()

    def remove_admin(self, uid: int):
        conn = self._get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM admins WHERE uid = %s" if self.is_pg else "DELETE FROM admins WHERE uid = ?", (uid,))
        conn.commit(); conn.close()

    # ── TOURNAMENTS ──
    def create_tournament(self, name: str, prize: int = 0):
        from datetime import datetime
        conn = self._get_conn(); cur = conn.cursor()
        now = datetime.now().isoformat()
        cur.execute("INSERT INTO tournaments (name, prize_amount, created_at) VALUES (%s, %s, %s)" if self.is_pg else
                    "INSERT INTO tournaments (name, prize_amount, created_at) VALUES (?, ?, ?)", (name, prize, now))
        conn.commit(); conn.close()

    def get_tournaments(self):
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if self.is_pg else conn.cursor()
        cur.execute("SELECT * FROM tournaments ORDER BY created_at DESC")
        rows = cur.fetchall(); conn.close()
        return [dict(r) for r in rows]

    def join_tournament(self, tournament_id: int, uid: int):
        conn = self._get_conn(); cur = conn.cursor()
        query = "INSERT INTO tournament_participants (tournament_id, uid) VALUES (%s, %s) ON CONFLICT DO NOTHING" if self.is_pg else \
                "INSERT OR IGNORE INTO tournament_participants (tournament_id, uid) VALUES (?, ?)"
        cur.execute(query, (tournament_id, uid))
        conn.commit(); conn.close()

    def get_tournament_leaderboard(self, tournament_id: int):
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if self.is_pg else conn.cursor()
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
        rows = cur.fetchall(); conn.close()
        return [dict(r) for r in rows]

    def update_tournament_status(self, tournament_id: int, status: str):
        conn = self._get_conn(); cur = conn.cursor()
        cur.execute("UPDATE tournaments SET status = %s WHERE id = %s" if self.is_pg else
                    "UPDATE tournaments SET status = ? WHERE id = ?", (status, tournament_id))
        conn.commit(); conn.close()

    def finish_tournament(self, tournament_id: int):
        """Turnirni yakunlash va g'olibga sovg'ani berish"""
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if self.is_pg else conn.cursor()
        
        # Turnir info olish
        cur.execute("SELECT * FROM tournaments WHERE id = %s" if self.is_pg else "SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
        t = cur.fetchone()
        if not t or t['status'] == 'finished':
            conn.close(); return None
        
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
            # Foydalanuvchi ma'lumotlarini cache dan o'chirib, update qilamiz
            self._invalidate(winner_uid)
            # Pulni users table-da yangilash
            cur.execute("UPDATE users SET money = money + %s WHERE uid = %s" if self.is_pg else
                        "UPDATE users SET money = money + ? WHERE uid = ?", (prize, winner_uid))
            
            conn.commit(); conn.close()
            return {"uid": winner_uid, "prize": prize}
        
        conn.close()
        return None

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
