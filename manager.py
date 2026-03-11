import subprocess
import json
import time
import os
import signal
import sys
import threading
import hashlib
import hmac
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from database import DB, get_uid_data

# Flask App Sozlamalari
app = Flask(__name__, static_folder='web')
# Barcha serverlardan kelgan so'rovlarga ruxsat berish (Distributed hosting uchun)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Konfiguratsiya fayli
CONFIG_FILE = "config.json"
# Asosiy bot fayli
MAIN_SCRIPT = "main.py"

# Ishlayotgan jarayonlar: {token: Popen_object}
processes = {}

# ── API ENDPOINTS ──

@app.route('/')
def serve_dashboard():
    return send_from_directory('web', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('web', path)

@app.route('/api/config')
def get_config():
    return jsonify({
        "bot_username": os.getenv("BOT_USERNAME", "MafiaAnimeBot")
    })

@app.route('/api/stats')
def get_stats():
    try:
        total_users = DB.get_total_users()
        total_clones = len(processes) - 1 if len(processes) > 0 else 0
        return jsonify({
            "status": "online",
            "total_users": total_users,
            "total_clones": max(0, total_clones),
            "active_games": 0, # Bu ma'lumotni botlardan olish kerak bo'ladi, hozircha 0
            "money_flow": "1.2M"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def check_telegram_hash(auth_data, bot_token):
    if not bot_token:
        return False
    check_hash = auth_data.get('hash')
    if not check_hash:
        return False
    
    # Ma'lumotlarni alfavit tartibida saralash
    data_check_arr = []
    for key in sorted(auth_data.keys()):
        if key != 'hash':
            data_check_arr.append(f"{key}={auth_data[key]}")
    data_check_string = "\n".join(data_check_arr)
    
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    hash_hmac = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    return hash_hmac == check_hash

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if not data or 'hash' not in data:
        return jsonify({"success": False, "error": "No data"}), 400
    
    # Haqiqiy Telegram OAuth tekshiruvi
    bot_token = os.getenv("BOT_TOKEN")
    print(f"DEBUG: Login so'rovi keldi. BOT_TOKEN mavjudmi? {'Ha' if bot_token else 'Yoq'}")
    
    if not bot_token:
        print("DEBUG: BOT_TOKEN topilmadi!")
        return jsonify({"success": False, "error": "Serverda BOT_TOKEN sozlanmagan"}), 500

    print("DEBUG: Tekshirilayotgan ma'lumotlar:", data)
    
    is_valid = check_telegram_hash(data, bot_token)
    print(f"DEBUG: Hash tekshiruvi natijasi: {is_valid}")
    
    if not is_valid:
        return jsonify({"success": False, "error": "Telegram tasdiqlash xatosi (Hash match failed)"}), 401
    
    uid = int(data.get('id', 0))
    user = get_uid_data(uid)
    
    # Admin tekshirish
    is_admin = uid == int(os.getenv("ADMIN_ID", 0)) or uid in DB.get_admins()
    
    return jsonify({
        "success": True,
        "user": {
            "id": uid,
            "first_name": data.get('first_name'),
            "photo_url": data.get('photo_url'),
            "is_admin": is_admin
        }
    })

@app.route('/api/user/<int:uid>')
def get_user_profile(uid):
    user = DB.get_user(uid)
    if not user:
        return jsonify({"error": "Not found"}), 404
    return jsonify(user)

# ── TOURNAMENT API ──

@app.route('/api/tournaments', methods=['GET'])
def list_tournaments():
    return jsonify(DB.get_tournaments())

@app.route('/api/tournaments', methods=['POST'])
def create_tournament():
    data = request.json
    if not data or 'name' not in data:
        return jsonify({"success": False, "error": "Name required"}), 400
    
    prize = int(data.get('prize_amount', 0))
    DB.create_tournament(data['name'], prize)
    return jsonify({"success": True})

@app.route('/api/tournaments/<int:tid>/join', methods=['POST'])
def join_tournament(tid):
    data = request.json
    uid = data.get('uid')
    if not uid:
        return jsonify({"success": False, "error": "UID required"}), 400
    DB.join_tournament(tid, uid)
    return jsonify({"success": True})

@app.route('/api/tournaments/<int:tid>/leaderboard', methods=['GET'])
def get_leaderboard(tid):
    return jsonify(DB.get_tournament_leaderboard(tid))

@app.route('/api/tournaments/<int:tid>/status', methods=['POST'])
def update_status(tid):
    data = request.json
    status = data.get('status')
    if not status:
        return jsonify({"success": False, "error": "Status required"}), 400
    DB.update_tournament_status(tid, status)
    return jsonify({"success": True})

@app.route('/api/tournaments/<int:tid>/finish', methods=['POST'])
def finish_tournament(tid):
    result = DB.finish_tournament(tid)
    if not result:
        return jsonify({"success": False, "error": "Could not finish tournament"}), 400
    return jsonify({"success": True, "winner_uid": result['uid'], "prize": result['prize']})

def run_flask():
    port = int(os.getenv("PORT", 5000))
    print(f"🌐 Web Dashboard portda ishlamoqda: {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def start_bot(token, admin_id=None):
    """Yangi bot instance'ini ishga tushirish"""
    cmd = [sys.executable, MAIN_SCRIPT, "--token", token]
    if admin_id:
        cmd.extend(["--admin", str(admin_id)])
    
    print(f"🚀 Ishga tushirilmoqda: {token[:10]}... (Admin: {admin_id})")
    try:
        process = subprocess.Popen(cmd)
        return process
    except Exception as e:
        print(f"❌ Xatolik {token[:10]}... ni ishga tushirishda: {e}")
        return None

def main():
    print("🤖 Mafia Multi-Bot Manager (v2.2) boshlandi...")
    
    # Web serverni alohida thread da ochish
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # 1. Asosiy botni ishga tushirish (default .env dagi token bilan)
    # Asosiy bot --admin argumentisiz ishlaydi (yoki .env dan oladi)
    # Ammo biz uni ham process sifatida boshqarsak yaxshi
    # Lekin hozircha asosiy botni manager'dan tashqarida yoki manager ichida "master" sifatida ishlatish mumkin.
    # Keling, asosiy botni ham boshqaramiz.
    
    while True:
        try:
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, "r") as f:
                        config = json.load(f)
                except Exception as e:
                    print(f"❌ config.json o'qishda xato: {e}")
                    config = []
            else:
                config = []

            # Master botni ham boshqarish (agar BOT_TOKEN bo'lsa)
            master_token = os.getenv("BOT_TOKEN")
            if master_token and not any(c["token"] == master_token for c in config):
                # Master botni virtual config'ga qo'shish
                config.insert(0, {"token": master_token, "admin_id": os.getenv("ADMIN_ID")})

            # Hozirgi configdagi botlarni tekshirish
            active_tokens = [c["token"] for c in config]
            
            # Yangi qo'shilganlarni ishga tushirish
            for entry in config:
                token = entry["token"]
                if token not in processes:
                    proc = start_bot(token, entry.get("admin_id"))
                    if proc:
                        processes[token] = proc

            # O'chirilganlarni to'xtatish (agar configdan o'chirilsa)
            to_remove = []
            now = time.time()
            for token, proc in processes.items():
                if token not in active_tokens:
                    print(f"🛑 To'xtatilmoqda: {token[:10]}...")
                    proc.terminate()
                    to_remove.append(token)
                
                # Agar jarayon o'zi to'xtab qolgan bo'lsa (crash), qayta ishga tushirish
                elif proc.poll() is not None:
                    print(f"⚠️ Bot crash bo'ldi, 5 soniyadan keyin qayta ishga tushirilmoqda: {token[:10]}...")
                    time.sleep(5) # Crash loop'dan himoya
                    processes[token] = start_bot(token, next((c.get("admin_id") for c in config if c["token"] == token), None))

            for token in to_remove:
                del processes[token]

        except Exception as e:
            print(f"❗ Managerda xato: {e}")

        # 10 sekund kutish
        time.sleep(10)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Manager to'xtatilmoqda. Barcha botlar yopilmoqda...")
        for proc in processes.values():
            proc.terminate()
        sys.exit(0)
