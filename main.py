# advanced_secret_mafia_bot.py
# PROFESSIONAL PRODUCTION VERSION - ANIME THEMED MAFIA GAME

import asyncio
import random
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
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
)

# ================== LOGGING ==================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================== CONFIG ==================

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi. Railway Variables yoki .env ni tekshiring.")

USERS_FILE = Path("users.json")           # Foydalanuvchilar ma'lumotlari
ADMINS_FILE = Path("admins.json")         # Adminlar ro'yxati
PROFILE_DIR = Path("data/profile")        # Profil rasmlari
PROFILE_DIR.mkdir(parents=True, exist_ok=True)
MAX_GAMES = 100
COMMAND_COOLDOWN = 2
MIN_PLAYERS = 3
MAX_PLAYERS = 50

# ESLATMA: Private kanal linklaridan bot rasm yubora olmaydi.
# Agar rasmlar kerak bo'lsa, public URL yoki file_id bilan almashtiring.
# Hozirda xato bo'lsa matnga fallback qiladi.
DAY_IMAGE_URL = "https://t.me/c/3348020476/3"
NIGHT_IMAGE_URL = "https://t.me/c/3348020476/4"

REGISTRATION_TIME = 120
NIGHT_DURATION = 60
DAY_DURATION = 120
VOTING_DURATION = 60

WIN_REWARD = 60

# ================== PERSISTENT STORAGE ==================

import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
import io

# ================== DATABASE MANAGER ==================

class DatabaseManager:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.is_pg = self.db_url is not None and self.db_url.startswith("postgres")
        self._init_db()

    def _get_conn(self):
        if self.is_pg:
            return psycopg2.connect(self.db_url)
        else:
            conn = sqlite3.connect("mafia.db")
            conn.row_factory = sqlite3.Row
            return conn

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
        conn.commit()
        conn.close()

    def get_user(self, uid: int) -> Optional[dict]:
        conn = self._get_conn()
        if self.is_pg:
            cur = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cur = conn.cursor()
        
        cur.execute("SELECT * FROM users WHERE uid = %s" if self.is_pg else "SELECT * FROM users WHERE uid = ?", (uid,))
        row = cur.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None

    def create_user(self, uid: int, name: str = None, username: str = None):
        conn = self._get_conn()
        cur = conn.cursor()
        query = """
            INSERT INTO users (uid, name, username) 
            VALUES (%s, %s, %s)
            ON CONFLICT (uid) DO NOTHING
        """ if self.is_pg else """
            INSERT OR IGNORE INTO users (uid, name, username)
            VALUES (?, ?, ?)
        """
        cur.execute(query, (uid, name, username))
        conn.commit()
        conn.close()

    def update_user(self, uid: int, **kwargs):
        if not kwargs: return
        conn = self._get_conn()
        cur = conn.cursor()
        
        cols = ", ".join([f"{k} = %s" if self.is_pg else f"{k} = ?" for k in kwargs.keys()])
        vals = list(kwargs.values()) + [uid]
        
        query = f"UPDATE users SET {cols} WHERE uid = %s" if self.is_pg else f"UPDATE users SET {cols} WHERE uid = ?"
        cur.execute(query, vals)
        conn.commit()
        conn.close()

    def get_admins(self) -> set:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT uid FROM admins")
        rows = cur.fetchall()
        conn.close()
        return {row[0] for row in rows}

    def add_admin(self, uid: int):
        conn = self._get_conn()
        cur = conn.cursor()
        query = "INSERT INTO admins (uid) VALUES (%s) ON CONFLICT DO NOTHING" if self.is_pg else "INSERT OR IGNORE INTO admins (uid) VALUES (?)"
        cur.execute(query, (uid,))
        conn.commit()
        conn.close()

    def remove_admin(self, uid: int):
        conn = self._get_conn()
        cur = conn.cursor()
        query = "DELETE FROM admins WHERE uid = %s" if self.is_pg else "DELETE FROM admins WHERE uid = ?"
        cur.execute(query, (uid,))
        conn.commit()
        conn.close()

DB = DatabaseManager()

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
            # os.rename("users.json", "users.json.bak") # Havfsizlik uchun o'chirmaymiz
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

def get_uid_data(uid: int) -> dict:
    """Foydalanuvchi ma'lumotlarini olish (baza orqali)"""
    data = DB.get_user(uid)
    if not data:
        DB.create_user(uid)
        data = DB.get_user(uid)
    return data

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

# ================== ANIME SHOP ITEMS ==================

ANIME_ITEMS = {
    "uz": {
        "shield": {
            "name": "🌀 Infinity Barrier",
            "emoji": "🌀",
            "anime": "Gojo - Jujutsu Kaisen",
            "desc": "Kechalik himoya - O'lmasizlanish",
            "price": 20
        },
        "documents": {
            "name": "🎭 Kitsune Mask",
            "emoji": "🎭",
            "anime": "Itachi - Naruto",
            "desc": "Roli yashirish - Haqiqatni bilmaslik",
            "price": 15
        },
        "active_role": {
            "name": "⚡ Bankai Power",
            "emoji": "⚡",
            "anime": "Ichigo - Bleach",
            "desc": "Kuchini o'sishi - Kechalari ish qilish",
            "price": 25
        },
        "immortality": {
            "name": "♾️ Gojoni Cheksizlik",
            "emoji": "♾️",
            "anime": "Senju Hashirama - Naruto",
            "desc": "O'lmasizlik kuchiga boy",
            "price": 50
        },
    },
    "ru": {
        "shield": {
            "name": "🌀 Infinity Barrier",
            "emoji": "🌀",
            "anime": "Gojo - Jujutsu Kaisen",
            "desc": "Защита ночью - Неуязвимость",
            "price": 20
        },
        "documents": {
            "name": "🎭 Kitsune Mask",
            "emoji": "🎭",
            "anime": "Itachi - Naruto",
            "desc": "Скрыть роль - Анонимность",
            "price": 15
        },
        "active_role": {
            "name": "⚡ Bankai Power",
            "emoji": "⚡",
            "anime": "Ichigo - Bleach",
            "desc": "Усиление - Действие ночью",
            "price": 25
        },
        "immortality": {
            "name": "♾️ Вечное Бессмертие",
            "emoji": "♾️",
            "anime": "Senju Hashirama - Naruto",
            "desc": "Сила бессмертия",
            "price": 50
        },
    },
    "en": {
        "shield": {
            "name": "🌀 Infinity Barrier",
            "emoji": "🌀",
            "anime": "Gojo - Jujutsu Kaisen",
            "desc": "Night protection - Invulnerability",
            "price": 20
        },
        "documents": {
            "name": "🎭 Kitsune Mask",
            "emoji": "🎭",
            "anime": "Itachi - Naruto",
            "desc": "Hide your role - Anonymous",
            "price": 15
        },
        "active_role": {
            "name": "⚡ Bankai Power",
            "emoji": "⚡",
            "anime": "Ichigo - Bleach",
            "desc": "Power boost - Act at night",
            "price": 25
        },
        "immortality": {
            "name": "♾️ Eternal Immortality",
            "emoji": "♾️",
            "anime": "Senju Hashirama - Naruto",
            "desc": "Power of eternity",
            "price": 50
        },
    },
}

