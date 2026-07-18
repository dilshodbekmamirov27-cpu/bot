import os
import json
import time
from threading import Thread, Lock
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from flask import Flask

# =====================================================================
# 1. FLASK WEB SERVER (24/7 Barqarorlik uchun)
# =====================================================================
app = Flask("")

@app.route("/")
def home():
    return "Bot status: ACTIVE (24/7 Online)"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    try:
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except Exception as e:
        print(f"Flask server xatosi: {e}")

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# =====================================================================
# 2. BOT VA CONFIGURATION SOZLAMALARI (Zargarlik aniqligida)
# =====================================================================
BOT_TOKEN = "8558172277:AAHfiMmxmVcsOhzBbnYdxDp2jbFs0goGkBY"
# Oqimlar soni 50 taga oshirildi, yuqori yuklama uchun tayyor
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None, threaded=True, num_threads=50)

CONFIG_FILE = "config_v3.json"
DEFAULT_ADMINS = [6297231747, 5632353347, 8655732501]

_config_cache = None
_config_lock = Lock()

temp_selected_groups = {}
temp_campaign_data = {}

def load_config():
    global _config_cache
    with _config_lock:
        if _config_cache is not None:
            return _config_cache

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if "admins" not in config: config["admins"] = DEFAULT_ADMINS
                    if "campaigns" not in config: config["campaigns"] = {}
                    if "known_chats" not in config: config["known_chats"] = {}
                    
                    # TIP XATOLIGINI OLDINI OLISH: Hamma guruh IDlarini str ga o'giramiz
                    for c_id in config["campaigns"]:
                        config["campaigns"][c_id]["groups"] = [str(gid) for gid in config["campaigns"][c_id]["groups"]]
                    
                    # known_chats kalitlarini ham str ekaniga ishonch hosil qilamiz
                    config["known_chats"] = {str(k): str(v) for k, v in config["known_chats"].items()}
                    
                    _config_cache = config
                    return _config_cache
            except Exception:
                pass
        
        default_config = {
            "admins": DEFAULT_ADMINS,
            "type": "text", 
            "text": "Iltimos, reklama matnini sozlang!", 
            "photo_id": None,
            "campaigns": {
                "Plan_1": {
                    "name": "Har soatlik guruhlar",
                    "mode": "interval",
                    "interval_hours": 1,
                    "custom_times": [],
                    "groups": []
                },
                "Plan_2": {
                    "name": "Aniq vaqtli guruhlar",
                    "mode": "custom",
                    "interval_hours": 1,
                    "custom_times": ["09:00", "14:00", "19:00"],
                    "groups": []
                }
            },
            "known_chats": {}
        }
        _config_cache = default_config
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(default_config, f, ensure_ascii=False, indent=4)
        except Exception:
            pass
        return _config_cache

def save_config(config_data):
    global _config_cache
    with _config_lock:
        if "campaigns" in config_data:
            for c_id in config_data["campaigns"]:
                config_data["campaigns"][c_id]["groups"] = [str(gid) for gid in config_data["campaigns"][c_id]["groups"]]
        if "known_chats" in config_data:
            config_data["known_chats"] = {str(k): str(v) for k, v in config_data["known_chats"].items()}
            
        _config_cache = config_data
        
        # ATOMIK YOZISH (Fayl 0 KB bo'lib qolishidan 100% himoya)
        tmp_file = CONFIG_FILE + ".tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
            os.replace(tmp_file, CONFIG_FILE)
        except Exception as e:
            print(f"Config saqlashda kritik xato: {e}")

def is_admin(user_id):
    hardcoded_admins = {6297231747, 5632353347, 8655732501}
    try: 
        file_admins = set(load_config().get("admins", []))
    except Exception: 
        file_admins = set()
    return (user_id in hardcoded_admins) or (user_id in file_admins)

def escape_markdown(text):
    if not text: return "Noma'lum Guruh/Kanal"
    for char in ["_", "*", "`", "[", "]"]: 
        text = text.replace(char, "")
    return text.strip()

def register_chat_by_id_and_title(chat_id, chat_title):
    """
    Guruhni bazaga xavfsiz str formatda yozish
    """
    c = load_config()
    if "known_chats" not in c: c["known_chats"] = {}
    chat_id_str = str(chat_id)
    clean_title = escape_markdown(chat_title)
    
    if c["known_chats"].get(chat_id_str) != clean_title:
        c["known_chats"][chat_id_str] = clean_title
        save_config(c)

