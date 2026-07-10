# advanced_secret_mafia_bot.py
# PROFESSIONAL PRODUCTION VERSION - CLASSIC MAFIA GAME

import asyncio
import random
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
import argparse
import sys
import html
import re
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ApplicationHandlerStop,
)

# ================== LOGGING ==================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================== CONFIG ==================

import os
import httpx
import base64
from dotenv import load_dotenv
import admin as adm
from downloader import download_instagram_video

load_dotenv()

UPDATE_VERSION = "2.2"
BOT_USERNAME = None

# CLI Argumentlarni tekshirish
parser = argparse.ArgumentParser(description="Mafia Bot Instance")
parser.add_argument("--token", help="Bot Token")
parser.add_argument("--admin", type=int, help="Admin User ID")
args, unknown = parser.parse_known_args()

BOT_TOKEN = args.token or os.getenv("BOT_TOKEN")
ADMIN_ID = args.admin or int(os.getenv("ADMIN_ID", "0"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

CHANNEL_ID = -1003882935867  # Official Channel ID
POST_GAMES_TO_CHANNEL = False  # O'yin natijalarini kanalga yuborish

# Premium Config (Persistent state should be in DB, but for now in memory/file)
PREMIUM_CONFIG = {
    "items": {
        "shield": {"price": 20, "enabled": True},
        "documents": {"price": 15, "enabled": True},
        "active_role": {"price": 25, "enabled": True},
        "immortality": {"price": 50, "enabled": True},
        "death_note": {"price": 200, "enabled": True},
        "radar": {"price": 5000, "enabled": True},
    },
    "roles": {
        "samurai": {"enabled": True},
        "ninja": {"enabled": True},
    }
}

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi. Railway Variables yoki .env ni tekshiring.")

MAX_GAMES = 100
COMMAND_COOLDOWN = 2
MIN_PLAYERS = 3
MAX_PLAYERS = 50

# ESLATMA: Private kanal linklaridan bot rasm yubora olmaydi.
# Agar rasmlar kerak bo'lsa, public URL yoki file_id bilan almashtiring.
# Hozirda xato bo'lsa matnga fallback qiladi.
DAY_IMAGE_URL = "https://t.me/c/3882935867/12"
NIGHT_IMAGE_URL = "https://t.me/c/3882935867/13"

REGISTRATION_TIME = 120
NIGHT_DURATION = 60
DAY_DURATION = 120
VOTING_DURATION = 60

WIN_REWARD = 60

# ================== PERSISTENT STORAGE ==================

# ================== DATABASE & STORAGE ==================
import sqlite3
from contextlib import contextmanager
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None


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
                        tournament_id INT,
                        uid BIGINT,
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
                        PRIMARY KEY (tournament_id, uid)
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

import io

def migrate_from_json():
    """Lokal JSON ma'lumotlarini bazaga ko'chirish"""
    if os.path.exists("users.json"):
        try:
            with open("users.json", "r") as f:
                data = json.load(f)
                for uid_str, d in data.items():
                    uid = int(uid_str)
                    if not DB.get_user(uid):
                        DB.create_user(uid, d.get("name"), d.get("username"))
                        DB.update_user(uid, 
                            money=d.get("money", 100),
                            shield=d.get("shield", 0),
                            documents=d.get("documents", 0),
                            active_role=d.get("active_role", 0),
                            immortality=d.get("immortality", 0),
                            games_played=d.get("games_played", 0),
                            games_won=d.get("games_won", 0),
                            last_played=d.get("last_played"),
                            lang=d.get("lang", "uz")
                        )
            logger.info("JSON data migrated to Database successfully.")
        except Exception as e:
            logger.error(f"Migration error: {e}")

    if os.path.exists("admins.json"):
        try:
            with open("admins.json", "r") as f:
                data = json.load(f)
                for aid in data.get("admins", []):
                    DB.add_admin(aid)
            logger.info("Admin data migrated successfully.")
        except Exception as e:
            logger.error(f"Admin migration error: {e}")

migrate_from_json()

# ================== COMMAND COOLDOWN ==================

user_cooldowns: Dict[int, float] = {}

def check_cooldown(uid: int) -> bool:
    """True qaytarsa - kutish kerak"""
    now = datetime.now().timestamp()
    if uid in user_cooldowns:
        if now - user_cooldowns[uid] < COMMAND_COOLDOWN:
            return True
    user_cooldowns[uid] = now
    return False

def cooldown_msg(uid: int) -> str:
    """Cooldown xabari foydalanuvchi tili asosida"""
    remaining = max(0, int(COMMAND_COOLDOWN - (datetime.now().timestamp() - user_cooldowns.get(uid, 0))))
    user_data = get_uid_data(uid)
    lang = user_data.get("lang", "uz")
    msgs = {
        "uz": f"⏱️ {remaining} soniyaga kutib turing",
        "ru": f"⏱️ Подождите {remaining} сек",
        "en": f"⏱️ Wait {remaining} sec"
    }
    return msgs.get(lang, msgs["uz"])

# ================== SHOP ITEMS ==================

SHOP_ITEMS = {
    "uz": {
        "shield": {
            "name": "🌀 Qalqon (Shield)",
            "emoji": "🌀",
            "type": "",
            "desc": "Tungi himoya - O'limdan saqlaydi",
            "price": 20
        },
        "documents": {
            "name": "🎭 Niqob (Mask)",
            "emoji": "🎭",
            "type": "",
            "desc": "Rolingizni yashiradi",
            "price": 15
        },
        "active_role": {
            "name": "⚡ Faol Rol (Active Card)",
            "emoji": "⚡",
            "type": "",
            "desc": "Tunda faol bo'ladigan rol beradi",
            "price": 25
        },
        "immortality": {
            "name": "♾️ O'lmaslik (Immortality)",
            "emoji": "♾️",
            "type": "",
            "desc": "O'yin davomida doimiy o'lmaslik",
            "price": 50
        },
        "death_note": {
            "name": "📓 Qotillik Daftari",
            "emoji": "📓",
            "type": "",
            "desc": "Bir martalik o'ldirish huquqi",
            "price": 100
        },
        "radar": {
            "name": "📡 Radar",
            "emoji": "📡",
            "type": "",
            "desc": "Mafiyani aniqlash (100%)",
            "price": 5000
        },
    },
    "ru": {
        "shield": {
            "name": "🌀 Щит (Shield)",
            "emoji": "🌀",
            "type": "",
            "desc": "Защита ночью - спасает от смерти",
            "price": 20
        },
        "documents": {
            "name": "🎭 Маска (Mask)",
            "emoji": "🎭",
            "type": "",
            "desc": "Скрывает вашу роль",
            "price": 15
        },
        "active_role": {
            "name": "⚡ Активная роль",
            "emoji": "⚡",
            "type": "",
            "desc": "Дает активную роль на ночь",
            "price": 25
        },
        "immortality": {
            "name": "♾️ Бессмертие",
            "emoji": "♾️",
            "type": "",
            "desc": "Постоянное бессмертие в игре",
            "price": 50
        },
        "death_note": {
            "name": "📓 Тетрадь Смерти",
            "emoji": "📓",
            "type": "",
            "desc": "Одноразовое право на убийство",
            "price": 100
        },
        "radar": {
            "name": "📡 Радар",
            "emoji": "📡",
            "type": "",
            "desc": "Обнаружение мафии (100%)",
            "price": 5000
        },
    },
    "en": {
        "shield": {
            "name": "🌀 Shield",
            "emoji": "🌀",
            "type": "",
            "desc": "Night protection - saves from death",
            "price": 20
        },
        "documents": {
            "name": "🎭 Mask",
            "emoji": "🎭",
            "type": "",
            "desc": "Hides your role",
            "price": 15
        },
        "active_role": {
            "name": "⚡ Active Role Card",
            "emoji": "⚡",
            "type": "",
            "desc": "Gives you an active role at night",
            "price": 25
        },
        "immortality": {
            "name": "♾️ Immortality",
            "emoji": "♾️",
            "type": "",
            "desc": "Permanent immortality in the game",
            "price": 50
        },
        "death_note": {
            "name": "📓 Death Note",
            "emoji": "📓",
            "type": "",
            "desc": "One-time kill right",
            "price": 100
        },
        "radar": {
            "name": "📡 Radar",
            "emoji": "📡",
            "type": "",
            "desc": "Detect Mafia (100%)",
            "price": 5000
        },
    },
}

# ================== CHARACTER UNIQUE ABILITIES ==================

CHARACTER_ABILITIES = {}

# ================== GAME CONFIGS ==================

# ================== LANGUAGE ==================

LANGUAGES = {
    "uz": {
        "need_admin": "❗ Bot guruhda ADMIN bo'lishi shart!",
        "make_admin": "📌 Botni admin qiling va qayta urinib ko'ring.",
        "reg_started": "📝 Ro'yxatdan o'tish boshlandi",
        "joined": "✅ Siz o'yinga qo'shildingiz",
        "already_joined": "⚠️ Siz allaqachon qo'shilgansiz",
        "night": "🌙 Kecha boshlandi\n🤫 Shahar uxlayapti...",
        "day": "☀️ Tong otdi\n💬 Endi bahslashish mumkin",
        "vote_used": "⚠️ Siz allaqachon ovoz bergansiz",
        "shop_blocked": "⛔ O'yin davomida shop yopiq!",
        "not_enough_money": "❌ Pul yetarli emas",
        "gift_sent": "🎁 Sovg'a yuborildi",
        "lang_set": "✅ Til o'zgartirildi",
        "balance": "💰 Balans: {} coin",
        "shop_menu": "🛍 Magazin:",
        "you_are": "👤 Siz: {}",
        "mafia_target": "🎯 Bugun kimni o'ldirasiz?",
        "doctor_heal": "⚕️ Bugun kimni davolaysiz?",
        "killer_show": "🔎 Bugun kim haqida o'rganasiz?",
        "sheriff_check": "🕵️‍♂️ Bugun kimni tekshirasiz?",
        "maniac_kill": "🔪 Bugun kimni qurbon qilasiz?",
        "sheriff_result": "🕵️‍♂️ Tekshirish natijasi: {}",
        "maniac_result": "🔪 Qurbon tanlandi",
        "target_selected": "✅ Maqsad tanlandi",
        "samurai_kill": "⚔️ Kimni qatl qilamiz? (Ehtiyot bo'ling: begunohni o'ldirsangiz, o'zingiz ham halok bo'lasiz!)",
        "ninja_watch": "👁️ Kimni kuzatamiz?",
        "game_end": "🏁 O'yin tugadi!\n{}: {}\n💰 G'alaba: {} coin",
        "night_actions": "🌙 Kechadagi harakatlar kutilmoqda...",
        "eliminated": "💀 {} o'ldirildi!",
        "hung": "🪤 {} osib o'ldirildi!",
        "healed": "💚 {} saqlandi!",
        "investigated": "🔎 Tekshirish natijalari yuborildi",
        "insufficient_players": "❌ O'yin uchun kamida 3 ta o'yinchi kerak",
        "not_admin": "❌ Siz admin emasiz",
        "admin_only": "🔐 Admin uchun buyruq",
        "game_stopped": "🛑 O'yin to'xtatildi",
        "game_not_found": "❌ O'yin topilmadi",
        "admin_panel": "👨‍💼 Admin Panel",
        "stop_game": "🛑 O'yinni to'xtating",
        "reset_game": "📝 Yangi o'yin",
        "admins_list": "👨‍💼 Adminlar",
        "voting_start": "🗳️ Ovoz berish boshlandi! Kim aybdor?",
        "no_votes": "Hech kim ovoz bermadi, o'yin davom etadi",
        "hang": "Osib o'ldirish",
        "save": "Saqlash",
        "accused": "⚖️ Ayblanuvchi: {}",
    },
    "ru": {
        "need_admin": "❗ Бот должен быть администратором!",
        "make_admin": "📌 Сделайте бота администратором и попробуйте снова.",
        "reg_started": "📝 Регистрация началась",
        "joined": "✅ Вы присоединились",
        "already_joined": "⚠️ Вы уже в игре",
        "night": "🌙 Ночь наступила\n🤫 Город спит...",
        "day": "☀️ Утро наступило\n💬 Можно обсуждать",
        "vote_used": "⚠️ Вы уже голосовали",
        "shop_blocked": "⛔ Магазин закрыт!",
        "not_enough_money": "❌ Недостаточно средств",
        "gift_sent": "🎁 Подарок отправлен",
        "lang_set": "✅ Язык изменён",
        "balance": "💰 Баланс: {} монет",
        "shop_menu": "🛍 Магазин:",
        "you_are": "👤 Вы: {}",
        "mafia_target": "🎯 Кого убить?",
        "doctor_heal": "⚕️ Кого лечить?",
        "killer_show": "🔎 Кого проверить?",
        "sheriff_check": "🕵️‍♂️ Кого проверить?",
        "maniac_kill": "🔪 Кого принести в жертву?",
        "sheriff_result": "🕵️‍♂️ Результат проверки: {}",
        "maniac_result": "🔪 Жертва выбрана",
        "target_selected": "✅ Цель выбрана",
        "game_end": "🏁 Игра окончена!\n{}: {}\n💰 Награда: {} монет",
        "night_actions": "🌙 Ожидаются ночные действия...",
        "eliminated": "💀 {} убит!",
        "hung": "🪤 {} повешен!",
        "healed": "💚 {} спасен!",
        "investigated": "🔎 Результаты отправлены",
        "insufficient_players": "❌ Нужно минимум 3 игрока",
        "not_admin": "❌ Вы не администратор",
        "admin_only": "🔐 Команда для админов",
        "game_stopped": "🛑 Игра остановлена",
        "game_not_found": "❌ Игра не найдена",
        "admin_panel": "👨‍💼 Панель админа",
        "stop_game": "🛑 Остановить игру",
        "reset_game": "📝 Новая игра",
        "admins_list": "👨‍💼 Администраторы",
        "voting_start": "🗳️ Голосование началось! Кто виновен?",
        "no_votes": "Никто не проголосовал, игра продолжается",
        "hang": "Повесить",
        "save": "Спасти",
        "accused": "⚖️ Обвиняемый: {}",
    },
    "en": {
        "need_admin": "❗ Bot must be an admin!",
        "make_admin": "📌 Make the bot admin and try again.",
        "reg_started": "📝 Registration started",
        "joined": "✅ You joined the game",
        "already_joined": "⚠️ You already joined",
        "night": "🌙 Night started\n🤫 City sleeps...",
        "day": "☀️ Morning started\n💬 Discussion allowed",
        "vote_used": "⚠️ You already voted",
        "shop_blocked": "⛔ Shop is closed during the game!",
        "not_enough_money": "❌ Not enough money",
        "gift_sent": "🎁 Gift sent",
        "lang_set": "✅ Language updated",
        "balance": "💰 Balance: {} coins",
        "shop_menu": "🛍 Shop:",
        "you_are": "👤 You are: {}",
        "mafia_target": "🎯 Who to kill tonight?",
        "doctor_heal": "⚕️ Who to heal tonight?",
        "killer_show": "🔎 Who to investigate tonight?",
        "sheriff_check": "🕵️‍♂️ Who to investigate?",
        "maniac_kill": "🔪 Who to sacrifice?",
        "sheriff_result": "🕵️‍♂️ Investigation result: {}",
        "maniac_result": "🔪 Victim selected",
        "target_selected": "✅ Target selected",
        "game_end": "🏁 Game Over!\n{}: {}\n💰 Reward: {} coins",
        "night_actions": "🌙 Waiting for night actions...",
        "eliminated": "💀 {} eliminated!",
        "hung": "🪤 {} hanged!",
        "healed": "💚 {} saved!",
        "investigated": "🔎 Investigation results sent",
        "insufficient_players": "❌ Need at least 3 players",
        "not_admin": "❌ You are not an admin",
        "admin_only": "🔐 Admin command",
        "game_stopped": "🛑 Game stopped",
        "game_not_found": "❌ Game not found",
        "admin_panel": "👨‍💼 Admin Panel",
        "stop_game": "🛑 Stop game",
        "reset_game": "📝 New game",
        "admins_list": "👨‍💼 Admins",
        "voting_start": "🗳️ Voting started! Who is guilty?",
        "no_votes": "Nobody voted, game continues",
        "hang": "Hang",
        "save": "Save",
        "accused": "⚖️ Accused: {}",
    },
}

def t(uid: int, key: str) -> str:
    """Foydalanuvchi tili asosida matn qaytarish"""
    user_data = get_uid_data(uid)
    lang = user_data.get("lang", "uz")
    return LANGUAGES.get(lang, LANGUAGES["uz"]).get(key, key)

# ================== DATA MODELS ==================

class Player:
    def __init__(self, uid: int, name: str):
        self.id = uid
        self.name = name
        self.alive = True
        self.role: Optional[str] = None
        self.character: Optional[dict] = None
        self.shield = 1  # Hammaga default shield
        self.has_documents = False
        self.active_role = False
        self.last_words = ""

class Game:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.state = "registration"
        self.players: Dict[int, Player] = {}
        self.reg_msg_id: Optional[int] = None
        self.used_night: set = set()
        self.night_actions: List[dict] = []
        self.private_votes: Dict[int, int] = {}
        self.public_votes: Dict[str, set] = {"like": set(), "dislike": set()}
        self.round = 0
        self._accused_target: Optional[int] = None   # final vote ayblanuvchi
        self._vote_msg_id: Optional[int] = None      # guruh ovoz xabar ID

games: Dict[int, Game] = {}

# Bot username (post_init da to'ldiriladi)
BOT_USERNAME: str = ""

# ================== JSON SESSION STORAGE ==================

SESSION_FILE = "session_players.json"

def session_save(chat_id: int):
    """Ro'yxatdagi o'yinchilarni JSON ga yozish"""
    try:
        # Mavjud faylni o'qish
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}

        game = games.get(chat_id)
        if game and game.state == "registration":
            data[str(chat_id)] = {
                "chat_id": chat_id,
                "reg_msg_id": game.reg_msg_id,
                "created_at": datetime.now().isoformat(),
                "players": [
                    {"uid": p.id, "name": p.name}
                    for p in game.players.values()
                ]
            }
        else:
            data.pop(str(chat_id), None)

        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"session_save xatosi: {e}")