# ================== CHARACTER UNIQUE ABILITIES ==================

CHARACTER_ABILITIES = {
    "Gojo Satoru": {
        "abilities": [
            "♾️ Infinity Barrier - Absolute protection",
            "🔵 Blue - Attraction technique",
            "⚫ White - Repulsion technique",
            "🌟 Domain Expansion - Unlimited Void"
        ]
    },
    "Itachi Uchiha": {
        "abilities": [
            "👁️ Tsukuyomi - Infinite torture",
            "🔥 Amaterasu - Black flames",
            "🦅 Susanoo - Perfect defense",
            "🕷️ Genjutsu - Mind control"
        ]
    },
    "Aizen Sosuke": {
        "abilities": [
            "🌀 Kyoka Suigetsu - Perfect illusion",
            "⚔️ Zanpakuto - Soul sword",
            "👑 Hogyoku - Transcendence",
            "💫 Reiryoku - Spiritual power"
        ]
    },
    "Sukuna": {
        "abilities": [
            "🌊 Domain Expansion - Malevolent Shrine",
            "✂️ Dismantle - Slashing technique",
            "📉 Cleave - Devastating attack",
            "🔥 Fire Technique - Immense power"
        ]
    },
    "Pain": {
        "abilities": [
            "👁️ Rinnegan - All seeing eyes",
            "🌍 Universal Pull - Attraction",
            "💥 Planetary Devastation - Mass destruction",
            "🗡️ Six Paths - Multiple bodies"
        ]
    },
    "Deidara": {
        "abilities": [
            "💣 Clay Explosives - Various sizes",
            "🛩️ Flying Clay Bird - Transportation",
            "🎨 Art is Explosion - Philosophy",
            "✨ C4 - Microscopic bombs"
        ]
    },
    "Tony Tony Chopper": {
        "abilities": [
            "🦌 Human form - Medical knowledge",
            "💪 Heavy Point - Strength boost",
            "🧲 Magnet form - Metal control",
            "❄️ Rumble Balls - Transformation"
        ]
    },
    "Orihime Inoue": {
        "abilities": [
            "✨ Tsubaki - Offensive power",
            "🛡️ Santen Kesshun - Defense",
            "🔄 Shun'o - Speed boost",
            "💚 Healing - Restore health"
        ]
    },
    "Sakura Haruno": {
        "abilities": [
            "💚 Healing Jutsu - Restore health",
            "💪 Strength boost - Powerful strikes",
            "🧠 Intelligence - Strategic thinking",
            "🏥 Medical Ninjutsu - Advanced healing"
        ]
    },
    "L Lawliet": {
        "abilities": [
            "🔎 Deduction - Logical analysis",
            "🧠 Strategy - Perfect planning",
            "🎵 Mind Games - Psychological warfare",
            "📊 Analysis - Information gathering"
        ]
    },
    "Toji Fushiguro": {
        "abilities": [
            "⚔️ Cursed Weapons - Enhanced tools",
            "💪 Physical Prowess - Superhuman strength",
            "🔪 Assassination Techniques - Deadly accuracy",
            "🛡️ Combat Experience - Master fighter"
        ]
    },
    "Shikamaru Nara": {
        "abilities": [
            "🎲 Shadow Possession - Control opponents",
            "🌑 Shadow Clone - Create duplicates",
            "🧠 Strategy - Brilliant planning",
            "📐 Geometry - Spatial awareness"
        ]
    },
    "Tanjiro Kamado": {
        "abilities": [
            "🔥 Water Breathing - Flowing techniques",
            "💨 Dance of the Fire God - Devastating attacks",
            "👃 Smell Detection - Track enemies",
            "❤️ Willpower - Never give up"
        ]
    },
    "Luffy": {
        "abilities": [
            "🏴‍☠️ Gear Second - Speed boost",
            "💪 Gear Third - Power technique",
            "⚫ Gear Fourth - Ultimate form",
            "🤜 Gum Gum Fruit - Rubber body"
        ]
    },
    "Ichigo Kurosaki": {
        "abilities": [
            "⚡ Bankai - Ultimate soul form",
            "🗡️ Zangetsu - Spirit sword",
            "👻 Hollow Powers - Mask transformation",
            "🔥 Getsuga Tensho - Destructive wave"
        ]
    },
    "Naruto Uzumaki": {
        "abilities": [
            "🍜 Rasengan - Spinning sphere",
            "🦊 Nine-Tailed Fox - Beast power",
            "🔴 Bijuu Mode - Full power",
            "😤 Never Give Up - Determination"
        ]
    },
}

# ================== ANIME CHARACTERS ==================

