import os
import json
import time
import asyncio
from threading import Thread, Lock
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from flask import Flask

# Akkaunt ulanishi uchun Pyrogram kutubxonasi
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired

# =====================================================================
# 1. ASOSIY SOZLAMALAR (BU YERGA REAL MA'LUMOTLARINGIZNI YOZING)
# =====================================================================
# my.telegram.org saytidan olinadigan standart API kalitlar. 
# Buni o'zgartirmasangiz ham ko'pincha ishlaydi, lekin o'zingiznikini qo'yish tavsiya etiladi.
API_ID = 26543189  
API_HASH = "8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d"

BOT_TOKEN = "8558172277:AAHfiMmxmVcsOhzBbnYdxDp2jbFs0goGkBY"
CONFIG_FILE = "config_v3.json"
DEFAULT_ADMINS = [6297231747, 5632353347, 8655732501]

# =====================================================================
# 2. FLASK WEB SERVER (24/7 UCHUN)
# =====================================================================
app = Flask("")
@app.route("/")
def home(): return "ACTIVE"

def keep_alive():
    t = Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False, use_reloader=False))
    t.daemon = True
    t.start()

# =====================================================================
# 3. KODNING ASOSIY MANTIQIY QISMI
# =====================================================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None, threaded=True, num_threads=40)
_config_cache = None
_config_lock = Lock()

user_sessions = {}  # Adminlarning ulanish jarayonini eslab qolish uchun
temp_selected_groups = {}
temp_campaign_data = {}

def load_config():
    global _config_cache
    with _config_lock:
        if _config_cache is not None: return _config_cache
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    c = json.load(f)
                    c["known_chats"] = {str(k): str(v) for k, v in c.get("known_chats", {}).items()}
                    for cid in c.get("campaigns", {}):
                        c["campaigns"][cid]["groups"] = [str(g) for g in c["campaigns"][cid].get("groups", [])]
                    _config_cache = c
                    return _config_cache
            except: pass
        
        default = {
            "admins": DEFAULT_ADMINS, "type": "text", "text": "Reklama matni...", "photo_id": None,
            "campaigns": {
                "Plan_1": {"name": "Har soatlik", "mode": "interval", "interval_hours": 1, "custom_times": [], "groups": []},
                "Plan_2": {"name": "Aniq vaqtli", "mode": "custom", "interval_hours": 1, "custom_times": ["09:00", "18:00"], "groups": []}
            }, "known_chats": {}
        }
        _config_cache = default
        save_config(default)
        return _config_cache

def save_config(data):
    global _config_cache
    with _config_lock:
        _config_cache = data
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e: print(f"Save error: {e}")

def is_admin(uid):
    return uid in DEFAULT_ADMINS or uid in load_config().get("admins", [])

def register_chat(chat_id, title):
    c = load_config()
    c["known_chats"][str(chat_id)] = str(title).replace("_", "").replace("*", "").strip()
    save_config(c)

# =====================================================================
# 4. REKLAMA TARQATISH SCHEDULER (FLOOD CONTROL BILAN)
# =====================================================================
executors = {'default': ThreadPoolExecutor(max_workers=50)}
scheduler = BackgroundScheduler(daemon=True, executors=executors)

def send_campaign_ad(campaign_id):
    c = load_config()
    camp = c.get("campaigns", {}).get(campaign_id, {})
    if not camp or not camp.get("groups"): return
    
    for gid in camp["groups"]:
        try:
            if c.get("type") == "photo" and c.get("photo_id"):
                bot.send_photo(int(gid), c["photo_id"], caption=c.get("text", ""))
            else:
                bot.send_message(int(gid), c.get("text", ""))
            time.sleep(1.5)
        except ApiTelegramException as e:
            if e.error_code == 429:
                time.sleep(int(e.result_json.get("parameters", {}).get("retry_after", 5)) + 1)
        except: pass

def restart_scheduler():
    c = load_config()
    scheduler.remove_all_jobs()
    for cid, camp in c.get("campaigns", {}).items():
        if not camp.get("groups"): continue
        if camp.get("mode") == "interval":
            scheduler.add_job(send_campaign_ad, "interval", hours=camp.get("interval_hours", 1), args=[cid], id=f"int_{cid}")
        elif camp.get("mode") == "custom":
            for t in camp.get("custom_times", []):
                h, m = map(int, t.split(":"))
                scheduler.add_job(send_campaign_ad, "cron", hour=h, minute=m, args=[cid], id=f"cron_{cid}_{h}_{m}")