def session_remove(chat_id: int):
    """O'yin tugaganda JSON dan o'chirish"""
    try:
        if not os.path.exists(SESSION_FILE):
            return
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.pop(str(chat_id), None)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"session_remove xatosi: {e}")

def session_load_all() -> dict:
    """Barcha saqlangan sessiyalarni yuklash"""
    try:
        if not os.path.exists(SESSION_FILE):
            return {}
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"session_load_all xatosi: {e}")
        return {}

# Adminlarni bazadan yuklash, ADMIN_ID ni ham qo'shish
ADMINS: set = DB.get_admins()
if ADMIN_ID and ADMIN_ID != 0:
    ADMINS.add(ADMIN_ID)
    DB.add_admin(ADMIN_ID)

# ================== HELPERS ==================

async def is_bot_admin(context, chat_id: int) -> bool:
    # Private chatlarda bot har doim "admin"
    if chat_id > 0:
        return True
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        return any(a.user.id == context.bot.id for a in admins)
    except Exception as e:
        if "private chat" in str(e).lower():
            return True
        logger.error(f"Error checking bot admin status: {e}")
        return False

def is_user_admin(uid: int) -> bool:
    return adm.is_user_admin(uid)

def validate_game_state(chat_id: int) -> Optional[str]:
    if len(games) >= MAX_GAMES:
        return "❌ Maksimal o'yin soni to'ldi"
    if chat_id in games and games[chat_id].state not in ("end", "stopped"):
        return "⚠️ Bu guruhda allaqachon o'yin olib borilmoqda"
    return None

def role_pool(n: int) -> List[str]:
    """n o'yinchi uchun rol ro'yxati — har doim muvozanatli"""
    # Mafia soni: o'yinchilarning 1/4, minimum 1
    mafia_count = max(1, n // 4)
    # Asosiy rollar: don (1) + mafiyalar + doctor + killer
    roles = ["don"] + ["mafia"] * mafia_count + ["doctor", "killer"]

    # New roles: Sheriff (5+), Maniac (6+), Samurai (7+), Ninja (8+)
    if n >= 5:
        roles.append("sheriff")
    if n >= 6:
        roles.append("maniac")
    
    # Premium Roles Logic
    if n >= 7 and PREMIUM_CONFIG["roles"].get("samurai", {}).get("enabled", True):
        roles.append("samurai")
    if n >= 8 and PREMIUM_CONFIG["roles"].get("ninja", {}).get("enabled", True):
        roles.append("ninja")

    # Agar keragidan ko'p bo'lsa — ortiqchasini olib tashlash
    while len(roles) > n:
        if "ninja" in roles:
            roles.remove("ninja")
        elif "samurai" in roles:
            roles.remove("samurai")
        elif "maniac" in roles:
            roles.remove("maniac")
        elif "sheriff" in roles:
            roles.remove("sheriff")
        elif "killer" in roles:
            roles.remove("killer")
        elif "doctor" in roles:
            roles.remove("doctor")
        else:
            roles.remove("mafia")
    # Yetmasa — citizen qo'shish
    while len(roles) < n:
        roles.append("citizen")
    random.shuffle(roles)
    return roles

def get_role_details(role: str, lang: str = "uz") -> dict:
    classic_chars = {
        "uz": {
            "don": {"name": "Mafiya Doni", "emoji": "👔", "type": "Klassik", "desc": "Guruh sardori, mafiya a'zolarini boshqaradi."},
            "mafia": {"name": "Mafiya", "emoji": "🔪", "type": "Klassik", "desc": "Kechalari shahar fuqarolarini o'ldiradi."},
            "doctor": {"name": "Shifokor", "emoji": "💚", "type": "Klassik", "desc": "Kechalari bir kishini davolashi mumkin."},
            "killer": {"name": "Qotil", "emoji": "🔎", "type": "Klassik", "desc": "Kechalari tergov o'tkazib, mafiyani qidiradi."},
            "sheriff": {"name": "Sherif", "emoji": "👮‍♂️", "type": "Klassik", "desc": "Shahar adolati himoyachisi."},
            "maniac": {"name": "Telba", "emoji": "🩸", "type": "Klassik", "desc": "Mustaqil qotil, har kecha kimnidir o'ldiradi."},
            "samurai": {"name": "Samuray", "emoji": "⚔️", "type": "Klassik", "desc": "Shahar himoyachisi, jonini fido qilishga tayyor."},
            "ninja": {"name": "Ninja", "emoji": "👁️", "type": "Klassik", "desc": "Tunda pinhona kuzatuv olib boradi."},
            "citizen": {"name": "Fuqaro", "emoji": "👤", "type": "Klassik", "desc": "Tinch shahar aholisi, kunduzgi ovoz berishda ishtirok etadi."}
        },
        "ru": {
            "don": {"name": "Дон Мафии", "emoji": "👔", "type": "Классика", "desc": "Глава мафии, координирует действия банды."},
            "mafia": {"name": "Мафия", "emoji": "🔪", "type": "Классика", "desc": "Убивает мирных жителей ночью."},
            "doctor": {"name": "Доктор", "emoji": "💚", "type": "Классика", "desc": "Может спасти одного игрока ночью."},
            "killer": {"name": "Киллер", "emoji": "🔎", "type": "Классика", "desc": "Проводит расследования ночью."},
            "sheriff": {"name": "Шериф", "emoji": "👮‍♂️", "type": "Классика", "desc": "Защитник правопорядка."},
            "maniac": {"name": "Маньяк", "emoji": "🩸", "type": "Классика", "desc": "Одинокий убийца, убивает каждую ночь."},
            "samurai": {"name": "Самурай", "emoji": "⚔️", "type": "Классика", "desc": "Защитник города, готов пожертвовать собой."},
            "ninja": {"name": "Ниндзя", "emoji": "👁️", "type": "Классика", "desc": "Ведет скрытое наблюдение ночью."},
            "citizen": {"name": "Мирный житель", "emoji": "👤", "type": "Классика", "desc": "Обычный житель города, голосует днем."}
        },
        "en": {
            "don": {"name": "Mafia Don", "emoji": "👔", "type": "Classic", "desc": "Leader of the Mafia, coordinates actions."},
            "mafia": {"name": "Mafia", "emoji": "🔪", "type": "Classic", "desc": "Kills town members at night."},
            "doctor": {"name": "Doctor", "emoji": "💚", "type": "Classic", "desc": "Can heal one player at night."},
            "killer": {"name": "Killer", "emoji": "🔎", "type": "Classic", "desc": "Performs investigations at night."},
            "sheriff": {"name": "Sheriff", "emoji": "👮‍♂️", "type": "Classic", "desc": "Protector of justice."},
            "maniac": {"name": "Maniac", "emoji": "🩸", "type": "Classic", "desc": "Lone wolf killer, kills every night."},
            "samurai": {"name": "Samurai", "emoji": "⚔️", "type": "Classic", "desc": "Protector of the city, ready to sacrifice."},
            "ninja": {"name": "Ninja", "emoji": "👁️", "type": "Classic", "desc": "Conducts stealth observation at night."},
            "citizen": {"name": "Civilian", "emoji": "👤", "type": "Classic", "desc": "Ordinary town member, votes during the day."}
        }
    }
    role_chars = classic_chars.get(lang, classic_chars["uz"])
    return role_chars.get(role, {"name": "Civilian", "emoji": "👤", "type": "Classic", "desc": "Civilian"})

async def safe_send_photo(context, chat_id: int, photo_url: str, caption: str):
    """Rasm yuborishga urinadi, xato bo'lsa matn yuboradi"""
    try:
        await context.bot.send_photo(chat_id, photo_url, caption=caption)
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        await context.bot.send_message(chat_id, caption)

async def safe_send_media(context, chat_id: int, url: str, caption: str):
    """Media (video, animation yoki photo) yuborishga urinadi, xato bo'lsa oddiy matn yuboradi"""
    try:
        ext = url.split('.')[-1].lower() if '.' in url else ''
        if 'video' in url or ext in ('mp4', 'mkv', 'mov', 'webm', 'gif'):
            try:
                await context.bot.send_animation(chat_id, url, caption=caption, parse_mode="HTML")
            except Exception:
                await context.bot.send_video(chat_id, url, caption=caption, parse_mode="HTML")
        else:
            await context.bot.send_photo(chat_id, url, caption=caption, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error sending media: {e}")
        await context.bot.send_message(chat_id, caption, parse_mode="HTML")

async def safe_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    """Xatolikka chidamli javob qaytarish"""
    if not update.message:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, **kwargs)
        return
    try:
        await update.message.reply_text(text, quote=False, **kwargs)
    except Exception:
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, **kwargs)
        except Exception as e:
            logger.error(f"Safe reply failed: {e}")

async def send_role_message(context, player: Player, game: Game):
    """O'yinchiga uning roli va amallarini yuborish"""
    uid = player.id
    user_data = get_uid_data(uid)
    lang = user_data.get("lang", "uz")
    char = player.character

    # Remove type source display if it's Classic
    source_str = f" ({char['type']})" if char.get('type') and char['type'] not in ("Klassik", "Классика", "Classic") else ""
    text = f"{char['emoji']} <b>{char['name']}</b>{source_str}\n"
    text += f"🎭 Rol: {player.role.upper()}\n"
    text += f"📖 {char['desc']}\n"
    text += f"🛡️ Himoya: {player.shield}\n\n"

    # Only show abilities if there's any non-classic abilities assigned
    if char['name'] in CHARACTER_ABILITIES:
        abilities = CHARACTER_ABILITIES[char['name']]['abilities']
        if lang == "uz":
            text += "⚡ Qo'shimcha kuchlar:\n"
        elif lang == "ru":
            text += "⚡ Дополнительные силы:\n"
        else:
            text += "⚡ Special Powers:\n"
        for ability in abilities:
            text += f"  {ability}\n"
        text += "\n"

    text += t(uid, "you_are").format(player.role.upper())

    # BUG FIX #4: Don ham mafia kabi o'ldirish tugmasini oladi
    if player.role in ("mafia", "don"):
        targets = [p for p in game.players.values() if p.alive and p.id != uid and p.role not in ("mafia", "don")]
        if targets:
            kb = [[InlineKeyboardButton(f"🎯 {x.name}", callback_data=f"mafia_kill_{game.chat_id}_{x.id}")] for x in targets]
            text += "\n\n" + t(uid, "mafia_target")
            try:
                await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(kb))
            except Exception as e:
                logger.error(f"Error sending kill buttons to {uid}: {e}")
        else:
            try:
                await context.bot.send_message(uid, text)
            except Exception as e:
                logger.error(f"Error sending mafia message to {uid}: {e}")

    elif player.role == "doctor":
        targets = [p for p in game.players.values() if p.alive]
        kb = [[InlineKeyboardButton(f"💚 {x.name}", callback_data=f"doctor_heal_{game.chat_id}_{x.id}")] for x in targets]
        text += "\n\n" + t(uid, "doctor_heal")
        try:
            await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            logger.error(f"Error sending heal buttons to {uid}: {e}")

    elif player.role == "killer":
        targets = [p for p in game.players.values() if p.alive and p.id != uid]
        kb = [[InlineKeyboardButton(f"🔍 {x.name}", callback_data=f"killer_check_{game.chat_id}_{x.id}")] for x in targets]
        text += "\n\n" + t(uid, "killer_show")
        try:
            await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            logger.error(f"Error sending killer buttons to {uid}: {e}")

    elif player.role == "sheriff":
        targets = [p for p in game.players.values() if p.alive and p.id != uid]
        kb = [[InlineKeyboardButton(f"🕵️‍♂️ {x.name}", callback_data=f"sheriff_check_{game.chat_id}_{x.id}")] for x in targets]
        text += "\n\n" + t(uid, "sheriff_check")
        try:
            await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            logger.error(f"Error sending sheriff buttons to {uid}: {e}")

    elif player.role == "maniac":
        targets = [p for p in game.players.values() if p.alive and p.id != uid]
        kb = [[InlineKeyboardButton(f"🔪 {x.name}", callback_data=f"maniac_kill_{game.chat_id}_{x.id}")] for x in targets]
        text += "\n\n" + t(uid, "maniac_kill")
        try:
            await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            logger.error(f"Error sending maniac buttons to {uid}: {e}")

    elif player.role == "samurai":
        targets = [p for p in game.players.values() if p.alive and p.id != uid]
        kb = [[InlineKeyboardButton(f"⚔️ {x.name}", callback_data=f"samurai_kill_{game.chat_id}_{x.id}")] for x in targets]
        text += "\n\n" + t(uid, "samurai_kill")
        try:
            await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            logger.error(f"Error sending samurai buttons to {uid}: {e}")

    elif player.role == "ninja":
        targets = [p for p in game.players.values() if p.alive and p.id != uid]
        kb = [[InlineKeyboardButton(f"👁️ {x.name}", callback_data=f"ninja_watch_{game.chat_id}_{x.id}")] for x in targets]
        text += "\n\n" + t(uid, "ninja_watch")
        try:
            await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            logger.error(f"Error sending ninja buttons to {uid}: {e}")

    else:
        try:
            await context.bot.send_message(uid, text)
        except Exception as e:
            logger.error(f"Error sending citizen message to {uid}: {e}")

async def check_win_conditions(context, chat_id: int) -> Optional[str]:
    """G'alaba shartini tekshirish"""
    game = games.get(chat_id)
    if not game:
        return None
    alive = [p for p in game.players.values() if p.alive]
    
    mafia = [p for p in alive if p.role in ("mafia", "don")]
    maniacs = [p for p in alive if p.role == "maniac"]
    good = [p for p in alive if p.role not in ("mafia", "don", "maniac")]

    # 1. Maniac Win
    if maniacs:
        # If Maniac is alone or 1v1 with anyone
        if len(alive) <= 2:
            return "maniac"
        # Game continues if Maniac is alive and more than 2 players
        return None

    # 2. Good Win (No Mafia, No Maniac)
    if len(mafia) == 0:
        return "good"

    # 3. Mafia Win (No Maniac, Mafia >= Good)
    if len(mafia) >= len(good):
        return "mafia"

    return None

