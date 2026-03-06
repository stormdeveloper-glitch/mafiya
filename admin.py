# admin.py — Premium Admin Tizimi v2.0
# Funksiyalar: statistika, ban/unban, warn, broadcast,
#              balans boshqaruvi, user qidirish/tahrirlash,
#              top reytingi, o'yin boshqaruvi (ko'rish, tezlashtirish, qayta boshlash)

import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

SPEED_NORMAL = 1.0
SPEED_FAST   = 0.3  # 30% — 120s → 36s

# ================== SHARED STATE ==================

_DB             = None
_ADMIN_ID       = None
_ADMINS         = None
_games          = None
_session_remove = None
_t              = None
_safe_reply     = None
_check_cooldown = None
_cooldown_msg   = None
_NIGHT_DURATION = 60
_DAY_DURATION   = 120
_VOTING_DURATION= 60
_REG_TIME       = 120
_PREMIUM_CONFIG = None

_speed_overrides: dict = {}  # {chat_id: float}


def setup(DB, ADMIN_ID, ADMINS, games, session_remove, t,
          safe_reply, check_cooldown, cooldown_msg,
          NIGHT_DURATION=60, DAY_DURATION=120,
          VOTING_DURATION=60, REGISTRATION_TIME=120,
          PREMIUM_CONFIG=None):
    global _DB, _ADMIN_ID, _ADMINS, _games, _session_remove, _t
    global _safe_reply, _check_cooldown, _cooldown_msg
    global _NIGHT_DURATION, _DAY_DURATION, _VOTING_DURATION, _REG_TIME
    global _PREMIUM_CONFIG
    _DB             = DB
    _ADMIN_ID       = ADMIN_ID
    _ADMINS         = ADMINS
    _games          = games
    _session_remove = session_remove
    _t              = t
    _safe_reply     = safe_reply
    _check_cooldown = check_cooldown
    _cooldown_msg   = cooldown_msg
    _NIGHT_DURATION = NIGHT_DURATION
    _DAY_DURATION   = DAY_DURATION
    _VOTING_DURATION= VOTING_DURATION
    _REG_TIME       = REGISTRATION_TIME
    _PREMIUM_CONFIG = PREMIUM_CONFIG


def get_speed(chat_id: int) -> float:
    return _speed_overrides.get(chat_id, SPEED_NORMAL)

def set_speed(chat_id: int, speed: float):
    _speed_overrides[chat_id] = speed

def clear_speed(chat_id: int):
    _speed_overrides.pop(chat_id, None)

# ================== HELPERS ==================

def is_user_admin(uid: int) -> bool:
    return uid in _ADMINS

def _role_label(role: str) -> str:
    return {"don": "👔 DON", "mafia": "🔪 MAFIA",
            "doctor": "💚 DOCTOR", "killer": "🔎 KILLER",
            "citizen": "👤 FUQARO"}.get(role, role.upper() if role else "?")

def _main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistika",        callback_data="adm:stats"),
         InlineKeyboardButton("🏆 Top o'yinchilar",   callback_data="adm:top")],
        [InlineKeyboardButton("🔍 User qidirish",     callback_data="adm:search_prompt"),
         InlineKeyboardButton("💰 Balans",            callback_data="adm:balance_prompt")],
        [InlineKeyboardButton("💎 Premium Boshqaruv", callback_data="adm:premium_menu")],
        [InlineKeyboardButton("🚫 Ban / Unban",        callback_data="adm:ban_menu"),
         InlineKeyboardButton("⚠️ Warn tizimi",       callback_data="adm:warn_menu")],
        [InlineKeyboardButton("📢 Broadcast",         callback_data="adm:broadcast_prompt"),
         InlineKeyboardButton("🎮 O'yin boshqaruvi",  callback_data="adm:game_menu")],
        [InlineKeyboardButton("🤖 AI Boshqaruv",      callback_data="adm:ai_menu"),
         InlineKeyboardButton("🖼 Rasm Sozlamalar",   callback_data="adm:image_menu")],
        [InlineKeyboardButton("👨‍💼 Adminlar ro'yxati", callback_data="list_admins"),
         InlineKeyboardButton("📢 Yangilik yuborish", callback_data="adm:announce_menu")],
        [InlineKeyboardButton("🛑 O'yinni to'xtatish", callback_data="admin_stop_game")],
    ])