scheduler.start()
restart_scheduler()

# =====================================================================
# 5. AKKAUNTNI NOMER ORQALI ULAB GURUXLARNI SUG'URIB OLISH
# =====================================================================
async def fetch_groups_via_pyrogram(chat_id, session_name):
    try:
        # Loop muammosini oldini olish uchun yangi event loop yaratamiz
        loop = asyncio.get_event_loop()
        app = Client(session_name, api_id=API_ID, api_hash=API_HASH, loop=loop)
        await app.start()
        
        count = 0
        async for dialog in app.get_dialogs():
            if dialog.chat.type in ["group", "supergroup"]:
                title = dialog.chat.title if dialog.chat.title else f"Guruh ({dialog.chat.id})"
                register_chat(dialog.chat.id, title)
                count += 1
                
        await app.stop()
        bot.send_message(chat_id, f"✅ Tayyor! Profilingizdagi jami **{count} ta guruh** muvaffaqiyatli aniqlandi va tizimga qo'shildi!", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Guruhlarni yuklashda xatolik yuz berdi: {e}")

# =====================================================================
# 6. BOT MENYULARI VA KLAVIATURALARI
# =====================================================================
def get_admin_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("📱 Yangi Akkaunt Ulash (+Nomer)"), types.KeyboardButton("⚙️ Reklama rejalarini boshqarish"))
    keyboard.add(types.KeyboardButton("📝 Xabarni ko'rish"), types.KeyboardButton("✍️ Yangi xabar yozish"))
    keyboard.add(types.KeyboardButton("🚀 Hozir hammasiga yo'llash"))
    return keyboard

@bot.message_handler(commands=["start", "admin"])
def send_welcome(message):
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "🤖 Boshqaruv paneli ishga tushdi. Quyidagi tugmalar orqali akkaunt ulab, guruhlarni avtomat ro'yxatga olishingiz mumkin:", reply_markup=get_admin_keyboard())