# ================== AI CHAT (GEMINI) + IMAGE (IMAGEN 3) ==================

ai_conversations: Dict[int, List[dict]] = {}
AI_MAX_HISTORY = 20

# Admin boshqaradigan sozlamalar
AI_SETTINGS = {
    "ai_enabled": True,
    "image_enabled": True,
    "image_daily_limit": 5,
}
image_usage: Dict[int, dict] = {}

# ── SYSTEM PROMPT ──────────────────────────────────────────────────────────────
GEMINI_SYSTEM_PROMPT = """Sen "Mafia Bot" — Telegram'dagi professional va klassik Mafiya o'yini botining aqlli yordamchisisan.

🎭 SEN KIMSAN:
- Ismingiz: Mafia Bot AI
- Shaxsiyating: Do'stona, sirli, aqlli va biroz dramatik (klassik detektiv uslubida)
- Suhbat olib borish uslubi: Jonli, qiziqarli, ba'zan emoji ishlatib, lekin haddan oshmasdan

🎮 O'YIN HAQIDA BILADIGAN NARSALARING:
Rollar:
  • 👔 DON — Mafiya boshlig'i. Kechasi o'ldirish buyrug'i beradi.
  • 🔪 MAFIA — Don'ning sheriklari. Kechasi birga harakat qiladi.
  • 💚 DOCTOR — Kechasi bir kishini o'ldirishdan himoya qila oladi.
  • 🔎 KILLER (Tergovchi) — Kechasi bir kishining rolini bilib oladi.
  • 👤 CITIZEN — Oddiy fuqaro. Kunduz ovoz berib mafiyani topmog'i kerak.

O'yin bosqichlari:
  1. Ro'yxatdan o'tish (120 soniya)
  2. Kecha (60 soniya) — maxfiy harakatlar
  3. Kunduz (120 soniya) — muhokama
  4. Ovoz berish (60 soniya) — kimni osish
  5. Final ovoz — osish yoki saqlash

G'alaba shartlari:
  • Shahar g'alaba qiladi — barcha mafiyani topib ossa
  • Mafia g'alaba qiladi — fuqarolar soni mafiyadan kam bo'lsa

Shop buyumlari:
  • 🌀 Qalqon (Shield) (20 coin) — 1 kecha himoya
  • 🎭 Niqob (Mask) (15 coin) — rolni yashirish
  • ⚡ Faol Rol (Active Card) (25 coin) — faol rol kuchaytirgichi
  • ♾️ O'lmasizlik (50 coin) — bir marta o'lmaydi

Buyruqlar: /newgame, /join, /shop, /balance, /profile, /top, /lang, /imagine

🌟 UMUMIY SUHBAT:
Sen faqat o'yin haqida emas, har qanday mavzuda suhbatlasha olasan:
  • Hayot, sevgi, do'stlik, maqsadlar qahtda
  • Detektiv filmlar, sirlar va sarguzashtlar
  • Texnologiya, fan, qiziqarli faktlar
  • Hazil va qiziqarli suhbat
  • Agar biror narsa haqida bilmasang — rostini ayt

💬 JAVOB BERISH QOIDALARI:
  • Har doim O'zbek tilida javob ber (foydalanuvchi boshqa tilda yozsa ham, o'zbek tilida javob ber)
  • Qisqa va aniq javob ber (3-5 jumla odatda yetarli)
  • Haddan ortiq rasmiy bo'lma — do'stona gapir
  • Foydalanuvchi nomini bilsang, ishlatib gapir
  • O'yin davomida yordam so'rasa — tezda strategiya ber
  • Haqorat yoki yomon niyatli so'rovlarga javob berma

🕵️ DETEKTIV USLUBI:
Gohida klassik detektiv va mafiya filmlaridan iqtibos keltirish yoki ularning uslubida gapirish mumkin, lekin haddan oshmaslik kerak."""


def _get_today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _image_count_today(uid: int) -> int:
    return image_usage.get(uid, {}).get(_get_today(), 0)


def _increment_image_count(uid: int):
    today = _get_today()
    if uid not in image_usage:
        image_usage[uid] = {}
    image_usage[uid] = {today: image_usage[uid].get(today, 0) + 1}


async def _gemini_chat(uid: int, text: str, user_name: str = "") -> str:
    """Gemini 2.0 Flash bilan suhbat"""
    if uid not in ai_conversations:
        ai_conversations[uid] = []

    # Foydalanuvchi ismini system prompt ga qo'shish
    system = GEMINI_SYSTEM_PROMPT
    if user_name:
        system += f"\n\nHozir suhbatlashayotgan foydalanuvchi ismi: {user_name}"

    ai_conversations[uid].append({"role": "user", "parts": [{"text": text}]})
    if len(ai_conversations[uid]) > AI_MAX_HISTORY * 2:
        ai_conversations[uid] = ai_conversations[uid][-AI_MAX_HISTORY * 2:]

    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": ai_conversations[uid],
        "generationConfig": {
            "maxOutputTokens": 800,
            "temperature": 0.85,
            "topP": 0.95,
            "topK": 40,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ],
    }

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    reply = data["candidates"][0]["content"]["parts"][0]["text"]
    ai_conversations[uid].append({"role": "model", "parts": [{"text": reply}]})
    return reply