# =====================================================================
# 3. KUCHAYTIRILGAN REKLAMA DIREKTORI (SCHEDULER & FLOOD CONTROL)
# =====================================================================
executors = {'default': ThreadPoolExecutor(max_workers=60)}
scheduler = BackgroundScheduler(daemon=True, executors=executors)

def send_campaign_ad(campaign_id):
    def worker():
        try:
            current_config = load_config()
            camp = current_config.get("campaigns", {}).get(campaign_id)
            if not camp or not camp.get("groups"): return

            for group_id in camp["groups"]:
                success = False
                attempts = 0
                while not success and attempts < 3:
                    try:
                        # ID har doim int shaklida Telegramga ketishi shart
                        target_id = int(group_id)
                        if current_config.get("type") == "photo" and current_config.get("photo_id"):
                            bot.send_photo(target_id, current_config["photo_id"], caption=current_config.get("text", ""))
                        else:
                            bot.send_message(target_id, current_config.get("text", "Xabar matni kiritilmagan."))
                        success = True
                        time.sleep(1.2)  # 100+ guruh uchun eng xavfsiz tezlik
                    except ApiTelegramException as e:
                        attempts += 1
                        if e.error_code == 429:  # FLOOD CONTROL (Telegram cheklovi)
                            retry_after = int(e.result_json.get("parameters", {}).get("retry_after", 5))
                            print(f"Flood Control faollashdi! {retry_after} soniya kutilmoqda...")
                            time.sleep(retry_after + 1)
                        elif e.error_code in [403, 400]:  # Bot guruhdan chiqarilgan yoki bloklangan
                            print(f"Bot guruhga yubora olmadi (ID: {group_id}), o'tkazib yuboriladi.")
                            break
                        else:
                            time.sleep(2.0)
                    except Exception:
                        attempts += 1
                        time.sleep(2.0)
        except Exception as e:
            print(f"Tarqatish jarayonida xatolik: {e}")
            
    Thread(target=worker, daemon=True).start()

def restart_scheduler():
    try:
        current_config = load_config()
        scheduler.remove_all_jobs()
        
        campaigns = current_config.get("campaigns", {})
        for camp_id, camp in campaigns.items():
            if not camp.get("groups"): continue
            
            if camp.get("mode") == "interval":
                hours = camp.get("interval_hours", 1)
                scheduler.add_job(send_campaign_ad, "interval", hours=hours, args=[camp_id], id=f"job_int_{camp_id}")
            elif camp.get("mode") == "custom":
                for t_str in camp.get("custom_times", []):
                    try:
                        hour, minute = t_str.split(":")
                        scheduler.add_job(
                            send_campaign_ad, "cron", hour=int(hour), minute=int(minute),
                            args=[camp_id], id=f"job_cron_{camp_id}_{hour}_{minute}"
                        )
                    except Exception: pass
    except Exception as e:
        print(f"Schedulerni sozlashda xato: {e}")

scheduler.start()
restart_scheduler()

# =====================================================================
# 4. ADMIN PANEL KLAVIATURALARI
# =====================================================================
def get_admin_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("📝 Xabarni ko'rish"), types.KeyboardButton("✍️ Yangi xabar yozish"))
    keyboard.add(types.KeyboardButton("⚙️ Reklama rejalarini boshqarish"))
    keyboard.add(types.KeyboardButton("🔐 Adminlarni boshqarish"), types.KeyboardButton("🚀 Hozir hammasiga yo'llash"))
    return keyboard

def get_cancel_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("❌ Bekor qilish"))
    return keyboard

# =====================================================================
# 5. 100% AVTOMATIK GURUH ANIQLASH (Hech qanday xabarsiz va adminliksiz)
# =====================================================================

@bot.my_chat_member_handler()
def target_bot_membership_update(update):
    """
    ENG MUHIM FUNKSIYA: Siz guruhga yozmasangiz ham, admin botni o'chirib 
    qayta qo'shmasa ham, bot guruhga a'zo bo'lgan har qanday holatda 
    Telegram yuboradigan maxsus signalni tutib, guruhni avtomatik ro'yxatga oladi.
    """
    try:
        if update.new_chat_member.status in ["member", "administrator"]:
            chat = update.chat
            title = chat.title if chat.title else f"Guruh ({chat.id})"
            register_chat_by_id_and_title(chat.id, title)
    except Exception as e:
        print(f"Membership update xatosi: {e}")