def _back_kb(cb="adm:back_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data=cb)]])

def _game_status_text(game, chat_id: int) -> str:
    state_labels = {
        "registration": "📝 Ro'yxat", "night": "🌙 Kecha",
        "day": "☀️ Kunduz", "voting": "🗳️ Ovoz berish",
        "final_vote": "⚖️ Final ovoz", "stopped": "🛑 To'xtatildi", "end": "🏁 Tugadi",
    }
    speed = get_speed(chat_id)
    alive = [p for p in game.players.values() if p.alive]
    dead  = [p for p in game.players.values() if not p.alive]
    lines = [
        f"🎮 <b>O'yin holati: {state_labels.get(game.state, game.state)}</b>",
        f"⚡ Tezlik: {'⏩ Tez (×3)' if speed < 1 else '🔵 Normal'}",
        f"🔢 Round: {game.round}",
        f"",
        f"✅ <b>Tirik ({len(alive)}):</b>",
    ] + [f"  • {p.name}" for p in alive]
    if dead:
        lines += [f"\n💀 <b>O'lgan ({len(dead)}):</b>"] + [f"  • {p.name}" for p in dead]
    return "\n".join(lines)

# ================== ADMIN PANEL ==================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if _check_cooldown(uid):
        await _safe_reply(update, context, _cooldown_msg(uid)); return
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    await _safe_reply(update, context,
        "👨‍💼 <b>Admin Panel</b>\n\nQuyidagi bo'limlardan birini tanlang:",
        parse_mode="HTML", reply_markup=_main_kb())

# ================== STOPGAME / RESETGAME ==================

async def stopgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    if _check_cooldown(uid):
        await _safe_reply(update, context, _cooldown_msg(uid)); return
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if chat_id not in _games:
        await _safe_reply(update, context, _t(uid, "game_not_found")); return
    _games[chat_id].state = "stopped"
    del _games[chat_id]
    _session_remove(chat_id)
    clear_speed(chat_id)
    logger.info(f"Admin {uid} stopped game in chat {chat_id}")
    await update.message.reply_text("🛑 " + _t(uid, "game_stopped"))

async def resetgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    if _check_cooldown(uid):
        await _safe_reply(update, context, _cooldown_msg(uid)); return
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if chat_id in _games:
        _games[chat_id].state = "stopped"
        del _games[chat_id]
        _session_remove(chat_id)
        clear_speed(chat_id)
    await _safe_reply(update, context, "✅ O'yin tiklandi / Сброс / Game reset")

# ================== ADMIN MANAGEMENT ==================

async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if not context.args:
        await _safe_reply(update, context, "❓ /addadmin <user_id>"); return
    try:
        nid = int(context.args[0])
    except ValueError:
        await _safe_reply(update, context, "❌ ID raqam bo'lishi kerak"); return
    if nid in _ADMINS:
        await _safe_reply(update, context, f"⚠️ {nid} allaqachon admin"); return
    _ADMINS.add(nid)
    _DB.add_admin(nid)
    logger.info(f"Admin {uid} added new admin: {nid}")
    await _safe_reply(update, context, f"✅ {nid} admin qilindi!\n👥 Jami: {len(_ADMINS)}")

async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await update.message.reply_text(_t(uid, "not_admin")); return
    if not context.args:
        await update.message.reply_text("❓ /removeadmin <user_id>"); return
    try:
        rid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID raqam bo'lishi kerak"); return
    if rid == _ADMIN_ID:
        await update.message.reply_text("❌ Asosiy adminni o'chirib bo'lmaydi"); return
    if rid not in _ADMINS:
        await update.message.reply_text(f"⚠️ {rid} admin emas"); return
    _ADMINS.discard(rid)
    _DB.remove_admin(rid)
    await update.message.reply_text(f"✅ {rid} adminlikdan olib tashlandi")

async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    lines = [f"• {a}{' 👑' if a == _ADMIN_ID else ''}" for a in _ADMINS]
    await _safe_reply(update, context,
        f"👨‍💼 Adminlar ({len(_ADMINS)}):\n\n" + "\n".join(lines) +
        "\n\n/addadmin <id>  |  /removeadmin <id>")

# ================== BAN / UNBAN ==================

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if not context.args:
        await _safe_reply(update, context, "❓ /ban <user_id> [sabab]"); return
    try:
        target = int(context.args[0])
    except ValueError:
        await _safe_reply(update, context, "❌ ID raqam bo'lishi kerak"); return
    if target == _ADMIN_ID:
        await _safe_reply(update, context, "❌ Asosiy adminni ban qilib bo'lmaydi"); return
    reason = " ".join(context.args[1:]) or "Sabab ko'rsatilmagan"
    _DB.ban_user(target, reason, uid)
    logger.info(f"Admin {uid} banned {target}: {reason}")
    await _safe_reply(update, context,
        f"🚫 <b>Ban qilindi!</b>\n👤 ID: <code>{target}</code>\n📋 Sabab: {reason}",
        parse_mode="HTML")
    try:
        await context.bot.send_message(target,
            f"🚫 Siz botdan ban qilindingiz!\n📋 Sabab: {reason}")
    except:
        pass

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if not context.args:
        await _safe_reply(update, context, "❓ /unban <user_id>"); return
    try:
        target = int(context.args[0])
    except ValueError:
        await _safe_reply(update, context, "❌ ID raqam bo'lishi kerak"); return
    if not _DB.is_banned(target):
        await _safe_reply(update, context, f"⚠️ {target} banlangan emas"); return
    _DB.unban_user(target)
    await _safe_reply(update, context,
        f"✅ <b>Ban olib tashlandi!</b>\n👤 ID: <code>{target}</code>", parse_mode="HTML")
    try:
        await context.bot.send_message(target, "✅ Sizning ban'ingiz olib tashlandi!")
    except:
        pass

# ================== WARN ==================

async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if not context.args:
        await _safe_reply(update, context, "❓ /warn <user_id> [sabab]"); return
    try:
        target = int(context.args[0])
    except ValueError:
        await _safe_reply(update, context, "❌ ID raqam bo'lishi kerak"); return
    reason = " ".join(context.args[1:]) or "Sabab ko'rsatilmagan"
    count = _DB.warn_user(target, reason, uid)
    await _safe_reply(update, context,
        f"⚠️ <b>Ogohlantirish berildi!</b>\n"
        f"👤 ID: <code>{target}</code>\n"
        f"📋 Sabab: {reason}\n"
        f"⚠️ Jami warn: {count}/3",
        parse_mode="HTML")
    try:
        await context.bot.send_message(target,
            f"⚠️ Siz ogohlantirilgansiz!\n📋 Sabab: {reason}\n"
            f"⚠️ Jami warn: {count}/3"
            + ("\n🚫 Keyingi warn — avtomatik ban!" if count == 2 else ""))
    except:
        pass
    if count >= 3:
        _DB.ban_user(target, f"3 ta warn (oxirgisi: {reason})", uid)
        _DB.clear_warns(target)
        await _safe_reply(update, context,
            f"🚫 {target} avtomatik ban qilindi (3 warn)!")
        try:
            await context.bot.send_message(target,
                "🚫 3 ta warn to'plandi — ban qilindingiz!")
        except:
            pass

async def unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if not context.args:
        await _safe_reply(update, context, "❓ /unwarn <user_id>"); return
    try:
        target = int(context.args[0])
    except ValueError:
        await _safe_reply(update, context, "❌ ID raqam bo'lishi kerak"); return
    warns = _DB.get_warns(target)
    if not warns:
        await _safe_reply(update, context, f"⚠️ {target} da warn yo'q"); return
    _DB.clear_warns(target)
    await _safe_reply(update, context,
        f"✅ {target} ning {len(warns)} ta warni tozalandi!")

# ================== BALANCE ==================

async def setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if len(context.args or []) < 2:
        await _safe_reply(update, context, "❓ /setbalance <user_id> <miqdor>"); return
    try:
        target, amount = int(context.args[0]), int(context.args[1])
    except ValueError:
        await _safe_reply(update, context, "❌ Raqam bo'lishi kerak"); return
    _DB.update_user(target, money=amount)
    await _safe_reply(update, context,
        f"💰 <code>{target}</code> balansi → <b>{amount} coin</b>", parse_mode="HTML")

async def addmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if len(context.args or []) < 2:
        await _safe_reply(update, context, "❓ /addmoney <user_id> <miqdor>"); return
    try:
        target, amount = int(context.args[0]), int(context.args[1])
    except ValueError:
        await _safe_reply(update, context, "❌ Raqam bo'lishi kerak"); return
    d = _DB.get_user(target)
    if not d:
        await _safe_reply(update, context, "❌ Foydalanuvchi topilmadi"); return
    new_bal = d.get("money", 0) + amount
    _DB.update_user(target, money=new_bal)
    await _safe_reply(update, context,
        f"💸 <code>{target}</code> ga <b>+{amount} coin</b>\n"
        f"💰 Yangi balans: <b>{new_bal}</b>", parse_mode="HTML")

async def removemoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if len(context.args or []) < 2:
        await _safe_reply(update, context, "❓ /removemoney <user_id> <miqdor>"); return
    try:
        target, amount = int(context.args[0]), int(context.args[1])
    except ValueError:
        await _safe_reply(update, context, "❌ Raqam bo'lishi kerak"); return
    d = _DB.get_user(target)
    if not d:
        await _safe_reply(update, context, "❌ Foydalanuvchi topilmadi"); return
    new_bal = max(0, d.get("money", 0) - amount)
    _DB.update_user(target, money=new_bal)
    await _safe_reply(update, context,
        f"💸 <code>{target}</code> dan <b>-{amount} coin</b>\n"
        f"💰 Yangi balans: <b>{new_bal}</b>", parse_mode="HTML")

# ================== BROADCAST ==================

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if not context.args:
        await _safe_reply(update, context, "❓ /broadcast <xabar matni>"); return
    text = "📢 " + " ".join(context.args)
    uids = _DB.get_all_uids()
    sent = failed = 0
    status_msg = await update.message.reply_text(f"⏳ Yuborilmoqda... 0/{len(uids)}")
    for i, tid in enumerate(uids):
        try:
            await context.bot.send_message(tid, text)
            sent += 1
        except:
            failed += 1
        if (i + 1) % 20 == 0:
            try:
                await status_msg.edit_text(f"⏳ {i+1}/{len(uids)} yuborildi...")
            except:
                pass
        await asyncio.sleep(0.05)
    await status_msg.edit_text(
        f"📢 <b>Broadcast tugadi!</b>\n✅ Yuborildi: {sent}\n❌ Xato: {failed}",
        parse_mode="HTML")

# ================== USER INFO / SEARCH ==================

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if not context.args:
        await _safe_reply(update, context, "❓ /userinfo <user_id yoki @username>"); return
    query = context.args[0].lstrip("@")
    results = []
    try:
        d = _DB.get_user(int(query))
        if d:
            results = [d]
    except ValueError:
        results = _DB.search_user(query)
    if not results:
        await _safe_reply(update, context, "❌ Foydalanuvchi topilmadi"); return
    d = results[0]
    ban_info = _DB.is_banned(d["uid"])
    warns    = _DB.get_warns(d["uid"])
    gp = d.get("games_played", 0)
    gw = d.get("games_won", 0)
    wr = round(gw / gp * 100) if gp else 0
    text = (
        f"👤 <b>{d.get('name','?')}</b>  (@{d.get('username','—')})\n"
        f"🆔 <code>{d['uid']}</code>\n"
        f"💰 Balans: <b>{d.get('money',0)} coin</b>\n"
        f"🎮 O'yinlar: {gp}  🏆 G'alaba: {gw} ({wr}%)\n"
        f"⚠️ Warnlar: {len(warns)}/3\n"
        f"{'🚫 BAN: ' + ban_info['reason'] if ban_info else '✅ Faol'}\n"
        + (f"\n📅 Oxirgi o'yin: {d.get('last_played','—')[:10]}" if d.get("last_played") else "")
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚫 Ban",   callback_data=f"adm:ban_q_{d['uid']}"),
        InlineKeyboardButton("⚠️ Warn",  callback_data=f"adm:warn_q_{d['uid']}"),
        InlineKeyboardButton("💰 Balans",callback_data=f"adm:bal_q_{d['uid']}"),
    ]])
    await _safe_reply(update, context, text, parse_mode="HTML",
        reply_markup=kb if len(results) == 1 else None)