async def _imagen3_generate(prompt: str) -> bytes:
    """Google Imagen 3 orqali rasm generatsiya"""
    # Promptni classic/noir uslubida kuchaytirish
    enhanced_prompt = (
        f"{prompt}, classic mafia style, film noir, high quality, detailed, dark mysterious colors, "
        f"digital art, professional illustration"
    )

    payload = {
        "instances": [{"prompt": enhanced_prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "1:1",
            "safetyFilterLevel": "block_some",
            "personGeneration": "allow_adult",
        },
    }

    url = (
        f"https://us-central1-aiplatform.googleapis.com/v1/projects/"
        f"generativelanguage/locations/us-central1/publishers/google/models/"
        f"imagen-3.0-generate-002:predict"
    )

    # Gemini API key bilan Imagen 3 (Google AI Studio endpoint)
    imagen_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"imagen-3.0-generate-002:predict?key={GEMINI_API_KEY}"
    )

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(imagen_url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    # Base64 rasmni decode qilish
    predictions = data.get("predictions", [])
    if not predictions:
        raise ValueError("Imagen API bo'sh javob qaytardi")

    img_b64 = predictions[0].get("bytesBase64Encoded", "")
    if not img_b64:
        raise ValueError("Rasmda base64 ma'lumot yo'q")

    return base64.b64decode(img_b64)


async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Private chatda oddiy matn — Gemini javob beradi"""
    if not update.message or not update.message.text:
        return
    if update.effective_chat.type != "private":
        return

    uid = update.effective_user.id
    text = update.message.text.strip()

    if text.startswith("/"):
        return

    if not AI_SETTINGS.get("ai_enabled", True):
        await update.message.reply_text("🤖 AI hozircha o'chirilgan.")
        return

    if not GEMINI_API_KEY:
        await update.message.reply_text(
            "🤖 AI sozlanmagan.\nAdmin GEMINI_API_KEY ni Railway ga qo'shishi kerak."
        )
        return

    await context.bot.send_chat_action(chat_id=uid, action="typing")

    user_name = update.effective_user.first_name or ""

    try:
        reply = await _gemini_chat(uid, text, user_name)
        await update.message.reply_text(f"🤖 {reply}")
    except httpx.HTTPStatusError as e:
        logger.error(f"Gemini HTTP error {uid}: {e.response.status_code} — {e.response.text}")
        if e.response.status_code == 400:
            await update.message.reply_text("❌ API so'rovi noto'g'ri (400). GEMINI_API_KEY ni tekshiring.")
        elif e.response.status_code == 403:
            await update.message.reply_text("❌ API ruxsat yo'q (403). Key noto'g'ri yoki bloklangan.")
        elif e.response.status_code == 429:
            await update.message.reply_text("⏳ API limiti to'ldi (429). Bir oz kuting.")
        else:
            await update.message.reply_text(f"❌ API xatosi: {e.response.status_code}")
    except httpx.TimeoutException:
        logger.error(f"Gemini timeout {uid}")
        await update.message.reply_text("⏳ AI javob bermadi (timeout). Qayta urinib ko'ring.")
    except Exception as e:
        logger.error(f"Gemini error {uid}: {type(e).__name__}: {e}")
        await update.message.reply_text(f"❌ Xato: {type(e).__name__}: {str(e)[:100]}")


async def imagine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/imagine <tavsif> — Imagen 3 orqali rasm yaratish"""
    uid = update.effective_user.id
    user_data = get_uid_data(uid)
    lang = user_data.get("lang", "uz")

    if not AI_SETTINGS.get("image_enabled", True):
        await update.message.reply_text("🖼 Rasm generatsiya hozircha o'chirilgan.")
        return

    limit = AI_SETTINGS.get("image_daily_limit", 5)
    used = _image_count_today(uid)
    if used >= limit and limit < 999:
        await update.message.reply_text(
            f"⛔ Kunlik limitga yetdingiz: {used}/{limit} ta rasm.\n"
            f"⏰ Ertaga qayta urinib ko'ring!"
        )
        return

    if not context.args:
        await update.message.reply_text(
            "🎨 <b>Rasm yaratish</b>\n\n"
            "Foydalanish: /imagine <tavsif>\n\n"
            "Misollar:\n"
            "• /imagine mafia boss in dark office\n"
            "• /imagine ninja warrior in forest\n"
            "• /imagine futuristic city at sunset\n\n"
            f"📊 Bugun: {used}/{limit} ta rasm ishlatilgan",
            parse_mode="HTML"
        )
        return

    if not GEMINI_API_KEY:
        await update.message.reply_text(
            "🖼 Imagen API sozlanmagan.\nAdmin GEMINI_API_KEY ni qo'shishi kerak."
        )
        return

    prompt = " ".join(context.args)
    wait_msg = await update.message.reply_text("🎨 Rasm yaratilmoqda... ⏳")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")

    try:
        img_bytes = await _imagen3_generate(prompt)
        _increment_image_count(uid)
        remaining = limit - _image_count_today(uid)

        await wait_msg.delete()
        import io as _io
        remaining_str = "♾️" if limit >= 999 else str(remaining)
        await update.message.reply_photo(
            photo=_io.BytesIO(img_bytes),
            caption=(
                f"🎨 <b>{prompt}</b>\n\n"
                f"✨ Google Imagen 3 | Qoldi: {remaining_str}/{limit if limit < 999 else '♾️'}"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Imagen3 error {uid}: {e}")
        await wait_msg.delete()
        await update.message.reply_text(
            "❌ Rasm yaratishda xato yuz berdi.\n"
            "Promptni o'zgartirib qayta urinib ko'ring."
        )


async def ai_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI suhbat tarixini tozalash"""
    uid = update.effective_user.id
    ai_conversations.pop(uid, None)
    await update.message.reply_text(
        "🔄 AI suhbat tarixi tozalandi!\n"
        "Endi yangi suhbat boshlanadi. 😊"
    )





async def post_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin buyrug'i: Kanalga xabar yozish (/post <matn>)"""
    uid = update.effective_user.id
    if not is_user_admin(uid):
        return

    if not context.args:
        await update.message.reply_text("📝 Kanalga yozish uchun matn kiriting:\n/post Assalomu alaykum!")
        return

    text = " ".join(context.args)
    
    # Rasm bilan bo'lsa
    if update.message.reply_to_message and update.message.reply_to_message.photo:
        photo = update.message.reply_to_message.photo[-1]
        try:
            await context.bot.send_photo(chat_id=CHANNEL_ID, photo=photo.file_id, caption=text, parse_mode="HTML")
            await update.message.reply_text("✅ Kanalga rasm va matn yuborildi!")
        except Exception as e:
            await update.message.reply_text(f"❌ Xatolik: {e}")
        return

    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML")
        await update.message.reply_text("✅ Kanalga matn yuborildi!")
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat = update.effective_chat

    # Foydalanuvchini DBga qo'shish/yangilash
    DB.create_user(uid, update.effective_user.full_name, update.effective_user.username)

    # ===== JOIN tizimi: /start chat_-1001234567890 =====
    if context.args and context.args[0].startswith("chat_"):
        # Ban tekshiruvi
        ban_info = DB.is_banned(uid)
        if ban_info:
            await update.message.reply_text(
                f"🚫 Siz botdan ban qilingansiz!\n"
                f"📋 Sabab: {ban_info.get('reason', 'Ko\'rsatilmagan')}"
            )
            return
        raw = context.args[0].replace("chat_", "", 1)
        try:
            group_chat_id = int(raw)
        except ValueError:
            await update.message.reply_text("❌ Noto'g'ri havola.")
            return

        if group_chat_id not in games:
            await update.message.reply_text("❌ O'yin topilmadi yoki tugagan.")
            return

        game = games[group_chat_id]
        if game.state != "registration":
            await update.message.reply_text("⛔ Ro'yxatga olish yopiq.")
            return
        if uid in game.players:
            await update.message.reply_text(t(uid, "already_joined"))
            return

        first_name = update.effective_user.first_name
        game.players[uid] = Player(uid, first_name)
        player_count = len(game.players)
        logger.info(f"User {uid} joined game in chat {group_chat_id} via start link (total: {player_count})")

        # O'yinchilarni JSON ga saqlash
        session_save(group_chat_id)

        # Foydalanuvchiga shaxsiy xabar
        await update.message.reply_text(
            f"✅ {first_name}, siz o'yinga qo'shildingiz!\n"
            f"👥 Jami o'yinchilar: {player_count}\n\n"
            f"🎭 O'yin boshlanishini kuting...",
            parse_mode="HTML"
        )

        # Guruh xabarini yangilash
        names = "\n".join([f"• {html.escape(p.name)}" for p in game.players.values()])
        new_text = (
            f"⚔️ <b>MAFIYA O'YINi BOSHLANMOQDA!</b> ⚔️\n\n"
            f"🎲 O'yinchilar:\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{names}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👥 Jami: <b>{player_count}</b> nafar\n"
            f"⏳ Ro'yxat davom etmoqda..."
        )
        try:
            bot_name = BOT_USERNAME or "bot"
            join_url = f"https://t.me/{bot_name}?start=chat_{group_chat_id}"
            await context.bot.edit_message_text(
                chat_id=group_chat_id,
                message_id=game.reg_msg_id,
                text=new_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"➕ Qo'shilish ({player_count})", url=join_url)
                ]])
            )
        except Exception as e:
            logger.error(f"Error updating reg message: {e}")
        return

    # Normal START message
    user_data = get_uid_data(uid)
    lang = user_data.get("lang", "uz")

    if lang == "ru":
        text = (
            "⚖️ <b>Mafia Bot — Добро пожаловать!</b> ⚖️\n\n"
            "Присоединяйтесь к увлекательной игре Мафия с вашими друзьями.\n\n"
            "📜 <b>Основные команды:</b>\n"
            "┣ <b>/newgame</b> — Начать игру в группе\n"
            "┣ <b>/profile</b> — Профиль\n"
            "┣ <b>/shop</b> — Магазин\n"
            "┣ <b>/help</b> — <b>Полное руководство</b>\n\n"
            "🚀 <b>v2.2: Клонирование (Новинка!)</b>\n"
            "Создайте своего бота! Отправьте токен от @BotFather сюда.\n\n"
            "🤖 <b>AI чат:</b> Просто напишите мне сообщение!"
        )

    elif lang == "en":
        text = (
            "⚖️ <b>Mafia Bot — Welcome!</b> ⚖️\n\n"
            "Play with friends in an exciting game of Mafia.\n\n"
            "📜 <b>Main Commands:</b>\n"
            "┣ <b>/newgame</b> — Start game in group\n"
            "┣ <b>/profile</b> — Your profile\n"
            "┣ <b>/shop</b> — Shop\n"
            "┣ <b>/help</b> — <b>Complete guide</b>\n\n"
            "🚀 <b>v2.2: Bot Cloning (New!)</b>\n"
            "Create your own bot! Just send the token from @BotFather here.\n\n"
            "🤖 <b>AI Chat:</b> Just send me a message!"
        )

    else:
        text = (
            "⚖️ <b>Mafia Bot — Rasmiy Botga Xush Kelibsiz!</b> ⚖️\n\n"
            "Siz bu yerda do'stlaringiz bilan "
            "qiziqarli mafiya o'yinini o'ynashingiz mumkin.\n\n"
            "📜 <b>Asosiy Buyruqlar:</b>\n"
            "┣ <b>/newgame</b> — Guruhda yangi o'yin boshlash\n"
            "┣ <b>/profile</b> — O'z statistikangizni ko'rish\n"
            "┣ <b>/shop</b> — Do'kondan buyumlar sotib olish\n"
            "┣ <b>/help</b> — <b>Barcha buyruqlar va qo'llanma</b>\n\n"
            "🚀 <b>v2.2: Bot Klonlash (Yangilik!)</b>\n"
            "Endi siz o'z botingizni yaratishingiz mumkin! Shunchaki @BotFather orqali olingan "
            "tokenni shu yerga yuboring va shaxsiy botingizga ega bo'ling.\n\n"
            "🤖 <b>AI suhbatdosh:</b> Menga shunchaki matn yozing!"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 To'liq qo'llanma (Help)", callback_data="help_main")],
        [InlineKeyboardButton("📢 Rasmiy kanal", url="https://t.me/mafia_anime_rasmiy")]
    ])

    await safe_reply(update, context, text, parse_mode="HTML", reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Categorized help menu"""
    text = (
        "📖 <b>Mafia Bot — Qo'llanma</b>\n\n"
        "Quyidagi kategoriyalardan birini tanlang:"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 O'yin qoidalari", callback_data="help_rules"),
         InlineKeyboardButton("🎭 Rollar", callback_data="help_roles")],
        [InlineKeyboardButton("🛍 Magazin & Buyumlar", callback_data="help_shop"),
         InlineKeyboardButton("💰 Iqtisodiyot", callback_data="help_economy")],
        [InlineKeyboardButton("🤖 Bot Klonlash (v2.2)", callback_data="help_clone")],
        [InlineKeyboardButton("👮‍♂️ Admin Buyruqlar", callback_data="help_admin")]
    ])
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id
    
    help_texts = {
        "rules": (
            "🎮 <b>O'yin Qoidalari</b>\n\n"
            "1. O'yinni boshlash uchun guruhda /newgame yuboring.\n"
            "2. Kamida 3 kishi qo'shilishi kerak.\n"
            "3. O'yin Kecha va Kunduz bosqichlaridan iborat.\n"
            "4. <b>Kecha:</b> Mafia va maxsus rollar o'z harakatlarini qiladi.\n"
            "5. <b>Kunduz:</b> Hamma muhokama qiladi va bir kishini osish uchun ovoz beradi."
        ),
        "roles": (
            "🎭 <b>Rollar haqida</b>\n\n"
            "• 🤵 <b>Don:</b> Mafiya boshlig'i, Sherifga fuqaro bo'lib ko'rinadi.\n"
            "• 🔪 <b>Mafiya:</b> Kechasi odamlarni o'ldiradi.\n"
            "• 💚 <b>Doktor:</b> Bir kishini davolaydi.\n"
            "• 🕵️‍♂️ <b>Sherif:</b> O'yinchilarni tekshiradi.\n"
            "• ⚔️ <b>Samurai:</b> O'ldirishi mumkin, lekin xato qilsa o'zi ham o'ladi.\n"
            "• 👁️ <b>Ninja:</b> Bir kishini kimlar kelishini kuzatadi."
        ),
        "shop": (
            "🛍 <b>Magazin Buyumlari</b>\n\n"
            "• 🛡 <b>Shield:</b> Kechasi mafiya hujumidan himoya.\n"
            "• 📝 <b>Docs:</b> Sherif tekshirsa fuqaro bo'lib ko'rinish.\n"
            "• 📓 <b>Death Note:</b> Kechasi bir kishini 100% o'ldirish.\n"
            "• 📡 <b>Radar:</b> Mafiyani aniq topib beruvchi qurilma."
        ),
        "economy": (
            "💰 <b>Iqtisodiyot va Balans</b>\n\n"
            "• Har bir g'alaba uchun <b>+60 coin</b> beriladi.\n"
            "• Coinga do'kondan buyumlar olishingiz mumkin.\n"
            "• Balansni tekshirish: /balance\n"
            "• Top o'yinchilar: /top"
        ),
        "clone": (
            "🚀 <b>Bot Klonlash (v2.2)</b>\n\n"
            "Siz o'z shaxsiy Mafia botingizni ochishingiz mumkin!\n\n"
            "1. @BotFather ga boring.\n"
            "2. Yangi bot ochib, API Tokenini oling.\n"
            "3. Olingan tokenni ushbu botga yuboring.\n"
            "4. Botingiz avtomatik ishga tushadi va siz unda Admin bo'lasiz!"
        ),
        "admin": (
            "👮‍♂️ <b>Admin Buyruqlari</b>\n\n"
            "• /admin — Boshqaruv paneli\n"
            "• /ban — Userni bloklash\n"
            "• /broadcast — Barcha foydalanuvchilarga xabar\n"
            "• /setbalance — Pul berish\n"
            "• /stopgame — O'yinni majburiy to'xtatish"
        )
    }
    
    target = data.replace("help_", "")
    if target == "main":
        await help_command(update, context)
        return

    text = help_texts.get(target, "Ma'lumot topilmadi.")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="help_main")]])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

async def lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if check_cooldown(uid):
        await safe_reply(update, context, cooldown_msg(uid))
        return
    kb = [
        [InlineKeyboardButton("🇺🇿 O'zbek", callback_data="lang_uz")],
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
    ]
    await safe_reply(update, context, "🌍 Tilni tanlang / Выберите язык / Choose language:",
                    reply_markup=InlineKeyboardMarkup(kb))

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if check_cooldown(uid):
        await safe_reply(update, context, cooldown_msg(uid))
        return
    money = get_uid_data(uid)["money"]
    await safe_reply(update, context, t(uid, "balance").format(money))

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    uid = update.effective_user.id

    if check_cooldown(uid):
        await safe_reply(update, context, cooldown_msg(uid))
        return

    if chat_id in games and games[chat_id].state not in ("registration", "end", "stopped"):
        await safe_reply(update, context, t(uid, "shop_blocked"))
        return

    user_data = get_uid_data(uid)
    lang_code = user_data.get("lang", "uz")
    items = SHOP_ITEMS.get(lang_code, SHOP_ITEMS["uz"])

    kb = []
    shop_text = "🛍 " + t(uid, "shop_menu") + "\n\n"

    for item_key, item_data in items.items():
        # Check if enabled
        conf = PREMIUM_CONFIG.get("items", {}).get(item_key)
        if conf and not conf.get("enabled", True):
            continue
            
        # Get dynamic price
        price = conf["price"] if conf else item_data["price"]
        
        price_str = f"{price} coin" if price > 0 else "🎁 FREE"
        kb.append([InlineKeyboardButton(
            f"{item_data['emoji']} {item_data['name']} ({price_str})",
            # BUG FIX #1: callback_data "buy_active_role" uchun to'liq key ishlatiladi
            callback_data=f"buy_{item_key}"
        )])
        shop_text += f"{item_data['emoji']} {item_data['name']} ({price_str})\n"
        if item_data.get('type'):
            shop_text += f"  📺 {item_data['type']}\n"
        shop_text += f"  {item_data['desc']}\n\n"

    await safe_reply(update, context, shop_text, reply_markup=InlineKeyboardMarkup(kb))

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Profil ko'rsatish"""
    uid = update.effective_user.id
    user = update.effective_user

    # Foydalanuvchi ma'lumotlarini yaratish/yangilash
    DB.create_user(uid, user.full_name, user.username)
    DB.update_user(uid, name=user.full_name, username=user.username)
    d = get_uid_data(uid)

    games_played = d.get("games_played", 0)
    games_won = d.get("games_won", 0)
    win_rate = round((games_won / games_played * 100)) if games_played > 0 else 0
    money = d.get("money", 100)
    shield = d.get("shield", 0)
    documents = d.get("documents", 0)
    active_role = d.get("active_role", 0)
    immortality = d.get("immortality", 0)

    lang_code = d.get("lang", "uz")
    username_str = f"@{user.username}" if user.username else "—"

    full_name_esc = html.escape(user.full_name)
    premium = d.get("premium", 0)

    if lang_code == "ru":
        prem_str = "Активен" if premium == 1 else "Нет"
        text = (
            f"👤 <b>{full_name_esc}</b>\n"
            f"🔖 {username_str}\n"
            f"🆔 <code>{uid}</code>\n"
            f"👑 Premium: <b>{prem_str}</b>\n\n"
            f"💰 Баланс: <b>{money} монет</b>\n\n"
            f"🎮 Статистика:\n"
            f"  🕹 Игр сыграно: <b>{games_played}</b>\n"
            f"  🏆 Побед: <b>{games_won}</b>\n"
            f"  📊 Винрейт: <b>{win_rate}%</b>\n\n"
            f"🎒 Инвентарь:\n"
            f"  🌀 Shield: {shield}\n"
            f"  🎭 Documents: {documents}\n"
            f"  ⚡ Active Role: {active_role}\n"
            f"  ♾️ Immortality: {immortality}\n\n"
            f"📸 Чтобы сменить фото: отправьте фото с подписью /setphoto"
        )
    elif lang_code == "en":
        prem_str = "Active" if premium == 1 else "No"
        text = (
            f"👤 <b>{full_name_esc}</b>\n"
            f"🔖 {username_str}\n"
            f"🆔 <code>{uid}</code>\n"
            f"👑 Premium: <b>{prem_str}</b>\n\n"
            f"💰 Balance: <b>{money} coins</b>\n\n"
            f"🎮 Stats:\n"
            f"  🕹 Games played: <b>{games_played}</b>\n"
            f"  🏆 Wins: <b>{games_won}</b>\n"
            f"  📊 Win rate: <b>{win_rate}%</b>\n\n"
            f"🎒 Inventory:\n"
            f"  🌀 Shield: {shield}\n"
            f"  🎭 Documents: {documents}\n"
            f"  ⚡ Active Role: {active_role}\n"
            f"  ♾️ Immortality: {immortality}\n\n"
            f"📸 To change photo: send a photo with caption /setphoto"
        )
    else:
        prem_str = "Faol" if premium == 1 else "Yo'q"
        text = (
            f"👤 <b>{full_name_esc}</b>\n"
            f"🔖 {username_str}\n"
            f"🆔 <code>{uid}</code>\n"
            f"👑 Premium: <b>{prem_str}</b>\n\n"
            f"💰 Balans: <b>{money} coin</b>\n\n"
            f"🎮 Statistika:\n"
            f"  🕹 O'yinlar: <b>{games_played}</b>\n"
            f"  🏆 G'alabalar: <b>{games_won}</b>\n"
            f"  📊 Win rate: <b>{win_rate}%</b>\n\n"
            f"🎒 Inventar:\n"
            f"  🌀 Shield: {shield}\n"
            f"  🎭 Documents: {documents}\n"
            f"  ⚡ Active Role: {active_role}\n"
            f"  ♾️ Immortality: {immortality}\n\n"
            f"📸 Rasm o'zgartirish: rasmni /setphoto yozib yuboring"
        )

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🖼 Rasmni o'zgartirish", callback_data="change_photo")]])

    photo_blob = d.get("photo")
    if photo_blob:
        try:
            # SQLite memoryview yoki bytes qaytarishi mumkin, ikkalasini ham handle qilamiz
            if isinstance(photo_blob, memoryview):
                photo_bytes = bytes(photo_blob)
            elif isinstance(photo_blob, (bytes, bytearray)):
                photo_bytes = bytes(photo_blob)
            else:
                photo_bytes = None

            if photo_bytes and len(photo_bytes) > 0:
                await update.message.reply_photo(
                    photo=io.BytesIO(photo_bytes),
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=kb
                )
                return
        except Exception as e:
            logger.error(f"Error sending profile photo for {uid}: {e}")
            # Rasm ishlamasa matn bilan davom etamiz

    # Rasmsiz profil
    await safe_reply(update, context, text, parse_mode="HTML", reply_markup=kb)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi rasm yuborganda saqlash:
    1. Caption: /setphoto
    2. /setphoto buyrug'iga reply qilib rasm yuborish
    """
    if not update.message or not update.message.photo:
        return

    uid = update.effective_user.id
    caption = (update.message.caption or "").strip().lower()

    # Usul 1: caption orqali — "/setphoto" yozib rasm yuborish
    is_caption = caption in ("/setphoto", "setphoto")

    # Usul 2: reply orqali — /setphoto ga reply qilib rasm yuborish
    is_reply = False
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        replied_text = (replied.text or replied.caption or "").strip().lower()
        if replied_text in ("/setphoto", "setphoto"):
            is_reply = True

    if not is_caption and not is_reply:
        return

    # Faqat PRIVATE chatda qabul qilamiz
    if update.effective_chat.type != "private":
        bot_name = BOT_USERNAME or "bot"
        await update.message.reply_text(
            f"📸 Rasmni bot bilan shaxsiy chatda yuboring:\n"
            f"👉 @{bot_name}"
        )
        return

    photo = update.message.photo[-1]

    if photo.file_size and photo.file_size > 5 * 1024 * 1024:
        await update.message.reply_text("❌ Rasm hajmi 5MB dan oshmasligi kerak.")
        return

    try:
        f_info = await context.bot.get_file(photo.file_id)
        photo_bytes = bytes(await f_info.download_as_bytearray())

        DB.create_user(uid, update.effective_user.full_name, update.effective_user.username)
        DB.update_user(uid, photo=photo_bytes)

        user_data = get_uid_data(uid)
        lang_code = user_data.get("lang", "uz")
        if lang_code == "ru":
            msg = "✅ Фото профиля обновлено!\n👉 /profile — посмотреть"
        elif lang_code == "en":
            msg = "✅ Profile photo updated!\n👉 /profile — view"
        else:
            msg = "✅ Profil rasmi yangilandi!\n👉 /profile — ko'rish"

        await update.message.reply_text(msg)
        logger.info(f"User {uid} updated profile photo ({len(photo_bytes)} bytes)")

    except Exception as e:
        logger.error(f"Error saving photo for {uid}: {e}")
        await update.message.reply_text(
            "❌ Rasm saqlashda xato yuz berdi.\n"
            "Qayta urinib ko'ring yoki kichikroq rasm yuboring."
        )

async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Eski /join command - endi start link orqali qo'shilish kerak"""
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Guruhda /join bosilsa, link yuborish
    if chat_id < 0:  # guruh chat
        game = games.get(chat_id)
        if not game or game.state != "registration":
            await safe_reply(update, context, "⛔ Hozir ro'yxatga olish yo'q.")
            return
        bot_name = BOT_USERNAME or "bot"
        join_url = f"https://t.me/{bot_name}?start=chat_{chat_id}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎮 Qo'shilish", url=join_url)]])
        await safe_reply(update, context, "👇 Qo'shilish uchun tugmani bosing:", reply_markup=kb)
    else:
        await safe_reply(update, context, "ℹ️ Guruh chatida /newgame buyrug'ini ishlating.")


