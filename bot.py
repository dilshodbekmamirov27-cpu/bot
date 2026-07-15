import os
import json
import time
from threading import Thread
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask

# =====================================================================
# 1. SERVER SOZLAMALARI
# =====================================================================
app = Flask('')
@app.route('/')
def home(): return "Bot status: OK (24/7 ishlamoqda)"
def run_web_server(): app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
def keep_alive():
    t = Thread(target=run_web_server); t.daemon = True; t.start()

# =====================================================================
# 2. BOT VA CONFIG SOZLAMALARI
# =====================================================================
BOT_TOKEN = "8558172277:AAHfiMmxmVcsOhzBbnYdxDp2jbFs0goGkBY"
bot = telebot.TeleBot(BOT_TOKEN)
CONFIG_FILE = "config_v2.json"
DEFAULT_ADMINS = [6297231747, 5632353347, 8655732501]

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {
        "admins": DEFAULT_ADMINS,
        "type": "text", "text": "Xush kelibsiz!", "photo_id": None,
        "groups": [], "is_active": True, "interval_hours": 1
    }

def save_config(config_data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

def is_admin(user_id):
    # Kod ichiga yozilgan asosiy adminlar ro'yxati
    hardcoded_admins = [6297231747, 5632353347, 8655732501]
    
    # JSON fayl ichidagi adminlar ro'yxati
    file_admins = load_config().get("admins", [])
    
    # Agar foydalanuvchi ikkalasidan birida bo'lsa ham TRUE qaytaradi
    return (user_id in hardcoded_admins) or (user_id in file_admins)
# =====================================================================
# 3. TARQATISH FUNKSIYALARI
# =====================================================================
scheduler = BackgroundScheduler()

def send_hourly_reminder():
    current_config = load_config()
    if not current_config.get("is_active", True): return
    groups = current_config.get("groups", [])
    for group_id in groups:
        try:
            if current_config["type"] == "photo":
                bot.send_photo(group_id, current_config["photo_id"], caption=current_config["text"])
            else:
                bot.send_message(group_id, current_config["text"])
            time.sleep(1.5)
        except Exception as e: print(f"Xatolik {group_id}: {e}")

def restart_scheduler():
    current_config = load_config()
    scheduler.remove_all_jobs()
    scheduler.add_job(send_hourly_reminder, 'interval', hours=current_config.get("interval_hours", 1))

scheduler.start()
restart_scheduler()

# =====================================================================
# 4. ADMIN MENYUSI
# =====================================================================
def get_admin_keyboard():
    c = load_config()
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("📝 Xabarni ko'rish"), types.KeyboardButton("✍️ Yangi xabar yozish"))
    keyboard.add(types.KeyboardButton("🟢 Status" if c.get("is_active") else "🔴 Status"), types.KeyboardButton(f"⏱ Interval: {c.get('interval_hours', 1)} soat"))
    keyboard.add(types.KeyboardButton("👥 Guruhlarni boshqarish"), types.KeyboardButton("🔐 Adminlarni boshqarish"))
    keyboard.add(types.KeyboardButton("🚀 Hozir yo'llash (Test)"))
    return keyboard

@bot.message_handler(commands=['start', 'admin'])
def send_welcome(message):
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "Boshqaruv paneli:", reply_markup=get_admin_keyboard())
    else:
        bot.send_message(message.chat.id, f"Guruh ID: `{message.chat.id}`", parse_mode="Markdown")

# =====================================================================
# 5. ADMIN HANDLERS (O'zgartirilgan)
# =====================================================================
@bot.message_handler(func=lambda msg: is_admin(msg.from_user.id))
def handle_admin_buttons(message):
    c = load_config()
    text = message.text
    
    if text == "🔐 Adminlarni boshqarish":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("➕ Admin qo'shish", callback_data="add_admin"),
                   types.InlineKeyboardButton("➖ Adminni o'chirish", callback_data="del_admin"))
        bot.send_message(message.chat.id, "Adminlarni boshqarish:", reply_markup=markup)

    elif text == "📝 Xabarni ko'rish":
        if c["type"] == "photo": bot.send_photo(message.chat.id, c["photo_id"], caption=c["text"])
        else: bot.send_message(message.chat.id, c["text"])
        
    elif text == "✍️ Yangi xabar yozish":
        sent = bot.send_message(message.chat.id, "Yangi matn yoki rasm yuboring:")
        bot.register_next_step_handler(sent, lambda m: (save_new_message(m)))
        
    elif text.startswith("🟢 Status") or text.startswith("🔴 Status"):
        c["is_active"] = not c.get("is_active", True)
        save_config(c)
        bot.send_message(message.chat.id, f"Holat o'zgardi!", reply_markup=get_admin_keyboard())
        
    elif text == "🚀 Hozir yo'llash (Test)":
        send_hourly_reminder()
        bot.send_message(message.chat.id, "Yuborildi!")

# =====================================================================
# 6. CALLBACK VA NEXT STEP HANDLERS (Qisqartirilgan logika)
# =====================================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    c = load_config()
    if call.data == "add_admin":
        sent = bot.send_message(call.message.chat.id, "Adminning Telegram ID sini yozing:")
        bot.register_next_step_handler(sent, lambda m: add_admin(m))
    elif call.data == "del_admin":
        markup = types.InlineKeyboardMarkup()
        for aid in c["admins"]:
            markup.add(types.InlineKeyboardButton(str(aid), callback_data=f"remove_{aid}"))
        bot.edit_message_text("O'chirish uchun ID ni tanlang:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    elif call.data.startswith("remove_"):
        aid = int(call.data.split("_")[1])
        c["admins"].remove(aid)
        save_config(c)
        bot.answer_callback_query(call.id, "O'chirildi!")
        bot.delete_message(call.message.chat.id, call.message.message_id)

def add_admin(message):
    try:
        new_id = int(message.text)
        c = load_config()
        if new_id not in c["admins"]:
            c["admins"].append(new_id)
            save_config(c)
            bot.send_message(message.chat.id, "Admin qo'shildi!")
    except: bot.send_message(message.chat.id, "Xato ID!")

def save_new_message(message):
    c = load_config()
    if message.content_type == 'photo':
        c["type"], c["text"], c["photo_id"] = "photo", message.caption or "", message.photo[-1].file_id
    else:
        c["type"], c["text"], c["photo_id"] = "text", message.text, None
    save_config(c)
    bot.send_message(message.chat.id, "Saqlandi!", reply_markup=get_admin_keyboard())

if __name__ == "__main__":
    keep_alive()
    bot.infinity_polling()