# ================== TOP PLAYERS ==================

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_list = _DB.get_top_players(10)
    if not top_list:
        await _safe_reply(update, context, "📊 Hali ma'lumot yo'q"); return
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    lines = []
    for i, d in enumerate(top_list):
        wr = round(d["games_won"]/d["games_played"]*100) if d.get("games_played") else 0
        lines.append(
            f"{medals[i]} <b>{d.get('name','?')}</b> — "
            f"🏆 {d.get('games_won',0)} g'alaba ({wr}%) | 💰 {d.get('money',0)} coin"
        )
    await _safe_reply(update, context,
        "🏆 <b>Top 10 O'yinchilar</b>\n\n" + "\n".join(lines), parse_mode="HTML")

# ================== GAME COMMANDS ==================

async def gamestatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    game = _games.get(chat_id)
    if not game:
        await _safe_reply(update, context, "❌ Bu guruhda faol o'yin yo'q"); return
    await _safe_reply(update, context, _game_status_text(game, chat_id), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎭 Rollar",        callback_data=f"adm:roles_{chat_id}"),
             InlineKeyboardButton("⏩ Tezlashtirish", callback_data=f"adm:speed_{chat_id}")],
            [InlineKeyboardButton("🔄 Qayta boshlash",callback_data=f"adm:restart_{chat_id}"),
             InlineKeyboardButton("🛑 To'xtatish",    callback_data=f"adm:stop_{chat_id}")],
        ]))