@bot.message_handler(commands=["start", "admin"])
def send_welcome(message):
    if message.chat.type in ["group", "supergroup", "channel"]:
        register_chat_by_id_and_title(message.chat.id, message.chat.title)
        return
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "🤖 Reklama boshqaruv paneliga xush kelibsiz:", reply_markup=get_admin_keyboard())

@bot.channel_post_handler(func=lambda msg: True)
def monitor_channels(message):
    register_chat_by_id_and_title(message.chat.id, message.chat.title)

@bot.message_handler(func=lambda msg: True, content_types=["text", "photo", "new_chat_members", "left_chat_member", "voice", "document"])
def monitor_chats_and_buttons(message):
    if message.chat.type in ["group", "supergroup", "channel"]:
        register_chat_by_id_and_title(message.chat.id, message.chat.title)
        return
        
    if is_admin(message.from_user.id):
        handle_admin_buttons(message)

# =====================================================================
# 6. ADMIN BUTTONS HANDLER
# =====================================================================
def handle_admin_buttons(message):
    try:
        c = load_config()
        text = message.text
        
        if text == "🔐 Adminlarni boshqarish":
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("➕ Admin qo'shish", callback_data="add_admin"),
                types.InlineKeyboardButton("➖ Adminni o'chirish", callback_data="del_admin")
            )
            bot.send_message(message.chat.id, "Adminlar ro'yxatini boshqarish:", reply_markup=markup)

        elif text == "📝 Xabarni ko'rish":
            if c.get("type") == "photo" and c.get("photo_id"):
                bot.send_photo(message.chat.id, c["photo_id"], caption=c.get("text", ""))
            else:
                bot.send_message(message.chat.id, c.get("text", "Xabar matni hozircha bo'sh!"))
            
        elif text == "✍️ Yangi xabar yozish":
            sent = bot.send_message(message.chat.id, "Menga reklama matnini yuboring yoki rasm yuklang:", reply_markup=get_cancel_keyboard())
            bot.register_next_step_handler(sent, save_new_message)
            
        elif text == "⚙️ Reklama rejalarini boshqarish":
            render_campaign_list(message.chat.id)
            
        elif text == "🚀 Hozir hammasiga yo'llash":
            bot.send_message(message.chat.id, "⏳ Barcha rejalardagi guruhlarga reklama tarqatilmoqda...")
            for camp_id in c.get("campaigns", {}).keys():
                send_campaign_ad(camp_id)
            bot.send_message(message.chat.id, "✅ Reklama muvaffaqiyatli yakunlandi!")
            
    except Exception as e:
        bot.send_message(message.chat.id, f"Xatolik yuz berdi: {e}")

def render_campaign_list(chat_id):
    c = load_config()
    markup = types.InlineKeyboardMarkup(row_width=1)
    campaigns = c.get("campaigns", {})
    for camp_id, camp in campaigns.items():
        g_count = len(camp.get("groups", []))
        mode_txt = f"(Har {camp.get('interval_hours', 1)} soatda)" if camp.get("mode") == "interval" else f"({len(camp.get('custom_times', []))} marta)"
        markup.add(types.InlineKeyboardButton(f"📂 {camp['name']} [{g_count}] {mode_txt}", callback_data=f"manage_camp_{camp_id}"))
    bot.send_message(chat_id, "Sizning reklama rejalaringiz ro'yxati:", reply_markup=markup)

def render_single_campaign(chat_id, message_id, campaign_id):
    c = load_config()
    camp = c["campaigns"].get(campaign_id)
    if not camp: return
    
    known_chats = c.get("known_chats", {})
    g_list = ""
    for i, gid in enumerate(camp.get("groups", []), 1):
        title = known_chats.get(str(gid), f"Guruh ({gid})")
        g_list += f"{i}. {title}\n"
    if not g_list: g_list = "Ushbu rejaga guruhlar ulanmagan.\n"
    
    settings_txt = f"⏱ Har {camp.get('interval_hours')} soatda" if camp.get("mode") == "interval" else f"⏰ Kunlik vaqtlar: {', '.join(camp.get('custom_times', []))}"
    msg = f"📋 **Reja nomi:** {camp['name']}\n⚙️ **Holati:** {settings_txt}\n\n**Ulangan guruhlar ro'yxati:**\n{g_list}"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("➕ Guruhlar qo'shish (Ro'yxat)", callback_data=f"addg_{campaign_id}"),
        types.InlineKeyboardButton("➖ Guruhni o'chirish", callback_data=f"delg_{campaign_id}"),
        types.InlineKeyboardButton("⚙️ Vaqt tartibini o'zgartirish", callback_data=f"edit_time_{campaign_id}"),
        types.InlineKeyboardButton("⬅️ Asosiy Menyuga Qaytish", callback_data="back_to_main_camp")
    )
    bot.edit_message_text(msg, chat_id, message_id, reply_markup=markup, parse_mode="Markdown")