ANIME_CHARACTERS = {
    "uz": {
        "don": [
            {"name": "Gojo Satoru", "emoji": "👔", "anime": "Jujutsu Kaisen", "desc": "Qudratli rahbar"},
            {"name": "Itachi Uchiha", "emoji": "🕵️", "anime": "Naruto", "desc": "Jimjit don"},
            {"name": "Aizen Sosuke", "emoji": "⚫", "anime": "Bleach", "desc": "Sehrli rahbar"},
        ],
        "mafia": [
            {"name": "Sukuna", "emoji": "👹", "anime": "Jujutsu Kaisen", "desc": "Kuchli qotil"},
            {"name": "Pain", "emoji": "💜", "anime": "Naruto", "desc": "Ko'p ko'zli"},
            {"name": "Deidara", "emoji": "💣", "anime": "Naruto", "desc": "Portlovchi"},
        ],
        "doctor": [
            {"name": "Tony Tony Chopper", "emoji": "🦌", "anime": "One Piece", "desc": "Tabib"},
            {"name": "Orihime Inoue", "emoji": "💫", "anime": "Bleach", "desc": "Davolovchi"},
            {"name": "Sakura Haruno", "emoji": "🌸", "anime": "Naruto", "desc": "Shifokor"},
        ],
        "killer": [
            {"name": "L Lawliet", "emoji": "🔎", "anime": "Death Note", "desc": "Aqlli tergovchi"},
            {"name": "Toji Fushiguro", "emoji": "⚔️", "anime": "Jujutsu Kaisen", "desc": "Kasbiy qotil"},
            {"name": "Shikamaru Nara", "emoji": "🎲", "anime": "Naruto", "desc": "Strategist"},
        ],
        "citizen": [
            {"name": "Tanjiro Kamado", "emoji": "🔥", "anime": "Demon Slayer", "desc": "Jasur yo'lovchi"},
            {"name": "Luffy", "emoji": "🏴‍☠️", "anime": "One Piece", "desc": "Shodmon kapitan"},
            {"name": "Ichigo Kurosaki", "emoji": "⚪", "anime": "Bleach", "desc": "Oddiy talaba"},
            {"name": "Naruto Uzumaki", "emoji": "🍜", "anime": "Naruto", "desc": "Yosh ninja"},
        ],
    },
    "ru": {
        "don": [
            {"name": "Gojo Satoru", "emoji": "👔", "anime": "Jujutsu Kaisen", "desc": "Могущественный лидер"},
            {"name": "Itachi Uchiha", "emoji": "🕵️", "anime": "Naruto", "desc": "Молчаливый босс"},
            {"name": "Aizen Sosuke", "emoji": "⚫", "anime": "Bleach", "desc": "Мистический лидер"},
        ],
        "mafia": [
            {"name": "Sukuna", "emoji": "👹", "anime": "Jujutsu Kaisen", "desc": "Жестокий убийца"},
            {"name": "Pain", "emoji": "💜", "anime": "Naruto", "desc": "Всевидящие глаза"},
            {"name": "Deidara", "emoji": "💣", "anime": "Naruto", "desc": "Взрывчатый художник"},
        ],
        "doctor": [
            {"name": "Tony Tony Chopper", "emoji": "🦌", "anime": "One Piece", "desc": "Переродившийся врач"},
            {"name": "Orihime Inoue", "emoji": "💫", "anime": "Bleach", "desc": "Сила исцеления"},
            {"name": "Sakura Haruno", "emoji": "🌸", "anime": "Naruto", "desc": "Гениальный медик"},
        ],
        "killer": [
            {"name": "L Lawliet", "emoji": "🔎", "anime": "Death Note", "desc": "Блестящий детектив"},
            {"name": "Toji Fushiguro", "emoji": "⚔️", "anime": "Jujutsu Kaisen", "desc": "Профессиональный киллер"},
            {"name": "Shikamaru Nara", "emoji": "🎲", "anime": "Naruto", "desc": "Стратегический гений"},
        ],
        "citizen": [
            {"name": "Tanjiro Kamado", "emoji": "🔥", "anime": "Demon Slayer", "desc": "Решительный охотник"},
            {"name": "Luffy", "emoji": "🏴‍☠️", "anime": "One Piece", "desc": "Весёлый капитан"},
            {"name": "Ichigo Kurosaki", "emoji": "⚪", "anime": "Bleach", "desc": "Обычный студент"},
            {"name": "Naruto Uzumaki", "emoji": "🍜", "anime": "Naruto", "desc": "Духовный ниндзя"},
        ],
    },
    "en": {
        "don": [
            {"name": "Gojo Satoru", "emoji": "👔", "anime": "Jujutsu Kaisen", "desc": "Powerful Leader"},
            {"name": "Itachi Uchiha", "emoji": "🕵️", "anime": "Naruto", "desc": "Silent Don"},
            {"name": "Aizen Sosuke", "emoji": "⚫", "anime": "Bleach", "desc": "Mystical Leader"},
        ],
        "mafia": [
            {"name": "Sukuna", "emoji": "👹", "anime": "Jujutsu Kaisen", "desc": "Cruel Killer"},
            {"name": "Pain", "emoji": "💜", "anime": "Naruto", "desc": "All-Seeing Eyes"},
            {"name": "Deidara", "emoji": "💣", "anime": "Naruto", "desc": "Explosive Artist"},
        ],
        "doctor": [
            {"name": "Tony Tony Chopper", "emoji": "🦌", "anime": "One Piece", "desc": "Reborn Doctor"},
            {"name": "Orihime Inoue", "emoji": "💫", "anime": "Bleach", "desc": "Healing Power"},
            {"name": "Sakura Haruno", "emoji": "🌸", "anime": "Naruto", "desc": "Brilliant Medic"},
        ],
        "killer": [
            {"name": "L Lawliet", "emoji": "🔎", "anime": "Death Note", "desc": "Brilliant Detective"},
            {"name": "Toji Fushiguro", "emoji": "⚔️", "anime": "Jujutsu Kaisen", "desc": "Professional Killer"},
            {"name": "Shikamaru Nara", "emoji": "🎲", "anime": "Naruto", "desc": "Strategic Genius"},
        ],
        "citizen": [
            {"name": "Tanjiro Kamado", "emoji": "🔥", "anime": "Demon Slayer", "desc": "Determined Slayer"},
            {"name": "Luffy", "emoji": "🏴‍☠️", "anime": "One Piece", "desc": "Cheerful Captain"},
            {"name": "Ichigo Kurosaki", "emoji": "⚪", "anime": "Bleach", "desc": "Ordinary Student"},
            {"name": "Naruto Uzumaki", "emoji": "🍜", "anime": "Naruto", "desc": "Spirited Ninja"},
        ],
    },
}

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
        "target_selected": "✅ Maqsad tanlandi",
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

