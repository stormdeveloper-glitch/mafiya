# 🎭 Mafia Telegram Bot

Telegram uchun yozilgan **Mafia o‘yin boti**. Guruh chatlarda avtomatik o‘yin boshqaradi: rollar taqsimoti, kecha-kunduz fazalari, ovoz berish va g‘olibni aniqlash.

---

## ✨ Imkoniyatlar

* Avtomatik rollar taqsimlash (Mafia, Doctor, Sheriff, Civilian)
* Kecha / kunduz fazalarini boshqarish
* Ovoz berish (voting) tizimi
* O‘yinchilarni chiqarish (lynch)
* O‘yin holatini kuzatish
* Admin nazorati
* Guruh chatlar uchun moslangan

---

## 🧠 Ishlash prinsipi

Bot Telegram polling orqali ishlaydi.
Server doimiy ishlasa — bot ham 24/7 ishlaydi.

---

## ⚙️ O‘rnatish (Local)

### 1. Reponi yuklab olish

```bash
git clone https://github.com/USERNAME/mafia-bot.git
cd mafia-bot
```

### 2. Virtual muhit (tavsiya)

```bash
python -m venv venv
source venv/bin/activate
```

### 3. Kutubxonalarni o‘rnatish

```bash
pip install -r requirements.txt
```

### 4. `.env` fayl yaratish

Papka ichida `.env` fayl oching:

```
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ADMIN_ID=YOUR_TELEGRAM_ID
```

> Tokenni @BotFather dan olasiz

### 5. Ishga tushirish

```bash
python main.py
```

---

## ☁️ Railway orqali deploy

1. GitHub ga yuklang
2. Railway ga kiring
3. **Deploy from GitHub repo** ni tanlang
4. Variables bo‘limiga kiring va qo‘shing:

| Key       | Value     |
| --------- | --------- |
| BOT_TOKEN | Bot token |
| ADMIN_ID  | Admin ID  |

5. Deploy bosing — bot avtomatik ishga tushadi

---

## 🤖 Botni ishlatish

Botni guruhga qo‘shing va admin qiling.

Asosiy buyruqlar:

* `/start` — botni ishga tushirish
* `/game` — o‘yinni boshlash
* `/join` — o‘yinga qo‘shilish
* `/stop` — o‘yinni to‘xtatish

---

## 🔐 Xavfsizlik

* Tokenni hech qachon kodga yozmang
* `.env` faylni GitHubga yuklamang
* Har doim environment variables ishlating

---

## 🛠 Texnologiyalar

* Python 3.10+
* python-telegram-bot
* Railway hosting

---

## 📄 Litsenziya

Open-source loyiha. O‘zgartirish va foydalanish mumkin.

---

## 👤 Muallif

Created by Oyatilloxon
