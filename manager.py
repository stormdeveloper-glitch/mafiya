import subprocess
import json
import time
import os
import signal
import sys

# Konfiguratsiya fayli
CONFIG_FILE = "config.json"
# Asosiy bot fayli
MAIN_SCRIPT = "main.py"

# Ishlayotgan jarayonlar: {token: Popen_object}
processes = {}

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
    
    # 1. Asosiy botni ishga tushirish (default .env dagi token bilan)
    # Asosiy bot --admin argumentisiz ishlaydi (yoki .env dan oladi)
    # Ammo biz uni ham process sifatida boshqarsak yaxshi
    # Lekin hozircha asosiy botni manager'dan tashqarida yoki manager ichida "master" sifatida ishlatish mumkin.
    # Keling, asosiy botni ham boshqaramiz.
    
    while True:
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r") as f:
                    config = json.load(f)
            else:
                config = []

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
            for token, proc in processes.items():
                if token not in active_tokens:
                    print(f"🛑 To'xtatilmoqda: {token[:10]}...")
                    proc.terminate()
                    to_remove.append(token)
                
                # Agar jarayon o'zi to'xtab qolgan bo'lsa (crash), qayta ishga tushirish
                elif proc.poll() is not None:
                    print(f"⚠️ Bot crash bo'ldi, qayta ishga tushirilmoqda: {token[:10]}...")
                    processes[token] = start_bot(token, next(c.get("admin_id") for c in config if c["token"] == token))

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