async def instagram_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Instagram videolarini yuklab beruvchi handler"""
    if not update.message or not update.message.text:
        return

    url_match = re.search(r'https?://(?:www\.)?instagram\.com/(?:p|reels|reel)/[A-Za-z0-9_-]+', update.message.text)
    if not url_match:
        return
    
    url = url_match.group(0)
    status_msg = await update.message.reply_text("⏳ Yuklanmoqda... / Downloading...")
    file_path = None

    try:
        file_path = await download_instagram_video(url)
        if file_path and os.path.exists(file_path):
            file_size = os.path.getsize(file_path) / (1024 * 1024)
            
            # Bucket'ga yuklash
            from storage import upload_to_bucket
            bucket_url = upload_to_bucket(file_path)
            
            if file_size > 50:
                if bucket_url:
                    await status_msg.edit_text(
                        f"⚠️ Video hajmi {file_size:.1f} MB (Telegram limiti 50 MB).\n"
                        f"Biroq video bulutli saqlagichimizga yuklandi! Quyidagi havola orqali ko'rishingiz va yuklab olishingiz mumkin:\n\n"
                        f"🔗 {bucket_url}",
                        disable_web_page_preview=False
                    )
                else:
                    await status_msg.edit_text(f"❌ Video juda katta ({file_size:.1f} MB). Telegram limiti 50 MB.")
            else:
                ext = os.path.splitext(file_path)[1].lower()
                kb = None
                if bucket_url:
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎥 Bulutdan yuklab olish (S3 Link)", url=bucket_url)]])
                
                with open(file_path, 'rb') as f:
                    if ext in ('.mp4', '.mkv', '.mov', '.webm'):
                        await update.message.reply_video(
                            video=f,
                            caption="✅ Video yuklab olindi\n\n@"+(BOT_USERNAME or ""),
                            reply_markup=kb
                        )
                    elif ext in ('.jpg', '.jpeg', '.png', '.webp'):
                        await update.message.reply_photo(
                            photo=f,
                            caption="✅ Rasm yuklab olindi\n\n@"+(BOT_USERNAME or ""),
                            reply_markup=kb
                        )
                    else:
                        await update.message.reply_document(
                            document=f,
                            caption="✅ Fayl yuklab olindi\n\n@"+(BOT_USERNAME or ""),
                            reply_markup=kb
                        )
                await status_msg.delete()
        else:
            await status_msg.edit_text("❌ Videoni yuklab bo'lmadi. Havola noto'g'ri yoki profil yopiq bo'lishi mumkin.")
    except Exception as e:
        logger.error(f"Instagram download error: {e}")
        await status_msg.edit_text(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                logger.error(f"Error deleting temp file {file_path}: {e}")


async def admin_file_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin yuborgan har qanday faylni (rasm, video, hujjat) bucket'ga yuklash"""
    if not update.message:
        return
    uid = update.effective_user.id
    if not adm.is_user_admin(uid):
        return
        
    is_bucket = context.user_data.get("waiting_for_bucket_file")
    asset_type = context.user_data.get("waiting_for_asset")
    
    if is_bucket or asset_type:
        msg = update.message
        file_obj = None
        file_name = "file"
        
        # OAV turiga qarab file ID olish
        if msg.photo:
            file_obj = await msg.photo[-1].get_file()
            file_name = f"photo_{file_obj.file_unique_id}.jpg"
        elif msg.video:
            file_obj = await msg.video.get_file()
            file_name = msg.video.file_name or f"video_{file_obj.file_unique_id}.mp4"
        elif msg.document:
            file_obj = await msg.document.get_file()
            file_name = msg.document.file_name or f"doc_{file_obj.file_unique_id}"
        elif msg.audio:
            file_obj = await msg.audio.get_file()
            file_name = msg.audio.file_name or f"audio_{file_obj.file_unique_id}.mp3"
        elif msg.voice:
            file_obj = await msg.voice.get_file()
            file_name = f"voice_{file_obj.file_unique_id}.ogg"
        elif msg.animation:
            file_obj = await msg.animation.get_file()
            file_name = msg.animation.file_name or f"animation_{file_obj.file_unique_id}.mp4"
        elif msg.video_note:
            file_obj = await msg.video_note.get_file()
            file_name = f"video_note_{file_obj.file_unique_id}.mp4"
            
        if not file_obj:
            await msg.reply_text("❌ Iltimos, rasm, video, audio yoki hujjat yuboring.")
            raise ApplicationHandlerStop()
            
        status = await msg.reply_text("⏳ Fayl bulutli saqlagichga (Bucket) yuklanmoqda...")
        
        try:
            if not os.path.exists("downloads"):
                os.makedirs("downloads", exist_ok=True)
                
            local_path = os.path.join("downloads", file_name)
            await file_obj.download_to_drive(local_path)
            
            from storage import upload_to_bucket
            import asyncio
            loop = asyncio.get_event_loop()
            bucket_url = await loop.run_in_executor(None, upload_to_bucket, local_path)
            
            if os.path.exists(local_path):
                os.remove(local_path)
                
            if bucket_url:
                if is_bucket:
                    context.user_data["waiting_for_bucket_file"] = False
                    await status.edit_text(
                        f"✅ <b>Fayl muvaffaqiyatli yuklandi!</b>\n\n"
                        f"🔗 <b>Havola (URL):</b>\n<code>{bucket_url}</code>\n\n"
                        f"Yana yuklash uchun admin panelga kiring.",
                        parse_mode="HTML"
                    )
                else:
                    # Tun yoki kun rasmini o'rnatish
                    DB.set_asset_url(asset_type, bucket_url)
                    context.user_data.pop("waiting_for_asset", None)
                    label = "🌙 Tun (Kecha)" if asset_type == "night_start" else "☀️ Tong (Kun)"
                    await status.edit_text(
                        f"✅ <b>{label} videosi (GIF) muvaffaqiyatli yuklandi va bazada saqlandi!</b>\n\n"
                        f"🔗 <b>Yangi havola:</b>\n<code>{bucket_url}</code>\n\n"
                        f"Endi o'yinda shu video ishlatiladi.",
                        parse_mode="HTML"
                    )
            else:
                await status.edit_text("❌ Faylni bulutga yuklashda xatolik yuz berdi. Sozlamalarni tekshiring.")
        except Exception as e:
            logger.error(f"Admin file upload error: {e}")
            await status.edit_text(f"❌ Yuklashda kutilmagan xatolik yuz berdi: {str(e)}")
            
        raise ApplicationHandlerStop()


async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi yuborgan bot tokenini qabul qilish va jsonga saqlash"""
    uid = update.effective_user.id
    token = update.message.text.strip()
    
    # Faqat private chatda ishlasin
    if update.effective_chat.type != "private":
        return

    # Token formatini tekshirish (faqat oddiy regex, chuqur tekshiruv keyinroq)
    if not re.match(r'^\d{8,12}:[a-zA-Z0-9_-]{35}$', token):
        return # Agar shunchaki matn bo'lsa, boshqa handlerlar (AI chat) ishlasin

    logger.info(f"Yangi token qabul qilindi: {token[:10]}... kimdan: {uid}")

    config_file = "config.json"
    try:
        # Hozirgi config'ni yuklash
        if os.path.exists(config_file):
            with open(config_file, "r") as f:
                config = json.load(f)
        else:
            config = []

        # Limit tekshiruvi (20 ta)
        if len(config) >= 20:
            await update.message.reply_text("❌ Kechirasiz, bot klonlash limiti (20 ta) to'lgan.")
            return

        # Token allaqachon bormi?
        if any(c["token"] == token for c in config):
            await update.message.reply_text("⚠️ Bu bot tokeni allaqachon ro'yxatdan o'tgan.")
            return

        # Yangi botni qo'shish
        config.append({
            "token": token,
            "admin_id": uid,
            "created_at": datetime.now().isoformat()
        })

        with open(config_file, "w") as f:
            json.dump(config, f, indent=4)

        await update.message.reply_text(
            f"✅ <b>Tabriklaymiz! Botingiz navbatga qo'shildi.</b>\n\n"
            f"👤 Siz bot admini etib tayinlandingiz.\n"
            f"🚀 Tez orada botingiz ishga tushadi (@{token.split(':')[0]}).\n\n"
            f"<i>Eslatma: Bu v2.2 Beta test tizimi.</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Token saqlashda xato: {e}")
        await update.message.reply_text("❌ Xatolik yuz berdi. Iltimos keyinroq urinib ko'ring.")


async def preview_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin uchun kanal xabarini generatsiya qilish va ko'rsatish"""
    uid = update.effective_user.id
    if uid != ADMIN_ID and not DB.is_admin(uid):
        return

    msg = await update.message.reply_text("⏳ AI yangiliklar postini tayyorlamoqda...")
    
    prompt = (
        "Sen Mafia Botining rasmiy yangiliklar yozuvchisisan. "
        "v2.2 Bot Klonlash yangilanishi haqida professional post yoz. "
        "Postda klonlash imkoniyati, manager tizimi va yangi premium dizayn haqida aytilsin. "
        "Emoji va formatlashdan keng foydalan."
    )
    
    try:
        ai_text = await _gemini_chat(0, prompt, "System")
        safe_ai_text = html.escape(ai_text) if ai_text else "Yangiliklar tayyorlashda xatolik."
        full_text = f"📢 <b>KANALGA YUBORILADIGAN POST:</b>\n\n{safe_ai_text}\n\n👇 O'z botingizni yarating: @{BOT_USERNAME}"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Kanalga yuborish", callback_data="adm:send_update")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="adm:back_main")]
        ])
        
        await msg.edit_text(full_text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        await msg.edit_text(f"❌ AI xatolik: {e}")


async def newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    uid = update.effective_user.id

    if check_cooldown(uid):
        await safe_reply(update, context, cooldown_msg(uid))
        return

    error = validate_game_state(chat_id)
    if error:
        await safe_reply(update, context, error)
        return

    if not await is_bot_admin(context, chat_id):
        await safe_reply(update, context, t(uid, "need_admin") + "\n" + t(uid, "make_admin"))
        return

    game = Game(chat_id)
    games[chat_id] = game
    logger.info(f"New game started in chat {chat_id} by user {uid}")

    # Bot username olish
    bot_name = BOT_USERNAME
    if not bot_name:
        try:
            bot_info = await context.bot.get_me()
            bot_name = bot_info.username
        except:
            bot_name = "bot"

    join_url = f"https://t.me/{bot_name}?start=chat_{chat_id}"

    reg_text = (
        f"⚔️ <b>MAFIYA O'YINi BOSHLANMOQDA!</b> ⚔️\n\n"
        f"🎲 O'yinchilar yig'ilmoqda...\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 O'yinchilar: <b>0</b> nafar\n"
        f"⏳ Ro'yxat: <b>{REGISTRATION_TIME} soniya</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👇 <b>Qo'shilish uchun tugmani bosing!</b>"
    )

    try:
        msg = await update.message.reply_text(
            reg_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎮 Qo'shilish / Join", url=join_url)
            ]])
        )
    except Exception:
        msg = await context.bot.send_message(
            chat_id,
            reg_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎮 Qo'shilish / Join", url=join_url)
            ]])
        )
    game.reg_msg_id = msg.message_id
    try:
        await context.bot.pin_chat_message(chat_id, msg.message_id, disable_notification=True)
    except:
        pass

    # Handler darhol qaytadi - o'yin background da ishlaydi
    asyncio.create_task(_registration_timer(context, chat_id))

async def _registration_timer(context, chat_id: int):
    """Registration vaqti tugagandan keyin o'yinni boshlash"""
    await asyncio.sleep(REGISTRATION_TIME)
    if chat_id in games and games[chat_id].state == "registration":
        await start_game(context, chat_id)

# ================== GAME LOGIC ==================

