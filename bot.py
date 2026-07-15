import os
import json
import time
from threading import Thread, Lock
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask

# =====================================================================
# 1. FLASK WEB SERVER (24/7 running)
# =====================================================================
app = Flask("")

@app.route("/")
def home():
    return "Bot status: ACTIVE (24/7 running)"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# =====================================================================
# 2. BOT VA CONFIG SOZLAMALARI
# =====================================================================
BOT_TOKEN = "8558172277:AAHfiMmxmVcsOhzBbnYdxDp2jbFs0goGkBY"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None, threaded=True, num_threads=30)

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
        except Exception as e:
            print(f"Config yozishda xato: {e}")
        return _config_cache

def save_config(config_data):
    global _config_cache
    with _config_lock:
        _config_cache = config_data
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Config saqlashda xatolik: {e}")

def is_admin(user_id):
    hardcoded_admins = {6297231747, 5632353347, 8655732501}
    try: 
        file_admins = set(load_config().get("admins", []))
    except Exception: 
        file_admins = set()
    return (user_id in hardcoded_admins) or (user_id in file_admins)

def escape_markdown(text):
    if not text: return "Noma'lum"
    for char in ["_", "*", "`", "[", "]"]: 
        text = text.replace(char, "")
    return text

def register_chat(chat):
    if chat and chat.type in ["group", "supergroup", "channel"]:
        c = load_config()
        if "known_chats" not in c: c["known_chats"] = {}
        chat_id_str = str(chat.id)
        
        # XATO TUZATILDI: Yopiq guruh nomini Telegram'dan majburlab tortib olish
        title = chat.title
        if not title or title.startswith("-") or chat_id_str not in c["known_chats"]:
            try:
                chat_info = bot.get_chat(chat.id)
                title = chat_info.title
            except Exception:
                title = f"Guruh ({chat.id})"

        clean_title = escape_markdown(title)
        c["known_chats"][chat_id_str] = clean_title
        save_config(c)

# =====================================================================
# 3. SCHEDULER TIZIMI
# =====================================================================
scheduler = BackgroundScheduler(daemon=True)

def send_campaign_ad(campaign_id):
    def worker():
        try:
            current_config = load_config()
            camp = current_config.get("campaigns", {}).get(campaign_id)
            if not camp or not camp.get("groups"): return

            for group_id in camp["groups"]:
                try:
                    if current_config.get("type") == "photo" and current_config.get("photo_id"):
                        bot.send_photo(group_id, current_config["photo_id"], caption=current_config.get("text", ""))
                    else:
                        bot.send_message(group_id, current_config.get("text", "Xabar matni kiritilmagan."))
                    time.sleep(1.5)
                except ApiTelegramException as e:
                    print(f"API xatosi guruh {group_id}: {e.description}")
                except Exception as e:
                    print(f"Xatolik guruh {group_id}: {e}")
        except Exception as e:
            print(f"Tarqatish xizmatida xatolik: {e}")
            
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
# 5. BUYRUQLAR
# =====================================================================
@bot.message_handler(commands=["start", "admin"])
def send_welcome(message):
    if message.chat.type in ["group", "supergroup", "channel"]:
        register_chat(message.chat)
        return
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "Boshqaruv paneliga xush kelibsiz:", reply_markup=get_admin_keyboard())

@bot.message_handler(commands=["id"])
def get_group_id_command(message):
    """XATO TUZATILDI: Guruh nomini aniqlab bazaga chiroyli yozuvchi buyruq"""
    register_chat(message.chat)
    c = load_config()
    guruh_nomi = c.get("known_chats", {}).get(str(message.chat.id), "Noma'lum guruh")
    bot.reply_to(message, f"✅ **{guruh_nomi}** muvaffaqiyatli tizimga qo'shildi!\nID: `{message.chat.id}`", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: True, content_types=["text", "photo", "new_chat_members", "left_chat_member"])
def monitor_chats(message):
    if message.chat.type in ["group", "supergroup", "channel"]:
        register_chat(message.chat)
        return
    if is_admin(message.from_user.id):
        handle_admin_buttons(message)