USER_LANG: Dict[int, str] = {} # Legacy fallback

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
        self.anime_character: Optional[dict] = None
        self.abilities: List[str] = []
        self.shield = 1  # Hammaga default shield
        self.has_documents = False
        self.active_role = False

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

games: Dict[int, Game] = {}

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
    return uid in ADMINS

def validate_game_state(chat_id: int) -> Optional[str]:
    if len(games) >= MAX_GAMES:
        return "❌ Maksimal o'yin soni to'ldi"
    if chat_id in games and games[chat_id].state not in ("end", "stopped"):
        return "⚠️ Bu guruhda allaqachon o'yin olib borilmoqda"
    return None

def role_pool(n: int) -> List[str]:
    """n o'yinchi uchun rol ro'yxati"""
    # Asosiy rollar (kamida 1 don, 1 mafia kerak)
    mafia_count = max(1, n // 4)
    roles = ["don"] + ["mafia"] * mafia_count + ["doctor", "killer"]
    while len(roles) < n:
        roles.append("citizen")
    random.shuffle(roles)
    return roles[:n]

def get_anime_char(role: str, lang: str = "uz") -> dict:
    chars = ANIME_CHARACTERS.get(lang, ANIME_CHARACTERS["uz"])
    options = chars.get(role, [{"name": "Unknown", "emoji": "❓", "anime": "Unknown", "desc": ""}])
    return random.choice(options)

async def safe_send_photo(context, chat_id: int, photo_url: str, caption: str):
    """Rasm yuborishga urinadi, xato bo'lsa matn yuboradi"""
    try:
        await context.bot.send_photo(chat_id, photo_url, caption=caption)
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        await context.bot.send_message(chat_id, caption)

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
    char = player.anime_character

    text = f"{char['emoji']} {char['name']} ({char['anime']})\n"
    text += f"🎭 Rol: {player.role.upper()}\n"
    text += f"📖 {char['desc']}\n"
    text += f"🛡️ Himoya: {player.shield}\n\n"

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
            kb = [[InlineKeyboardButton(f"🎯 {x.name}", callback_data=f"mafia_kill_{x.id}")] for x in targets]
            text += "\n\n" + t(uid, "mafia_target")
            try:
                await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(kb))
            except Exception as e:
                logger.error(f"Error sending kill buttons to {uid}: {e}")
        else:
            await context.bot.send_message(uid, text)

    elif player.role == "doctor":
        targets = [p for p in game.players.values() if p.alive]
        kb = [[InlineKeyboardButton(f"💚 {x.name}", callback_data=f"doctor_heal_{x.id}")] for x in targets]
        text += "\n\n" + t(uid, "doctor_heal")
        try:
            await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            logger.error(f"Error sending heal buttons to {uid}: {e}")

    elif player.role == "killer":
        targets = [p for p in game.players.values() if p.alive and p.id != uid]
        kb = [[InlineKeyboardButton(f"🔍 {x.name}", callback_data=f"killer_check_{x.id}")] for x in targets]
        text += "\n\n" + t(uid, "killer_show")
        try:
            await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            logger.error(f"Error sending killer buttons to {uid}: {e}")

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
    good = [p for p in alive if p.role not in ("mafia", "don")]

    if len(mafia) == 0:
        return "good"
    elif len(mafia) >= len(good):
        return "mafia"
    return None

# ================== COMMANDS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_data = get_uid_data(uid)
    lang = user_data.get("lang", "uz")

    if lang == "ru":
        text = ("🎭 Advanced Secret Mafia Bot\n\n"
                "📋 Команды:\n"
                "/newgame - Начать игру\n"
                "/join - Присоединиться\n"
                "/lang - Сменить язык\n"
                "/shop - Магазин\n"
                "/balance - Баланс\n\n"
                "👮‍♂️ Для админов:\n"
                "/admin - Панель\n"
                "/stopgame - Остановить игру\n"
                "/resetgame - Сброс")
    elif lang == "en":
        text = ("🎭 Advanced Secret Mafia Bot\n\n"
                "📋 Commands:\n"
                "/newgame - Start game\n"
                "/join - Join game\n"
                "/lang - Change language\n"
                "/shop - Shop\n"
                "/balance - Check balance\n\n"
                "👮‍♂️ Admin commands:\n"
                "/admin - Admin panel\n"
                "/stopgame - Stop game\n"
                "/resetgame - Reset game")
    else:
        text = ("🎭 Advanced Secret Mafia Bot\n\n"
                "📋 Buyruqlar:\n"
                "/newgame - O'yin boshlash\n"
                "/join - O'yinga qo'shilish\n"
                "/lang - Tilni o'zgartirish\n"
                "/shop - Magazin\n"
                "/balance - Balans\n\n"
                "👮‍♂️ Admin buyruqlari:\n"
                "/admin - Admin panel\n"
                "/stopgame - O'yinni to'xtating\n"
                "/resetgame - O'yinni tikla")

    await safe_reply(update, context, text)

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
    items = ANIME_ITEMS.get(lang_code, ANIME_ITEMS["uz"])

    kb = []
    shop_text = "🛍 " + t(uid, "shop_menu") + "\n\n"

    for item_key, item_data in items.items():
        price_str = f"{item_data['price']} coin" if item_data['price'] > 0 else "🎁 FREE"
        kb.append([InlineKeyboardButton(
            f"{item_data['emoji']} {item_data['name']} ({price_str})",
            # BUG FIX #1: callback_data "buy_active_role" uchun to'liq key ishlatiladi
            callback_data=f"buy_{item_key}"
        )])
        shop_text += f"{item_data['emoji']} {item_data['name']} ({price_str})\n"
        shop_text += f"  📺 {item_data['anime']}\n"
        shop_text += f"  {item_data['desc']}\n\n"

    await safe_reply(update, context, shop_text, reply_markup=InlineKeyboardMarkup(kb))

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if check_cooldown(uid):
        await safe_reply(update, context, cooldown_msg(uid))
        return
    if not is_user_admin(uid):
        await safe_reply(update, context, t(uid, "not_admin"))
        return
    kb = [
        [InlineKeyboardButton("👥 " + t(uid, "admins_list"), callback_data="list_admins")],
        [InlineKeyboardButton("🛑 " + t(uid, "stop_game"), callback_data="admin_stop_game")],
    ]
    await safe_reply(update, context, t(uid, "admin_panel"), reply_markup=InlineKeyboardMarkup(kb))