async def start_game(context, chat_id: int):
    """Yangi round boshlash (faqat tirik o'yinchilar bilan)"""
    game = games.get(chat_id)
    if not game or game.state == "stopped":
        return

    # BUG FIX #7: Faqat tirik o'yinchilar bilan o'yin
    alive_players = {uid: p for uid, p in game.players.items() if p.alive}

    if len(alive_players) < MIN_PLAYERS:
        ref_uid = next(iter(game.players), 0)
        try:
            await context.bot.send_message(
                chat_id,
                f"❌ O'yin tugadi — kamida {MIN_PLAYERS} ta o'yinchi kerak!\n"
                f"👥 Hozir: {len(alive_players)} ta"
            )
        except Exception as e:
            logger.error(f"Error sending insufficient players msg: {e}")
        if chat_id in games:
            del games[chat_id]
            session_remove(chat_id)
        return

    try:
        await context.bot.unpin_chat_message(chat_id)
    except:
        pass

    game.round += 1
    
    # --- ACTIVE ROLE & ITEM LOADING ---
    player_id_list = list(alive_players.keys())
    # O'yinchilarning active_role statusini tekshirish
    guaranteed_active = []
    for pid in player_id_list:
        udata = get_uid_data(pid)
        if udata.get("active_role", 0) > 0:
            guaranteed_active.append(pid)
            DB.update_user(pid, active_role=udata["active_role"] - 1)

    # Rol poolini olish
    roles = role_pool(len(alive_players))
    
    # Agar guaranteed_active bo'lsa, ularga Citizen bo'lmagan rollarni berishga harakat qilish
    assigned_roles = {}
    if guaranteed_active:
        # Citizen bo'lmagan rollarni ajratish
        non_citizen_roles = [r for r in roles if r != "citizen"]
        random.shuffle(guaranteed_active)
        for pid in guaranteed_active:
            if non_citizen_roles:
                r = non_citizen_roles.pop(0)
                assigned_roles[pid] = r
                roles.remove(r)
    
    # Qolgan rollarni tarqatish
    remaining_pids = [pid for pid in player_id_list if pid not in assigned_roles]
    random.shuffle(remaining_pids)
    for pid, r in zip(remaining_pids, roles):
        assigned_roles[pid] = r

    # O'yinchilarni yangilash va itemlarni yuklash
    for pid, r in assigned_roles.items():
        p = alive_players[pid]
        p.role = r
        udata = get_uid_data(pid)
        lang_code = udata.get("lang", "uz")
        p.character = get_role_details(r, lang_code)
        
        # Itemlarni yuklash
        p.shield = udata.get("shield", 0)
        # Bitta o'yin uchun max 1 ta ishlatilsin (bazada kamaytirish)
        if p.shield > 0:
            DB.update_user(pid, shield=p.shield - 1)
            p.shield = 1 # Faqat bitta himoya beramiz
        
        # Shield integration: if user has a shield in inventory, consume 1 and set game shield to 2
        inv_shields = user_data.get("shield", 0)
        if inv_shields > 0:
            DB.update_user(p.id, shield=inv_shields - 1)
            p.shield = 2
            logger.info(f"Player {p.id} used a shield from inventory. Game shield: 2")
        else:
            p.shield = 1  # Har roundda default shield

    # Rollarni adminga shaxsiy chatda yuborish
    try:
        role_emojis = {
            "don": "👔", "mafia": "🔪", "doctor": "💚", "killer": "🔎", "sheriff": "👮‍♂️", 
            "maniac": "🩸", "samurai": "⚔️", "ninja": "👁️", "citizen": "👤"
        }
        role_labels = {
            "don": "Don", "mafia": "Mafiya", "doctor": "Shifokor", "killer": "Qotil",
            "sheriff": "Sherif", "maniac": "Telba", "samurai": "Samuray", "ninja": "Ninja",
            "citizen": "Fuqaro"
        }
        admin_report_lines = []
        for pid, r in assigned_roles.items():
            p = alive_players[pid]
            emoji = role_emojis.get(r, "🎭")
            label = role_labels.get(r, r.capitalize())
            admin_report_lines.append(f"{emoji} {label} -> {p.name}")
        
        admin_report = (
            f"🎮 <b>Yangi o'yin rollari taqsimoti:</b>\n"
            f"🏢 Guruh ID: <code>{chat_id}</code>\n\n"
            + "\n".join(admin_report_lines)
        )
        for admin_id in ADMINS:
            asyncio.create_task(context.bot.send_message(admin_id, admin_report, parse_mode="HTML"))
    except Exception as e:
        logger.error(f"Error preparing or sending admin roles report: {e}")

    # Kecha fazasi
    game.state = "night"
    session_remove(chat_id)  # O'yin boshlandi — JSON sessiya kerak emas
    game.private_votes.clear()
    game.night_actions = []
    game.public_votes = {"like": set(), "dislike": set()}
    game.used_night.clear()

    uid = list(alive_players.keys())[0]

    # O'yin boshlanishi e'loni
    player_list = "\n".join([f"   {'👑' if p.role in ('don','mafia') else '👤'} {html.escape(p.name)}" 
                              for p in alive_players.values()])
    start_announce = (
        f"🎲 <b>O'YIN BOSHLANDI!</b> 🎲\n\n"
        f"⚔️ Round <b>{game.round}</b> — O'yinchilar:\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{player_list}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 Jami: <b>{len(alive_players)}</b> nafar\n\n"
        f"📩 Har bir o'yinchi shaxsiy xabar orqali o'z rolini oladi!"
    )
    try:
        await context.bot.send_message(chat_id, start_announce, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error sending start announce: {e}")

    night_text = (
        f"🌙 <b>KECHA BOSHLANDI...</b> 🌙\n\n"
        f"🤫 <i>Shahar uxlab qoldi...</i>\n"
        f"🔪 Mafiya harakatga tayyor!\n"
        f"💚 Doktor kimnidir saqlamoqda...\n"
        f"🔎 Tergovchi sir izlamoqda...\n\n"
        f"⏳ <b>{NIGHT_DURATION} soniya</b> — Jim turing!"
    )
    night_url = DB.get_asset_url("night_start", NIGHT_IMAGE_URL)
    await safe_send_media(context, chat_id, night_url, night_text)

    for player in alive_players.values():
        await send_role_message(context, player, game)

    # Kecha vaqti o'tgach background da process qilish
    asyncio.create_task(_night_timer(context, chat_id))

async def _night_timer(context, chat_id: int):
    await asyncio.sleep(NIGHT_DURATION * adm.get_speed(chat_id))
    if chat_id in games and games[chat_id].state == "night":
        await process_night_actions(context, chat_id)

async def process_night_actions(context, chat_id: int):
    """Kechadagi amallarni bajarish"""
    game = games.get(chat_id)
    if not game or game.state != "night":
        return

    killed_targets: set = set()
    healed_targets: set = set()

    # 1. Gather all actions
    for action in game.night_actions:
        t_id = action.get("target")
        if t_id not in game.players:
            continue
        
        target = game.players[t_id]
        target_inv = get_uid_data(t_id)

        if action["type"] in ("kill", "maniac_kill"):
            # Immortality check
            immortality = target_inv.get("immortality", 0)
            if immortality > 0:
                DB.update_user(t_id, immortality=immortality - 1)
                continue

            if target.shield > 0:
                target.shield -= 1
            else:
                killed_targets.add(t_id)

        elif action["type"] == "heal":
            healed_targets.add(t_id)

        elif action["type"] == "investigate": # Killer
            role = target.role
            docs = target_inv.get("documents", 0)
            if docs > 0:
                DB.update_user(t_id, documents=docs - 1)
                role = "citizen (masked)"
            
            actor = action["actor"]
            try:
                await context.bot.send_message(actor, f"🔎 {target.name}: {role.upper()}")
            except Exception as e:
                logger.error(f"Error sending investigation result to {actor}: {e}")

        elif action["type"] == "sheriff_check": # Sheriff
            role = target.role
            # Sheriff only finds Don and Mafia
            # If target is masked (documents), they appear as citizen
            docs = target_inv.get("documents", 0)
            if docs > 0:
                DB.update_user(t_id, documents=docs - 1)
                result = "✅ CITIZEN"
            elif role in ("mafia", "don"):
                result = f"⚠️ {role.upper()}!"
            else:
                result = "✅ CITIZEN"
            
            actor = action["actor"]
            try:
                msg = t(actor, "sheriff_result").format(result)
                await context.bot.send_message(actor, msg)
            except Exception as e:
                logger.error(f"Error sending sheriff result to {actor}: {e}")

        elif action["type"] == "samurai_kill":
            if target.role in ("mafia", "don"):
                killed_targets.add(t_id)
            else:
                # Samurai killed a good player - both die
                killed_targets.add(t_id)
                killed_targets.add(action["actor"])

        elif action["type"] == "ninja_watch":
            # Just mark for later report
            pass

    # Ninja reporting
    for action in [a for a in game.night_actions if a["type"] == "ninja_watch"]:
        ninja_id = action["actor"]
        target_id = action["target"]
        visitors = []
        for a in game.night_actions:
            if a["actor"] != ninja_id and a.get("target") == target_id:
                visitor = game.players[a["actor"]]
                visitors.append(f"{visitor.name} ({visitor.role.upper()})")
        
        report = f"👁️ <b>Kuzatuv natijasi:</b>\n"
        if visitors:
            report += f"Nishoningizni quyidagilar ziyorat qildi:\n" + "\n".join([f"• {v}" for v in visitors])
        else:
            report += f"Nishoningizni hech kim ziyorat qilmadi."
        
        try:
            await context.bot.send_message(ninja_id, report, parse_mode="HTML")
        except: pass

    # Process deaths
    final_dead = []
    for k_id in killed_targets:
        if k_id in healed_targets:
            # Saved
            try:
                await context.bot.send_message(
                    game.chat_id,
                    t(game.chat_id, "healed").format(game.players[k_id].name)
                )
            except: pass
        else:
            # Dies
            game.players[k_id].alive = False
            final_dead.append(game.players[k_id].name)

    if final_dead:
        try:
            dead_str = ", ".join([html.escape(n) for n in final_dead])
            await context.bot.send_message(
                game.chat_id,
                t(game.chat_id, "eliminated").format(dead_str)
            )
            # O'lgan har bir o'yinchining oxirgi gapini guruhda chiqarish
            for k_id in killed_targets:
                if k_id not in healed_targets:
                    p = game.players[k_id]
                    if p.last_words:
                        await context.bot.send_message(
                            game.chat_id,
                            f"🗣️ <b>{html.escape(p.name)}</b> o'limidan oldin baqirdi: <i>\"{html.escape(p.last_words)}\"</i>",
                            parse_mode="HTML"
                        )
        except Exception as e:
            logger.error(f"Error sending eliminated msg: {e}")

    # G'alaba shartini tekshirish
    winner = await check_win_conditions(context, chat_id)
    if winner:
        await end_game(context, chat_id, winner)
        return

    # Kunduz fazasi
    game.state = "day"
    game.private_votes.clear()

    alive_ids = [p.id for p in game.players.values() if p.alive]
    ref_uid = alive_ids[0] if alive_ids else next(iter(game.players), 0)

    alive_names = "\n".join([f"   ✅ {html.escape(p.name)}" for p in game.players.values() if p.alive])
    dead_names = "\n".join([f"   💀 {html.escape(p.name)}" for p in game.players.values() if not p.alive])

    day_text = (
        f"☀️ <b>TONG OTDI!</b> ☀️\n\n"
        f"🌅 <i>Shahar uyg'ondi... lekin kimdir yo'q!</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>Tirik ({len(alive_ids)}):</b>\n{alive_names}\n"
    )
    if dead_names:
        day_text += f"\n💀 <b>Halok bo'lganlar:</b>\n{dead_names}\n"
    day_text += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💬 <b>Muhokama boshlandi!</b>\n"
        f"⏳ {DAY_DURATION} soniya — Mafiyani toping!"
    )

    day_url = DB.get_asset_url("day_start", DAY_IMAGE_URL)
    await safe_send_media(context, chat_id, day_url, day_text)

    asyncio.create_task(_day_timer(context, chat_id))

async def _day_timer(context, chat_id: int):
    await asyncio.sleep(DAY_DURATION * adm.get_speed(chat_id))
    if chat_id in games and games[chat_id].state == "day":
        await start_voting(context, chat_id)

async def start_voting(context, chat_id: int):
    """Ovoz berish boshlash - shaxsiy chatlarda"""
    game = games.get(chat_id)
    if not game:
        return

    game.state = "voting"
    game.public_votes = {"like": set(), "dislike": set()}
    game.private_votes.clear()

    alive = [p for p in game.players.values() if p.alive]

    # Guruhga e'lon
    try:
        await context.bot.send_message(
            chat_id,
            f"🗳️ <b>Ovoz berish boshlandi!</b>\n\n"
            f"👇 Shaxsiy chatda kimni ayblamoqchiligingizni tanlang!\n"
            f"⏱ {VOTING_DURATION} soniya",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error sending voting announcement: {e}")

    # Har bir o'yinchiga SHAXSIY CHATDA tugmalar yuborish
    for p in alive:
        kb = [[InlineKeyboardButton(f"🗳️ {x.name}", callback_data=f"vote_{x.id}")]
              for x in alive if x.id != p.id]
        try:
            await context.bot.send_message(
                p.id,
                f"🗳️ <b>Kim aybdor?</b>\n\nBir kishini tanlang:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except Exception as e:
            logger.error(f"Error sending vote buttons to {p.id}: {e}")

    asyncio.create_task(_voting_timer(context, chat_id))

async def _voting_timer(context, chat_id: int):
    await asyncio.sleep(VOTING_DURATION * adm.get_speed(chat_id))
    if chat_id in games and games[chat_id].state == "voting":
        await finish_voting(context, chat_id)

async def finish_voting(context, chat_id: int):
    """Ovoz berish natijasini ko'rish va final ovozga o'tish"""
    game = games.get(chat_id)
    if not game:
        return

    alive_ids = [p.id for p in game.players.values() if p.alive]
    uid = alive_ids[0] if alive_ids else 0

    if not game.private_votes:
        try:
            await context.bot.send_message(chat_id, "❌ Hech kim ovoz bermadi. O'yin davom etadi.")
        except Exception as e:
            logger.error(f"Error sending no votes msg: {e}")
        if chat_id in games:
            await start_game(context, chat_id)
        return

    # Eng ko'p ovoz olgan kishini topish
    votes = game.private_votes
    vote_count: Dict[int, int] = {}
    for v in votes.values():
        vote_count[v] = vote_count.get(v, 0) + 1
    target = max(vote_count, key=vote_count.get)

    if target not in game.players:
        await start_game(context, chat_id)
        return

    target_name = game.players[target].name
    target_vote_count = vote_count[target]
    total_voters = len(votes)

    # game holatini yangilash
    game.state = "final_vote"
    game.public_votes = {"like": set(), "dislike": set()}
    # Ayblanuvchini game ichida saqlash
    game._accused_target = target

    # Guruhda ovoz xabari — InlineKeyboard bilan
    # Faqat ovoz SONI ko'rinadi, kimning ovozi emas
    hang_count = 0
    save_count = 0
    voter_count = len([p for p in game.players.values() if p.alive and p.id != target])

    group_text = (
        f"⚖️ <b>AYBLOV!</b>\n\n"
        f"👤 Ayblanuvchi: <b>{html.escape(target_name)}</b>\n"
        f"🗳️ Unga qarshi ovozlar: <b>{target_vote_count}/{total_voters}</b>\n\n"
        f"👍 Osish: <b>0</b>  |  👎 Saqlash: <b>0</b>\n"
        f"📊 {voter_count} nafar ovoz berishi kerak\n\n"
        f"⏱ Ovoz bering!"
    )

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"👍 Osish ({hang_count})", callback_data=f"fvote_h_{target}_{chat_id}"),
        InlineKeyboardButton(f"👎 Saqlash ({save_count})", callback_data=f"fvote_s_{target}_{chat_id}")
    ]])

    try:
        vote_msg = await context.bot.send_message(
            chat_id, group_text, parse_mode="HTML", reply_markup=kb
        )
        # Xabar ID ni saqlaymiz — keyinchalik yangilash uchun
        game._vote_msg_id = vote_msg.message_id
    except Exception as e:
        logger.error(f"Error sending final vote message: {e}")
        game._vote_msg_id = None

    # Ayblanuvchiga shaxsiy xabar
    try:
        await context.bot.send_message(
            target,
            f"⚖️ <b>Siz ayblanmoqdasiz!</b>\n\n"
            f"👥 O'yinchilar osish yoki saqlash haqida ovoz bermoqda...\n"
            f"Natijani guruhda kuting.",
            parse_mode="HTML"
        )
    except:
        pass

