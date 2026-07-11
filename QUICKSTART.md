# 🚀 Tez Boshlash Bo'yicha Yo'riqnoma

## Kerakli Narsalar

- Python 3.7 yoki undan yuqori versiya
- Internet ulanishi
- Telegram akkaaunti

## 1-qadam: Kutubxonalarni O'rnatish

Buyruq qatorini ochib quyidagini yozing:

```bash
pip install python-telegram-bot==20.0
```

## 2-qadam: Bot Tokenini Olish

1. Telegramda **@BotFather** ni toping
2. `/start` yuboring
3. `/newbot` yuboring
4. Bot yaratish uchun ko'rsatmalarni bajaring
5. Berilgan API tokenini nusxalang (masalan: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

## 3-qadam: Botni Sozlash

1. `main.py` faylini matnli muharrir bilan oching
2. Yuqori qismida bu qatorni toping:
   ```python
   BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
   ```
3. `"YOUR_BOT_TOKEN_HERE"` ni o'zingizning tokeningiz bilan almashtiring:
   ```python
   BOT_TOKEN = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
   ```

## 4-qadam: (Ixtiyoriy) Admin Foydalanuvchilarini O'rnatish

Admin buyruqlaridan (`/admin`, `/stopgame`, `/resetgame`) foydalanish uchun:

1. O'zingizning Telegram foydalanuvchi ID'ni olish:
   - **@userinfobot** ga xabar yuboring
   - Bot javobda ID'ni ko'rsatadi

2. `main.py` da bu qatorni toping:
   ```python
   ADMINS = {123456789}
   ```

3. `123456789` ni o'zingizning ID'ingiz bilan almashtiring:
   ```python
   ADMINS = {123456789}
   ```

4. Bir nechta adminlarni qo'shish uchun:
   ```python
   ADMINS = {123456789, 987654321, 555555555}
   ```

## 5-qadam: Botni Ishga Tushirish

Bot katalogiga o'ting va quyidagini yozing:

```bash
python main.py
```

Bunday chiqish ko'rish kerak:
```
2024-12-19 10:30:45,123 - INFO - Polling started
```

## 6-qadam: Botni Sinab Ko'rish

1. Telegramda o'zingizning botini toping (nom yoki @username orqali qidiring)
2. `/start` yuboring
3. Xush kelibsiz xabarini ko'rish kerak
4. O'yin yaratish uchun `/newgame` sinab ko'ring

## Foydalanuvchilar Uchun Asosiy Buyruqlar

- `/start` - Botni ishga tushirish va xush kelibsiz xabarini ko'rish
- `/newgame` - Yangi Mafia o'yini yaratish (faqat admin)
- `/lang` - Tilni o'zgartirish (O'Z, RU, EN)
- `/balance` - Tanga balansi tekshirish
- `/shop` - Anime kuchlarini sotib olish

## Admin Buyruqlari

- `/admin` - Admin panelini ochish
- `/stopgame` - Joriy o'yinni to'xtatish
- `/resetgame` - O'yin holatini qayta tiklash

## Muammolarni Hal Qilish

### Bot javob bermaydi
1. Bot tokenini tekshiring
2. Internet ulanishini tekshiring
3. Botni qayta ishga tushirishni sinab ko'ring

### "Invalid bot token" xatosi
1. Toq tokenni nusxalaganingizni tekshiring
2. Qo'shimcha bo'shliqlar yo'qligini tekshiring
3. BotFather dan yangi token oling

### O'yin ishga tushmaydi
1. Kamida 3 ta o'yinchi qo'shilganini tekshiring
2. Ro'yxatga olish yopilishi uchun 45 soniyani kutib turing
3. Tiqilgan o'yinlarni tozalash uchun `/resetgame` dan foydalaning

### Bot buzilib ketadi
1. python-telegram-bot o'rnatilganini tekshiring: `pip list | grep python-telegram`
2. Kutubxonani yangilang: `pip install --upgrade python-telegram-bot`
3. Xatolar uchun jurnallarni tekshiring

## Fayl Strukturasi

```
mafia/
├── main.py                 # Bot asosiy kodi
├── README.md              # Batafsil hujjatlar
├── IMPROVEMENTS.md        # Amalga oshirilgan takomillashtirishlar
├── QUICKSTART.md          # Bu fayl
└── mafia_data.json        # Foydalanuvchi ma'lumotlari (avtomatik yaratiladi)
```

## Ma'lumotlar va Xavfsizlik

- Foydalanuvchi ma'lumotlari `mafia_data.json` faylida saqlanadi (mahalliy fayl)
- Hech qanday ma'lumot tashqi serverlarga yuborilmaydi
- Barcha foydalanuvchi rivojlanishini qayta tiklash uchun `mafia_data.json` o'chiring

## Yordam

Agar muammolarga duch kelsangiz:

1. [python-telegram-bot hujjatlarini](https://python-telegram-bot.readthedocs.io/) tekshiring
2. `main.py` dagi barcha sozlamalarni tekshiring
3. `pip install --upgrade python-telegram-bot` sinab ko'ring
4. Python versiyasi 3.7+ ekanligini tekshiring

## Keyingi Bosqichlar

1. `start()` funktsiyasida matnni o'zgartirib xush kelibsiz xabarini tuzatish
2. Zarur bo'yicha ko'proq admin foydalanuvchi qo'shish
3. Bot faoliyatini kuzatish uchun jurnallarni kuzatish
4. Foydalanuvchi rivojlanishini ko'rish uchun `mafia_data.json` ni tekshirish

Mafia o'yini botidan bahramand bo'ling! 🎮