async def speedgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    if chat_id not in _games:
        await _safe_reply(update, context, "❌ Faol o'yin yo'q"); return
    if get_speed(chat_id) < 1:
        set_speed(chat_id, SPEED_NORMAL)
        await _safe_reply(update, context, "🔵 Tezlik normal rejimga qaytarildi")
    else:
        set_speed(chat_id, SPEED_FAST)
        await _safe_reply(update, context,
            f"⏩ O'yin tezlashtirildi!\n"
            f"🌙 Kecha: {int(_NIGHT_DURATION*SPEED_FAST)}s | "
            f"☀️ Kunduz: {int(_DAY_DURATION*SPEED_FAST)}s | "
            f"🗳️ Ovoz: {int(_VOTING_DURATION*SPEED_FAST)}s")

async def showroles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    game = _games.get(chat_id)
    if not game or not game.players:
        await _safe_reply(update, context, "❌ O'yin yoki o'yinchilar topilmadi"); return
    lines = ["🎭 <b>Barcha rollar (admin):</b>\n"]
    for p in game.players.values():
        icon = "✅" if p.alive else "💀"
        role = _role_label(p.role) if p.role else "—"
        lines.append(f"{icon} <b>{p.name}</b> — {role}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def restartgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    game = _games.get(chat_id)
    if not game:
        await _safe_reply(update, context, "❌ Faol o'yin yo'q"); return
    for p in game.players.values():
        p.alive = True; p.role = None; p.abilities = []
    game.state = "registration"; game.round = 0
    game.night_actions = []; game.private_votes = {}
    game.public_votes = {"like": set(), "dislike": set()}
    await _safe_reply(update, context,
        f"🔄 O'yin qayta boshlandi!\n"
        f"👥 {len(game.players)} ta o'yinchi saqlanib qoldi.\n"
        f"⏱ {_REG_TIME}s dan keyin o'yin boshlanadi.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_admin(uid):
        await _safe_reply(update, context, _t(uid, "not_admin")); return
    await _safe_reply(update, context,
        f"📊 <b>Bot Statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{_DB.get_total_users()}</b>\n"
        f"🎮 Faol o'yinlar: <b>{len(_games)}</b>\n"
        f"🚫 Banlangan: <b>{len(_DB.get_all_bans())}</b>\n"
        f"👨‍💼 Adminlar: <b>{len(_ADMINS)}</b>",
        parse_mode="HTML")

# ================== CALLBACKS ==================

async def handle_admin_callback(q, uid, safe_answer, safe_edit):
    """
    True — bu modulga tegishli
    False — boshqa modul ko'rib chiqsin
    """
    data = q.data

    # ── Eski sodda callbacklar ──
    if data == "list_admins":
        if not is_user_admin(uid):
            await safe_answer(_t(uid, "not_admin"), alert=True); return True
        lines = [f"• {a}{' 👑' if a == _ADMIN_ID else ''}" for a in _ADMINS]
        await safe_answer()
        await safe_edit(
            f"👨‍💼 Adminlar ({len(_ADMINS)}):\n\n" + "\n".join(lines) +
            "\n\n/addadmin <id>  |  /removeadmin <id>"); return True

    if data == "admin_stop_game":
        if not is_user_admin(uid):
            await safe_answer(_t(uid, "not_admin"), alert=True); return True
        chat_id = q.message.chat.id
        if chat_id in _games:
            _games[chat_id].state = "stopped"
            del _games[chat_id]
            _session_remove(chat_id)
            clear_speed(chat_id)
            await safe_answer(); await safe_edit("🛑 " + _t(uid, "game_stopped"))
        else:
            await safe_answer(_t(uid, "game_not_found"), alert=True)
        return True

    # ── Premium callbacklar ──
    if not data.startswith("adm:"):
        return False
    if not is_user_admin(uid):
        await safe_answer("❌ Admin emas", alert=True); return True

    cmd = data[4:]

    if cmd == "back_main":
        await safe_answer()
        await safe_edit("👨‍💼 <b>Admin Panel</b>\n\nQuyidagi bo'limlardan birini tanlang:",
            parse_mode="HTML", reply_markup=_main_kb()); return True

    if cmd == "stats":
        await safe_answer()
        await safe_edit(
            f"📊 <b>Bot Statistikasi</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{_DB.get_total_users()}</b>\n"
            f"🎮 Faol o'yinlar: <b>{len(_games)}</b>\n"
            f"🚫 Banlangan: <b>{len(_DB.get_all_bans())}</b>\n"
            f"👨‍💼 Adminlar: <b>{len(_ADMINS)}</b>",
            parse_mode="HTML", reply_markup=_back_kb()); return True

    if cmd == "top":
        top_list = _DB.get_top_players(10)
        medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        lines = []
        for i, d in enumerate(top_list):
            wr = round(d["games_won"]/d["games_played"]*100) if d.get("games_played") else 0
            lines.append(f"{medals[i]} <b>{d.get('name','?')}</b> — {d.get('games_won',0)} g'alaba ({wr}%) | 💰 {d.get('money',0)}")
        await safe_answer()
        await safe_edit(
            "🏆 <b>Top 10 O'yinchilar</b>\n\n" + ("\n".join(lines) or "Hali ma'lumot yo'q"),
            parse_mode="HTML", reply_markup=_back_kb()); return True

    if cmd == "ban_menu":
        bans = _DB.get_all_bans()
        text = f"🚫 <b>Ban tizimi</b>\n\nBanlangan: <b>{len(bans)}</b> ta\n\n"
        for b in bans[:5]:
            text += f"• <code>{b['uid']}</code> — {b.get('reason','?')}\n"
        if len(bans) > 5:
            text += f"... va yana {len(bans)-5} ta\n"
        text += "\n/ban &lt;uid&gt; [sabab]   |   /unban &lt;uid&gt;"
        await safe_answer()
        await safe_edit(text, parse_mode="HTML", reply_markup=_back_kb()); return True

    if cmd.startswith("ban_q_"):
        target = int(cmd.split("_", 2)[2])
        _DB.ban_user(target, "Admin panel orqali", uid)
        await safe_answer(f"🚫 {target} ban qilindi!", alert=True)
        try:
            await q.bot.send_message(target, "🚫 Siz botdan ban qilindingiz!")
        except:
            pass
        return True

    if cmd == "warn_menu":
        await safe_answer()
        await safe_edit(
            "⚠️ <b>Warn tizimi</b>\n\n3 warn = avtomatik ban\n\n"
            "/warn &lt;uid&gt; [sabab]\n/unwarn &lt;uid&gt;",
            parse_mode="HTML", reply_markup=_back_kb()); return True

    if cmd.startswith("warn_q_"):
        target = int(cmd.split("_", 2)[2])
        count = _DB.warn_user(target, "Admin panel orqali", uid)
        await safe_answer(f"⚠️ Warn berildi! Jami: {count}/3", alert=True)
        if count >= 3:
            _DB.ban_user(target, "3 warn — admin panel", uid)
            _DB.clear_warns(target)
        return True

    if cmd == "balance_prompt":
        await safe_answer()
        await safe_edit(
            "💰 <b>Balans boshqaruvi</b>\n\n"
            "/setbalance &lt;uid&gt; &lt;miqdor&gt;\n"
            "/addmoney &lt;uid&gt; &lt;miqdor&gt;\n"
            "/removemoney &lt;uid&gt; &lt;miqdor&gt;",
            parse_mode="HTML", reply_markup=_back_kb()); return True

    if cmd.startswith("bal_q_"):
        target = int(cmd.split("_", 2)[2])
        d = _DB.get_user(target)
        await safe_answer(f"💰 Balans: {d.get('money',0) if d else '?'} coin", alert=True)
        return True

    if cmd == "broadcast_prompt":
        await safe_answer()
        await safe_edit(
            "📢 <b>Broadcast</b>\n\n/broadcast &lt;xabar&gt;",
            parse_mode="HTML", reply_markup=_back_kb()); return True

    if cmd == "search_prompt":
        await safe_answer()
        await safe_edit(
            "🔍 <b>User qidirish</b>\n\n/userinfo &lt;uid yoki @username&gt;",
            parse_mode="HTML", reply_markup=_back_kb()); return True

    if cmd == "game_menu":
        chat_id = q.message.chat.id
        game = _games.get(chat_id)
        if not game:
            await safe_answer()
            await safe_edit(
                "🎮 <b>O'yin boshqaruvi</b>\n\n❌ Faol o'yin yo'q.\n\n"
                "/gamestatus | /speedgame | /showroles | /restartgame",
                parse_mode="HTML", reply_markup=_back_kb()); return True
        await safe_answer()
        await safe_edit(_game_status_text(game, chat_id), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎭 Rollar",        callback_data=f"adm:roles_{chat_id}"),
                 InlineKeyboardButton("⏩ Tezlashtirish", callback_data=f"adm:speed_{chat_id}")],
                [InlineKeyboardButton("🔄 Qayta boshlash",callback_data=f"adm:restart_{chat_id}"),
                 InlineKeyboardButton("🛑 To'xtatish",    callback_data=f"adm:stop_{chat_id}")],
                [InlineKeyboardButton("🔙 Orqaga",         callback_data="adm:back_main")],
            ])); return True

    if cmd.startswith("roles_"):
        chat_id = int(cmd.split("_", 1)[1])
        game = _games.get(chat_id)
        if not game:
            await safe_answer("❌ O'yin topilmadi", alert=True); return True
        lines = ["🎭 <b>Barcha rollar:</b>\n"]
        for p in game.players.values():
            icon = "✅" if p.alive else "💀"
            lines.append(f"{icon} {p.name} — {_role_label(p.role) if p.role else '—'}")
        await safe_answer()
        await safe_edit("\n".join(lines), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 O'yin menyu", callback_data="adm:game_menu")
            ]])); return True

    if cmd.startswith("speed_"):
        chat_id = int(cmd.split("_", 1)[1])
        if chat_id not in _games:
            await safe_answer("❌ O'yin topilmadi", alert=True); return True
        if get_speed(chat_id) < 1:
            set_speed(chat_id, SPEED_NORMAL)
            await safe_answer("🔵 Normal tezlik tiklandi", alert=True)
        else:
            set_speed(chat_id, SPEED_FAST)
            await safe_answer("⏩ O'yin tezlashtirildi!", alert=True)
        return True

    if cmd.startswith("restart_"):
        chat_id = int(cmd.split("_", 1)[1])
        game = _games.get(chat_id)
        if not game:
            await safe_answer("❌ O'yin topilmadi", alert=True); return True
        for p in game.players.values():
            p.alive = True; p.role = None; p.abilities = []
        game.state = "registration"; game.round = 0
        game.night_actions = []; game.private_votes = {}
        game.public_votes = {"like": set(), "dislike": set()}
        await safe_answer(f"🔄 Qayta boshlandi! ({len(game.players)} o'yinchi)", alert=True)
        return True

    if cmd.startswith("stop_"):
        chat_id = int(cmd.split("_", 1)[1])
        if chat_id in _games:
            _games[chat_id].state = "stopped"
            del _games[chat_id]
            _session_remove(chat_id)
            clear_speed(chat_id)
        await safe_answer("🛑 O'yin to'xtatildi!", alert=True); return True

    # ── AI boshqaruv menyusi ──
    if cmd == "ai_menu":
        from main import AI_SETTINGS
        ai_on = AI_SETTINGS.get("ai_enabled", True)
        img_on = AI_SETTINGS.get("image_enabled", True)
        limit = AI_SETTINGS.get("image_daily_limit", 5)
        ochiq = "O\'chiq"
        ochirish = "O\'chirish"
        status = (
            f"🤖 <b>AI Boshqaruv Paneli</b>\n\n"
            f"💬 Gemini Chat: {'✅ Yoqiq' if ai_on else '❌ ' + ochiq}\n"
            f"🖼 Nano Banana: {'✅ Yoqiq' if img_on else '❌ ' + ochiq}\n"
            f"📊 Kunlik rasm limiti: <b>{limit}</b> ta\n\n"
            f"Quyidagi tugmalar orqali boshqaring:"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                ("💬 Gemini: ✅ Yoqiq → " + ochirish) if ai_on else ("💬 Gemini: ❌ " + ochiq + " → Yoqish"),
                callback_data="adm:ai_toggle"
            )],
            [InlineKeyboardButton(
                ("🖼 Nano Banana: ✅ Yoqiq → " + ochirish) if img_on else ("🖼 Nano Banana: ❌ " + ochiq + " → Yoqish"),
                callback_data="adm:img_toggle"
            )],
            [InlineKeyboardButton("📊 Rasm limiti sozla", callback_data="adm:image_menu")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:back_main")],
        ])
        await safe_answer()
        await safe_edit(status, parse_mode="HTML", reply_markup=kb)
        return True

    if cmd == "ai_toggle":
        from main import AI_SETTINGS
        AI_SETTINGS["ai_enabled"] = not AI_SETTINGS.get("ai_enabled", True)
        state = "✅ Yoqildi" if AI_SETTINGS["ai_enabled"] else "❌ O'chirildi"
        await safe_answer(f"💬 Gemini Chat: {state}", alert=True)
        # Menyuni yangilash
        ai_on = AI_SETTINGS.get("ai_enabled", True)
        img_on = AI_SETTINGS.get("image_enabled", True)
        limit = AI_SETTINGS.get("image_daily_limit", 5)
        status = (
            f"🤖 <b>AI Boshqaruv Paneli</b>\n\n"
            f"💬 Gemini Chat: {'✅ Yoqiq' if ai_on else '❌ O\'chiq'}\n"
            f"🖼 Nano Banana: {'✅ Yoqiq' if img_on else '❌ O\'chiq'}\n"
            f"📊 Kunlik rasm limiti: <b>{limit}</b> ta"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"💬 Gemini: {'✅ Yoqiq → O\'chirish' if ai_on else '❌ O\'chiq → Yoqish'}",
                callback_data="adm:ai_toggle"
            )],
            [InlineKeyboardButton(
                f"🖼 Nano Banana: {'✅ Yoqiq → O\'chirish' if img_on else '❌ O\'chiq → Yoqish'}",
                callback_data="adm:img_toggle"
            )],
            [InlineKeyboardButton("📊 Rasm limiti sozla", callback_data="adm:image_menu")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:back_main")],
        ])
        await safe_edit(status, parse_mode="HTML", reply_markup=kb)
        return True

    if cmd == "announce_menu":
        await safe_answer()
        await safe_edit(
            "📢 <b>Yangiliklar Markazi (v2.2)</b>\n\n"
            "Kanalga avtomatik yangiliklar postini yuborish uchun "
            "avval uni ko'zdan kechirib (preview) oling.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👁️ Postni ko'rish (Preview)", callback_data="adm:preview_req")],
                [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:back_main")]
            ]))
        return True

    if cmd == "preview_req":
        await q.message.delete()
        from main import preview_update
        await preview_update(q, context)
        return True

    if cmd == "send_update":
        from main import announce_update
        await safe_answer("🚀 Yuborilmoqda...", alert=True)
        asyncio.create_task(announce_update(context))
        await safe_edit("✅ Yangiliklar kanalda e'lon qilindi!", reply_markup=_back_kb())
        return True

    if cmd == "img_toggle":
        from main import AI_SETTINGS
        AI_SETTINGS["image_enabled"] = not AI_SETTINGS.get("image_enabled", True)
        state = "✅ Yoqildi" if AI_SETTINGS["image_enabled"] else "❌ O'chirildi"
        await safe_answer(f"🖼 Nano Banana: {state}", alert=True)
        ai_on = AI_SETTINGS.get("ai_enabled", True)
        img_on = AI_SETTINGS.get("image_enabled", True)
        limit = AI_SETTINGS.get("image_daily_limit", 5)
        status = (
            f"🤖 <b>AI Boshqaruv Paneli</b>\n\n"
            f"💬 Gemini Chat: {'✅ Yoqiq' if ai_on else '❌ O\'chiq'}\n"
            f"🖼 Nano Banana: {'✅ Yoqiq' if img_on else '❌ O\'chiq'}\n"
            f"📊 Kunlik rasm limiti: <b>{limit}</b> ta"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"💬 Gemini: {'✅ Yoqiq → O\'chirish' if ai_on else '❌ O\'chiq → Yoqish'}",
                callback_data="adm:ai_toggle"
            )],
            [InlineKeyboardButton(
                f"🖼 Nano Banana: {'✅ Yoqiq → O\'chirish' if img_on else '❌ O\'chiq → Yoqish'}",
                callback_data="adm:img_toggle"
            )],
            [InlineKeyboardButton("📊 Rasm limiti sozla", callback_data="adm:image_menu")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:back_main")],
        ])
        await safe_edit(status, parse_mode="HTML", reply_markup=kb)
        return True

    # ── Rasm limiti menyusi ──
    if cmd == "image_menu":
        from main import AI_SETTINGS
        limit = AI_SETTINGS.get("image_daily_limit", 5)
        img_on = AI_SETTINGS.get("image_enabled", True)
        text = (
            f"🖼 <b>Rasm Sozlamalari</b>\n\n"
            f"Holat: {'✅ Yoqiq' if img_on else '❌ O\'chiq'}\n"
            f"📊 Hozirgi kunlik limit: <b>{limit}</b> ta/foydalanuvchi\n\n"
            f"Limitni o'zgartirish:"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1️⃣  1 ta",  callback_data="adm:setlimit_1"),
             InlineKeyboardButton("3️⃣  3 ta",  callback_data="adm:setlimit_3"),
             InlineKeyboardButton("5️⃣  5 ta",  callback_data="adm:setlimit_5")],
            [InlineKeyboardButton("🔟  10 ta", callback_data="adm:setlimit_10"),
             InlineKeyboardButton("🔄  20 ta", callback_data="adm:setlimit_20"),
             InlineKeyboardButton("♾️  Cheksiz", callback_data="adm:setlimit_999")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:ai_menu")],
        ])
        await safe_answer()
        await safe_edit(text, parse_mode="HTML", reply_markup=kb)
        return True

    if cmd.startswith("setlimit_"):
        from main import AI_SETTINGS
        new_limit = int(cmd.split("_", 1)[1])
        AI_SETTINGS["image_daily_limit"] = new_limit
        label = "♾️ Cheksiz" if new_limit >= 999 else f"{new_limit} ta"
        await safe_answer(f"✅ Kunlik limit: {label}", alert=True)
        # Menyuni yangilash
        text = (
            f"🖼 <b>Rasm Sozlamalari</b>\n\n"
            f"📊 Yangi kunlik limit: <b>{label}</b>\n\n"
            f"Limitni o'zgartirish:"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1️⃣  1 ta",  callback_data="adm:setlimit_1"),
             InlineKeyboardButton("3️⃣  3 ta",  callback_data="adm:setlimit_3"),
             InlineKeyboardButton("5️⃣  5 ta",  callback_data="adm:setlimit_5")],
            [InlineKeyboardButton("🔟  10 ta", callback_data="adm:setlimit_10"),
             InlineKeyboardButton("🔄  20 ta", callback_data="adm:setlimit_20"),
             InlineKeyboardButton("♾️  Cheksiz", callback_data="adm:setlimit_999")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:ai_menu")],
        ])
        await safe_edit(text, parse_mode="HTML", reply_markup=kb)
        return True

    # ── Premium Menu ──
    if cmd == "premium_menu":
        text = (
            "💎 <b>Premium Boshqaruv</b>\n\n"
            "Bu yerda siz do'kon buyumlari va premium rollarni boshqarishingiz mumkin."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛍 Do'kon Buyumlari", callback_data="adm:prem_items")],
            [InlineKeyboardButton("🎭 Premium Rollar", callback_data="adm:prem_roles")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:back_main")],
        ])
        await safe_answer()
        await safe_edit(text, parse_mode="HTML", reply_markup=kb)
        return True

    if cmd == "prem_items":
        items = _PREMIUM_CONFIG.get("items", {})
        text = "🛍 <b>Do'kon Buyumlari</b>\n\nTanlang:"
        kb = []
        for k, v in items.items():
            status = "✅" if v.get("enabled", True) else "❌"
            price = v.get("price", 0)
            kb.append([InlineKeyboardButton(f"{status} {k} ({price} coin)", callback_data=f"adm:pitem_{k}")])
        kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="adm:premium_menu")])
        await safe_answer()
        await safe_edit(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return True

    if cmd.startswith("pitem_"):
        item_key = cmd.split("_", 1)[1]
        conf = _PREMIUM_CONFIG.get("items", {}).get(item_key)
        if not conf:
            await safe_answer("Xato", alert=True); return True
        
        status = "✅ Sotuvda" if conf.get("enabled", True) else "❌ Yopilgan"
        price = conf.get("price", 0)
        
        text = (
            f"📦 <b>{item_key}</b>\n\n"
            f"Holat: <b>{status}</b>\n"
            f"Narx: <b>{price} coin</b>\n\n"
            f"Boshqaruv:"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Holatni o'zgartirish", callback_data=f"adm:pitoggle_{item_key}")],
            [InlineKeyboardButton("➖ 10", callback_data=f"adm:piprice_{item_key}_-10"),
             InlineKeyboardButton("➕ 10", callback_data=f"adm:piprice_{item_key}_10")],
            [InlineKeyboardButton("➖ 50", callback_data=f"adm:piprice_{item_key}_-50"),
             InlineKeyboardButton("➕ 50", callback_data=f"adm:piprice_{item_key}_50")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:prem_items")]
        ])
        await safe_answer()
        await safe_edit(text, parse_mode="HTML", reply_markup=kb)
        return True

    if cmd.startswith("pitoggle_"):
        item_key = cmd.split("_", 1)[1]
        conf = _PREMIUM_CONFIG.get("items", {}).get(item_key)
        if conf:
            conf["enabled"] = not conf.get("enabled", True)
            # Refresh menu
            status = "✅ Sotuvda" if conf.get("enabled", True) else "❌ Yopilgan"
            price = conf.get("price", 0)
            text = (
                f"📦 <b>{item_key}</b>\n\n"
                f"Holat: <b>{status}</b>\n"
                f"Narx: <b>{price} coin</b>\n\n"
                f"Boshqaruv:"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Holatni o'zgartirish", callback_data=f"adm:pitoggle_{item_key}")],
                [InlineKeyboardButton("➖ 10", callback_data=f"adm:piprice_{item_key}_-10"),
                 InlineKeyboardButton("➕ 10", callback_data=f"adm:piprice_{item_key}_10")],
                [InlineKeyboardButton("➖ 50", callback_data=f"adm:piprice_{item_key}_-50"),
                 InlineKeyboardButton("➕ 50", callback_data=f"adm:piprice_{item_key}_50")],
                [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:prem_items")]
            ])
            await safe_edit(text, parse_mode="HTML", reply_markup=kb)
        return True

    if cmd.startswith("piprice_"):
        parts = cmd.split("_")
        # adm:piprice_{key}_{amount}
        # parts: ['piprice', 'key', 'amount']
        # if key contains underscores, we need to be careful. Let's assume keys don't have underscores or handle it.
        # Actually keys like "active_role" have underscores.
        amount = int(parts[-1])
        item_key = "_".join(parts[1:-1])
        
        conf = _PREMIUM_CONFIG.get("items", {}).get(item_key)
        if conf:
            new_price = max(0, conf.get("price", 0) + amount)
            conf["price"] = new_price
            
            status = "✅ Sotuvda" if conf.get("enabled", True) else "❌ Yopilgan"
            text = (
                f"📦 <b>{item_key}</b>\n\n"
                f"Holat: <b>{status}</b>\n"
                f"Narx: <b>{new_price} coin</b>\n\n"
                f"Boshqaruv:"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Holatni o'zgartirish", callback_data=f"adm:pitoggle_{item_key}")],
                [InlineKeyboardButton("➖ 10", callback_data=f"adm:piprice_{item_key}_-10"),
                 InlineKeyboardButton("➕ 10", callback_data=f"adm:piprice_{item_key}_10")],
                [InlineKeyboardButton("➖ 50", callback_data=f"adm:piprice_{item_key}_-50"),
                 InlineKeyboardButton("➕ 50", callback_data=f"adm:piprice_{item_key}_50")],
                [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:prem_items")]
            ])
            await safe_answer(f"Narx o'zgardi: {new_price}")
            await safe_edit(text, parse_mode="HTML", reply_markup=kb)
        return True

    if cmd == "prem_roles":
        roles = _PREMIUM_CONFIG.get("roles", {})
        text = "🎭 <b>Premium Rollar</b>\n\nQaysi rollarni o'yinda ishlatmoqchisiz?"
        kb = []
        for k, v in roles.items():
            status = "✅ Yoqiq" if v.get("enabled", True) else "❌ O'chiq"
            kb.append([InlineKeyboardButton(f"{status} {k.title()}", callback_data=f"adm:protoggle_{k}")])
        kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="adm:premium_menu")])
        await safe_answer()
        await safe_edit(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return True

    if cmd.startswith("protoggle_"):
        role_key = cmd.split("_", 1)[1]
        conf = _PREMIUM_CONFIG.get("roles", {}).get(role_key)
        if conf:
            conf["enabled"] = not conf.get("enabled", True)
            # Refresh menu
            roles = _PREMIUM_CONFIG.get("roles", {})
            text = "🎭 <b>Premium Rollar</b>\n\nQaysi rollarni o'yinda ishlatmoqchisiz?"
            kb = []
            for k, v in roles.items():
                status = "✅ Yoqiq" if v.get("enabled", True) else "❌ O'chiq"
                kb.append([InlineKeyboardButton(f"{status} {k.title()}", callback_data=f"adm:protoggle_{k}")])
            kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="adm:premium_menu")])
            await safe_answer(f"{role_key} holati o'zgardi")
            await safe_edit(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return True

    return False