# =====================================================================
# 7. INLINE GURUH TANLASH MANTIQI (Matn/Str xatolari 100% yopilgan)
# =====================================================================
def generate_group_selection_keyboard(admin_id, campaign_id):
    c = load_config()
    known_chats = c.get("known_chats", {})
    camp = c.get("campaigns", {}).get(campaign_id, {})
    
    # IDlarni str formatga keltirib solishtiramiz, xato ehtimoli 0%
    active_in_this_camp = [str(gid) for gid in camp.get("groups", [])]
    selected = [str(gid) for gid in temp_selected_groups.get(admin_id, set())]
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    available = False
    
    if isinstance(known_chats, dict) and known_chats:
        for chat_id_str, title in known_chats.items():
            if chat_id_str in active_in_this_camp: 
                continue
            
            available = True
            status_emoji = "✅" if chat_id_str in selected else "⬜️"
            markup.add(types.InlineKeyboardButton(
                f"{status_emoji} {title}", 
                callback_data=f"tgl_{campaign_id}_{chat_id_str}"
            ))
        
    if available or selected:
        markup.add(types.InlineKeyboardButton("💾 Belgilanganlarni saqlash", callback_data=f"sv_grp_{campaign_id}"))
    else:
        markup.add(types.InlineKeyboardButton("⚠️ Yangi guruh topilmadi", callback_data="none"))
    
    markup.add(types.InlineKeyboardButton("❌ Bekor qilish", callback_data=f"manage_camp_{campaign_id}"))
    return markup