async def end_game(context, chat_id: int, winner: str):
    """O'yinni tugatish"""
    game = games.get(chat_id)
    if not game:
        return

    game.state = "end"

    if winner == "mafia":
        winner_ids = [p.id for p in game.players.values() if p.role in ("mafia", "don")]
        winner_label = "🔴 MAFIA"
    elif winner == "maniac":
        winner_ids = [p.id for p in game.players.values() if p.role == "maniac"]
        winner_label = "🔪 MANIAC"
    elif winner == "samurai":
        winner_ids = [p.id for p in game.players.values() if p.role == "samurai"]
        winner_label = "⚔️ SAMURAI"
    elif winner == "ninja":
        winner_ids = [p.id for p in game.players.values() if p.role == "ninja"]
        winner_label = "🥷 NINJA"
    else:
        winner_ids = [p.id for p in game.players.values() if p.role not in ("mafia", "don", "maniac", "ninja", "samurai")]
        winner_label = "🟢 SHAHAR"

    # Statistika yangilash
    for p in game.players.values():
        d = get_uid_data(p.id)
        DB.update_user(p.id,
            games_played=d.get("games_played", 0) + 1,
            last_played=datetime.now().isoformat()
        )

    for wid in winner_ids:
        d = get_uid_data(wid)
        DB.update_user(wid,
            money=d.get("money", 0) + WIN_REWARD,
            games_won=d.get("games_won", 0) + 1
        )

    # Barcha rollarni guruhda ochish
    role_emoji = {
        "don":     "👔 DON",
        "mafia":   "🔪 MAFIA",
        "doctor":  "💊 DOCTOR",
        "killer":  "🔎 KILLER",
        "sheriff": "👮 SHERIFF",
        "maniac":  "🔪 MANIAC",
        "samurai": "⚔️ SAMURAI",
        "ninja":   "🥷 NINJA",
        "citizen": "👨‍💼 TINCH AHOLI",
    }
    roles_text = ""
    for p in game.players.values():
        r = role_emoji.get(p.role, p.role.upper() if p.role else "?")
        alive_icon = "✅" if p.alive else "💀"
        roles_text += f"{alive_icon} {html.escape(p.name)} — <b>{r}</b>\n"

    if winner == "mafia":
        winner_banner = (
            f"🔴 <b>MAFIA G'ALABA QILDI!</b> 🔴\n\n"
            f"😈 <i>Qorong'ulik shaharni yutdi...</i>\n"
            f"🔪 Don va uning sheriklari hamma narsani nazorat ostiga oldi!"
        )
    elif winner == "maniac":
        winner_banner = (
            f"🔪 <b>MANYAK G'ALABA QILDI!</b> 🔪\n\n"
            f"🩸 <i>Hamma o'ldi... faqat u qoldi!</i>\n"
            f"😈 U haqiqiy yirtqich!"
        )
    else:
        winner_banner = (
            f"🟢 <b>SHAHAR G'ALABA QILDI!</b> 🟢\n\n"
            f"🎉 <i>Adolat qaror topdi!</i>\n"
            f"🦸 Qahramonlar mafiyani mag'lub etdi!"
        )

    result_text = (
        f"🏁 <b>O'YIN TUGADI!</b> 🏁\n\n"
        f"{winner_banner}\n\n"
        f"💰 G'oliblar mukofoti: <b>{WIN_REWARD} coin</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎭 <b>Barcha rollar:</b>\n{roles_text}"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎮 Yangi o'yin: /newgame"
    )

    try:
        await context.bot.send_message(chat_id, result_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error sending game end message: {e}")

    # Kanalga natijani yuborish (agar yoqilgan bo'lsa)
    if POST_GAMES_TO_CHANNEL:
        try:
            channel_text = (
                f"🏆 <b>YANGI O'YIN NATIJASI</b> 🏆\n\n"
                f"🎮 O'yin holati: <b>TUGADI</b>\n"
                f"👤 G'olib jamoa: <b>{winner_label}</b>\n"
                f"👥 Ishtirokchilar: <b>{len(game.players)}</b> nafar\n"
                f"💰 Mukofot jamg'armasi: <b>{len(winner_ids) * WIN_REWARD}</b> coin\n"
                f"📅 Sana: <b>{datetime.now().strftime('%d.%m.%Y %H:%M')}</b>\n\n"
                f"🔥 Siz ham o'z botingizni yarating yoki o'yinga qo'shiling: @{BOT_USERNAME}"
            )
            await context.bot.send_message(CHANNEL_ID, channel_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error posting result to channel: {e}")

    # Har bir o'yinchiga shaxsiy xabar
    for p in game.players.values():
        won = p.id in winner_ids
        role_name = role_emoji.get(p.role, "?")
        try:
            if won:
                personal = (
                    f"🎊 <b>TABRIKLAYMIZ!</b> 🎊\n\n"
                    f"🏆 Siz <b>G'OLIB</b>siz!\n"
                    f"🎭 Rolingiz: <b>{role_name}</b>\n"
                    f"💰 Mukofot: <b>+{WIN_REWARD} coin</b> qo'shildi!\n\n"
                    f"⚔️ Yana o'ynash: /newgame"
                )
            else:
                personal = (
                    f"💀 <b>Siz yutqazdingiz...</b>\n\n"
                    f"😔 <i>Bu safar omad kulib boqmadi</i>\n"
                    f"🎭 Rolingiz: <b>{role_name}</b>\n\n"
                    f"💪 Keyingi o'yinda qaytib keling: /newgame"
                )
            await context.bot.send_message(p.id, personal, parse_mode="HTML")
        except:
            pass

    if chat_id in games:
        del games[chat_id]
        session_remove(chat_id)

async def roles_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline menu with role descriptions"""
    uid = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("👔 Don", callback_data="role_info_don"),
         InlineKeyboardButton("🔪 Mafia", callback_data="role_info_mafia")],
        [InlineKeyboardButton("💚 Doctor", callback_data="role_info_doctor"),
         InlineKeyboardButton("🔎 Killer", callback_data="role_info_killer")],
        [InlineKeyboardButton("🕵️‍♂️ Sheriff", callback_data="role_info_sheriff"),
         InlineKeyboardButton("🔪 Maniac", callback_data="role_info_maniac")],
        [InlineKeyboardButton("⚔️ Samurai", callback_data="role_info_samurai"),
         InlineKeyboardButton("👁️ Ninja", callback_data="role_info_ninja")],
        [InlineKeyboardButton("👤 Citizen", callback_data="role_info_citizen")],
    ]
    
    text = (
        "🎭 <b>Rollar haqida ma'lumot</b>\n\n"
        "Quyidagi tugmalarni bosib har bir rol haqida batafsil o'qing:"
    )
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def role_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    role = data.replace("role_info_", "")
    
    info = {
        "don": "👔 <b>DON (Mafia Boshlig'i)</b>\n\n• Kechasi: Bir kishini o'ldirishga buyruq beradi.\n• Kunduz: Oddiy fuqaro kabi ko'rinadi (Sherif tekshirsa ham).",
        "mafia": "🔪 <b>MAFIA</b>\n\n• Kechasi: Don bilan birga o'ldiradi.\n• Maqsad: Shaharni yo'q qilish.",
        "doctor": "💚 <b>DOCTOR</b>\n\n• Kechasi: Bir kishini o'limdan saqlaydi.\n• O'zini ham davolashi mumkin (faqat 1 marta).",
        "killer": "🔎 <b>KILLER (Tergovchi)</b>\n\n• Kechasi: Bir kishining rolini tekshiradi.\n• Maqsad: Mafiyani topish.",
        "sheriff": "🕵️‍♂️ <b>SHERIFF</b>\n\n• Kechasi: Gumondorni tekshiradi.\n• Agar Don yoki Mafia bo'lsa, aniqlaydi.\n• Agar fuqaro bo'lsa, 'Citizen' deb chiqadi.",
        "maniac": "🔪 <b>MANIAC (Manyak)</b>\n\n• Kechasi: Xohlagan kishini o'ldiradi.\n• Yolg'iz o'zi yutishi kerak (yoki 1vs1 qolsa).",
        "samurai": "⚔️ <b>SAMURAI</b>\n\n• Premium rol.\n• Kechasi: Bir kishini o'ldirishi mumkin.\n• Agar begunoh fuqaroni o'ldirsa, o'zi ham o'ladi (Seppuku).",
        "ninja": "👁️ <b>NINJA</b>\n\n• Premium rol.\n• Kechasi: Bir kishini kuzatadi.\n• Agar u kishiga kimdir tashrif buyursa (mafia, doctor, killer...), Ninja buni biladi.",
        "citizen": "👤 <b>CITIZEN (Fuqaro)</b>\n\n• Kechasi: Uxlaydi.\n• Kunduz: Muhokamada qatnashadi va ovoz beradi.\n• Maqsad: Mafiyani topib osish."
    }
    
    text = info.get(role, "Ma'lumot topilmadi.")
    
    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="back_to_roles")]]
    
    await query.answer()
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def announce_update(context: ContextTypes.DEFAULT_TYPE):
    """Kanalga yangilikni e'lon qilish (faqat yangi versiya bo'lsa)"""
    # Check if this version was already announced
    version_file = "last_update.txt"
    last_version = ""
    if os.path.exists(version_file):
        with open(version_file, "r") as f:
            last_version = f.read().strip()
    
    if last_version == UPDATE_VERSION:
        logger.info(f"Update {UPDATE_VERSION} already announced.")
        return

    # Gemini AI orqali yangilik postini generatsiya qilish
    try:
        # Promptni tayyorlash
        prompt = (
            "Sen Mafia Botining rasmiy yangiliklar yozuvchisisan. "
            "Quyidagi yangi qo'shilgan funksiyalar haqida qiziqarli, emojilarga boy va tushunarli post yozib ber. "
            "Post O'zbek tilida bo'lishi kerak. "
            "Postda har bir yangilik nima ekanligi va uni qanday ishlatish kerakligi tushuntirilsin. "
            "\n\nYangi qo'shilgan narsalar:\n"
            "1. Bot Klonlash Tizimi (Multi-bot) - foydalanuvchilar o'z botlarini yaratishi mumkin.\n"
            "2. Har bir foydalanuvchi @BotFather orqali olgan tokenni yuborib bot ochadi.\n"
            "3. Token yuborgan shaxs yangi botga avtomatik Admin bo'ladi.\n"
            "4. Klonlar soni limiti 20 ta.\n"
            "5. O'yin natijalari kanalda yangi premium dizaynda chiqadi.\n\n"
            "Postni sarlavhasi: 🚀 YANGILANISH: Mafia Bot v2.2 Beta!"
        )
        
        # AIni chaqirish (admin nomidan emas, tizim o'zi)
        ai_text = await _gemini_chat(0, prompt, "System")
        
        # Agar AI bo'sh qaytarsa yoki xato bo'lsa, fallback matn ishlatiladi
        safe_ai_text = html.escape(ai_text) if ai_text else ""
        update_text = safe_ai_text + f"\n\n👇 Hoziroq sinab ko'ring: @{BOT_USERNAME}"
        
    except Exception as e:
        logger.error(f"AI generation failed for update post: {e}")
        # Fallback (agar AI ishlamasa)
        update_text = (
            "🚀 <b>YANGILANISH: Mafia Bot v2.2 Beta!</b>\n\n"
            "Yangi versiyada nimalar qo'shildi?\n\n"
            "🤖 <b>Bot Klonlash Tizimi:</b>\n"
            "Endi siz o'z botingizga ega bo'lishingiz mumkin! @BotFather orqasli olingan tokenni bizga yuboring va botingiz ishga tushadi.\n\n"
            "👮‍♂️ <b>Adminlik Huquqi:</b>\n"
            "O'z botingizni yaratganingizda, siz darhol o'sha botning adminiga aylanasiz.\n\n"
            "📊 <b>Premium Dizayn:</b>\n"
            "O'yin natijalari kanalda yangi, chiroyli dizaynda chiqadi.\n\n"
            f"👇 Hoziroq sinab ko'ring: @{BOT_USERNAME}"
        )
    
    try:
        # Kanalga yuborish
        await context.bot.send_message(chat_id=CHANNEL_ID, text=update_text, parse_mode="HTML")
        # Save version
        with open(version_file, "w") as f:
            f.write(UPDATE_VERSION)
        logger.info(f"Announced update {UPDATE_VERSION} to channel.")
        
        # Adminlarga xabar
        for admin_id in ADMINS:
            try:
                await context.bot.send_message(chat_id=admin_id, text="✅ v2.2 Beta e'loni kanalga yuborildi!")
            except: pass
    except Exception as e:
        logger.error(f"Error announcing update: {e}")

# ================== CALLBACKS ==================

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id

    async def safe_answer(text="", alert=False):
        """q.answer() — timeout yoki ikki marta chaqirilganda xato bermaydi"""
        try:
            await q.answer(text, show_alert=alert)
        except Exception:
            pass

    async def safe_edit(text, **kwargs):
        """q.edit_message_text() — xato bo'lsa ignore"""
        try:
            await q.edit_message_text(text, **kwargs)
        except Exception:
            pass

    # Profil rasm o'zgartirish yo'riqnomasi
    if q.data == "change_photo":
        user_data = get_uid_data(uid)
        lang_code = user_data.get("lang", "uz")
        if lang_code == "ru":
            msg = "📸 Отправьте фото с подписью /setphoto — и оно станет вашим фото профиля."
        elif lang_code == "en":
            msg = "📸 Send a photo with caption /setphoto — it will become your profile picture."
        else:
            msg = "📸 Rasmni /setphoto caption bilan yuboring — u profil rasmingiz bo'ladi."
        await safe_answer(msg, alert=True)
        return

    # Til o'zgartirish
    elif q.data.startswith("lang_"):
        lang_code = q.data.split("_")[1]
        DB.update_user(uid, lang=lang_code)
        await safe_answer(t(uid, "lang_set"))
        await safe_edit(t(uid, "lang_set"))

    # Admin callbacklari (admin.py ga yo'naltiriladi)
    if await adm.handle_admin_callback(q, uid, safe_answer, safe_edit, context):
        return

    # Shaxsiy ovoz (kunduz muhokamada)
    elif q.data.startswith("vote_") and not q.data.startswith("fvote_"):
        game = next((g for g in games.values() if uid in g.players and g.state == "voting"), None)
        if not game:
            await safe_answer("⏰ Ovoz berish tugadi.", alert=True)
            return
        if uid in game.private_votes:
            await safe_answer(t(uid, "vote_used"), alert=True)
            return
        try:
            target = int(q.data.split("_")[1])
        except (IndexError, ValueError):
            await safe_answer()
            return
        if target not in game.players:
            await safe_answer()
            return
        game.private_votes[uid] = target
        await safe_answer(t(uid, "target_selected"))

    # Mafia o'ldirish
    elif q.data.startswith("mafia_kill_"):
        # format: mafia_kill_{chat_id}_{target_id}
        parts = q.data.split("_")
        try:
            group_chat_id = int(parts[2])
            target = int(parts[3])
        except (IndexError, ValueError):
            await safe_answer()
            return
        game = games.get(group_chat_id)
        if game and game.state == "night" and uid in game.players and game.players[uid].role in ("mafia", "don"):
            if target in game.players and game.players[target].alive:
                game.night_actions = [a for a in game.night_actions if not (a["type"] == "kill" and a["actor"] == uid)]
                game.night_actions.append({"type": "kill", "actor": uid, "target": target})
                await safe_edit(f"🎯 Nishon: <b>{game.players[target].name}</b>\n✅ Tanlandi!", parse_mode="HTML")
                await safe_answer(t(uid, "target_selected"))
            else:
                await safe_answer("❌ Nishon yo'q yoki o'lgan", alert=True)
        else:
            await safe_answer()

    # Doktor davolash
    elif q.data.startswith("doctor_heal_"):
        # format: doctor_heal_{chat_id}_{target_id}
        parts = q.data.split("_")
        try:
            group_chat_id = int(parts[2])
            target = int(parts[3])
        except (IndexError, ValueError):
            await safe_answer()
            return
        game = games.get(group_chat_id)
        if game and game.state == "night" and uid in game.players and game.players[uid].role == "doctor":
            if target in game.players and game.players[target].alive:
                game.night_actions = [a for a in game.night_actions if not (a["type"] == "heal" and a["actor"] == uid)]
                game.night_actions.append({"type": "heal", "actor": uid, "target": target})
                await safe_edit(f"💚 Davolash: <b>{game.players[target].name}</b>\n✅ Tanlandi!", parse_mode="HTML")
                await safe_answer(t(uid, "target_selected"))
            else:
                await safe_answer()
        else:
            await safe_answer()

    # Killer tekshirish
    elif q.data.startswith("killer_check_"):
        # format: killer_check_{chat_id}_{target_id}
        parts = q.data.split("_")
        try:
            group_chat_id = int(parts[2])
            target = int(parts[3])
        except (IndexError, ValueError):
            await safe_answer()
            return
        game = games.get(group_chat_id)
        if game and game.state == "night" and uid in game.players and game.players[uid].role == "killer":
            if target in game.players and game.players[target].alive:
                if not any(a["type"] == "investigate" and a["actor"] == uid for a in game.night_actions):
                    game.night_actions.append({"type": "investigate", "actor": uid, "target": target})
                    await safe_edit(f"🔍 Tekshirish: <b>{game.players[target].name}</b>\n✅ Yuborildi!", parse_mode="HTML")
                    await safe_answer(t(uid, "investigated"))
                else:
                    await safe_answer("⚠️ Siz allaqachon tekshirdingiz", alert=True)
            else:
                await safe_answer()
        else:
            await safe_answer()

    # Sheriff tekshirish
    elif q.data.startswith("sheriff_check_"):
        parts = q.data.split("_")
        try:
            group_chat_id = int(parts[2])
            target = int(parts[3])
        except (IndexError, ValueError):
            await safe_answer()
            return
        game = games.get(group_chat_id)
        if game and game.state == "night" and uid in game.players and game.players[uid].role == "sheriff":
            if target in game.players and game.players[target].alive:
                game.night_actions = [a for a in game.night_actions if not (a["type"] == "sheriff_check" and a["actor"] == uid)]
                game.night_actions.append({"type": "sheriff_check", "actor": uid, "target": target})
                await safe_edit(f"🕵️‍♂️ Tekshirish: <b>{game.players[target].name}</b>\n✅ Tanlandi!", parse_mode="HTML")
                await safe_answer(t(uid, "target_selected"))
            else:
                await safe_answer()
        else:
            await safe_answer()

    # Maniac o'ldirish
    elif q.data.startswith("maniac_kill_"):
        parts = q.data.split("_")
        try:
            group_chat_id = int(parts[2])
            target = int(parts[3])
        except (IndexError, ValueError):
            await safe_answer()
            return
        game = games.get(group_chat_id)
        if game and game.state == "night" and uid in game.players and game.players[uid].role == "maniac":
            if target in game.players and game.players[target].alive:
                game.night_actions = [a for a in game.night_actions if not (a["type"] == "maniac_kill" and a["actor"] == uid)]
                game.night_actions.append({"type": "maniac_kill", "actor": uid, "target": target})
                await safe_edit(f"🔪 Qurbon: <b>{game.players[target].name}</b>\n✅ Tanlandi!", parse_mode="HTML")
                await safe_answer(t(uid, "maniac_result"))
            else:
                await safe_answer()
        else:
            await safe_answer()

    # === Roles Info Callbacks ===
    elif q.data.startswith("role_info_"):
        await role_info_callback(update, context)
        return

    elif q.data == "back_to_roles":
        await roles_info(update, context)
        return

    # === GURUH FINAL OVOZ: osish/saqlash ===
    elif q.data.startswith("fvote_h_") or q.data.startswith("fvote_s_"):
        # format: fvote_h_{target}_{chat_id}  yoki  fvote_s_{target}_{chat_id}
        parts = q.data.split("_", 3)
        # ['fvote', 'h|s', 'target_id', 'chat_id']
        action = parts[1]  # 'h' = hang, 's' = save
        try:
            target = int(parts[2])
            group_chat_id = int(parts[3])
        except (IndexError, ValueError):
            await safe_answer()
            return

        game = games.get(group_chat_id)
        if not game or game.state != "final_vote":
            await safe_answer("⏰ Ovoz berish tugadi.", alert=True)
            return

        if uid not in game.players or not game.players[uid].alive:
            await safe_answer("❌ Siz ovoz bera olmaysiz.", alert=True)
            return

        if uid == target:
            await safe_answer("❌ O'zingizga ovoz bera olmaysiz!", alert=True)
            return

        if uid in game.public_votes["like"] or uid in game.public_votes["dislike"]:
            await safe_answer("⚠️ Siz allaqachon ovoz bergansiz!", alert=True)
            return

        if action == "h":
            game.public_votes["like"].add(uid)
            await safe_answer("✅ Osish uchun ovoz berdingiz")
        else:
            game.public_votes["dislike"].add(uid)
            await safe_answer("✅ Saqlash uchun ovoz berdingiz")

        hang_count = len(game.public_votes["like"])
        save_count = len(game.public_votes["dislike"])
        total_votes = hang_count + save_count

        target_name = html.escape(game.players[target].name) if target in game.players else "?"
        alive_voters = [p for p in game.players.values() if p.alive and p.id != target]
        remaining = len(alive_voters) - total_votes

        updated_text = (
            f"⚖️ <b>AYBLOV!</b>\n\n"
            f"👤 Ayblanuvchi: <b>{target_name}</b>\n\n"
            f"👍 Osish: <b>{hang_count}</b>  |  👎 Saqlash: <b>{save_count}</b>\n"
            f"📊 Jami: {total_votes}/{len(alive_voters)} ovoz\n"
            + (f"⏳ {remaining} ta ovoz kutilmoqda..." if remaining > 0 else "✅ Barcha ovoz berildi!")
        )

        new_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"👍 Osish ({hang_count})", callback_data=f"fvote_h_{target}_{group_chat_id}"),
            InlineKeyboardButton(f"👎 Saqlash ({save_count})", callback_data=f"fvote_s_{target}_{group_chat_id}")
        ]])

        await safe_edit(updated_text, parse_mode="HTML", reply_markup=new_kb)

        # Barcha tirik o'yinchilar ovoz berdimi?
        if total_votes >= len(alive_voters):
            final_text = (
                f"⚖️ <b>OVOZ TUGADI!</b>\n\n"
                f"👤 Ayblanuvchi: <b>{target_name}</b>\n\n"
                f"👍 Osish: <b>{hang_count}</b>  |  👎 Saqlash: <b>{save_count}</b>"
            )
            await safe_edit(final_text, parse_mode="HTML")

            if hang_count > save_count:
                if target in game.players:
                    game.players[target].alive = False
                    hung_name = game.players[target].name
                    hung_role = game.players[target].role
                    role_emoji_map = {
                        "don": "👔 DON", "mafia": "🔪 MAFIA",
                        "doctor": "💚 DOCTOR", "killer": "🔎 KILLER", "citizen": "👤 FUQARO"
                    }
                    r_label = role_emoji_map.get(hung_role, "?")
                    asyncio.create_task(
                        context.bot.send_message(
                            group_chat_id,
                            f"🪤 <b>{hung_name}</b> osib o'ldirildi!\n"
                            f"🎭 Uning roli: <b>{r_label}</b>",
                            parse_mode="HTML"
                        )
                    )
                    # Osilgan o'yinchining oxirgi gapini guruhda chiqarish
                    p = game.players[target]
                    if p.last_words:
                        asyncio.create_task(
                            context.bot.send_message(
                                group_chat_id,
                                f"🗣️ <b>{html.escape(hung_name)}</b> o'limidan oldin baqirdi: <i>\"{html.escape(p.last_words)}\"</i>",
                                parse_mode="HTML"
                            )
                        )
                    try:
                        await context.bot.send_message(
                            target,
                            f"💀 Siz osib o'ldirildigiz!\n"
                            f"👍 Osish: {hang_count} | 👎 Saqlash: {save_count}"
                        )
                    except:
                        pass
            else:
                # Saqlash (teng bo'lsa ham saqlash)
                if target in game.players:
                    saved_name = game.players[target].name
                    asyncio.create_task(
                        context.bot.send_message(
                            group_chat_id,
                            f"🛡️ <b>{saved_name}</b> saqlab qolindi!\n"
                            f"👍 Osish: {hang_count} | 👎 Saqlash: {save_count}",
                            parse_mode="HTML"
                        )
                    )
                    try:
                        await context.bot.send_message(
                            target,
                            f"🎉 Siz saqlab qolindingiz!\n"
                            f"👍 Osish: {hang_count} | 👎 Saqlash: {save_count}"
                        )
                    except:
                        pass

            asyncio.create_task(start_game(context, group_chat_id))

    # BUG FIX #1: "buy_active_role" uchun to'liq key
    elif q.data.startswith("buy_"):
        item = "_".join(q.data.split("_")[1:])  # "active_role" to'g'ri olinadi
        user_data = get_uid_data(uid)
        lang_code = user_data.get("lang", "uz")
        items = SHOP_ITEMS.get(lang_code, SHOP_ITEMS["uz"])

        if item not in items:
            await safe_answer("❌ Noma'lum mahsulot", alert=True)
            return

        # Radar faqat premium a'zolar uchun
        if item == "radar" and user_data.get("premium", 0) != 1:
            if lang_code == "uz":
                await safe_answer("❌ Radar faqat Premium a'zolar uchun!", alert=True)
            elif lang_code == "ru":
                await safe_answer("❌ Радар доступен только для Premium пользователей!", alert=True)
            else:
                await safe_answer("❌ Radar is only available for Premium members!", alert=True)
            return

        conf = PREMIUM_CONFIG.get("items", {}).get(item)
        if conf and not conf.get("enabled", True):
            await safe_answer("⛔ Bu mahsulot sotuvda yo'q", alert=True)
            return

        price = conf["price"] if conf else items[item]["price"]
        user_money = get_uid_data(uid)["money"]

        if user_money < price:
            await safe_answer(t(uid, "not_enough_money"), alert=True)
            return

        # BUG FIX #3: Persistent storage dan foydalanish
        new_money = user_money - price
        new_item_count = user_data.get(item, 0) + 1
        DB.update_user(uid, money=new_money, **{item: new_item_count})

        item_data = items[item]
        remaining = new_money
        if lang_code == "uz":
            bought_msg = f"Sotib olindi! Qoldi: {remaining} coin"
        elif lang_code == "ru":
            bought_msg = f"Куплено! Осталось: {remaining} монет"
        else:
            bought_msg = f"Purchased! Remaining: {remaining} coins"

        # Classic format message (without anime details)
        type_str = f"\n📺 {item_data['type']}" if item_data.get('type') else ""
        msg = f"✅ {item_data['emoji']} {item_data['name']}{type_str}\n\n{bought_msg}"
        await safe_answer(bought_msg)
        await safe_edit(msg)

    elif q.data.startswith("samurai_kill_"):
        parts = q.data.split("_")
        try:
            group_chat_id = int(parts[2])
            target = int(parts[3])
        except (IndexError, ValueError):
            await safe_answer()
            return
        game = games.get(group_chat_id)
        if game and game.state == "night" and uid in game.players and game.players[uid].role == "samurai":
            if target in game.players and game.players[target].alive:
                game.night_actions = [a for a in game.night_actions if not (a["type"] == "samurai_kill" and a["actor"] == uid)]
                game.night_actions.append({"type": "samurai_kill", "actor": uid, "target": target})
                await safe_edit(f"⚔️ Qatl: <b>{game.players[target].name}</b>\n✅ Tanlandi!", parse_mode="HTML")
                await safe_answer(t(uid, "target_selected"))
            else:
                await safe_answer()
        else:
            await safe_answer()

    elif q.data.startswith("ninja_watch_"):
        parts = q.data.split("_")
        try:
            group_chat_id = int(parts[2])
            target = int(parts[3])
        except (IndexError, ValueError):
            await safe_answer()
            return
        game = games.get(group_chat_id)
        if game and game.state == "night" and uid in game.players and game.players[uid].role == "ninja":
            if target in game.players and game.players[target].alive:
                game.night_actions = [a for a in game.night_actions if not (a["type"] == "ninja_watch" and a["actor"] == uid)]
                game.night_actions.append({"type": "ninja_watch", "actor": uid, "target": target})
                await safe_edit(f"👁️ Kuzatish: <b>{game.players[target].name}</b>\n✅ Tanlandi!", parse_mode="HTML")
                await safe_answer(t(uid, "target_selected"))
            else:
                await safe_answer()
        else:
            await safe_answer()

    else:
        # Noma'lum callback — faqat answer qilish
        await safe_answer()