async def stopgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    if check_cooldown(uid):
        await safe_reply(update, context, cooldown_msg(uid))
        return
    if not is_user_admin(uid):
        await safe_reply(update, context, t(uid, "not_admin"))
        return
    if chat_id not in games:
        await safe_reply(update, context, t(uid, "game_not_found"))
        return
    games[chat_id].state = "stopped"
    del games[chat_id]
    logger.info(f"Admin {uid} stopped game in chat {chat_id}")
    await update.message.reply_text("🛑 " + t(uid, "game_stopped"))

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Profil ko'rsatish"""
    uid = update.effective_user.id
    user = update.effective_user

    # Foydalanuvchi ma'lumotlarini yangilash
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

    if lang_code == "ru":
        text = (
            f"👤 <b>{user.full_name}</b>\n"
            f"🔖 {username_str}\n"
            f"🆔 <code>{uid}</code>\n\n"
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
        text = (
            f"👤 <b>{user.full_name}</b>\n"
            f"🔖 {username_str}\n"
            f"🆔 <code>{uid}</code>\n\n"
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
        text = (
            f"👤 <b>{user.full_name}</b>\n"
            f"🔖 {username_str}\n"
            f"🆔 <code>{uid}</code>\n\n"
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
            await update.message.reply_photo(
                photo=io.BytesIO(photo_blob),
                caption=text,
                parse_mode="HTML",
                reply_markup=kb
            )
            return
        except Exception as e:
            logger.error(f"Error sending profile photo from DB for {uid}: {e}")
            # Fallback to text only if photo fails or message is missing
            await safe_reply(update, context, text, parse_mode="HTML", reply_markup=kb)
            return

    # Rasmsiz profil
    await safe_reply(update, context, text, parse_mode="HTML", reply_markup=kb)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi rasm yuborganda — /setphoto caption bo'lsa saqlash"""
    if not update.message or not update.message.photo:
        return

    caption = (update.message.caption or "").strip().lower()
    uid = update.effective_user.id

    # Faqat /setphoto caption bilan yuborilgan rasmlarni qabul qilish
    if caption not in ("/setphoto", "setphoto"):
        return

    # Eng yuqori sifatli rasmni olish
    photo = update.message.photo[-1]

    try:
        # Faylni yuklab olish va binary ko'rinishda saqlash
        f_info = await context.bot.get_file(photo.file_id)
        photo_bytes = await f_info.download_as_bytearray()
        
        # Baza yangilash
        DB.update_user(uid, photo=photo_bytes)

        user_data = get_uid_data(uid)
        lang_code = user_data.get("lang", "uz")
        if lang_code == "ru":
            msg = "✅ Фото профиля обновлено! Используйте /profile для просмотра."
        elif lang_code == "en":
            msg = "✅ Profile photo updated! Use /profile to view."
        else:
            msg = "✅ Profil rasmi yangilandi! Ko'rish uchun /profile."

        await safe_reply(update, context, msg)
        logger.info(f"User {uid} updated profile photo in Database.")

    except Exception as e:
        logger.error(f"Error saving binary photo to DB for {uid}: {e}")
        await update.message.reply_text("❌ Rasm saqlashda xato. Qayta urinib ko'ring.")

async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await safe_reply(update, context, t(uid, "not_admin"))
        return
    if not context.args:
        await safe_reply(update, context, "❓ Ishlatish: /addadmin <user_id>")
        return
    try:
        new_admin_id = int(context.args[0])
    except ValueError:
        await safe_reply(update, context, "❌ ID raqam bo'lishi kerak")
        return
    if new_admin_id in ADMINS:
        await safe_reply(update, context, f"⚠️ {new_admin_id} allaqachon admin")
        return
    ADMINS.add(new_admin_id)
    DB.add_admin(new_admin_id)
    logger.info(f"Admin {uid} added new admin: {new_admin_id}")
    await safe_reply(update, context, f"✅ {new_admin_id} admin qilindi!\n👥 Jami adminlar: {len(ADMINS)}")

async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await update.message.reply_text(t(uid, "not_admin"))
        return
    if not context.args:
        await update.message.reply_text("❓ Ishlatish: /removeadmin <user_id>")
        return
    try:
        rem_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID raqam bo'lishi kerak")
        return
    if rem_id == ADMIN_ID:
        await update.message.reply_text("❌ Asosiy adminni o'chirib bo'lmaydi")
        return
    if rem_id not in ADMINS:
        await update.message.reply_text(f"⚠️ {rem_id} admin emas")
        return
    ADMINS.discard(rem_id)
    DB.remove_admin(rem_id)
    logger.info(f"Admin {uid} removed admin: {rem_id}")
    await update.message.reply_text(f"✅ {rem_id} admin ro'yxatidan olib tashlandi")

async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await safe_reply(update, context, t(uid, "not_admin"))
        return
    if not ADMINS:
        await safe_reply(update, context, "👥 Adminlar yo'q")
        return
    lines = []
    for a in ADMINS:
        tag = " 👑 (asosiy)" if a == ADMIN_ID else ""
        lines.append(f"• {a}{tag}")
    await safe_reply(update, context, f"👨‍💼 Adminlar ro'yxati ({len(ADMINS)}):\n\n" + "\n".join(lines))

async def resetgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    if check_cooldown(uid):
        await safe_reply(update, context, cooldown_msg(uid))
        return
    if not is_user_admin(uid):
        await safe_reply(update, context, t(uid, "not_admin"))
        return
    if chat_id in games:
        games[chat_id].state = "stopped"
        del games[chat_id]
    await safe_reply(update, context, "✅ O'yin tiklandi / Сброс выполнен / Game reset")

async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    uid = update.effective_user.id
    first_name = update.effective_user.first_name

    game = games.get(chat_id)
    if not game:
        await safe_reply(update, context, "❌ O'yin yo'q. /newgame")
        return
    if game.state != "registration":
        await safe_reply(update, context, "⛔ Ro'yxatga olish yopiq.")
        return
    if uid in game.players:
        await safe_reply(update, context, t(uid, "already_joined"))
        return

    game.players[uid] = Player(uid, first_name)
    await safe_reply(update, context, f"✅ {first_name} qo'shildi! Jami: {len(game.players)}")

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

    try:
        msg = await update.message.reply_text(
            t(uid, "reg_started"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Qo'shilish / Join", callback_data="join")]])
        )
    except Exception:
        msg = await context.bot.send_message(
            chat_id,
            t(uid, "reg_started"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Qo'shilish / Join", callback_data="join")]])
        )
    game.reg_msg_id = msg.message_id
    try:
        await context.bot.pin_chat_message(chat_id, msg.message_id, disable_notification=True)
    except:
        pass

    await asyncio.sleep(REGISTRATION_TIME)

    # O'yin hali mavjud va to'xtatilmagan bo'lsa boshlash
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
        try:
            await context.bot.send_message(chat_id, t(list(game.players.keys())[0] if game.players else 0, "insufficient_players"))
        except Exception as e:
            logger.error(f"Error sending insufficient players msg: {e}")
        if chat_id in games:
            del games[chat_id]
        return

    try:
        await context.bot.unpin_chat_message(chat_id)
    except:
        pass

    game.round += 1
    roles = role_pool(len(alive_players))

    # Rolllarni faqat tirik o'yinchilarga berish
    for p, r in zip(alive_players.values(), roles):
        p.role = r
        user_data = get_uid_data(p.id)
        lang_code = user_data.get("lang", "uz")
        p.anime_character = get_anime_char(r, lang_code)
        
        # Shield integration: if user has a shield in inventory, consume 1 and set game shield to 2
        inv_shields = user_data.get("shield", 0)
        if inv_shields > 0:
            DB.update_user(p.id, shield=inv_shields - 1)
            p.shield = 2
            logger.info(f"Player {p.id} used a shield from inventory. Game shield: 2")
        else:
            p.shield = 1  # Har roundda default shield
            
        if p.anime_character['name'] in CHARACTER_ABILITIES:
            p.abilities = CHARACTER_ABILITIES[p.anime_character['name']]['abilities'].copy()

    # Kecha fazasi
    game.state = "night"
    game.private_votes.clear()
    game.night_actions = []
    game.public_votes = {"like": set(), "dislike": set()}
    game.used_night.clear()

    uid = list(alive_players.keys())[0]
    await safe_send_photo(context, chat_id, NIGHT_IMAGE_URL, t(uid, "night"))

    for player in alive_players.values():
        await send_role_message(context, player, game)

    await asyncio.sleep(NIGHT_DURATION)

    if chat_id in games and games[chat_id].state == "night":
        await process_night_actions(context, chat_id)

async def process_night_actions(context, chat_id: int):
    """Kechadagi amallarni bajarish"""
    game = games.get(chat_id)
    if not game or game.state != "night":
        return

    killed: Optional[int] = None
    healed: Optional[int] = None

    for action in game.night_actions:
        t_id = action.get("target")
        if t_id not in game.players:
            continue

        target = game.players[t_id]
        target_inv = get_uid_data(t_id)

        if action["type"] == "kill":
            # BUG FIX: Immortality check
            immortality = target_inv.get("immortality", 0)
            if immortality > 0:
                DB.update_user(t_id, immortality=immortality - 1)
                continue

            if target.shield > 0:
                target.shield -= 1
                # Shield ishlatildi, yana bir marta o'ldirilsa - o'ladi
            else:
                killed = t_id

        elif action["type"] == "heal":
            healed = t_id

        elif action["type"] == "investigate":
            role = target.role
            # BUG FIX: Documents check
            docs = target_inv.get("documents", 0)
            if docs > 0:
                DB.update_user(t_id, documents=docs - 1)
                role = "citizen (masked)"
            
            actor = action["actor"]
            try:
                await context.bot.send_message(actor, f"🔎 {target.name}: {role.upper()}")
            except Exception as e:
                logger.error(f"Error sending investigation result to {actor}: {e}")

    # Tibbiy yordam bo'lmasa o'ldirish
    if killed and killed != healed:
        game.players[killed].alive = False
        uid = list(game.players.keys())[0]
        await context.bot.send_message(
            game.chat_id,
            t(uid, "eliminated").format(game.players[killed].name)
        )
    elif killed and killed == healed:
        uid = list(game.players.keys())[0]
        await context.bot.send_message(
            game.chat_id,
            t(uid, "healed").format(game.players[killed].name)
        )

    # G'alaba shartini tekshirish
    winner = await check_win_conditions(context, chat_id)
    if winner:
        await end_game(context, chat_id, winner)
        return

    # Kunduz fazasi
    game.state = "day"
    game.private_votes.clear()
    
    # Robust UID selection for translation
    alive_ids = [p.id for p in game.players.values() if p.alive]
    uid = alive_ids[0] if alive_ids else (list(game.players.keys())[0] if game.players else 0)
    
    await safe_send_photo(context, chat_id, DAY_IMAGE_URL, t(uid, "day"))

    await asyncio.sleep(DAY_DURATION)

    if chat_id in games and games[chat_id].state == "day":
        await start_voting(context, chat_id)

async def start_voting(context, chat_id: int):
    """Ovoz berish boshlash"""
    game = games.get(chat_id)
    if not game:
        return

    game.state = "voting"
    game.public_votes = {"like": set(), "dislike": set()}
    game.private_votes.clear()

    alive = [p for p in game.players.values() if p.alive]
    for p in alive:
        kb = [[InlineKeyboardButton(f"🗳️ {x.name}", callback_data=f"vote_{x.id}")]
              for x in alive if x.id != p.id]
        try:
            await context.bot.send_message(
                p.id,
                "🗳️ " + t(p.id, "voting_start"),
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except Exception as e:
            logger.error(f"Error sending vote buttons to {p.id}: {e}")

    await asyncio.sleep(VOTING_DURATION)

    if chat_id in games and games[chat_id].state == "voting":
        await finish_voting(context, chat_id)

async def finish_voting(context, chat_id: int):
    """Ovoz berish natijasini ko'rish"""
    game = games.get(chat_id)
    if not game:
        return

    alive_ids = [p.id for p in game.players.values() if p.alive]
    # BUG FIX #6: t() uchun haqiqiy uid ishlatish (uid=1 emas)
    uid = alive_ids[0] if alive_ids else 0

    if not game.private_votes:
        try:
            await context.bot.send_message(chat_id, "❌ " + t(uid, "no_votes"))
        except Exception as e:
            logger.error(f"Error sending no votes msg: {e}")
        # Ovoz berilmasa keyingi rund
        if chat_id in games:
            await start_game(context, chat_id)
        return

    votes = game.private_votes
    target = max(set(votes.values()), key=list(votes.values()).count)

    if target not in game.players:
        await start_game(context, chat_id)
        return

    kb = [[
        InlineKeyboardButton(f"👍 {t(uid, 'hang')}", callback_data=f"like_{target}"),
        InlineKeyboardButton(f"👎 {t(uid, 'save')}", callback_data=f"dislike_{target}")
    ]]

    try:
        await context.bot.send_message(
            game.chat_id,
            t(uid, "accused").format(game.players[target].name),
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception as e:
        logger.error(f"Error sending accused message: {e}")

    game.state = "final_vote"

async def end_game(context, chat_id: int, winner: str):
    """O'yinni tugatish"""
    game = games.get(chat_id)
    if not game:
        return

    game.state = "end"

    if winner == "mafia":
        winner_ids = [p.id for p in game.players.values() if p.role in ("mafia", "don")]
    else:
        winner_ids = [p.id for p in game.players.values() if p.role not in ("mafia", "don")]

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

    uid = list(game.players.keys())[0]
    try:
        await context.bot.send_message(
            chat_id,
            t(uid, "game_end").format(winner.upper(), len(winner_ids), WIN_REWARD)
        )
    except Exception as e:
        logger.error(f"Error sending game end message: {e}")

    if chat_id in games:
        del games[chat_id]

# ================== CALLBACKS ==================

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

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
        await q.answer(msg, show_alert=True)

    # Til o'zgartirish
    if q.data.startswith("lang_"):
        lang_code = q.data.split("_")[1]
        DB.update_user(uid, lang=lang_code)
        await q.edit_message_text(t(uid, "lang_set"))

    # Admin: adminlar ro'yxati
    elif q.data == "list_admins":
        if not is_user_admin(uid):
            await q.answer(t(uid, "not_admin"), show_alert=True)
            return
        lines = []
        for a in ADMINS:
            tag = " 👑" if a == ADMIN_ID else ""
            lines.append(f"• {a}{tag}")
        text = f"👨‍💼 Adminlar ({len(ADMINS)}):\n\n" + "\n".join(lines)
        text += "\n\n➕ Admin qo'shish: /addadmin <id>\n➖ O'chirish: /removeadmin <id>"
        await q.edit_message_text(text)

    # Admin: o'yinni to'xtatish
    elif q.data == "admin_stop_game":
        if not is_user_admin(uid):
            await q.answer(t(uid, "not_admin"), show_alert=True)
            return
        chat_id = q.message.chat.id
        if chat_id in games:
            games[chat_id].state = "stopped"
            del games[chat_id]
            await q.edit_message_text("🛑 " + t(uid, "game_stopped"))
        else:
            await q.answer(t(uid, "game_not_found"), show_alert=True)

    # O'yinga qo'shilish
    elif q.data == "join":
        game = games.get(q.message.chat.id)
        if not game or game.state != "registration":
            await q.answer("⛔ Ro'yxatga olish yopiq.", show_alert=True)
            return
        if uid in game.players:
            await q.answer(t(uid, "already_joined"), show_alert=True)
            return
        game.players[uid] = Player(uid, q.from_user.first_name)
        logger.info(f"User {uid} joined game in chat {game.chat_id} (total: {len(game.players)})")
        await q.answer(t(uid, "joined"))

        # Guruhda ko'rinadigan: registration xabarini yangilash
        player_count = len(game.players)
        names = "\n".join([f"• {p.name}" for p in game.players.values()])
        new_text = (
            f"📝 Ro'yxatdan o'tish boshlandi\n\n"
            f"👥 O'yinchilar ({player_count}):\n{names}"
        )
        try:
            await q.edit_message_text(
                new_text,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(f"➕ Qo'shilish ({player_count})", callback_data="join")]]
                )
            )
        except Exception:
            pass

    # Shaxsiy ovoz
    elif q.data.startswith("vote_"):
        game = next((g for g in games.values() if uid in g.players and g.state == "voting"), None)
        if not game:
            return
        if uid in game.private_votes:
            await q.answer(t(uid, "vote_used"), show_alert=True)
            return
        target = int(q.data.split("_")[1])
        if target not in game.players:
            return
        game.private_votes[uid] = target
        await q.answer(t(uid, "target_selected"))

    # Mafia o'ldirish
    elif q.data.startswith("mafia_kill_"):
        game = next((g for g in games.values() if g.state == "night" and uid in g.players), None)
        if game and game.players.get(uid) and game.players[uid].role in ("mafia", "don"):
            target = int(q.data.split("_")[2])
            if target in game.players:
                # Avvalgi kill actionni ushbu mafiyadan olib tashlash
                game.night_actions = [a for a in game.night_actions if not (a["type"] == "kill" and a["actor"] == uid)]
                game.night_actions.append({"type": "kill", "actor": uid, "target": target})
                try:
                    await q.edit_message_text(f"✅ {game.players[target].name}")
                except:
                    pass
                await q.answer(t(uid, "target_selected"))

    # Doktor davolash
    elif q.data.startswith("doctor_heal_"):
        game = next((g for g in games.values() if g.state == "night" and uid in g.players), None)
        if game and game.players.get(uid) and game.players[uid].role == "doctor":
            target = int(q.data.split("_")[2])
            if target in game.players:
                game.night_actions = [a for a in game.night_actions if not (a["type"] == "heal" and a["actor"] == uid)]
                game.night_actions.append({"type": "heal", "actor": uid, "target": target})
                try:
                    await q.edit_message_text(f"💚 {game.players[target].name}")
                except:
                    pass
                await q.answer(t(uid, "target_selected"))

    # Killer tekshirish
    elif q.data.startswith("killer_check_"):
        game = next((g for g in games.values() if g.state == "night" and uid in g.players), None)
        if game and game.players.get(uid) and game.players[uid].role == "killer":
            target = int(q.data.split("_")[2])
            if target in game.players:
                # Faqat bir marta tekshirish
                if not any(a["type"] == "investigate" and a["actor"] == uid for a in game.night_actions):
                    game.night_actions.append({"type": "investigate", "actor": uid, "target": target})
                    try:
                        await q.edit_message_text(f"🔍 {game.players[target].name}")
                    except:
                        pass
                    await q.answer(t(uid, "investigated"))
                else:
                    await q.answer("⚠️ Siz allaqachon tekshirdingiz", show_alert=True)

    # Osish ovozi
    elif q.data.startswith("like_"):
        game = next((g for g in games.values() if g.state == "final_vote"), None)
        if not game:
            return
        target = int(q.data.split("_")[1])
        if uid in game.public_votes["like"] or uid in game.public_votes["dislike"]:
            await q.answer("⚠️ Siz allaqachon ovoz bergansiz", show_alert=True)
            return
        game.public_votes["like"].add(uid)
        alive_count = len([p for p in game.players.values() if p.alive])
        if len(game.public_votes["like"]) + len(game.public_votes["dislike"]) >= alive_count:
            if target in game.players:
                game.players[target].alive = False
                uid2 = list(game.players.keys())[0]
                asyncio.create_task(
                    context.bot.send_message(game.chat_id, t(uid2, "hung").format(game.players[target].name))
                )
            asyncio.create_task(start_game(context, game.chat_id))

    # Saqlash ovozi
    elif q.data.startswith("dislike_"):
        game = next((g for g in games.values() if g.state == "final_vote"), None)
        if not game:
            return
        if uid in game.public_votes["like"] or uid in game.public_votes["dislike"]:
            await q.answer("⚠️ Siz allaqachon ovoz bergansiz", show_alert=True)
            return
        game.public_votes["dislike"].add(uid)
        alive_count = len([p for p in game.players.values() if p.alive])
        if len(game.public_votes["like"]) + len(game.public_votes["dislike"]) >= alive_count:
            asyncio.create_task(start_game(context, game.chat_id))

    # BUG FIX #1: "buy_active_role" uchun to'liq key
    elif q.data.startswith("buy_"):
        item = "_".join(q.data.split("_")[1:])  # "active_role" to'g'ri olinadi
        user_data = get_uid_data(uid)
        lang_code = user_data.get("lang", "uz")
        items = ANIME_ITEMS.get(lang_code, ANIME_ITEMS["uz"])

        if item not in items:
            await q.answer("❌ Noma'lum mahsulot", show_alert=True)
            return

        price = items[item]["price"]
        user_money = get_uid_data(uid)["money"]

        if user_money < price:
            await q.answer(t(uid, "not_enough_money"), show_alert=True)
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

        msg = f"✅ {item_data['emoji']} {item_data['name']}\n📺 {item_data['anime']}\n\n{bought_msg}"
        await q.edit_message_text(msg)

# ================== CHAT GUARD ==================

async def chat_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kechasi guruhda yozilgan xabarlarni o'chirish"""
    if not update.message or not update.message.from_user or update.message.from_user.is_bot:
        return
    # /setphoto caption bilan yuborilgan rasmlarni o'chirmaslik
    if update.message.photo:
        caption = (update.message.caption or "").strip().lower()
        if caption in ("/setphoto", "setphoto"):
            return
    chat_id = update.effective_chat.id
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
        await application.bot.set_my_commands([
            ("start",      "🎭 Botni ishga tushirish"),
            ("newgame",    "🎮 Yangi o'yin boshlash"),
            ("join",       "➕ O'yinga qo'shilish"),
            ("profile",    "👤 Profilni ko'rish"),
            ("balance",    "💰 Balansni ko'rish"),
            ("shop",       "🛍 Magazin"),
            ("lang",       "🌍 Tilni o'zgartirish"),
            ("stopgame",   "🛑 O'yinni to'xtatish (admin)"),
            ("resetgame",  "♻️ O'yinni reset (admin)"),
            ("addadmin",   "➕ Admin qo'shish (admin)"),
            ("removeadmin","➖ Adminni o'chirish (admin)"),
            ("listadmins", "👨‍💼 Adminlar ro'yxati (admin)"),
            ("admin",      "⚙️ Admin panel"),
        ])
        logger.info("Bot komandalar menyusi o'rnatildi!")

    app.post_init = post_init

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newgame", newgame))
    app.add_handler(CommandHandler("lang", lang))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("stopgame", stopgame))
    app.add_handler(CommandHandler("resetgame", resetgame))
    app.add_handler(CommandHandler("join", join_command))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("removeadmin", removeadmin))
    app.add_handler(CommandHandler("listadmins", listadmins))
    app.add_handler(CallbackQueryHandler(callbacks))
    # Rasm handler — /setphoto caption bilan (shaxsiy va guruh)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, chat_guard))

    logger.info("Bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()