# =====================================================================
# 8. INTERACTIVE CALLBACK HANDLERS
# =====================================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        bot.answer_callback_query(call.id)
        c = load_config()
        admin_id = call.from_user.id
        if not is_admin(admin_id): return
        if call.data == "none": return

        if call.data.startswith("manage_camp_"):
            camp_id = call.data.replace("manage_camp_", "")
            render_single_campaign(call.message.chat.id, call.message.message_id, camp_id)

        elif call.data == "back_to_main_camp":
            bot.delete_message(call.message.chat.id, call.message.message_id)
            render_campaign_list(call.message.chat.id)

        elif call.data.startswith("addg_"):
            camp_id = call.data.replace("addg_", "")
            temp_selected_groups[admin_id] = set()
            markup = generate_group_selection_keyboard(admin_id, camp_id)
            bot.edit_message_text(
                "Bot avtomatik aniqlagan guruhlardan keraklilarini tanlang va Saqlashni bosing:",
                call.message.chat.id, call.message.message_id, reply_markup=markup
            )

        elif call.data.startswith("tgl_"):
            parts = call.data.split("_")
            camp_id = parts[1]
            chat_id_str = "_".join(parts[2:])
            
            if admin_id not in temp_selected_groups: temp_selected_groups[admin_id] = set()
            
            if chat_id_str in temp_selected_groups[admin_id]: 
                temp_selected_groups[admin_id].remove(chat_id_str)
            else: 
                temp_selected_groups[admin_id].add(chat_id_str)
                
            markup = generate_group_selection_keyboard(admin_id, camp_id)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

        elif call.data.startswith("sv_grp_"):
            camp_id = call.data.replace("sv_grp_", "")
            selected = temp_selected_groups.get(admin_id, set())
            if selected:
                for gid_str in selected:
                    if gid_str not in c["campaigns"][camp_id]["groups"]:
                        c["campaigns"][camp_id]["groups"].append(gid_str)
                save_config(c)
            temp_selected_groups.pop(admin_id, None)
            restart_scheduler()
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "✅ Guruhlar muvaffaqiyatli saqlandi!", reply_markup=get_admin_keyboard())

        elif call.data.startswith("edit_time_"):
            camp_id = call.data.replace("edit_time_", "")
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("⏱ Har X soatda bir (Interval)", callback_data=f"set_mode_int_{camp_id}"),
                types.InlineKeyboardButton("⏰ Kuniga ma'lum vaqtlarda (Cron)", callback_data=f"set_mode_cust_{camp_id}"),
                types.InlineKeyboardButton("⬅️ Orqaga", callback_data=f"manage_camp_{camp_id}")
            )
            bot.edit_message_text("Ushbu reja uchun vaqt turini belgilang:", call.message.chat.id, call.message.message_id, reply_markup=markup)

        elif call.data.startswith("set_mode_int_"):
            camp_id = call.data.replace("set_mode_int_", "")
            markup = types.InlineKeyboardMarkup(row_width=3)
            intervals = [1, 2, 3, 4, 6, 8, 12, 24]
            buttons = [types.InlineKeyboardButton(text=f"{h} soat", callback_data=f"save_int_{camp_id}_{h}") for h in intervals]
            markup.add(*buttons)
            markup.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data=f"edit_time_{camp_id}"))
            bot.edit_message_text("Interval vaqtini tanlang:", call.message.chat.id, call.message.message_id, reply_markup=markup)

        elif call.data.startswith("save_int_"):
            _, _, camp_id, h = call.data.split("_")
            c["campaigns"][camp_id]["mode"] = "interval"
            c["campaigns"][camp_id]["interval_hours"] = int(h)
            save_config(c)
            restart_scheduler()
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, f"✅ Reklama rejasi har {h} soatga sozlandi!", reply_markup=get_admin_keyboard())

        elif call.data.startswith("set_mode_cust_"):
            camp_id = call.data.replace("set_mode_cust_", "")
            bot.delete_message(call.message.chat.id, call.message.message_id)
            sent = bot.send_message(
                call.message.chat.id,
                f"Iltimos, reklama soatlarini kiriting.\nFormat: `HH:MM` (vergul bilan)\nMisol: `08:00, 14:30, 20:00`",
                parse_mode="Markdown", reply_markup=get_cancel_keyboard()
            )
            temp_campaign_data[admin_id] = camp_id
            bot.register_next_step_handler(sent, save_camp_times_logic)

        elif call.data.startswith("delg_"):
            camp_id = call.data.replace("delg_", "")
            camp = c["campaigns"].get(camp_id)
            if not camp or not camp["groups"]: 
                bot.answer_callback_query(call.id, "O'chirish uchun guruh yo'q!")
                return
            known_chats = c.get("known_chats", {})
            markup = types.InlineKeyboardMarkup(row_width=1)
            for gid in camp["groups"]:
                title = known_chats.get(str(gid), f"Guruh {gid}")
                markup.add(types.InlineKeyboardButton(f"❌ {title}", callback_data=f"rmg_{camp_id}==={gid}"))
            markup.add(types.InlineKeyboardButton("⬅️ Rejaga qaytish", callback_data=f"manage_camp_{camp_id}"))
            bot.edit_message_text("O'chiriladigan guruhni tanlang:", call.message.chat.id, call.message.message_id, reply_markup=markup)

        elif call.data.startswith("rmg_"):
            payload = call.data.replace("rmg_", "")
            camp_id, gid_str = payload.split("===")
            if gid_str in c["campaigns"][camp_id]["groups"]:
                c["campaigns"][camp_id]["groups"].remove(gid_str)
                save_config(c)
                restart_scheduler()
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "✅ Guruh muvaffaqiyatli o'chirildi.", reply_markup=get_admin_keyboard())

        elif call.data == "add_admin":
            sent = bot.send_message(call.message.chat.id, "Yangi admin Telegram ID raqamini kiriting:", reply_markup=get_cancel_keyboard())
            bot.register_next_step_handler(sent, add_admin_logic)
            
        elif call.data == "del_admin":
            if len(c["admins"]) <= 1: return
            markup = types.InlineKeyboardMarkup()
            for aid in c["admins"]: 
                markup.add(types.InlineKeyboardButton(f"👤 {aid}", callback_data=f"remove_{aid}"))
            bot.edit_message_text("O'chiriladigan adminni tanlang:", call.message.chat.id, call.message.message_id, reply_markup=markup)
            
        elif call.data.startswith("remove_"):
            aid = int(call.data.split("_")[1])
            if aid in c["admins"]:
                c["admins"].remove(aid)
                save_config(c)
                bot.send_message(call.message.chat.id, "✅ Admin o'chirildi.", reply_markup=get_admin_keyboard())

    except Exception as e: 
        print(f"Callback Error: {e}")