# Nomerni qabul qilish bosqichi
@bot.message_handler(func=lambda m: m.text == "📱 Yangi Akkaunt Ulash (+Nomer)")
def ask_phone_number(message):
    if not is_admin(message.from_user.id): return
    sent = bot.send_message(message.chat.id, "📱 Iltimos, Telegram akkauntingiz ulangan telefon raqamni kiriting:\n(Format: `+998901234567`)", parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(sent, process_phone_number)

def process_phone_number(message):
    phone = message.text.strip().replace(" ", "")
    uid = message.from_user.id
    session_name = f"session_{uid}_{int(time.time())}"
    
    bot.send_message(message.chat.id, "⏳ Telegram billing tizimiga ulanilmoqda, kutilmoqda...")
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = Client(session_name, api_id=API_ID, api_hash=API_HASH, loop=loop)
        loop.run_until_complete(client.connect())
        
        # Kod yuborish
        code_hash = loop.run_until_complete(client.send_code(phone))
        
        user_sessions[uid] = {
            "client": client, "phone": phone, "code_hash": code_hash.phone_code_hash, 
            "session_name": session_name, "loop": loop
        }
        
        sent = bot.send_message(message.chat.id, "💬 Telegram ilovangizga kelgan **5 xonali kodni** yuboring:", parse_mode="Markdown")
        bot.register_next_step_handler(sent, process_telegram_code)
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ulanishda xato: {e}\nQaytadan urinib ko'ring.", reply_markup=get_admin_keyboard())

def process_telegram_code(message):
    uid = message.from_user.id
    code = message.text.strip()
    
    if uid not in user_sessions:
        bot.send_message(message.chat.id, "Jarayon eskirgan. Qaytadan boshlang.", reply_markup=get_admin_keyboard())
        return
        
    sess = user_sessions[uid]
    client = sess["client"]
    loop = sess["loop"]
    
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(client.sign_in(sess["phone"], sess["code_hash"], code))
        
        bot.send_message(message.chat.id, "⚡️ Akkaunt ulandi! Endi barcha guruhlaringiz ro'yxati bazaga avtomat tortib olinmoqda...")
        
        # Guruhlarni olishni orqa fonda asinxron boshlaymiz
        Thread(target=lambda: asyncio.run(fetch_groups_via_pyrogram(message.chat.id, sess["session_name"])), daemon=True).start()
        
    except SessionPasswordNeeded:
        # Agar ikki bosqichli parol yoniq bo'lsa
        sent = bot.send_message(message.chat.id, "🔐 Akkauntingizda Ikki bosqichli xavfsizlik paroli yoniq ekan. Parolingizni yuboring:")
        bot.register_next_step_handler(sent, process_2fa_password)
        return
    except (PhoneCodeInvalid, PhoneCodeExpired):
        bot.send_message(message.chat.id, "❌ Kiritilgan kod noto'g'ri yoki muddati o'tgan. Qaytadan urinib ko'ring.", reply_markup=get_admin_keyboard())
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Xatolik yuz berdi: {e}", reply_markup=get_admin_keyboard())
        
    user_sessions.pop(uid, None)

def process_2fa_password(message):
    uid = message.from_user.id
    password = message.text.strip()
    sess = user_sessions.get(uid)
    
    if not sess: return
    client = sess["client"]
    loop = sess["loop"]
    
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(client.check_password(password))
        bot.send_message(message.chat.id, "⚡️ Parol tasdiqlandi! Guruhlar ro'yxati yig'ilmoqda...")
        Thread(target=lambda: asyncio.run(fetch_groups_via_pyrogram(message.chat.id, sess["session_name"])), daemon=True).start()
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Noto'g'ri parol kiritildi yoki xato: {e}", reply_markup=get_admin_keyboard())
        
    user_sessions.pop(uid, None)

# =====================================================================
# 7. INLINE TUGMALAR VA BOTNING BOSHQA ADMIN FUNKSIYALARI
# =====================================================================
@bot.message_handler(func=lambda msg: is_admin(msg.from_user.id))
def handle_admin_buttons(message):
    c = load_config()
    text = message.text
    if text == "⚙️ Reklama rejalarini boshqarish":
        render_campaign_list(message.chat.id)
    elif text == "📝 Xabarni ko'rish":
        if c.get("type") == "photo" and c.get("photo_id"):
            bot.send_photo(message.chat.id, c["photo_id"], caption=c.get("text", ""))
        else: bot.send_message(message.chat.id, c.get("text", "Bo'sh"))
    elif text == "✍️ Yangi xabar yozish":
        sent = bot.send_message(message.chat.id, "Reklama matnini kiriting yoki rasm yuklang:")
        bot.register_next_step_handler(sent, save_new_message)
    elif text == "🚀 Hozir hammasiga yo'llash":
        bot.send_message(message.chat.id, "🚀 Barcha rejalarga reklama yuborish boshlandi...")
        for cid in c.get("campaigns", {}).keys(): send_campaign_ad(cid)
        bot.send_message(message.chat.id, "✅ Yakunlandi!")

def render_campaign_list(chat_id):
    c = load_config()
    markup = types.InlineKeyboardMarkup(row_width=1)
    for cid, camp in c.get("campaigns", {}).items():
        g_count = len(camp.get("groups", []))
        markup.add(types.InlineKeyboardButton(f"📂 {camp['name']} [{g_count}]", callback_data=f"manage_camp_{cid}"))
    bot.send_message(chat_id, "Sizning reklama rejalaringiz:", reply_markup=markup)

def render_single_campaign(chat_id, message_id, campaign_id):
    c = load_config()
    camp = c["campaigns"].get(campaign_id)
    if not camp: return
    known_chats = c.get("known_chats", {})
    g_list = "".join([f"{i+1}. {known_chats.get(str(gid), f'Guruh ({gid})')}\n" for i, gid in enumerate(camp.get("groups", []))])
    if not g_list: g_list = "Guruhlar ulanmagan.\n"
    
    msg = f"📋 **Reja:** {camp['name']}\n**Ulangan guruhlar:**\n{g_list}"
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("➕ Guruhlar qo'shish (Avtomat Ro'yxat)", callback_data=f"addg_{campaign_id}"),
        types.InlineKeyboardButton("➖ Guruhni o'chirish", callback_data=f"delg_{campaign_id}"),
        types.InlineKeyboardButton("⬅️ Orqaga", callback_data="back_to_main_camp")
    )
    bot.edit_message_text(msg, chat_id, message_id, reply_markup=markup, parse_mode="Markdown")