# ================== CHAT GUARD ==================

async def chat_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kechasi guruhda yozilgan xabarlarni o'chirish va tirik o'yinchilarning oxirgi xabarlarini saqlab borish"""
    if not update.message or not update.message.from_user or update.message.from_user.is_bot:
        return
    # /setphoto caption bilan yuborilgan rasmlarni o'chirmaslik
    if update.message.photo:
        caption = (update.message.caption or "").strip().lower()
        if caption in ("/setphoto", "setphoto"):
            return
    chat_id = update.effective_chat.id
    uid = update.message.from_user.id
    
    if chat_id in games:
        game = games[chat_id]
        if uid in game.players and game.players[uid].alive:
            if update.message.text and not update.message.text.startswith('/'):
                game.players[uid].last_words = update.message.text

    if chat_id in games and games[chat_id].state == "night":
        try:
            await update.message.delete()
        except:
            pass

# ================== MAIN ==================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # ================== BOT KOMANDALAR MENYUSI ==================
    async def post_init(application):
        global BOT_USERNAME
        bot_info = await application.bot.get_me()
        BOT_USERNAME = bot_info.username
        logger.info(f"Bot username: @{BOT_USERNAME}")

        # Admin modulini sozlash
        adm.setup(
            DB=DB,
            ADMIN_ID=ADMIN_ID,
            ADMINS=ADMINS,
            games=games,
            session_remove=session_remove,
            t=t,
            safe_reply=safe_reply,
            check_cooldown=check_cooldown,
            cooldown_msg=cooldown_msg,
            NIGHT_DURATION=NIGHT_DURATION,
            DAY_DURATION=DAY_DURATION,
            VOTING_DURATION=VOTING_DURATION,
            REGISTRATION_TIME=REGISTRATION_TIME,
            PREMIUM_CONFIG=PREMIUM_CONFIG,
        )
        await application.bot.set_my_commands([
            ("start",       "🎭 Botni ishga tushirish"),
            ("newgame",     "🎮 Yangi o'yin boshlash"),
            ("join",        "➕ O'yinga qo'shilish"),
            ("profile",     "👤 Profilni ko'rish"),
            ("balance",     "💰 Balansni ko'rish"),
            ("top",         "🏆 Top o'yinchilar"),
            ("shop",        "🛍 Magazin"),
            ("roles",       "ℹ️ Rollar haqida"),
            ("lang",        "🌍 Tilni o'zgartirish"),
            ("admin",       "⚙️ Admin panel"),
            ("stopgame",    "🛑 O'yinni to'xtatish"),
            ("resetgame",   "♻️ O'yinni reset"),
            ("gamestatus",  "📊 O'yin holati"),
            ("speedgame",   "⏩ O'yinni tezlashtirish"),
            ("showroles",   "🎭 Rollarni ko'rish"),
            ("restartgame", "🔄 O'yinni qayta boshlash"),
            ("ban",         "🚫 Ban qilish"),
            ("unban",       "✅ Ban olib tashlash"),
            ("warn",        "⚠️ Ogohlantirish"),
            ("unwarn",      "🗑 Warnlarni tozalash"),
            ("broadcast",   "📢 Xabar yuborish"),
            ("userinfo",    "🔍 User ma'lumotlari"),
            ("setbalance",  "💰 Balans o'rnatish"),
            ("addmoney",    "💸 Pul qo'shish"),
            ("removemoney", "💸 Pul olib tashlash"),
            ("stats",       "📊 Bot statistikasi"),
            ("addadmin",    "➕ Admin qo'shish"),
            ("removeadmin", "➖ Adminni o'chirish"),
            ("listadmins",  "👨‍💼 Adminlar ro'yxati"),
        ])
        logger.info("Bot komandalar menyusi o'rnatildi!")

        # Avtomatik yangilik e'lon qilish (har safar bot restart bo'lganda)
        # Haqiqiy prod muhitda buni ehtiyotkorlik bilan qilish kerak
        # Hozircha user so'rovi bo'yicha:
        # asyncio.create_task(announce_update(application))

        # ── JSON sessiyalardan o'yinchilarni tiklash ──
        sessions = session_load_all()
        restored = 0
        for key, sess in sessions.items():
            try:
                cid = int(key)
                # Agar o'yin allaqachon xotirada bo'lsa — o'tkazib yubor
                if cid in games:
                    continue
                game = Game(cid)
                game.reg_msg_id = sess.get("reg_msg_id")
                game.state = "registration"
                for p in sess.get("players", []):
                    game.players[p["uid"]] = Player(p["uid"], p["name"])
                games[cid] = game
                restored += 1
                logger.info(f"Sessiya tiklandi: chat {cid}, {len(game.players)} o'yinchi")
            except Exception as e:
                logger.error(f"Sessiya tiklash xatosi ({key}): {e}")
        if restored:
            logger.info(f"Jami {restored} ta sessiya JSON dan tiklandi")

    app.post_init = post_init

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("post", post_to_channel))  # New channel post command
    app.add_handler(CommandHandler("preview", preview_update)) # Admin preview update
    app.add_handler(CommandHandler("roles", roles_info))      # New roles info command
    app.add_handler(CommandHandler("newgame", newgame))
    app.add_handler(CommandHandler("lang", lang))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("admin", adm.admin))
    app.add_handler(CommandHandler("stopgame", adm.stopgame))
    app.add_handler(CommandHandler("resetgame", adm.resetgame))
    app.add_handler(CommandHandler("join", join_command))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("addadmin", adm.addadmin))
    app.add_handler(CommandHandler("removeadmin", adm.removeadmin))
    app.add_handler(CommandHandler("listadmins", adm.listadmins))
    # Premium admin komandalar
    app.add_handler(CommandHandler("ban",         adm.ban))
    app.add_handler(CommandHandler("unban",       adm.unban))
    app.add_handler(CommandHandler("warn",        adm.warn))
    app.add_handler(CommandHandler("unwarn",      adm.unwarn))
    app.add_handler(CommandHandler("setbalance",  adm.setbalance))
    app.add_handler(CommandHandler("addmoney",    adm.addmoney))
    app.add_handler(CommandHandler("removemoney", adm.removemoney))
    app.add_handler(CommandHandler("broadcast",   adm.broadcast))
    app.add_handler(CommandHandler("setpremium",  adm.setpremium))
    app.add_handler(CommandHandler("userinfo",    adm.userinfo))
    app.add_handler(CommandHandler("top",         adm.top))
    app.add_handler(CommandHandler("stats",       adm.stats))
    app.add_handler(CommandHandler("gamestatus",  adm.gamestatus))
    app.add_handler(CommandHandler("speedgame",   adm.speedgame))
    app.add_handler(CommandHandler("showroles",   adm.showroles))
    app.add_handler(CommandHandler("restartgame", adm.restartgame))
    # Help and Roles callbacks (must be before catch-all 'callbacks')
    app.add_handler(CallbackQueryHandler(help_callback, pattern=r'^help_'))
    app.add_handler(CallbackQueryHandler(role_info_callback, pattern=r'^role_info_'))
    app.add_handler(CallbackQueryHandler(roles_info, pattern=r'^back_to_roles$'))
    
    app.add_handler(CallbackQueryHandler(callbacks))
    
    # Admin bucket upload handler (Runs in group -1 to intercept admin uploads when active)
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND,
        admin_file_upload_handler
    ), group=-1)

    # Rasm handler — /setphoto caption bilan (private + guruh)
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, handle_photo))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.GROUPS, handle_photo))
    
    # Instagram Downloader Handler (Must be before chat_guard and ai_chat)
    app.add_handler(MessageHandler(
        filters.Regex(r'https?://(?:www\.)?instagram\.com/(?:p|reels|reel)/[\w-]+'),
        instagram_handler
    ))

    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, chat_guard))
    # AI chat (Gemini) + Nano Banana rasm
    app.add_handler(CommandHandler("aireset", ai_reset))
    app.add_handler(CommandHandler("imagine", imagine))

    # Token registration handler (v2.2)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & filters.Regex(r'^\d{8,12}:[a-zA-Z0-9_-]{35}$'),
        handle_token
    ))

    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        ai_chat
    ))

    logger.info("Bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