# =====================================================================
# 6. REACTION HANDLER
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
            bot.send_message(message.chat.id, "Adminlarni boshqarish menyusi:", reply_markup=markup)

        elif text == "📝 Xabarni ko'rish":
            if c.get("type") == "photo" and c.get("photo_id"):
                bot.send_photo(message.chat.id, c["photo_id"], caption=c.get("text", ""))
            else:
                bot.send_message(message.chat.id, c.get("text", "Xabar matni bo'sh!"))
            
        elif text == "✍️ Yangi xabar yozish":
            sent = bot.send_message(message.chat.id, "Menga yangi matn kiriting yoki rasm yuboring:", reply_markup=get_cancel_keyboard())
            bot.register_next_step_handler(sent, save_new_message)
            
        elif text == "⚙️ Reklama rejalarini boshqarish":
            render_campaign_list(message.chat.id)
            
        elif text == "🚀 Hozir hammasiga yo'llash":
            bot.send_message(message.chat.id, "Barcha rejalardagi guruhlarga xabar yuborilmoqda...")
            for camp_id in c.get("campaigns", {}).keys():
                send_campaign_ad(camp_id)
            bot.send_message(message.chat.id, "Yuborish yakunlandi!")
            
    except Exception as e:
        bot.send_message(message.chat.id, f"Xatolik yuz berdi: {e}")

def render_campaign_list(chat_id):
    c = load_config()
    markup = types.InlineKeyboardMarkup(row_width=1)
    campaigns = c.get("campaigns", {})
    for camp_id, camp in campaigns.items():
        g_count = len(camp.get("groups", []))
        if camp.get("mode") == "interval":
            mode_txt = f"(Har {camp.get('interval_hours', 1)} soatda)"
        else:
            mode_txt = f"({len(camp.get('custom_times', []))} marta qo'lda)"
        markup.add(types.InlineKeyboardButton(f"📂 {camp['name']} [{g_count}] {mode_txt}", callback_data=f"manage_camp_{camp_id}"))
    bot.send_message(chat_id, "Sizning reklama rejalaringiz ro'yxati:", reply_markup=markup)

def render_single_campaign(chat_id, message_id, campaign_id):
    c = load_config()
    camp = c["campaigns"].get(campaign_id)
    if not camp: return
    
    known_chats = c.get("known_chats", {})
    g_list = ""
    for i, gid in enumerate(camp.get("groups", []), 1):
        title = known_chats.get(str(gid), f"Guruh {gid}")
        g_list += f"{i}. {title}\n"
    if not g_list: g_list = "Guruhlar ulanmagan.\n"
    
    settings_txt = f"⏱ Har {camp.get('interval_hours')} soatda" if camp.get("mode") == "interval" else f"⏰ Belgilangan vaqtlar: {', '.join(camp.get('custom_times', []))}"
    msg = f"📋 **Reja nomi:** {camp['name']}\n⚙️ **Turi:** {settings_txt}\n\n**Ushbu rejaga ulangan guruhlar:**\n{g_list}"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("➕ Guruhlar qo'shish", callback_data=f"addg_{campaign_id}"),
        types.InlineKeyboardButton("➖ Guruhni o'chirish", callback_data=f"delg_{campaign_id}"),
        types.InlineKeyboardButton("⚙️ Vaqt/Intervalni o'zgartirish", callback_data=f"edit_time_{campaign_id}"),
        types.InlineKeyboardButton("⬅️ Orqaga", callback_data="back_to_main_camp")
    )
    bot.edit_message_text(msg, chat_id, message_id, reply_markup=markup, parse_mode="Markdown")

# =====================================================================
# 7. MULTI-SELECT GURUH JONLI INTERFEYSI
# =====================================================================
def generate_group_selection_keyboard(admin_id, campaign_id):
    c = load_config()
    known_chats = c.get("known_chats", {})
    camp = c["campaigns"].get(campaign_id, {})
    active_in_this_camp = set(camp.get("groups", []))
    
    selected = temp_selected_groups.get(admin_id, set())
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    available = False
    if isinstance(known_chats, dict):
        for chat_id_str, title in known_chats.items():
            chat_id = int(chat_id_str)
            if chat_id in active_in_this_camp: continue
            available = True
            status_emoji = "✅" if chat_id in selected else "⬜️"
            markup.add(types.InlineKeyboardButton(f"{status_emoji} {title}", callback_data=f"tgl_{campaign_id}_{chat_id}"))
        
    if not available: return None
    markup.add(
        types.InlineKeyboardButton("💾 Tanlanganlarni saqlash", callback_data=f"sv_grp_{campaign_id}"),
        types.InlineKeyboardButton("❌ Bekor qilish", callback_data=f"manage_camp_{campaign_id}")
    )
    return markup