def generate_group_selection_keyboard(admin_id, campaign_id):
    c = load_config()
    known_chats = c.get("known_chats", {})
    camp = c.get("campaigns", {}).get(campaign_id, {})
    active = [str(gid) for gid in camp.get("groups", [])]
    selected = [str(gid) for gid in temp_selected_groups.get(admin_id, set())]
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    available = False
    for chat_id_str, title in known_chats.items():
        if chat_id_str in active: continue
        available = True
        status = "✅" if chat_id_str in selected else "⬜️"
        markup.add(types.InlineKeyboardButton(f"{status} {title}", callback_data=f"tgl_{campaign_id}_{chat_id_str}"))
        
    if available or selected:
        markup.add(types.InlineKeyboardButton("💾 Belgilanganlarni saqlash", callback_data=f"sv_grp_{campaign_id}"))
    else:
        markup.add(types.InlineKeyboardButton("⚠️ Hozircha yangi guruh yo'q. Avval akkaunt ulang.", callback_data="none"))
    markup.add(types.InlineKeyboardButton("❌ Bekor qilish", callback_data=f"manage_camp_{campaign_id}"))
    return markup

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    c = load_config()
    admin_id = call.from_user.id
    if not is_admin(admin_id) or call.data == "none": return
    bot.answer_callback_query(call.id)

    if call.data.startswith("manage_camp_"):
        render_single_campaign(call.message.chat.id, call.message.message_id, call.data.replace("manage_camp_", ""))
    elif call.data == "back_to_main_camp":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        render_campaign_list(call.message.chat.id)
    elif call.data.startswith("addg_"):
        camp_id = call.data.replace("addg_", "")
        temp_selected_groups[admin_id] = set()
        bot.edit_message_text("Profilingizdagi aniqlangan guruhlar ro'yxati:", call.message.chat.id, call.message.message_id, reply_markup=generate_group_selection_keyboard(admin_id, camp_id))
    elif call.data.startswith("tgl_"):
        _, camp_id, chat_id_str = call.data.split("_", 2)
        if admin_id not in temp_selected_groups: temp_selected_groups[admin_id] = set()
        if chat_id_str in temp_selected_groups[admin_id]: temp_selected_groups[admin_id].remove(chat_id_str)
        else: temp_selected_groups[admin_id].add(chat_id_str)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=generate_group_selection_keyboard(admin_id, camp_id))
    elif call.data.startswith("sv_grp_"):
        camp_id = call.data.replace("sv_grp_", "")
        for gid_str in temp_selected_groups.get(admin_id, set()):
            if gid_str not in c["campaigns"][camp_id]["groups"]: c["campaigns"][camp_id]["groups"].append(gid_str)
        save_config(c); temp_selected_groups.pop(admin_id, None); restart_scheduler()
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "✅ Guruhlar muvaffaqiyatli saqlandi!", reply_markup=get_admin_keyboard())
    elif call.data.startswith("delg_"):
        camp_id = call.data.replace("delg_", ""); camp = c["campaigns"].get(camp_id)
        if not camp or not camp["groups"]: return
        known_chats = c.get("known_chats", {})
        markup = types.InlineKeyboardMarkup(row_width=1)
        for gid in camp["groups"]:
            markup.add(types.InlineKeyboardButton(f"❌ {known_chats.get(str(gid), gid)}", callback_data=f"rmg_{camp_id}==={gid}"))
        bot.edit_message_text("O'chiriladigan guruh ustiga bosing:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    elif call.data.startswith("rmg_"):
        camp_id, gid_str = call.data.replace("rmg_", "").split("===")
        if gid_str in c["campaigns"][camp_id]["groups"]: c["campaigns"][camp_id]["groups"].remove(gid_str)
        save_config(c); restart_scheduler()
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "✅ Guruh reja ro'yxatidan olib tashlandi.", reply_markup=get_admin_keyboard())

def save_new_message(message):
    c = load_config()
    if message.content_type == "photo":
        c["type"] = "photo"; c["text"] = message.caption or ""; c["photo_id"] = message.photo[-1].file_id
    elif message.content_type == "text":
        c["type"] = "text"; c["text"] = message.text; c["photo_id"] = None
    save_config(c)
    bot.send_message(message.chat.id, "✅ Yangi reklama xabari saqlandi!", reply_markup=get_admin_keyboard())

# =====================================================================
# 8. PROCESS START
# =====================================================================
if __name__ == "__main__":
    keep_alive()
    print("Telegram Bot (Userbot Scraper bilan) muvaffaqiyatli ishga tushdi...")
    bot.infinity_polling(timeout=30, long_polling_timeout=15)
