# 🎭 Mafia Telegram Bot

Telegram uchun yozilgan **Anime uslubidagi Mafia o'yin boti**.  
Guruh chatlarda to'liq avtomatik o'yin boshqaradi: rollar taqsimoti, kecha-kunduz fazalari, ovoz berish, g'olibni aniqlash va premium admin tizimi.

---

## ✨ Imkoniyatlar

### 🎮 O'yin
- Avtomatik rol taqsimlash: **Don, Mafia, Doctor, Killer, Fuqaro**
- Anime personajlar va qobiliyatlar tizimi
- Kecha / kunduz / ovoz berish fazalari
- Final ovoz (osish / saqlash) tizimi
- Shield, immortality, documents buyumlar
- Ko'p tilli interfeys: 🇺🇿 O'zbek, 🇷🇺 Rus, 🇬🇧 Ingliz
- Sessiyalarni JSON ga saqlash (restart bo'lganda o'yinchilar yo'qolmaydi)

### 👨‍💼 Premium Admin tizimi (`admin.py`)
- 📊 Bot statistikasi (foydalanuvchilar, o'yinlar, banlar)
- 🏆 Top 10 o'yinchilar reytingi
- 🔍 User qidirish (ID yoki username bo'yicha)
- 💰 Balans boshqaruvi (o'rnatish, qo'shish, olib tashlash)
- 🚫 Ban / Unban tizimi (sabab bilan, userni xabardor qilish)
- ⚠️ Warn tizimi (3 warn = avtomatik ban)
- 📢 Broadcast (barcha foydalanuvchilarga xabar yuborish)
- 🎮 O'yin boshqaruvi (holat ko'rish, rollarni ko'rish, tezlashtirish, qayta boshlash)

### 🗄 Ma'lumotlar bazasi
- SQLite (lokal) va PostgreSQL (Railway) qo'llab-quvvatlash
- `users`, `admins`, `bans`, `warns` jadvallari
- In-memory cache (tezkor ishlash uchun)

---

## 📁 Fayl tuzilmasi

```
├── main.py       — Asosiy bot (o'yin logikasi, DB, handlerlar)
├── admin.py      — Premium admin tizimi
├── .env          — Muhit o'zgaruvchilari (tokenlar)
├── .env.example  — .env namunasi
├── requirements.txt
├── Procfile      — Railway uchun
└── railway.toml  — Railway sozlamalari
```

---

## ⚙️ O'rnatish (Local)

### 1. Reponi yuklab olish

```bash
git clone https://github.com/USERNAME/mafia-bot.git
cd mafia-bot
```

### 2. Virtual muhit (tavsiya)

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 3. Kutubxonalarni o'rnatish

```bash
pip install -r requirements.txt
```

### 4. `.env` fayl yaratish

`.env.example` dan nusxa oling:

```bash
cp .env.example .env
```

Keyin `.env` ni tahrirlang:

```
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ADMIN_ID=YOUR_TELEGRAM_ID
# PostgreSQL uchun (ixtiyoriy):
# DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

> Tokenni @BotFather dan olasiz.  
> `ADMIN_ID` ni bilish uchun @userinfobot ga yozing.

### 5. Ishga tushirish

```bash
python main.py
```

---

## ☁️ Railway orqali deploy

1. GitHub ga yuklang
2. railway.app ga kiring
3. **Deploy from GitHub repo** ni tanlang
4. **Variables** bo'limiga qo'shing:

| Key            | Value                        |
|----------------|------------------------------|
| `BOT_TOKEN`    | BotFather dan olingan token  |
| `ADMIN_ID`     | Sizning Telegram ID ingiz    |
| `DATABASE_URL` | PostgreSQL URL (ixtiyoriy)   |

5. **Deploy** bosing — bot avtomatik ishga tushadi

> PostgreSQL qo'shish uchun Railway da **Add Plugin → PostgreSQL** ni tanlang.  
> `DATABASE_URL` avtomatik qo'shiladi.

---

## 🤖 Buyruqlar

### 👥 Foydalanuvchilar uchun

| Buyruq | Tavsif |
|--------|--------|
| `/start` | Botni ishga tushirish |
| `/newgame` | Yangi o'yin boshlash |
| `/join` | O'yinga qo'shilish |
| `/profile` | Profilni ko'rish |
| `/balance` | Balansni ko'rish |
| `/top` | Top 10 o'yinchilar |
| `/shop` | Buyumlar do'koni |
| `/lang` | Tilni o'zgartirish |

### 👨‍💼 Admin buyruqlari

| Buyruq | Tavsif |
|--------|--------|
| `/admin` | Admin panel (tugmali menyu) |
| `/stats` | Bot statistikasi |
| `/stopgame` | O'yinni to'xtatish |
| `/resetgame` | O'yinni reset qilish |
| `/gamestatus` | O'yin holati (tirik/o'lgan) |
| `/showroles` | Barcha rollarni ko'rish |
| `/speedgame` | O'yinni tezlashtirish (×3) |
| `/restartgame` | O'yinchilarni saqlab qayta boshlash |
| `/ban <id> [sabab]` | Foydalanuvchini ban qilish |
| `/unban <id>` | Banni olib tashlash |
| `/warn <id> [sabab]` | Ogohlantirish (3 ta → auto ban) |
| `/unwarn <id>` | Warnlarni tozalash |
| `/userinfo <id/@username>` | User ma'lumotlari |
| `/setbalance <id> <miqdor>` | Balansni o'rnatish |
| `/addmoney <id> <miqdor>` | Balansga qo'shish |
| `/removemoney <id> <miqdor>` | Balansdan olib tashlash |
| `/broadcast <matn>` | Hammaga xabar yuborish |
| `/addadmin <id>` | Admin qo'shish |
| `/removeadmin <id>` | Adminni o'chirish |
| `/listadmins` | Adminlar ro'yxati |

---

## 🔐 Xavfsizlik

- Tokenni hech qachon kodga yozmang
- `.env` faylni GitHubga yuklamang (`.gitignore` ga qo'shing)
- Har doim environment variables ishlating
- Asosiy adminni (`ADMIN_ID`) ban yoki o'chirib bo'lmaydi

---

## 🛠 Texnologiyalar

- **Python** 3.10+
- **python-telegram-bot** 20+
- **SQLite** (lokal) / **PostgreSQL** (production)
- **Railway** hosting

---

## 📄 Litsenziya

Open-source loyiha. O'zgartirish va foydalanish mumkin.

---

## 👤 Muallif

Created by Oyatilloxon