# =====================================================================
# 8. INLINE CALLBACK HANDLERS (XATOLAR TUZATILDI)
# =====================================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        bot.answer_callback_query(call.id)
        c = load_config()
        admin_id = call.from_user.id
        if not is_admin(admin_id): return

        # Rejani boshqarish oynasi
        if call.data.startswith("manage_camp_"):
            camp_id = call.data.replace("manage_camp_", "")
            render_single_campaign(call.message.chat.id, call.message.message_id, camp_id)

        # Bosh ro'yxatga qaytish
        elif call.data == "back_to_main_camp":
            bot.delete_message(call.message.chat.id, call.message.message_id)
            render_campaign_list(call.message.chat.id)

        # XATO TUZATILDI: Reja ichidagi guruh qo'shish tugmasi endi soat menyusini ochmaydi!
        elif call.data.startswith("addg_"):
            camp_id = call.data.replace("addg_", "")
            temp_selected_groups[admin_id] = set()
            markup = generate_group_selection_keyboard(admin_id, camp_id)
            if markup is None:
                bot.edit_message_text("Yangi guruh topilmadi.\n\n💡 **Qo'shish tartibi:** Bot a'zo bo'lgan o'sha yopiq guruh ichiga kirib `/id` deb yozing. Keyin bu yerga qayting.", call.message.chat.id, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data=f"manage_camp_{camp_id}")))
                return
            bot.edit_message_text("Rejaga qo'shmoqchi bo'lgan guruhlarni belgilang:", call.message.chat.id, call.message.message_id, reply_markup=markup)

        # Guruhni tanlash (Checkbox)
        elif call.data.startswith("tgl_"):
            _, camp_id, chat_id = call.data.split("_")
            chat_id = int(chat_id)
            if admin_id not in temp_selected_groups: temp_selected_groups[admin_id] = set()
            if chat_id in temp_selected_groups[admin_id]: temp_selected_groups[admin_id].remove(chat_id)
            else: temp_selected_groups[admin_id].add(chat_id)
            markup = generate_group_selection_keyboard(admin_id, camp_id)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

        # Tanlangan guruhlarni saqlash
        elif call.data.startswith("sv_grp_"):
            camp_id = call.data.replace("sv_grp_", "")
            selected = temp_selected_groups.get(admin_id, set())
            if selected:
                for gid in selected:
                    if gid not in c["campaigns"][camp_id]["groups"]:
                        c["campaigns"][camp_id]["groups"].append(gid)
                save_config(c)
            temp_selected_groups.pop(admin_id, None)
            restart_scheduler()
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "✅ Guruhlar muvaffaqiyatli saqlandi!", reply_markup=get_admin_keyboard())

        # Vaqtni o'zgartirish menyusi
        elif call.data.startswith("edit_time_"):
            camp_id = call.data.replace("edit_time_", "")
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("⏱ Har x soatda bir (Interval)", callback_data=f"set_mode_int_{camp_id}"),
                types.InlineKeyboardButton("⏰ Kuniga ma'lum soatlarda (Qo'lda kiritish)", callback_data=f"set_mode_cust_{camp_id}"),
                types.InlineKeyboardButton("⬅️ Orqaga", callback_data=f"manage_camp_{camp_id}")
            )
            bot.edit_message_text("Ushbu reja uchun vaqt rejimini tanlang:", call.message.chat.id, call.message.message_id, reply_markup=markup)

        # Interval tanlash (1, 2, 3 soat...)
        elif call.data.startswith("set_mode_int_"):
            camp_id = call.data.replace("set_mode_int_", "")
            markup = types.InlineKeyboardMarkup(row_width=3)
            intervals = [1, 2, 3, 4, 6, 8, 12, 24]
            buttons = [types.InlineKeyboardButton(text=f"{h} soat", callback_data=f"save_int_{camp_id}_{h}") for h in intervals]
            markup.add(*buttons)
            markup.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data=f"edit_time_{camp_id}"))
            bot.edit_message_text("Xabar necha soatda bir yuborilsin?", call.message.chat.id, call.message.message_id, reply_markup=markup)

        # Tanlangan interval soatini saqlash
        elif call.data.startswith("save_int_"):
            _, _, camp_id, h = call.data.split("_")
            c["campaigns"][camp_id]["mode"] = "interval"
            c["campaigns"][camp_id]["interval_hours"] = int(h)
            save_config(c)
            restart_scheduler()
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, f"✅ Vaqt muvaffaqiyatli o'zgartirildi: Har {h} soatda!", reply_markup=get_admin_keyboard())

        # Qo'lda vaqt kiritish tartibi
        elif call.data.startswith("set_mode_cust_"):
            camp_id = call.data.replace("set_mode_cust_", "")
            bot.delete_message(call.message.chat.id, call.message.message_id)
            sent = bot.send_message(
                call.message.chat.id,
                f"Vaqtlarni kiriting. Format: `HH:MM` (vergul bilan).\nMisol: `09:00, 14:00, 21:00`",
                parse_mode="Markdown", reply_markup=get_cancel_keyboard()
            )
            temp_campaign_data[admin_id] = camp_id
            bot.register_next_step_handler(sent, save_camp_times_logic)

        # Guruhni o'chirish oynasi
        elif call.data.startswith("delg_"):
            camp_id = call.data.replace("delg_", "")
            camp = c["campaigns"].get(camp_id)
            if not camp or not camp["groups"]: return
            known_chats = c.get("known_chats", {})
            markup = types.InlineKeyboardMarkup()
            for gid in camp["groups"]:
                title = known_chats.get(str(gid), f"Guruh {gid}")
                markup.add(types.InlineKeyboardButton(f"❌ {title}", callback_data=f"rmg_{camp_id}_{gid}"))
            markup.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data=f"manage_camp_{camp_id}"))
            bot.edit_message_text("O'chiriladigan guruhni tanlang:", call.message.chat.id, call.message.message_id, reply_markup=markup)

        # Guruhni o'chirishni tasdiqlash
        elif call.data.startswith("rmg_"):
            _, camp_id, gid = call.data.split("_")
            gid = int(gid)
            if gid in c["campaigns"][camp_id]["groups"]:
                c["campaigns"][camp_id]["groups"].remove(gid)
                save_config(c)
                restart_scheduler()
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "Guruh muvaffaqiyatli o'chirildi.", reply_markup=get_admin_keyboard())

        elif call.data == "add_admin":
            sent = bot.send_message(call.message.chat.id, "ID kiriting:", reply_markup=get_cancel_keyboard())
            bot.register_next_step_handler(sent, add_admin_logic)
            
        elif call.data == "del_admin":
            if len(c["admins"]) <= 1: return
            markup = types.InlineKeyboardMarkup()
            for aid in c["admins"]: markup.add(types.InlineKeyboardButton(str(aid), callback_data=f"remove_{aid}"))
            bot.edit_message_text("Adminni tanlang:", call.message.chat.id, call.message.message_id, reply_markup=markup)
            
        elif call.data.startswith("remove_"):
            aid = int(call.data.split("_")[1])
            if aid in c["admins"]:
                c["admins"].remove(aid)
                save_config(c)
                bot.send_message(call.message.chat.id, "Admin o'chirildi.", reply_markup=get_admin_keyboard())

    except Exception as e: 
        print(f"Callback error: {e}")