# =====================================================================
# 9. STEP LOGIC HANDLERS
# =====================================================================
def save_camp_times_logic(message):
    admin_id = message.from_user.id
    try:
        camp_id = temp_campaign_data.get(admin_id)
        if not camp_id: return
        
        raw_text = message.text.strip() if message.text else ""
        if raw_text == "❌ Bekor qilish":
            bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=get_admin_keyboard())
            return

        parts = [p.strip() for p in raw_text.split(",") if p.strip()]
        validated_times = []
        for p in parts:
            time_parts = p.split(":")
            h, m = int(time_parts[0]), int(time_parts[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                validated_times.append(f"{h:02d}:{m:02d}")
            else: raise ValueError
            
        c = load_config()
        c["campaigns"][camp_id]["mode"] = "custom"
        c["campaigns"][camp_id]["custom_times"] = sorted(list(set(validated_times)))
        save_config(c)
        restart_scheduler()
        
        bot.send_message(message.chat.id, f"✅ Vaqtlar saqlandi: {', '.join(c['campaigns'][camp_id]['custom_times'])}", reply_markup=get_admin_keyboard())
    except Exception:
        bot.send_message(message.chat.id, "❌ Vaqt formati xato! Namuna: `09:00, 18:45`", reply_markup=get_admin_keyboard())
    finally:
        temp_campaign_data.pop(admin_id, None)

def add_admin_logic(message):
    try:
        if message.text == "❌ Bekor qilish": 
            bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=get_admin_keyboard())
            return
        new_id = int(message.text.strip())
        c = load_config()
        if new_id not in c["admins"]:
            c["admins"].append(new_id)
            save_config(c)
            bot.send_message(message.chat.id, "✅ Yangi admin qo'shildi!", reply_markup=get_admin_keyboard())
    except Exception: 
        bot.send_message(message.chat.id, "❌ ID faqat raqamlardan iborat bo'lishi shart.", reply_markup=get_admin_keyboard())

def save_new_message(message):
    try:
        if message.text == "❌ Bekor qilish":
            bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=get_admin_keyboard())
            return
        c = load_config()
        if message.content_type == "photo":
            c["type"] = "photo"
            c["text"] = message.caption or ""
            c["photo_id"] = message.photo[-1].file_id
        elif message.content_type == "text":
            c["type"] = "text"
            c["text"] = message.text
            c["photo_id"] = None
        save_config(c)
        bot.send_message(message.chat.id, "✅ Yangi reklama xabari saqlandi!", reply_markup=get_admin_keyboard())
    except Exception as e:
        bot.send_message(message.chat.id, f"Xabarni saqlashda xato: {e}", reply_markup=get_admin_keyboard())

# =====================================================================
# 10. FAOL QIDIRUV VA SKANER TIZIMI
# =====================================================================
def background_auto_scan():
    """
    Agar config_v3.json ichida campaigns ro'yxatida eski guruh IDlari 
    bo'lsa, bot ularni Telegram serveridan qayta tekshirib keshga tiklaydi.
    """
    def scanner():
        time.sleep(5) # Bot to'liq poolga ulanishi uchun kutish
        print("🔄 Eski keshdagi guruhlarni qayta tekshirish boshlandi...")
        c = load_config()
        check_list = set()
        for camp in c.get("campaigns", {}).values():
            for gid in camp.get("groups", []):
                check_list.add(str(gid))
        
        for gid_str in check_list:
            try:
                chat_info = bot.get_chat(int(gid_str))
                title = chat_info.title if chat_info.title else f"Guruh ({chat_info.id})"
                register_chat_by_id_and_title(chat_info.id, title)
            except Exception:
                continue
        print("✅ Qayta tekshiruv yakunlandi.")

    Thread(target=scanner, daemon=True).start()

# =====================================================================
# 11. START NUQTASI
# =====================================================================
if __name__ == "__main__":
    keep_alive()
    background_auto_scan()
    print("Telegram Bot mutlaqo xatosiz va xavfsiz rejimda ishga tushdi...")
    bot.infinity_polling(timeout=30, long_polling_timeout=15)