# =====================================================================
# 9. YORDAMCHI LOGIKALAR
# =====================================================================
def save_camp_times_logic(message):
    try:
        admin_id = message.from_user.id
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
        temp_campaign_data.pop(admin_id, None)
        
        bot.send_message(message.chat.id, f"✅ Reja vaqtlari saqlandi: {', '.join(c['campaigns'][camp_id]['custom_times'])}", reply_markup=get_admin_keyboard())
    except Exception:
        bot.send_message(message.chat.id, "❌ Vaqt kiritishda xato. Format: `09:00, 15:30`", reply_markup=get_admin_keyboard())

def add_admin_logic(message):
    try:
        if message.text == "❌ Bekor qilish": return
        new_id = int(message.text.strip())
        c = load_config()
        if new_id not in c["admins"]:
            c["admins"].append(new_id)
            save_config(c)
            bot.send_message(message.chat.id, "✅ Admin qo'shildi!", reply_markup=get_admin_keyboard())
    except Exception: bot.send_message(message.chat.id, "Xato ID.", reply_markup=get_admin_keyboard())

def save_new_message(message):
    try:
        if message.text == "❌ Bekor qilish": return
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
        bot.send_message(message.chat.id, "✅ Reklama xabari saqlandi!", reply_markup=get_admin_keyboard())
    except Exception: pass

if __name__ == "__main__":
    keep_alive()
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
